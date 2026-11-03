# Agent Session Record export for OpenHands Canvas

Local patch package for [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands). The pinned base is `934612b3b6cee05d3a4400b98b48a9c69215401d`.

## Install

Set `ASR_PACKAGE` to this package's absolute path. In a clean writable checkout at the pinned base, run:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
```

Build and run the project using its own development instructions. These patches are not installed by the ASR CLI.

## Use

Open a conversation, open transcript export, and select Agent Session Record (.jsonl).

The [proposal](PROPOSAL.md) describes the source mapping and known losses. Exports use ASR 0.1 and the native producer method. Review content before sharing.

## Verification

From the ASR repository root:

```sh
node upstream/openhands/check.mjs
node upstream/openhands/reproduce.mjs /path/to/patched-checkout
```

The package check verifies digests, patch syntax, synthetic source contracts and sample validation. Reproduction replays patches in a temporary index and compares the resulting tree with the pinned head. It preserves the source checkout and makes no model requests.

See [TEST-RESULTS.md](TEST-RESULTS.md) for current project checks. Earlier live evidence is partial and predates this refresh. A live run of the refreshed code has not been verified.
