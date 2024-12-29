## Yet Another WayBack DownLoader

YAWBDL is a tool to download archived pages from Internet Archive, which I wrote because none of other tools worked good enough (or at all) in my use cases.

### Usage

```bash
git clone https://github.com/BGforgeNet/yawbdl.git
cd yawbdl
pip install -r requirements.txt

./yawbdl.py
usage: yawbdl.py [-h] [-d DOMAIN] [-o DST_DIR] [--from FROM_DATE] [--to TO_DATE]
                 [--timeout TIMEOUT] [-n] [--delay DELAY] [--retries RETRIES]
                 [--no-fail]
                 [--skip-timestamps SKIP_TIMESTAMPS [SKIP_TIMESTAMPS ...]]

Download a website from Internet Archive

options:
  -h, --help            show this help message and exit
  -d DOMAIN             domain to download
  -o DST_DIR            output directory
  --from FROM_DATE      from date, up to 14 digits: yyyyMMddhhmmss
  --to TO_DATE          to date
  --timeout TIMEOUT     request timeout
  -n                    dry run
  --delay DELAY         delay between requests
  --retries RETRIES     max number of retries
  --no-fail             if retries are exceeded, and the file still couldn't
                        have been downloaded, proceed to the next file instead
                        of aborting the run
  --skip-timestamps SKIP_TIMESTAMPS [SKIP_TIMESTAMPS ...]
                        skip snapshots with these timestamps (sometimes Internet
                        Archive just fails to serve a specific snapshot)

```
