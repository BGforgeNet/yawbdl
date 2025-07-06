#!/usr/bin/env python3

"""Yet Another Wayback Downloader.

A tool to download archived websites from Internet Archive's Wayback Machine.
Downloads all snapshots for a given domain within a specified date range,
preserving the original directory structure when possible.
"""

import argparse
import hashlib
import json
import os
from os import path
import re
import shutil
import sys
import time
from urllib.parse import urlsplit

import requests

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
DST_DIR = args.dst_dir
TIMEOUT = int(args.timeout)
DRY_RUN = args.n
DELAY = int(args.delay)
RETRIES = int(args.retries)
NO_FAIL = args.no_fail
try:
    skip_timestamps = args.skip_timestamps[0]
except (TypeError, AttributeError):
    skip_timestamps = []

# Type alias for snapshot records
Snapshot = tuple[str, str]
SnapshotList = list[Snapshot]


def get_snapshot_timestamp(row: list[str]) -> str:
    """Extract timestamp from snapshot row for sorting."""
    return row[0]


def cleanup_empty_directory(dirname: str, timestamp_dir: str):
    """Clean up empty directory tree created for a failed file save.

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
        if rel_path and rel_path != ".":
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


def build_snapshots_url(domain: str, from_date: str | None = None, to_date: str | None = None) -> str:
    """Build the full CDX API URL for retrieving the snapshots list for a domain and date range.
    
    Args:
        domain: The domain to query snapshots for
        from_date: Optional start date (yyyyMMddhhmmss)
        to_date: Optional end date (yyyyMMddhhmmss)
        
    Returns:
        Complete CDX API URL with domain and date filters
    """
    cdx_url = "http://web.archive.org/cdx/search/cdx?"
    params = f"output=json&url={domain}&matchType=host&filter=statuscode:200&fl=timestamp,original"
    if from_date is not None:
        params += f"&from={from_date}"
    if to_date is not None:
        params += f"&to={to_date}"
    return cdx_url + params


def get_snapshot_list() -> SnapshotList:
    """Load cached snapshot list from file or download from Internet Archive.

    Returns:
        List of snapshot records, each containing (timestamp, original_url)
    """
    print("Getting snapshot list...")

    # Try cached snapshots
    snapshots_path = path.join(DST_DIR, "snapshots.json")
    try:
        with open(snapshots_path, encoding="utf-8") as fh:
            snap_list = json.load(fh)
        print("Found cached snapshots.json")
    except:
        # No cache, downloading
        url = build_snapshots_url(args.domain, args.from_date, args.to_date)
        retry_count = 0
        while retry_count <= RETRIES:
            try:
                if DELAY:
                    time.sleep(DELAY * 2 * retry_count)  # increase delay with each try
                resp = requests.get(url, timeout=TIMEOUT)
                break
            except Exception:
                if retry_count < RETRIES:
                    retry_count += 1
                    new_delay = DELAY * 2 * retry_count
                    print(
                        f"    failed to get snapshot list, retrying after {new_delay} seconds... ",
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
        with open(snapshots_path, "w", encoding="utf-8") as fh:
            json.dump(snap_list, fh)

    if len(snap_list) == 0:
        print("Sorry, no snapshots found!")
        sys.exit(0)
    del snap_list[0]  # delete header
    snap_list.sort(key=get_snapshot_timestamp)  # sort by timestamp
    print("Got snapshot list!")
    return snap_list


def download_files(snapshot_list: SnapshotList):
    """Download all files from snapshot list with progress tracking.

    Args:
        snapshot_list: List of snapshot records, each containing (timestamp, original_url)
    """
    total = len(snapshot_list)
    i = 0
    for snap in snapshot_list:
        i += 1
        print(f"({i}/{total}) ", end="")
        download_file(snap)


def url_to_path(url: str) -> str:
    """Convert relative URL to local path compatible with current operating system.

    Follows wget-like behavior for filename escaping:
    https://www.gnu.org/software/wget/manual/wget.html#index-Windows-file-names
    Restricted characters are percent-encoded, and '?' is replaced with '@' on Windows
    for query separation. Forward slashes are preserved for later directory tree conversion.

    Args:
        url: The input URL to convert

    Returns:
        The converted filename safe for local filesystem
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
    """Convert original URL to local file path.

    Extracts path and query from URL, sanitizes for filesystem compatibility,
    and adds index.html for directory-like URLs.

    Args:
        original_url: The original URL to convert

    Returns:
        Local file path relative to timestamp directory
    """
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
    """Download and save a single URL from Internet Archive snapshot.

    Downloads content from Internet Archive for given timestamp and URL,
    then saves it to local filesystem with retry logic.

    Args:
        snap: Tuple containing (timestamp, original_url)
    """
    timestamp: str = snap[0]
    original_url: str = snap[1]

    # Some urls may be malformed and can't be printed with non-UTF-8 encodings.
    # See https://github.com/BGforgeNet/yawbdl/issues/5
    try:
        print(timestamp, original_url, " ", end="", flush=True)
    except Exception:
        print("[Error: malformed url, can't print. Set PYTHONUTF8=1 environment variable to see it.]")

    if timestamp in skip_timestamps:
        print("[Skip: by timestamp command line option]")
        return

    fpath = path.join(DST_DIR, timestamp, get_file_path(original_url))
    if path.isfile(fpath):
        print("[Skip: already on disk]")
        return

    if DRY_RUN:
        print("")  # carriage return
    else:
        retry_count = 0
        url = f"http://web.archive.org/web/{timestamp}id_/{original_url}"
        while retry_count <= RETRIES:
            try:
                if DELAY:
                    time.sleep(DELAY * 2 * retry_count)  # increase delay with each try
                resp = requests.get(url, timeout=TIMEOUT)
                break
            except Exception:
                if retry_count < RETRIES:
                    retry_count += 1
                    new_delay = DELAY * 2 * retry_count
                    print(
                        f"    failed to download, retrying after {new_delay} seconds... ",
                        flush=True,
                    )
                else:
                    if NO_FAIL:
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
            print(f"[Error: {code}]", flush=True)
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
    """
    dirname, basename = path.split(fpath)

    if path.isfile(dirname):
        print(
            f"[Warning] file {dirname} already exists, can't create directory with the same name for {basename}",
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
        file_hash = hashlib.sha1(original_url.encode("utf-8")).hexdigest()
        # Extract extension from original URL path, not the processed basename
        url_parts = urlsplit(original_url)
        file_ext = path.splitext(url_parts.path)[1] if "." in url_parts.path else ".html"
        hash_filename = file_hash + file_ext
        hash_fpath = path.join(timestamp_dir, hash_filename)

        print(
            f"[Warning: could not save full path to filesystem. Using hashed filename {hash_filename}]",
            flush=True,
        )
        try:
            with open(hash_fpath, "wb") as file:
                file.write(content)
            print("[OK]", flush=True)
        except OSError:
            print("[Error: failed to save even with hashed filename, skipped]", flush=True)


def main():
    """Main function to download website snapshots from Internet Archive.

    Downloads all snapshots for the specified domain and date range,
    saving them to the output directory with proper directory structure.
    """
    snap_list = get_snapshot_list()
    download_files(snap_list)
    if DRY_RUN:
        print("Dry run completed.")


if __name__ == "__main__":
    main()
