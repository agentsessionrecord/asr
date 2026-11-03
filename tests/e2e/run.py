#!/usr/bin/env python3
"""Build and run the optional clean-container ASR integration test."""

import argparse
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

from providers import loopback_endpoint, CheckFailure, private_file, provision, require

ROOT = Path(__file__).resolve().parents[2]
SUITE_FILES = ("Dockerfile", "Dockerfile.minio", "README.md", "providers.py", "run.py", "s3.py",
               "session_test.py", "test_ci.py", "test_harness.py", "viewer.mjs")


def source_archive():
    """Use tracked source and this suite. Exclude Git, caches and host settings."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                            capture_output=True).stdout.decode().split("\0")
    paths = {name for name in listed if name}
    paths.update("tests/e2e/" + name for name in SUITE_FILES)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name in sorted(paths):
            path = ROOT / name
            if path.is_file():
                require(not path.is_symlink(), "build_source_symlink")
                archive.add(path, arcname=name, recursive=False)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, default=os.environ.get("ASR_PROXY_KEY_FILE"))
    parser.add_argument("--minio-image", default=os.environ.get("ASR_E2E_MINIO_IMAGE"),
                        help="Use an existing local MinIO image instead of building the pinned source")
    parser.add_argument("--sudo", action="store_true", default=os.environ.get("ASR_TEST_DOCKER_SUDO") == "1")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--openai-base-url", default=os.environ.get("ASR_OPENAI_BASE_URL"))
    parser.add_argument("--anthropic-base-url", default=os.environ.get("ASR_ANTHROPIC_BASE_URL"))
    parser.add_argument("--openai-model", default=os.environ.get("ASR_OPENAI_MODEL"))
    parser.add_argument("--anthropic-model", default=os.environ.get("ASR_ANTHROPIC_MODEL"))
    args = parser.parse_args()
    require(sys.platform == "linux", "linux_host_network_required")
    require(args.key_file is not None and args.key_file.is_file(), "proxy_key_file_required")
    loopback_endpoint(args.openai_base_url)
    loopback_endpoint(args.anthropic_base_url)
    require(bool(args.openai_model) and bool(args.anthropic_model), "provider_models_required")
    docker = (["sudo", "-n"] if args.sudo else []) + ["docker"]
    suffix = secrets.token_hex(6)
    image = "asr-e2e:" + suffix
    owned = []
    built_images = []

    def command(argv, timeout=60, check=True, **kwargs):
        result = subprocess.run(docker + argv, capture_output=True, timeout=timeout, **kwargs)
        if result.returncode and argv[0] == "build":
            # Source builds happen before credentials exist and have no session data.
            print(result.stderr.decode(errors="replace")[-8000:], file=sys.stderr)
        require(not check or result.returncode == 0, "docker_" + argv[0] + "_failed")
        return result.stdout.decode().strip()

    with tempfile.TemporaryDirectory(prefix="asr-e2e-") as temporary:
        scratch = Path(temporary)
        scratch.chmod(0o700)
        try:
            print("stage=build_clean_image", flush=True)
            # No credential is read until the source image is built.
            built_images.append(image)
            command(["build", "--tag", image, "--file", "tests/e2e/Dockerfile", "-"],
                    timeout=2400, input=source_archive())
            print("stage=prepare_local_store", flush=True)
            minio_image = args.minio_image
            if minio_image is None:
                minio_image = "asr-e2e-minio:" + suffix
                built_images.append(minio_image)
                command(["build", "--tag", minio_image, "--file", "tests/e2e/Dockerfile.minio", "-"],
                        timeout=1200, input=source_archive())
            else:
                command(["image", "inspect", minio_image])
            provider_dir = scratch / "providers"
            provision(provider_dir, args.key_file.read_text().strip(), args.anthropic_base_url,
                      args.openai_base_url, args.anthropic_model, args.openai_model)
            access = "synthetic-" + secrets.token_hex(8)
            secret = secrets.token_hex(32)
            environment = scratch / "minio.env"
            private_file(environment, f"MINIO_ROOT_USER={access}\nMINIO_ROOT_PASSWORD={secret}\n")
            minio_name = "asr-e2e-minio-" + suffix
            owned.append(minio_name)
            command(["run", "--pull=never", "--detach", "--name", minio_name,
                     "--env-file", str(environment), "--publish", "127.0.0.1::9000",
                     minio_image, "server", "/data", "--address", ":9000"])
            port = command(["inspect", "--format",
                            '{{(index (index .NetworkSettings.Ports "9000/tcp") 0).HostPort}}', minio_name])
            endpoint = "http://127.0.0.1:" + port
            deadline = time.monotonic() + 30
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while True:
                try:
                    with opener.open(endpoint + "/minio/health/live", timeout=1) as response:
                        require(response.status == 200, "minio_health_failed")
                    break
                except OSError:
                    require(time.monotonic() < deadline, "minio_not_ready")
                    time.sleep(0.1)
            runtime = scratch / "runtime.env"
            private_file(runtime, f"AWS_ACCESS_KEY_ID={access}\nAWS_SECRET_ACCESS_KEY={secret}\n"
                         f"AWS_ENDPOINT={endpoint}\nAWS_ALLOW_HTTP=true\nAWS_REGION=us-east-1\n"
                         "AWS_VIRTUAL_HOSTED_STYLE_REQUEST=false\nAWS_EC2_METADATA_DISABLED=true\n")
            runner_name = "asr-e2e-runner-" + suffix
            owned.append(runner_name)
            print("stage=live_sessions_collect_view_export", flush=True)
            command(["create", "--pull=never", "--name", runner_name, "--network", "host",
                     "--shm-size", "512m", "--env-file", str(runtime),
                     "--mount", f"type=bind,src={provider_dir},dst=/run/asr-providers,readonly", image])
            output = command(["start", "--attach", runner_name], timeout=1200, check=False)
            # docker start does not reliably propagate the container's exit code.
            code = command(["inspect", "--format", "{{.State.ExitCode}}", runner_name])
            lines = output.splitlines()
            result = json.loads(lines[-1]) if lines else {}
            if code != "0" or result.get("passed") is not True:
                diagnostic = result.get("code", "container_test_failed")
                require(isinstance(diagnostic, str) and diagnostic.replace("_", "").isalnum(),
                        "invalid_container_diagnostic")
                stage = result.get("stage", "container")
                require(isinstance(stage, str) and stage.replace("_", "").isalnum(), "invalid_container_stage")
                raise CheckFailure(stage + "_" + diagnostic)
            print(json.dumps(result, sort_keys=True), flush=True)
            if args.report:
                private_file(args.report, json.dumps(result, indent=2, sort_keys=True) + "\n")
        finally:
            cleanup_errors = []
            for container in reversed(owned):
                result = subprocess.run(docker + ["rm", "--force", container], capture_output=True, timeout=30)
                if result.returncode:
                    # Creation may have failed before the owned name existed.
                    check = subprocess.run(docker + ["container", "ls", "--all", "--quiet",
                                                      "--filter", "name=^/" + container + "$"],
                                           capture_output=True, timeout=15)
                    if check.returncode or check.stdout.strip():
                        cleanup_errors.append("container_cleanup_failed")
            for built_image in reversed(built_images):
                subprocess.run(docker + ["image", "rm", built_image], capture_output=True, timeout=30)
                check = subprocess.run(docker + ["image", "ls", "--quiet", "--filter", "reference=" + built_image],
                                       capture_output=True, timeout=15)
                if check.returncode or check.stdout.strip():
                    cleanup_errors.append("image_cleanup_failed")
            require(not cleanup_errors, "owned_resources_cleanup_failed")


if __name__ == "__main__":
    try:
        main()
    except (CheckFailure, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as error:
        print(json.dumps({"passed": False, "code": str(error) if isinstance(error, CheckFailure)
                          else type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
