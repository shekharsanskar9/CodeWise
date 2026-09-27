"""
Upload validation: path normalisation, ignore rules, size limits and decoding.
"""

import posixpath
from pathlib import PurePosixPath

SUPPORTED_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.hpp',
                        '.cs', '.go', '.rb', '.php', '.swift', '.kt', '.rs', '.txt',
                        '.md', '.json', '.yaml', '.yml', '.xml', '.html', '.css', '.sql', '.toml'}

# Directories whose contents are generated, vendored or otherwise noise for Q&A.
IGNORED_DIRS = {'node_modules', '.git', 'dist', 'build', 'out', 'venv', '.venv', 'env',
                '__pycache__', '.next', '.nuxt', 'coverage', '.pytest_cache', '.mypy_cache',
                'target', 'vendor', '.idea', '.vscode', 'chroma_data'}

# Lockfiles and similar machine-written files that flood the index with useless chunks.
IGNORED_FILENAMES = {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock',
                     'Pipfile.lock', 'Cargo.lock', 'composer.lock', 'Gemfile.lock', 'go.sum'}

IGNORED_SUFFIXES = ('.min.js', '.min.css', '.map', '.bundle.js')

# Lines this long on average mean minified/generated code.
MINIFIED_AVG_LINE_LENGTH = 300


class FileRejected(ValueError):
    """Raised when an uploaded file should not be indexed."""


def normalize_path(raw_name):
    """
    Turn a client-supplied filename into a safe, relative POSIX path.

    Directory components are kept (so src/utils.py and tests/utils.py stay distinct),
    but absolute paths and '..' segments are stripped.
    """
    if not raw_name:
        raise FileRejected("No file selected")
    name = raw_name.replace('\\', '/')
    parts = [p for p in name.split('/') if p not in ('', '.', '..')]
    if not parts:
        raise FileRejected(f"Invalid filename: {raw_name!r}")
    return posixpath.join(*parts)


def check_path(path):
    """Reject paths that are unsupported or match the ignore rules."""
    p = PurePosixPath(path)
    ignored_dir = next((d for d in p.parts[:-1] if d in IGNORED_DIRS), None)
    if ignored_dir:
        raise FileRejected(f"Ignored directory: {ignored_dir}/")
    if p.name in IGNORED_FILENAMES:
        raise FileRejected(f"Ignored generated file: {p.name}")
    if p.name.lower().endswith(IGNORED_SUFFIXES):
        raise FileRejected(f"Ignored minified/generated file: {p.name}")
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise FileRejected(f"Unsupported file type: {p.suffix or '(none)'}")


def decode_content(raw, max_bytes):
    """Decode uploaded bytes, rejecting binaries, oversized and minified files."""
    if len(raw) > max_bytes:
        raise FileRejected(f"File too large ({len(raw):,} bytes, limit {max_bytes:,})")
    if b'\x00' in raw[:8192]:
        raise FileRejected("File looks binary")
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            content = raw.decode('cp1252')
        except UnicodeDecodeError:
            raise FileRejected("File is not valid UTF-8 or cp1252 text")

    content = content.replace('\r\n', '\n').replace('\r', '\n')
    lines = content.split('\n')
    if len(content) > 2000 and len(content) / max(len(lines), 1) > MINIFIED_AVG_LINE_LENGTH:
        raise FileRejected("File looks minified or generated")
    return content


def get_file_type(filename):
    """Determine file type from extension"""
    ext = PurePosixPath(filename).suffix.lower()
    if ext in {'.py'}:
        return 'python'
    elif ext in {'.js', '.jsx', '.ts', '.tsx'}:
        return 'javascript'
    elif ext in {'.java'}:
        return 'java'
    elif ext in {'.cpp', '.c', '.h', '.hpp'}:
        return 'cpp'
    elif ext in {'.cs'}:
        return 'csharp'
    elif ext in {'.go'}:
        return 'golang'
    elif ext in {'.md', '.txt'}:
        return 'text'
    else:
        return 'code'
