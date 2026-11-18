"""The carmeta repository, read through GitHub's public endpoints.

Standard library only, and every function takes the `fetch` it must use: the
tests never touch the network. Requests carry a generic User-Agent and nothing
about who is asking.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

REPOSITORY = "iggedi-ig-ig/carmeta"
BRANCH = "main"
API = f"https://api.github.com/repos/{REPOSITORY}"
RAW = f"https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}"
LFS = f"https://media.githubusercontent.com/media/{REPOSITORY}/{BRANCH}"
USER_AGENT = "carmeta-sync"
TOKEN_ENV = "GITHUB_TOKEN"
TIMEOUT_SECONDS = 120
ATTEMPTS = 6
RETRY_PAUSE_SECONDS = 2.0

# url, headers -> body
Fetch = Callable[[str, dict[str, str]], bytes]


class GithubError(RuntimeError):
    """The repository could not be read."""


class RateLimited(GithubError):
    """The hourly quota of the API is spent (60 calls without a token)."""

    def __init__(self, reset_at: str | None = None) -> None:
        self.reset_at = reset_at
        when = f" (resets at epoch {reset_at})" if reset_at else ""
        super().__init__(
            f"GitHub API rate limit reached{when}. Run again later, or set "
            f"{TOKEN_ENV} to raise the quota: what was already fetched is kept."
        )


class ContentChanged(GithubError):
    """A file changed between the tree listing and its download."""


@dataclass(frozen=True)
class Blob:
    sha: str
    size: int


@dataclass(frozen=True)
class Tree:
    sha: str
    blobs: dict[str, Blob]


def headers() -> dict[str, str]:
    result = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get(TOKEN_ENV)
    if token:
        result["Authorization"] = f"Bearer {token}"
    return result


def urllib_fetch(url: str, request_headers: dict[str, str]) -> bytes:
    """One GET that survives a connection cut short.

    A hundred-megabyte download losing its last kilobytes is the ordinary
    accident here, and it repeats: asking again for the whole file fails the
    same way. So the transfer is first asked compressed (the JSON shrinks about
    fourfold); if it is cut, it is asked again plain and *resumed* with a Range
    request from the bytes already held. `http.client.IncompleteRead` is not an
    `OSError`: without catching it the scheduled task would die on a traceback.
    An HTTP status is an answer, not an accident, and is never retried.
    """
    body = b""
    compressed = True
    failure: Exception | None = None
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(RETRY_PAUSE_SECONDS)
        sent = dict(request_headers)
        if body:
            sent["Range"] = f"bytes={len(body)}-"
        elif compressed:
            sent["Accept-Encoding"] = "gzip"
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=sent), timeout=TIMEOUT_SECONDS
            ) as response:
                gzipped = response.headers.get("Content-Encoding") == "gzip"
                if body and getattr(response, "status", 200) != 206:
                    # The server ignored the range and sent everything again.
                    body = b""
                try:
                    chunk = response.read()
                except http.client.IncompleteRead as exc:
                    failure = exc
                    if gzipped:
                        # Half a compressed stream cannot be resumed.
                        compressed = False
                    else:
                        body += exc.partial
                    continue
                return gzip.decompress(chunk) if gzipped else body + chunk
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and body:
                # Nothing left to send: what was held was already complete.
                return body
            if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
                raise RateLimited(exc.headers.get("X-RateLimit-Reset")) from None
            raise GithubError(f"{url}: HTTP {exc.code}") from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError,
                OSError, EOFError) as exc:
            failure = exc
    raise GithubError(f"{url}: {failure!r} after {ATTEMPTS} attempts") from None


def _api(fetch: Fetch, url: str):
    try:
        return json.loads(fetch(url, headers()))
    except json.JSONDecodeError as exc:
        raise GithubError(f"{url}: unreadable answer ({exc})") from None


def fetch_tree(fetch: Fetch) -> Tree:
    """Every file of the repository with its blob sha, in one single call."""
    payload = _api(fetch, f"{API}/git/trees/{BRANCH}?recursive=1")
    if payload.get("truncated"):
        # A truncated listing would read as "these files were deleted".
        raise GithubError(
            "the repository tree came back truncated: refusing to compare a "
            "partial listing with the local state")
    blobs = {
        entry["path"]: Blob(entry["sha"], int(entry.get("size", 0)))
        for entry in payload.get("tree", [])
        if entry.get("type") == "blob"
    }
    return Tree(sha=payload["sha"], blobs=blobs)


def commit_date(fetch: Fetch, path: str) -> str:
    """ISO date of the last commit that touched `path`.

    Never the date in the file name: the names mix European and American
    formats (`Ireland 08_01_26` was committed on the 1st of August).
    """
    payload = _api(fetch, f"{API}/commits?path={quote(path, safe='')}&per_page=1")
    if not payload:
        raise GithubError(f"{path}: no commit found")
    return payload[0]["commit"]["committer"]["date"]


def blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


_LFS_POINTER = re.compile(
    rb"\Aversion https://git-lfs\.github\.com/spec/v1\n"
    rb"oid sha256:(?P<oid>[0-9a-f]{64})\nsize (?P<size>\d+)\n?\Z")


def download(fetch: Fetch, path: str, expected_sha: str) -> bytes:
    """The content of `path`, checked against the sha the tree announced.

    A file committed between the listing and the download would otherwise be
    stored under the sha of its previous version; it is left for the next run.
    A Git LFS pointer is followed to the object it stands for.
    """
    quoted = quote(path, safe="/")
    raw_headers = {"User-Agent": USER_AGENT}
    raw = fetch(f"{RAW}/{quoted}", raw_headers)
    if blob_sha(raw) != expected_sha:
        raise ContentChanged(f"{path}: content does not match the listed sha")
    pointer = _LFS_POINTER.match(raw)
    if pointer is None:
        return raw
    content = fetch(f"{LFS}/{quoted}", raw_headers)
    if hashlib.sha256(content).hexdigest() != pointer.group("oid").decode():
        raise ContentChanged(f"{path}: LFS object does not match its pointer")
    return content
