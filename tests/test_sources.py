import io
import stat
import zipfile

import pytest

from codewise import sources
from codewise.sources import (GitIgnore, SourceError, filter_uploads, parse_github_url,
                              read_zip)


def make_zip(files, root="repo-abc123/"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for name, content in files.items():
            zf.writestr(root + name, content)
    return buffer.getvalue()


def test_read_zip_strips_root_and_applies_ignore_rules():
    data = make_zip({
        ".gitignore": "secrets/\n*.gen.py\n",
        "src/app.py": "print(1)\n",
        "src/model.gen.py": "x = 1\n",
        "secrets/key.py": "KEY = 1\n",
        "node_modules/lib/index.js": "x\n",
        "package-lock.json": "{}",
        "logo.png": "\x89PNG",
    })
    files, skipped = read_zip(data, max_files=100, max_total_bytes=10_000, max_file_bytes=1000)
    assert [p for p, _ in files] == ["src/app.py"]
    reasons = {s['filename']: s['message'] for s in skipped}
    assert reasons["src/model.gen.py"] == "Ignored by .gitignore"
    assert reasons["secrets/key.py"] == "Ignored by .gitignore"
    assert "node_modules" in reasons["node_modules/lib/index.js"]
    assert "package-lock.json" in reasons["package-lock.json"]


def test_read_zip_limits():
    many = make_zip({f"f{i}.py": "x = 1\n" for i in range(20)})
    with pytest.raises(SourceError, match="files"):
        read_zip(many, max_files=10, max_total_bytes=10_000, max_file_bytes=1000)
    big = make_zip({"a.py": "x" * 5000, "b.py": "y" * 5000})
    with pytest.raises(SourceError, match="expands"):
        read_zip(big, max_files=10, max_total_bytes=6000, max_file_bytes=10_000)
    files, skipped = read_zip(big, max_files=10, max_total_bytes=100_000, max_file_bytes=1000)
    assert files == [] and all("too large" in s['message'] for s in skipped)
    with pytest.raises(SourceError, match="valid zip"):
        read_zip(b"not a zip", 10, 10, 10)


def test_read_zip_blocks_traversal_and_symlinks():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr("../../etc/evil.py", "x = 1\n")
        link = zipfile.ZipInfo("link.py")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(link, "/etc/passwd")
    files, _ = read_zip(buffer.getvalue(), 10, 10_000, 1000)
    assert [p for p, _ in files] == ["etc/evil.py"]  # stays inside the project


def test_nested_gitignore_applies_below_its_directory():
    ignore = GitIgnore()
    ignore.add("pkg/.gitignore", "generated/\n")
    assert ignore.is_ignored("pkg/generated/a.py")
    assert not ignore.is_ignored("other/generated/a.py")


def test_filter_uploads_uses_gitignore_from_the_batch():
    files, skipped, count = filter_uploads([
        (".gitignore", b"build/\n"), ("build/out.py", b"x"), ("src/a.py", b"y"),
    ])
    assert count == 1
    assert [p for p, _ in files] == ["src/a.py"]
    assert skipped[0]['filename'] == "build/out.py"


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/psf/requests", ("psf", "requests", None)),
    ("https://github.com/psf/requests.git", ("psf", "requests", None)),
    ("github.com/psf/requests/tree/v2.0", ("psf", "requests", "v2.0")),
    ("psf/requests", ("psf", "requests", None)),
])
def test_parse_github_url(url, expected):
    assert parse_github_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://gitlab.com/a/b", "http://169.254.169.254/latest", "https://github.com/onlyowner",
    "file:///etc/passwd", "", None,
])
def test_parse_github_url_rejects(url):
    with pytest.raises(SourceError):
        parse_github_url(url)


class FakeResponse:
    def __init__(self, status=200, body=b"", url="https://codeload.github.com/x", headers=None):
        self.status_code = status
        self.body = body
        self.url = url
        self.headers = headers or {}

    def iter_content(self, chunk_size):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_github_zip(monkeypatch):
    calls = []
    monkeypatch.setattr(sources.requests, "get",
                        lambda url, **kw: calls.append((url, kw)) or FakeResponse(body=b"zipdata"))
    assert sources.download_github_zip("psf", "requests", "main", 100, token="t") == b"zipdata"
    assert calls[0][0] == "https://api.github.com/repos/psf/requests/zipball/main"
    assert calls[0][1]['headers']['Authorization'] == "Bearer t"


@pytest.mark.parametrize("response,message", [
    (FakeResponse(status=404), "not found"),
    (FakeResponse(status=403), "rate limit"),
    (FakeResponse(body=b"x" * 500), "too large"),
    (FakeResponse(url="https://evil.example.com/"), "redirect"),
])
def test_download_github_zip_errors(monkeypatch, response, message):
    monkeypatch.setattr(sources.requests, "get", lambda url, **kw: response)
    with pytest.raises(SourceError, match=message):
        sources.download_github_zip("a", "b", None, 100)
