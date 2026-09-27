"""
Where uploaded code comes from: plain files, folders (files with relative paths),
zip archives and GitHub repositories. Everything is normalised into (path, bytes)
pairs, filtered by the project's .gitignore files and the built-in ignore rules.
"""

import io
import posixpath
import re
import stat
import zipfile
from urllib.parse import urlparse

import pathspec
import requests

from .files import FileRejected, check_path, normalize_path


class SourceError(ValueError):
    """The archive or repository could not be read (bad input, too large, not found...)."""


# --- .gitignore -----------------------------------------------------------------------

class GitIgnore:
    """.gitignore rules from any number of directories, each applying to paths below it."""

    def __init__(self):
        self._specs = []  # (directory, spec)

    def add(self, gitignore_path, content):
        directory = posixpath.dirname(gitignore_path)
        spec = pathspec.GitIgnoreSpec.from_lines(content.splitlines())
        self._specs.append((directory, spec))

    def __bool__(self):
        return bool(self._specs)

    def is_ignored(self, path):
        for directory, spec in self._specs:
            if directory and not path.startswith(directory + '/'):
                continue
            relative = path[len(directory) + 1:] if directory else path
            if spec.match_file(relative):
                return True
        return False


def is_gitignore(path):
    return posixpath.basename(path) == '.gitignore'


def collect_gitignores(entries):
    """Build a GitIgnore from the .gitignore files among (path, read_fn) entries."""
    ignore = GitIgnore()
    for path, read in entries:
        if is_gitignore(path):
            ignore.add(path, read().decode('utf-8', errors='replace'))
    return ignore


# --- zip archives ---------------------------------------------------------------------

def _is_symlink(info):
    return stat.S_ISLNK(info.external_attr >> 16)


def _common_root(names):
    """GitHub (and most zip tools) wrap everything in one top-level folder; strip it."""
    tops = {n.split('/', 1)[0] for n in names}
    if len(tops) == 1 and all('/' in n for n in names):
        return next(iter(tops)) + '/'
    return ''


