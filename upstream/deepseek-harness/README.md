# DeepSeek Harness ASR plugin

[plugin/](plugin/) contains the installable unofficial `dsh-plugin-asr-export` package. It adds an ASR download route through the harness's authenticated Host connection and session-query service.

Source API: https://github.com/deepseek-ai/deepseek-harness at `8bd073392eef6f54e921a093b95076248eb08cbb`. There is no core patch series. DeepSeek Harness does not accept external PRs and supports community plugins tagged `dsh-plugin`.

See [plugin/README.md](plugin/README.md) for local build, installation, and use. The package includes built JavaScript, type declarations, a lockfile, synthetic tests, and a Cordis overlay. Nothing has been published.

```sh
node upstream/deepseek-harness/check.mjs
node upstream/deepseek-harness/reproduce.mjs /path/to/upstream-checkout
```

The package checks verify digests, synthetic output, and ASR validation. Reproduction also verifies that the pinned upstream commit exists without modifying the checkout. [TESTS.json](TESTS.json) records build, plugin lifecycle, Host access, and installation checks. No current model session was run.
