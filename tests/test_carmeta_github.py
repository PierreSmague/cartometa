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
    """What urlopen returns: a body, or a body that breaks off after `partial`."""

    def __init__(self, body=b"", status=200, headers=None, partial=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}
        self._partial = partial

    def read(self, *args):
        if self._partial is not None:
            raise http.client.IncompleteRead(self._partial)
        return super().read(*args)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def urlopen(monkeypatch):
    """Plays the given outcomes one call after the other; records the requests."""
    played = {"outcomes": [], "requests": []}

    def fake(request, timeout):
        played["requests"].append({k.lower(): v for k, v in request.header_items()})
        outcome = played["outcomes"][len(played["requests"]) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(github.urllib.request, "urlopen", fake)
    monkeypatch.setattr(github.time, "sleep", lambda seconds: None)
    return played


URL = "https://example.invalid/x"


def test_transfers_are_asked_compressed_and_inflated(urlopen):
    urlopen["outcomes"] = [_Response(gzip.compress(b'{"big": "json"}'),
                                     headers={"Content-Encoding": "gzip"})]

    assert github.urllib_fetch(URL, {"User-Agent": "carmeta-sync"}) == b'{"big": "json"}'
    assert urlopen["requests"] == [{"user-agent": "carmeta-sync", "accept-encoding": "gzip"}]


def test_a_plain_download_cut_short_is_resumed_from_where_it_stopped(urlopen):
    urlopen["outcomes"] = [_Response(partial=b"begin"), _Response(partial=b"ning and", status=206),
                           _Response(b" end", status=206)]

    assert github.urllib_fetch(URL, {}) == b"beginning and end"
    assert [r.get("range") for r in urlopen["requests"]] == [None, "bytes=5-", "bytes=13-"]


def test_a_compressed_download_cut_short_starts_over_plain(urlopen):
    urlopen["outcomes"] = [
        _Response(partial=b"\x1f\x8b half", headers={"Content-Encoding": "gzip"}),
        _Response(b"the whole file"),
    ]

    assert github.urllib_fetch(URL, {}) == b"the whole file"
    assert urlopen["requests"] == [{"accept-encoding": "gzip"}, {}]


def test_a_server_that_ignores_the_range_is_read_from_the_start(urlopen):
    urlopen["outcomes"] = [_Response(partial=b"begin"), _Response(b"beginning", status=200)]

    assert github.urllib_fetch(URL, {}) == b"beginning"


def test_a_range_past_the_end_means_the_file_was_already_whole(urlopen):
    urlopen["outcomes"] = [_Response(partial=b"all of it"),
                           urllib.error.HTTPError(URL, 416, "nope", {}, None)]

    assert github.urllib_fetch(URL, {}) == b"all of it"


def test_a_connection_that_keeps_failing_is_one_clean_error(urlopen):
    urlopen["outcomes"] = [urllib.error.URLError("down")] * github.ATTEMPTS

    with pytest.raises(github.GithubError, match=f"after {github.ATTEMPTS} attempts"):
        github.urllib_fetch(URL, {})
    assert len(urlopen["requests"]) == github.ATTEMPTS


def test_a_spent_quota_is_recognised_and_never_retried(urlopen):
    urlopen["outcomes"] = [urllib.error.HTTPError(
        URL, 403, "nope", {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790000000"},
        None)]

    with pytest.raises(github.RateLimited, match="1790000000"):
        github.urllib_fetch(URL, {})
    assert len(urlopen["requests"]) == 1


def test_an_http_status_is_an_answer_not_an_accident(urlopen):
    urlopen["outcomes"] = [urllib.error.HTTPError(URL, 404, "nope", {}, None)]

    with pytest.raises(github.GithubError, match="HTTP 404"):
        github.urllib_fetch(URL, {})
    assert len(urlopen["requests"]) == 1
