import hashlib
import json

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
