## Yet Another WayBack DownLoader

YAWBDL is a tool to download archived pages from Internet Archive, which I wrote because none of other tools worked good enough (or at all) in my use cases.

### Usage

```bash
pipx install yawbdl

usage: yawbdl.py [-h] [-d DOMAIN] [-o DST_DIR] [--from FROM_DATE] [--to TO_DATE]
                 [--timeout TIMEOUT] [-n] [--delay DELAY] [--retries RETRIES]
                 [--no-fail]
                 [--skip-timestamps SKIP_TIMESTAMPS [SKIP_TIMESTAMPS ...]]
                 [--latest-only]

Download a website from Internet Archive

options:
  -h, --help            show this help message and exit
  -d DOMAIN             domain to download (default: None)
  -o DST_DIR            output directory (default: None)
  --from FROM_DATE      from date, up to 14 digits: yyyyMMddhhmmss (default:
                        None)
  --to TO_DATE          to date (default: None)
  --timeout TIMEOUT     request timeout (default: 10)
  -n                    dry run (default: False)
  --delay DELAY         delay between requests (default: 1)
  --retries RETRIES     max number of retries (default: 0)
  --no-fail             if retries are exceeded, and the file still couldn't
                        have been downloaded, proceed to the next file instead
                        of aborting the run (default: False)
  --skip-timestamps SKIP_TIMESTAMPS [SKIP_TIMESTAMPS ...]
                        skip snapshots with these timestamps (sometimes Internet
                        Archive just fails to serve a specific snapshot)
                        (default: None)
  --latest-only         download only the latest version of each URL (default:
                        False)
```
