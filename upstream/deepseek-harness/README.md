# Agent Session Record plugin for DeepSeek Harness

[plugin/](plugin/) holds `dsh-plugin-asr-export`, an unofficial plugin that adds an ASR download route through the harness's authenticated Host connection and session-query service. It targets the source API of [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) at `8bd073392eef6f54e921a093b95076248eb08cbb`. There is no core patch series, because DeepSeek Harness does not accept external pull requests and supports community plugins tagged `dsh-plugin`.

See [plugin/README.md](plugin/README.md) to build, install and use it. The package includes built JavaScript, type declarations, a lockfile, synthetic tests and a Cordis overlay. The consuming profile must apply the documented `zod` 4.6.6 override. The plugin has not been published.

## Checks

```sh
node upstream/deepseek-harness/check.mjs
node upstream/deepseek-harness/reproduce.mjs /path/to/upstream-checkout
```

The package check verifies digests, synthetic output and ASR validation. The reproduce command checks that the pinned upstream commit exists without changing the checkout. The plugin build, lint, type check, three tests and production audit pass. [TESTS.json](TESTS.json) records the build, plugin lifecycle, Host access and installation checks. No live model run covers this revision.
