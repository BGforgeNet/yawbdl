#!/usr/bin/env python3

import requests
from urllib.parse import urlsplit
import sys
import os
import os.path as path
import argparse
import time
import re
import json
import hashlib
import shutil

parser = argparse.ArgumentParser(
    description="Download a website from Internet Archive",
    formatter_class=lambda prog: argparse.ArgumentDefaultsHelpFormatter(prog, width=80),
)

parser.add_argument("-d", dest="domain", help="domain to download")
parser.add_argument("-o", dest="dst_dir", help="output directory")
parser.add_argument(
    "--from",
    dest="from_date",
    default=None,
    help="from date, up to 14 digits: yyyyMMddhhmmss",
)
parser.add_argument("--to", dest="to_date", default=None, help="to date")
parser.add_argument("--timeout", dest="timeout", default=10, help="request timeout")
parser.add_argument("-n", action="store_true", help="dry run")
parser.add_argument("--delay", default=1, help="delay between requests")
parser.add_argument("--retries", default=0, help="max number of retries")
parser.add_argument(
    "--no-fail",
    default=False,
    action="store_true",
    help="if retries are exceeded, and the file still couldn't have been downloaded, proceed to the next file instead of aborting the run",
)
parser.add_argument(
    "--skip-timestamps",
    default=None,
    action="append",
    nargs="+",
    help="skip snapshots with these timestamps (sometimes Internet Archive just fails to serve a specific snapshot)",
)

args = parser.parse_args()

if len(sys.argv) < 2:
    parser.print_help(sys.stderr)
    sys.exit(1)

# init vars
domain = args.domain
DST_DIR = args.dst_dir
from_date = args.from_date
to_date = args.to_date
timeout = int(args.timeout)
dry_run = args.n
DELAY = int(args.delay)
RETRIES = int(args.retries)
no_fail = args.no_fail
try:
    skip_timestamps = args.skip_timestamps[0]
except:
    skip_timestamps = []

CDX_URL = "http://web.archive.org/cdx/search/cdx?"
params = "output=json&url={}&matchType=host&filter=statuscode:200&fl=timestamp,original".format(domain)
if from_date is not None:
    params = params + "&from={}".format(from_date)
if to_date is not None:
    params = params + "&to={}".format(to_date)

vanilla_url = "http://web.archive.org/web/{}id_/{}"


def get_snapshot_timestamp(row: list[str]) -> str:
    """Extract timestamp from snapshot row for sorting."""
    return row[0]


def cleanup_empty_directory(dirname: str, timestamp_dir: str) -> None:
    """
    Clean up empty directory tree created for a failed file save.

    Removes the top-level directory under timestamp_dir that was created for the file,
    but only if it contains no files (to avoid removing directories with successful saves).

    Args:
        dirname: The directory path where the file was supposed to be saved
        timestamp_dir: The timestamp directory path (e.g., DST_DIR/timestamp)
    """
    try:
        # Remove the entire directory tree that was created for this file
        # Find the first subdirectory under timestamp_dir and remove it entirely
        # but only if it's empty (no other files were saved there)
        rel_path = path.relpath(dirname, timestamp_dir)
        if rel_path and rel_path != '.':
            first_subdir = rel_path.split(path.sep)[0]
            cleanup_path = path.join(timestamp_dir, first_subdir)
            if path.exists(cleanup_path):
                # Check if directory tree is empty
                is_empty = True
                for _, _, files in os.walk(cleanup_path):
                    if files:
                        is_empty = False
                        break
                if is_empty:
                    shutil.rmtree(cleanup_path)
    except OSError:
        pass  # Ignore cleanup errors


def get_snapshot_list():
    """
    Load cached snapshot list. If not available, get it from IA.
    """
    print("Getting snapshot list...")

    # Try cached snapshots
    snapshots_path = path.join(DST_DIR, "snapshots.json")
    try:
        with open(snapshots_path) as fh:
            snap_list = json.load(fh)
        print("Found cached snapshots.json")
    except:
        # No cache, downloading
        url = CDX_URL + params
        retry_count = 0
        while retry_count <= RETRIES:
            try:
                if DELAY:
                    time.sleep(DELAY * 2 * retry_count)  # increase delay with each try
                resp = requests.get(url, timeout=timeout)
                break
            except Exception:
                if retry_count < RETRIES:
                    retry_count += 1
                    new_delay = DELAY * 2 * retry_count
                    print(
                        "    failed to get snapshot list, retrying after {} seconds... ".format(new_delay),
                        flush=True,
                    )
                else:
                    print("    failed to get snapshot list, aborting!")
                    sys.exit(1)

        code = resp.status_code  # type: ignore  # resp is always defined here - script exits above if all retries fail
        if resp.status_code != 200:  # type: ignore  # resp is always defined here - script exits above if all retries fail
            print(f"[Error: {code}]")
            print("    failed to get snapshot list, aborting!")
            sys.exit(1)
        snap_list = resp.json()  # type: ignore  # resp is always defined here - script exits above if all retries fail
        os.makedirs(DST_DIR, exist_ok=True)
        with open(snapshots_path, "w") as fh:
            json.dump(snap_list, fh)

    if len(snap_list) == 0:
        print("Sorry, no snapshots found!")
        sys.exit(0)
    del snap_list[0]  # delete header
    snap_list.sort(key=get_snapshot_timestamp)  # sort by timestamp
    print("Got snapshot list!")
    return snap_list


def download_files(snapshot_list: list[tuple[str, str]]):
    total = len(snapshot_list)
    i = 0
    for snap in snapshot_list:
        i += 1
        print("({}/{}) ".format(i, total), end="")
        download_file(snap)


