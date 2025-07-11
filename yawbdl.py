#!/usr/bin/env python3

"""Yet Another Wayback Downloader.

A tool to download archived websites from Internet Archive's Wayback Machine.
Downloads all snapshots for a given domain within a specified date range,
preserving the original directory structure when possible.
"""

import argparse
from dataclasses import dataclass
import functools
import hashlib
import json
import os
from os import path
import re
import shutil
import sys
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from loguru import logger
import requests

# Configure loguru for console-only output
logger.remove()
logger.add(sys.stdout, format="<level>{message}</level>", level="INFO")

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
    help="if retries are exceeded, and the file still couldn't have been downloaded, "
    "proceed to the next file instead of aborting the run",
)
parser.add_argument(
    "--skip-timestamps",
    default=None,
    action="append",
    nargs="+",
    help="skip snapshots with these timestamps (sometimes Internet Archive just fails to serve a specific snapshot)",
)
parser.add_argument(
    "--latest-only",
    action="store_true",
    default=False,
    help="download only the latest version of each URL",
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

# Add file logger
os.makedirs(DST_DIR, exist_ok=True)
LOG_FILE = path.join(DST_DIR, "yawbdl.log")
if path.exists(LOG_FILE):
    os.remove(LOG_FILE)
logger.add(LOG_FILE, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

# Type alias for snapshot records
Snapshot = tuple[str, str]
SnapshotList = list[Snapshot]


@dataclass
class DownloadContext:
    """Context information for a download operation."""

    current: int
    total: int
    timestamp: str
    original_url: str


def retry_download(func: Callable[..., Any]) -> Callable[..., Any | None]:
    """Decorator that adds retry logic with linear backoff to download functions.

    When @retry_download decorates a function, it replaces that function with a wrapper
    that catches exceptions and retries with linearly increasing delays (DELAY * 2 * retry_count).

    On first failure: logs full URL line with retry message
    On subsequent failures: logs indented continuation messages
    After max retries: proceeds to next file (NO_FAIL=True) or exits program

    The wrapper can have _url_context attribute set for progress logging:
        setattr(fetch_url, "_url_context", (current, total, timestamp, original_url))
    """

    @functools.wraps(func)
    def wrapper(*func_args: Any, **func_kwargs: Any) -> Any | None:
        retry_count = 0
        while retry_count <= RETRIES:
            try:
                if DELAY and retry_count > 0:
                    time.sleep(DELAY * 2 * retry_count)
                return func(*func_args, **func_kwargs)
            except Exception:  # pylint: disable=broad-except
                if retry_count < RETRIES:
                    retry_count += 1
                    new_delay = DELAY * 2 * retry_count
                    if hasattr(wrapper, "_url_context"):
                        # Show URL with retry message for each attempt
                        url_context = getattr(wrapper, "_url_context")
                        current, total, timestamp, original_url = url_context
                        context = DownloadContext(current, total, timestamp, original_url)
                        log_status(
                            context,
                            f"[Failed to download, retrying after {new_delay} seconds...]",
                            "warning",
                        )
                    else:
                        # Fallback for functions without URL context
                        logger.warning(f"Failed to download, retrying after {new_delay} seconds...")
                else:
                    if hasattr(wrapper, "_url_context"):
                        url_context = getattr(wrapper, "_url_context")
                        current, total, timestamp, original_url = url_context
                        context = DownloadContext(current, total, timestamp, original_url)
                        if NO_FAIL:
                            log_status(context, "[Failed to download, proceeding to next file]", "warning")
                            return None
                        log_status(context, f"[{RETRIES} retries failed, aborted]", "error")
                        sys.exit(1)
                    else:
                        # Fallback for functions without URL context. That's only snapshots.
                        logger.error(f"{RETRIES} retries failed, aborting")
                        sys.exit(1)
        return None  # This line should never be reached but satisfies pylint

    return wrapper


def get_snapshot_timestamp(snap: Snapshot) -> str:
    """Extract timestamp from snapshot tuple for sorting."""
    return snap[0]


def get_hashed_file_path(original_url: str, timestamp_dir: str) -> tuple[str, str]:
    """Generate hashed filename and full path for fallback saves.

    Args:
        original_url: The original URL to hash
        timestamp_dir: Directory where the hashed file should be saved

    Returns:
        Tuple of (full_path, filename) for the hashed file
    """
    file_hash = hashlib.sha1(original_url.encode("utf-8")).hexdigest()
    url_parts = urlsplit(original_url)
    file_ext = path.splitext(url_parts.path)[1] or ".html"
    hashed_filename = file_hash + file_ext
    hash_fpath = path.join(timestamp_dir, hashed_filename)
    return hash_fpath, hashed_filename


def get_latest_snapshots(snapshot_list: SnapshotList) -> SnapshotList:
    """Filter snapshot list to keep only the latest version of each URL.

    Args:
        snapshot_list: List of (timestamp, url) tuples, assumed to be sorted by timestamp

    Returns:
        Filtered list with only the latest timestamp for each unique URL
    """
    url_to_latest: dict[str, Snapshot] = {}

    for snap in snapshot_list:
        _, url = snap
        # Since list is sorted by timestamp, later entries will overwrite earlier ones
        url_to_latest[url] = snap

    # Return in original timestamp order
    result = list(url_to_latest.values())
    result.sort(key=get_snapshot_timestamp)
    return result


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


def build_snapshots_url(domain: str) -> str:
    """Build the full CDX API URL for retrieving all snapshots for a domain.

    Args:
        domain: The domain to query snapshots for

    Returns:
        Complete CDX API URL for all snapshots of the domain
    """
    cdx_url = "http://web.archive.org/cdx/search/cdx?"
    params = f"output=json&url={domain}&matchType=host&filter=statuscode:200&fl=timestamp,original"
    return cdx_url + params


def get_snapshot_list() -> SnapshotList:
    """Load cached snapshot list from file or download from Internet Archive.

    Always downloads the complete snapshot list for the domain, then applies
    timestamp filtering dynamically based on command line arguments.

    Returns:
        List of snapshot records, each containing (timestamp, original_url)
    """
    logger.info("Getting snapshot list...")

    # Try cached snapshots
    snapshots_path = path.join(DST_DIR, "snapshots.json")
    snap_list: SnapshotList = []

    try:
        with open(snapshots_path, encoding="utf-8") as fh:
            raw_list = json.load(fh)
            # Convert to properly typed list
            snap_list = [(str(item[0]), str(item[1])) for item in raw_list]
        logger.info("Found cached snapshots.json")
    except:  # pylint: disable=bare-except  # we don't care about the exception type here
        # No cache, downloading full snapshot list
        url = build_snapshots_url(args.domain)
        resp = fetch_snapshots(url)

        if resp is None:  # Failed after all retries
            logger.error("    failed to get snapshot list, aborting!")
            sys.exit(1)

        if resp.status_code != 200:
            logger.error(f"[HTTP status code: {resp.status_code}]")
            logger.error("    failed to get snapshot list, aborting!")
            sys.exit(1)

        raw_list = resp.json()
        with open(snapshots_path, "w", encoding="utf-8") as fh:
            json.dump(raw_list, fh)

        # Convert to properly typed list
        snap_list = [(str(item[0]), str(item[1])) for item in raw_list]

    if len(snap_list) == 0:
        logger.warning("Sorry, no snapshots found!")
        sys.exit(1)

    # Remove header row
    if snap_list:
        snap_list = snap_list[1:]

    # Apply timestamp filtering dynamically
    if args.from_date or args.to_date:
        original_count = len(snap_list)

        snap_list = list(
            filter(
                lambda snap: (not args.from_date or snap[0] >= args.from_date.ljust(14, "0"))
                and (not args.to_date or snap[0] <= args.to_date.ljust(14, "0")),
                snap_list,
            )
        )
        filtered_count = len(snap_list)
        logger.info(f"Applied timestamp filters: {original_count} -> {filtered_count} snapshots")

    snap_list.sort(key=get_snapshot_timestamp)  # sort by timestamp

    # Apply latest-only filtering if requested
    if args.latest_only:
        original_count = len(snap_list)
        snap_list = get_latest_snapshots(snap_list)
        filtered_count = len(snap_list)
        logger.info(f"Filtered to latest versions only: {original_count} -> {filtered_count} snapshots")

    logger.info("Got snapshot list!")
    return snap_list


def download_files(snapshot_list: SnapshotList):
    """Download all files from snapshot list with progress tracking.

    Args:
        snapshot_list: List of snapshot records, each containing (timestamp, original_url)
    """
    total = len(snapshot_list)
    for i, snap in enumerate(snapshot_list, 1):
        download_file(snap, i, total)


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


@retry_download
def fetch_snapshots(url: str) -> requests.Response | None:
    """Fetch snapshots list from CDX API with retry logic."""
    return requests.get(url, timeout=TIMEOUT)


@retry_download
def fetch_url(url: str) -> requests.Response | None:
    """Fetch content from URL with retry logic."""
    return requests.get(url, timeout=TIMEOUT)


def log_status(context: DownloadContext, status: str, level: str = "info"):
    """Log download status with progress counter, URL and result on same line."""
    try:
        message = f"({context.current}/{context.total}) {context.timestamp} {context.original_url} {status}"
    except:  # pylint: disable=bare-except
        message = f"({context.current}/{context.total}) {context.timestamp} [url malformed] {status}"
    getattr(logger, level)(message)


def download_file(snap: tuple[str, str], current: int, total: int):
    """Download and save a single URL from Internet Archive snapshot.

    Downloads content from Internet Archive for given timestamp and URL,
    then saves it to local filesystem with retry logic.

    Args:
        snap: Tuple containing (timestamp, original_url)
        current: Current file number
        total: Total number of files
    """
    timestamp: str = snap[0]
    original_url: str = snap[1]
    context = DownloadContext(current, total, timestamp, original_url)

    if timestamp in skip_timestamps:
        log_status(context, "[SKIP: by timestamp command line option]")
        return

    fpath = path.join(DST_DIR, timestamp, get_file_path(original_url))
    if path.isfile(fpath):
        log_status(context, "[SKIP: already on disk]")
        return

    # Also check if hashed filename exists (fallback save location)
    hash_fpath, hashed_filename = get_hashed_file_path(original_url, path.join(DST_DIR, timestamp))
    if path.isfile(hash_fpath):
        log_status(context, f"[SKIP: hashed filename {hashed_filename} already on disk]")
        return

    if DRY_RUN:
        log_status(context, "[DRY RUN]")
        return

    url = f"http://web.archive.org/web/{timestamp}id_/{original_url}"

    # Set context for this specific download
    setattr(fetch_url, "_url_context", (current, total, timestamp, original_url))

    resp = fetch_url(url)

    if resp is None:  # Failed after all retries with NO_FAIL=True
        # Don't log again since retry decorator already handled it
        return

    code = resp.status_code
    if code != 200:
        log_status(context, f"[HTTP code: {code}]", "error")
    else:
        content = resp.content
        if len(content) == 0:
            log_status(context, "[SKIP: file size is 0]")
        else:
            write_file(fpath, content, path.join(DST_DIR, timestamp), original_url, context)


def write_file(fpath: str, content: bytes, timestamp_dir: str, original_url: str, context: DownloadContext) -> None:
    """Write content to file with hash filename fallback on filesystem errors.

    Attempts to save file with original path structure. If that fails due to filesystem
    limitations (path length, invalid characters, etc.), cleans up empty directories
    and saves with SHA-1 hash of original URL as filename under timestamp directory.
    Handles all logging internally.

    Args:
        fpath: Full file path where content should be saved
        content: File content as bytes
        timestamp_dir: Timestamp directory path (e.g., DST_DIR/timestamp)
        original_url: Original URL from Internet Archive for hash generation
        context: Download context for logging
    """
    dirname, _ = path.split(fpath)

    if path.isfile(dirname):
        log_status(
            context,
            f"[SKIP: could not save] File {dirname} already exists, can't create directory with the same name",
            "error",
        )
        return

    # Try to create directory and write file normally
    try:
        os.makedirs(dirname, exist_ok=True)
        with open(fpath, "wb") as file:
            file.write(content)
        log_status(context, "[OK]", "success")
        return
    except OSError as e:
        # Cleanup any directories that might have been created
        cleanup_empty_directory(dirname, timestamp_dir)

        # Use SHA-1 hash as fallback filename, save directly under timestamp directory
        hash_fpath, hashed_filename = get_hashed_file_path(original_url, timestamp_dir)

        try:
            with open(hash_fpath, "wb") as file:
                file.write(content)
            log_status(
                context,
                f"[OK: could not save to original path ({e}), used hashed filename {hashed_filename}]",
                "success",
            )
            return
        except OSError as e2:
            log_status(
                context,
                f"[SKIP: could not save - hashed filename {hashed_filename} also failed ({e2})]",
                "error",
            )
            return


def main():
    """Main function to download website snapshots from Internet Archive.

    Downloads all snapshots for the specified domain and date range,
    saving them to the output directory with proper directory structure.
    """
    snap_list = get_snapshot_list()
    download_files(snap_list)
    if DRY_RUN:
        logger.info("Dry run completed.")


if __name__ == "__main__":
    main()