def read_zip(data, max_files, max_total_bytes, max_file_bytes):
    """
    Safely list a zip archive's files as (path, bytes) plus per-entry skip reasons.

    Guards against zip bombs (total/per-file uncompressed size, entry count), path
    traversal (normalize_path) and symlinks. Ignored paths are never decompressed.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SourceError("Not a valid zip archive")

    infos = [i for i in archive.infolist() if not i.is_dir() and not _is_symlink(i)]
    if len(infos) > max_files:
        raise SourceError(f"Archive has {len(infos):,} files (limit {max_files:,})")

    root = _common_root([i.filename for i in infos])
    entries = []
    for info in infos:
        name = info.filename[len(root):]
        try:
            path = normalize_path(name)
        except FileRejected:
            continue
        entries.append((path, info))

    ignore = collect_gitignores((p, lambda i=i: archive.read(i)) for p, i in entries)

    files, skipped, total = [], [], 0
    for path, info in entries:
        if is_gitignore(path):
            continue
        reason = _skip_reason(path, ignore)
        if reason is None and info.file_size > max_file_bytes:
            reason = f"File too large ({info.file_size:,} bytes, limit {max_file_bytes:,})"
        if reason:
            skipped.append({'filename': path, 'success': False, 'skipped': True, 'message': reason})
            continue
        total += info.file_size
        if total > max_total_bytes:
            raise SourceError(f"Archive expands to more than {max_total_bytes:,} bytes of source")
        # Read at most one byte past the declared size in case the header lies.
        with archive.open(info) as fh:
            content = fh.read(max_file_bytes + 1)
        files.append((path, content))
    return files, skipped


def _skip_reason(path, ignore):
    if ignore and ignore.is_ignored(path):
        return "Ignored by .gitignore"
    try:
        check_path(path)
    except FileRejected as e:
        return str(e)
    return None


def filter_uploads(uploads):
    """
    Apply .gitignore files included in an upload batch (folder uploads send them along)
    to the other files in the batch. Returns (files to ingest, skip results, gitignore count).
    """
    ignore = GitIgnore()
    kept = []
    count = 0
    for path, data in uploads:
        if is_gitignore(path):
            ignore.add(path, data.decode('utf-8', errors='replace'))
            count += 1
        else:
            kept.append((path, data))
    if not ignore:
        return kept, [], count
    files, skipped = [], []
    for path, data in kept:
        if ignore.is_ignored(path):
            skipped.append({'filename': path, 'success': False, 'skipped': True,
                            'message': "Ignored by .gitignore"})
        else:
            files.append((path, data))
    return files, skipped, count


# --- GitHub ---------------------------------------------------------------------------

_OWNER_RE = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})'
_REPO_RE = r'[A-Za-z0-9._-]{1,100}'
_ALLOWED_DOWNLOAD_HOSTS = {'api.github.com', 'codeload.github.com'}


def parse_github_url(url, ref=None):
    """
    Accepts https://github.com/owner/repo[.git][/tree/<ref>] or "owner/repo".
    Returns (owner, repo, ref-or-None). Anything else is rejected, so the server
    never fetches arbitrary URLs.
    """
    if not isinstance(url, str) or not url.strip():
        raise SourceError("Repository URL is required")
    url = url.strip()
    if re.fullmatch(rf'{_OWNER_RE}/{_REPO_RE}', url):
        owner, repo = url.split('/')
        rest = ''
    else:
        parsed = urlparse(url if '://' in url else f'https://{url}')
        if parsed.scheme not in ('https', 'http') or parsed.hostname not in ('github.com', 'www.github.com'):
            raise SourceError("Only github.com repository URLs are supported")
        match = re.fullmatch(rf'/({_OWNER_RE})/({_REPO_RE}?)(?:\.git)?(/.*)?/?', parsed.path)
        if not match:
            raise SourceError("URL must look like https://github.com/owner/repo")
        owner, repo, rest = match.group(1), match.group(2), match.group(3) or ''
    repo = repo[:-4] if repo.endswith('.git') else repo
    if repo in ('.', '..') or not repo:
        raise SourceError("Invalid repository name")

    tree = re.match(r'^/tree/(.+?)/?$', rest)
    ref = ref or (tree.group(1) if tree else None)
    if ref is not None and not re.fullmatch(r'[A-Za-z0-9._/-]{1,200}', ref):
        raise SourceError("Invalid branch or tag name")
    return owner, repo, ref


def download_github_zip(owner, repo, ref, max_bytes, token=None, timeout=60):
    """Download a repository snapshot as a zip via the GitHub API (default branch if ref is None)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/zipball" + (f"/{ref}" if ref else "")
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'CodeWise'}
    if token:
        headers['Authorization'] = f"Bearer {token}"
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=timeout)
    except requests.RequestException as e:
        raise SourceError(f"Could not reach GitHub: {e}")

    with response:
        if urlparse(response.url).hostname not in _ALLOWED_DOWNLOAD_HOSTS:
            raise SourceError("Unexpected redirect while downloading repository")
        if response.status_code == 404:
            raise SourceError(f"Repository {owner}/{repo}"
                              + (f" at '{ref}'" if ref else "")
                              + " not found (private repositories need CODEWISE_GITHUB_TOKEN)")
        if response.status_code in (401, 403):
            raise SourceError("GitHub refused the request (rate limit or missing access); "
                              "set CODEWISE_GITHUB_TOKEN to authenticate")
        if response.status_code != 200:
            raise SourceError(f"GitHub returned HTTP {response.status_code}")

        declared = response.headers.get('Content-Length')
        if declared and int(declared) > max_bytes:
            raise SourceError(f"Repository archive is too large (limit {max_bytes:,} bytes)")
        buffer = io.BytesIO()
        for block in response.iter_content(chunk_size=1 << 16):
            buffer.write(block)
            if buffer.tell() > max_bytes:
                raise SourceError(f"Repository archive is too large (limit {max_bytes:,} bytes)")
    return buffer.getvalue()
