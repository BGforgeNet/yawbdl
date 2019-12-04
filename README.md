## Yet Another WayBack DownLoader

YAWBDL is a tool to download archived pages from Internet Archive, which I wrote because none of other tools worked good enough (or at all) in my use cases.

### Usage

```bash
$ pip install -r requirements.txt
$ ./yawbdl.py
usage: yawbdl.py [-h] [-d DOMAIN] [-o DST_DIR] [--from FROM_DATE]
                 [--to TO_DATE] [--timeout TIMEOUT]

Download a website from Internet Archive

optional arguments:
  -h, --help         show this help message and exit
  -d DOMAIN          domain to download (default: None)
  -o DST_DIR         output directory (default: None)
  --from FROM_DATE   from date, up to 14 digits: yyyyMMddhhmmss (default:
                     None)
  --to TO_DATE       to date (default: None)
  --timeout TIMEOUT  request timeout (default: 10)
  -n                 dry run (default: False)
```