def url_to_path(url: str) -> str:
    """
    Converts a relative URL to a local path compatible with the current operating system.
    Wget-like https://www.gnu.org/software/wget/manual/wget.html#index-Windows-file-names
    Except "/", which we later turn into directory tree.

    Args:
        url (str): The input URL.

    Returns:
        str: The converted filename.
    """
    if os.name == "nt":  # Windows
        # Escape Windows restricted characters
        restricted_chars = r'[\\|:"*<>\x00-\x1F\x80-\x9F]'
        escaped_url = re.sub(restricted_chars, lambda match: f"%{ord(match.group(0)):02X}", url)
        # Replace '?' with '@' for query portion separation
        escaped_url = escaped_url.replace("?", "@")
    else:  # Unix-like systems
        # Escape Unix restricted characters (excluding '/')
        restricted_chars = r"[\x00-\x1F\x80-\x9F]"
        escaped_url = re.sub(restricted_chars, lambda match: f"%{ord(match.group(0)):02X}", url)
    return escaped_url


def get_file_path(original_url: str) -> str:
    url = urlsplit(original_url)
    fpath = url.path.lstrip("/")

    if url.query:
        fpath = fpath + "?" + url.query

    # Sanitize for local FS
    fpath = url_to_path(fpath)

    # Convert forward slashes to OS path separator
    fpath = fpath.replace("/", path.sep)

    # If it's a "directory"-like url, add index to have a filename
    if fpath.endswith(path.sep) or fpath == "":
        fpath = path.join(fpath, "index.html")
    return fpath


def download_file(snap: tuple[str, str]):
    """
    Download and save a single original URL at TIMESTAMP to the destination directory.
    Will retry RETRIES times.

    Args:
        snap: [timestamp, original_url]

    """
    timestamp: str = snap[0]
    original_url: str = snap[1]

    # Some urls may be malformed and can't be printed with non-UTF-8 encodings.
    # See https://github.com/BGforgeNet/yawbdl/issues/5
    try:
        print(timestamp, original_url, " ", end="", flush=True)
    except Exception:
        print(f"[Error: malformed url, can't print. Set PYTHONUTF8=1 environment variable to see it.]")

    if timestamp in skip_timestamps:
        print("[Skip: by timestamp command line option]")
        return

    fpath = path.join(DST_DIR, timestamp, get_file_path(original_url))
    if path.isfile(fpath):
        print("[Skip: already on disk]")
        return

    if dry_run:
        print("")  # carriage return
    else:
        retry_count = 0
        url = vanilla_url.format(timestamp, original_url)
        while retry_count <= RETRIES:
            try:
                if DELAY:
                    time.sleep(DELAY * 2 * retry_count)  # increase delay with each try
                resp = requests.get(url, timeout=timeout)
                break
            except Exception:
                if retry_count < RETRIES:
                    retry_count += 1
                    new_delay = DELAY * 2 * retry_count
                    print(
                        "    failed to download, retrying after {} seconds... ".format(new_delay),
                        flush=True,
                    )
                else:
                    if no_fail:
                        print(
                            "    failed to download, proceeding to next file",
                            flush=True,
                        )
                        return
                    else:
                        print("    failed to download, aborting", flush=True)
                        sys.exit(1)

        code = resp.status_code  # type: ignore  # resp is always defined here - script exits or returns above if all retries fail
        if code != 200:
            print("[Error: {}]".format(code), flush=True)
        else:
            content = resp.content  # type: ignore  # resp is always defined here - script exits or returns above if all retries fail
            if len(content) == 0:
                print("[Skip: file size is 0]", flush=True)
            else:
                write_file(fpath, content, path.join(DST_DIR, timestamp), original_url)


def write_file(fpath: str, content: bytes, timestamp_dir: str, original_url: str):
    """Write content to file with hash filename fallback on filesystem errors.

    Attempts to save file with original path structure. If that fails due to filesystem
    limitations (path length, invalid characters, etc.), cleans up empty directories
    and saves with SHA-1 hash of original URL as filename under timestamp directory.

    Args:
        fpath: Full file path where content should be saved
        content: File content as bytes
        timestamp_dir: Timestamp directory path (e.g., DST_DIR/timestamp)
        original_url: Original URL from Internet Archive for hash generation

    Returns:
        None
    """
    dirname, basename = path.split(fpath)

    if path.isfile(dirname):
        print(
            "[Warning] file {} already exists, can't create directory with the same name for {}".format(
                dirname, basename
            ),
            flush=True,
        )
        return

    # Try to create directory and write file normally
    try:
        os.makedirs(dirname, exist_ok=True)
        with open(fpath, "wb") as file:
            file.write(content)
        print("[OK]", flush=True)
    except OSError:
        # Cleanup any directories that might have been created
        cleanup_empty_directory(dirname, timestamp_dir)

        # Use SHA-1 hash as fallback filename, save directly under timestamp directory
        file_hash = hashlib.sha1(original_url.encode('utf-8')).hexdigest()
        # Extract extension from original URL path, not the processed basename
        url_parts = urlsplit(original_url)
        file_ext = path.splitext(url_parts.path)[1] if '.' in url_parts.path else '.html'
        hash_filename = file_hash + file_ext
        hash_fpath = path.join(timestamp_dir, hash_filename)

        print(f"[Warning: could not save full path to filesystem. Using hashed filename {hash_filename}]", flush=True)
        try:
            with open(hash_fpath, "wb") as file:
                file.write(content)
            print("[OK]", flush=True)
        except OSError:
            print("[Error: failed to save even with hashed filename, skipped]", flush=True)


def main():
    snap_list = get_snapshot_list()
    download_files(snap_list)
    if dry_run:
        print("Dry run completed.")


if __name__ == "__main__":
    main()
