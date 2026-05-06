## Changelog

### 1.1.4

- Snapshot list is now fetched page by page from the CDX API, avoiding `JSONDecodeError` on large domains where the single-shot response was truncated mid-stream ([#14](https://github.com/BGforgeNet/yawbdl/issues/14)).
- Truncated/malformed snapshot list responses now trigger the retry mechanism instead of aborting.
- Retry/abort log messages include the exception type and message (e.g. `HTTPError: 503 ...`, `JSONDecodeError: ...`) without needing `--debug`.

### 1.1.3

- KeyboardInterrupt (Ctrl+C) is no longer silently caught during snapshot cache loading and status logging.

### 1.1.2

- Added `--debug` argument to show detailed information.
- Added a [workaround](https://github.com/BGforgeNet/yawbdl/issues/9) for wrong encoding header sent by IA servers in some cases.

### 1.1.1

Added missing console script for pipx usage, lost in 1.1.0.

### 1.1.0

- Fixed crash on extra long urls.
- Improved logging with loguru. Logs are now saved to a file too.
- Added option to download only latest snapshots.
- Always download full snapshot data, to avoid caching a partial file.
- Files that can't be saved to disk for path reasons, now fallback to hashed filename.

### 1.0.1

Add a [workaround](https://github.com/BGforgeNet/yawbdl/issues/5) for malformed URLs in snapshots list.

### 1.0.0

Initial release.
