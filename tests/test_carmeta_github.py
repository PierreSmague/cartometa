import gzip
import hashlib
import http.client
import io
import json
import urllib.error

import pytest

from cartometa.carmeta import github
from tests.carmeta_helpers import FakeGithub


def test_the_tree_lists_every_blob_in_one_call():
    fake = FakeGithub({"Europe/France/France.json": b"{}", "README.md": b"hello"})

    tree = github.fetch_tree(fake)

    assert set(tree.blobs) == {"Europe/France/France.json", "README.md"}
    assert tree.blobs["README.md"] == github.Blob(github.blob_sha(b"hello"), 5)
    assert tree.sha == fake.tree_sha()
    assert len(fake.calls) == 1


def test_a_truncated_tree_is_refused():
    def fetch(url, headers):
        return json.dumps({"sha": "abc", "truncated": True, "tree": []}).encode()

    with pytest.raises(github.GithubError, match="truncated"):
        github.fetch_tree(fetch)


def test_the_blob_sha_is_gits_own():
    # `git hash-object` of a file holding "hello\n".
    assert github.blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_a_path_with_spaces_and_parentheses_is_encoded():
    path = "Europe/Baltics/Baltics 70K (24.03.26).json"
    fake = FakeGithub({path: b"{}"}, {path: "2026-05-06T13:05:16Z"})

    assert github.commit_date(fake, path) == "2026-05-06T13:05:16Z"
    assert github.download(fake, path, github.blob_sha(b"{}")) == b"{}"

    api, raw = fake.calls
    assert "path=Europe%2FBaltics%2FBaltics%2070K%20%2824.03.26%29.json" in api
    assert raw.endswith("/Europe/Baltics/Baltics%2070K%20%2824.03.26%29.json")


def test_a_file_that_changed_since_the_listing_is_refused():
    fake = FakeGithub({"Europe/a.json": b"new content"})

    with pytest.raises(github.ContentChanged):
        github.download(fake, "Europe/a.json", github.blob_sha(b"old content"))


def test_an_lfs_pointer_is_followed_and_checked():
    content = b'{"customCoordinates": []}'
    pointer = (b"version https://git-lfs.github.com/spec/v1\n"
               b"oid sha256:" + hashlib.sha256(content).hexdigest().encode()
               + b"\nsize %d\n" % len(content))
    served = {f"{github.RAW}/Asia/big.json": pointer, f"{github.LFS}/Asia/big.json": content}

    assert github.download(lambda url, headers: served[url], "Asia/big.json",
                           github.blob_sha(pointer)) == content

    served[f"{github.LFS}/Asia/big.json"] = b"something else"
    with pytest.raises(github.ContentChanged, match="LFS"):
        github.download(lambda url, headers: served[url], "Asia/big.json",
                        github.blob_sha(pointer))


def test_requests_carry_a_generic_agent_and_nothing_personal(monkeypatch):
    monkeypatch.delenv(github.TOKEN_ENV, raising=False)
    fake = FakeGithub({"Europe/a.json": b"{}"})

    github.fetch_tree(fake)
    github.commit_date(fake, "Europe/a.json")
    github.download(fake, "Europe/a.json", github.blob_sha(b"{}"))

    assert fake.headers[0] == {"User-Agent": "carmeta-sync",
                               "Accept": "application/vnd.github+json"}
    assert fake.headers[2] == {"User-Agent": "carmeta-sync"}


def test_the_token_is_sent_to_the_api_only(monkeypatch):
    monkeypatch.setenv(github.TOKEN_ENV, "s3cret")
    fake = FakeGithub({"Europe/a.json": b"{}"})

    github.fetch_tree(fake)
    github.download(fake, "Europe/a.json", github.blob_sha(b"{}"))

    assert fake.headers[0]["Authorization"] == "Bearer s3cret"
    assert "Authorization" not in fake.headers[1]


class _Response(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(outcomes):
    """A stand-in for urlopen that plays `outcomes` one call after the other."""
    calls = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)

    return urlopen, calls


def test_a_download_cut_short_is_retried(monkeypatch):
    urlopen, calls = _urlopen([http.client.IncompleteRead(b"par"), b"complete"])
    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(github.time, "sleep", lambda seconds: None)

    assert github.urllib_fetch("https://example.invalid/x", {}) == b"complete"
    assert len(calls) == 2


def test_a_connection_that_keeps_failing_is_one_clean_error(monkeypatch):
    urlopen, calls = _urlopen([urllib.error.URLError("down")] * github.ATTEMPTS)
    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(github.time, "sleep", lambda seconds: None)

    with pytest.raises(github.GithubError, match="after 3 attempts"):
        github.urllib_fetch("https://example.invalid/x", {})
    assert len(calls) == github.ATTEMPTS


def _http_error(code, headers):
    return urllib.error.HTTPError("https://example.invalid/x", code, "nope", headers, None)


def test_a_spent_quota_is_recognised_and_never_retried(monkeypatch):
    urlopen, calls = _urlopen([_http_error(403, {"X-RateLimit-Remaining": "0",
                                                 "X-RateLimit-Reset": "1790000000"})])
    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)

    with pytest.raises(github.RateLimited, match="1790000000"):
        github.urllib_fetch("https://example.invalid/x", {})
    assert len(calls) == 1


def test_an_http_status_is_an_answer_not_an_accident(monkeypatch):
    urlopen, calls = _urlopen([_http_error(404, {})])
    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)

    with pytest.raises(github.GithubError, match="HTTP 404"):
        github.urllib_fetch("https://example.invalid/x", {})
    assert len(calls) == 1


def test_transfers_are_compressed_and_transparently_inflated(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen.update(request.header_items())
        response = _Response(gzip.compress(b'{"big": "json"}'))
        response.headers = {"Content-Encoding": "gzip"}
        return response

    monkeypatch.setattr(github.urllib.request, "urlopen", urlopen)

    assert github.urllib_fetch("https://example.invalid/x", {"User-Agent": "carmeta-sync"}) \
        == b'{"big": "json"}'
    assert seen == {"User-agent": "carmeta-sync", "Accept-encoding": "gzip"}
