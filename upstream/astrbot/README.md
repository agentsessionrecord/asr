# Agent Session Record export for AstrBot

Local patch package for [AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot). The pinned base is `f926af99ec5f8bd85b64413f8bfad55da76ef73b`.

## Install

Set `ASR_PACKAGE` to this package's absolute path. In a clean writable checkout at the pinned base, run:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
```

Build and run the project using its own development instructions. These patches are not installed by the ASR CLI.

## Use

```sh
astrbot sessions export --format agent-session --session CONVERSATION_ID
astrbot sessions export --format agent-session --output exports
```

The [proposal](PROPOSAL.md) describes the source mapping and known losses. Exports use ASR 0.1 and the native producer method. Review content before sharing.

## Verification

From the ASR repository root:

```sh
node upstream/astrbot/check.mjs
node upstream/astrbot/reproduce.mjs /path/to/patched-checkout
```

The package check verifies digests, patch syntax, synthetic source contracts and sample validation. Reproduction replays patches in a temporary index and compares the resulting tree with the pinned head. It preserves the source checkout and makes no model requests.

See [TEST-RESULTS.md](TEST-RESULTS.md) for current project checks. Earlier live evidence is partial and predates this refresh. A live run of the refreshed code has not been verified.
