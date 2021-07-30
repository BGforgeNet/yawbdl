#!/usr/bin/env python3
# coding: utf-8

import requests
from urllib.parse import urlparse
from urllib.parse import urlsplit
import sys
import os
import os.path as path
import argparse
import errno
import time

parser = argparse.ArgumentParser(description='Download a website from Internet Archive', formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument('-d', dest='domain', help='domain to download')
parser.add_argument('-o', dest='dst_dir', help='output directory')
parser.add_argument('--from', dest='from_date', default=None, action='append', help='from date, up to 14 digits: yyyyMMddhhmmss')
parser.add_argument('--to', dest='to_date', default=None, help='to date')
parser.add_argument('--timeout', dest='timeout', default=10, help='request timeout')
parser.add_argument('-n', action='store_true', help="dry run")
parser.add_argument('--delay', default=1, help="delay between requests")
parser.add_argument('--retries', default=0, help="max number of retries")
parser.add_argument('--no-fail', default=False, action='store_true', help="if retries are exceeded, and the file still couldn't have been downloaded, proceed to the next file instead of aborting the run")
parser.add_argument('--skip-timestamps', default=None, action = 'append', nargs='+', help="skip snapshots with these timestamps (sometimes Internet Archive just fails to serve a specific snapshot)")

args = parser.parse_args()

if len(sys.argv) < 2:
  parser.print_help(sys.stderr)
  sys.exit(1)

# init vars
domain = args.domain
dst_dir = args.dst_dir
from_date = args.from_date
to_date = args.to_date
timeout = int(args.timeout)
dry_run = args.n
delay = int(args.delay)
retries = int(args.retries)
no_fail = args.no_fail
skip_timestamps = args.skip_timestamps[0]

cdx_url = "http://web.archive.org/cdx/search/cdx?"
params = "output=json&url={}&matchType=host&filter=statuscode:200&fl=timestamp,original".format(domain)
if from_date is not None:
  params = params + "&from={}".format(from_date)
if to_date is not None:
  params = params + "&to={}".format(to_date)

vanilla_url = "http://web.archive.org/web/{}id_/{}"

def get_snapshot_list():
  resp = requests.get(cdx_url + params)
  snap_list = resp.json()
  if len(snap_list) == 0:
    print("Sorry, no snapshots found!")
    sys.exit(0)
  del snap_list[0] # delete header
  snap_list.sort(key = lambda row: row[0]) # sort by timestamp
  return snap_list

def download_files(snapshot_list):
  total = len(snapshot_list)
  i = 0
  for snap in snapshot_list:
    i += 1
    print("({}/{}) ".format(i, total), end="")
    download_file(snap)

def get_file_path(original_url):
  url = urlsplit(original_url)
  fpath = url.path.lstrip('/')
  if url.query:
    fpath = fpath + "?" + url.query
  if fpath.endswith('/') or fpath == "":
    fpath = path.join(fpath, 'index.html')
  return fpath

def download_file(snap):
  timestamp = snap[0]
  original = snap[1]
  print(timestamp, original, " ", end="", flush=True)

  if timestamp in skip_timestamps:
    print("[Skip: by timestamp command line option]")
    return

  fpath = path.join(dst_dir, timestamp, get_file_path(original))
  if path.isfile(fpath):
    print("[Skip: already on disk]")
    return

  if dry_run:
    print("") # carriage return
  else:
    retry_count = 0
    url = vanilla_url.format(timestamp, original)
    while retry_count <= retries:
      try:
        if delay:
          time.sleep(delay * 2 * retry_count) # increase delay with each try
        resp = requests.get(url, timeout=timeout)
        break
      except Exception:
        if retry_count < retries:
          retry_count += 1
          new_delay = delay * 2* retry_count
          print("    failed to download, retrying after {} seconds... ".format(new_delay), flush=True)
        else:
          if no_fail:
            print("    failed to download, proceeding to next file", flush=True)
            return
          else:
            print("    failed to download, aborting", flush=True)
            sys.exit(1)

    code = resp.status_code
    if code != 200:
      print("[Error: {}]".format(code), flush=True)
    else:
      content = resp.content
      if len(content) == 0:
        print("[Skip: file size is 0]", flush=True)
      else:
        write_file(fpath, content)

def write_file(fpath, content):
  dirname, basename = path.split(fpath)
  os.makedirs(dirname, exist_ok=True)
  too_long = False
  try:
    with open(fpath, "wb") as file:
      file.write(content)
  except OSError as exc:
    if exc.errno == errno.ENAMETOOLONG:
      print("[Error: file name too long, skipped]", flush=True)
      too_long = True
    else:
      raise
  if not too_long:
    print("[OK]", flush=True)

snap_list = get_snapshot_list()
download_files(snap_list)
if dry_run:
  print("Dry run completed.")
