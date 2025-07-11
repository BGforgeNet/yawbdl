## Changelog

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
