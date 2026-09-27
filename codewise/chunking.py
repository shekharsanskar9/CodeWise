"""
Structure-aware code chunking.

Files are first cut into *segments* that follow the code's structure (Python AST nodes,
brace-delimited blocks for C-like languages, headings for Markdown). Small neighbouring
segments are then packed together up to ``max_chars``; segments that are still too
large are split into overlapping line windows. Line numbers are 1-based and inclusive.
"""

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .files import get_file_type

BRACE_EXTENSIONS = {'.js', '.jsx', '.ts', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
                    '.cs', '.go', '.rs', '.php', '.swift', '.kt', '.css'}

_SYMBOL_PATTERNS = [
    re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)'),
    re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:(?:public|private|protected|internal|abstract|static|final|sealed|partial|data|open)\s+)*'
               r'(?:class|interface|struct|enum|trait|object|record|impl)\s+([A-Za-z_]\w*)'),
    re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?'
               r'(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|[A-Za-z_$][\w$]*\s*=>)'),
    re.compile(r'^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)'),
    re.compile(r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)'),
    re.compile(r'^\s*(?:(?:public|private|protected|internal|override|open|suspend|inline)\s+)*fun\s+(?:<[^>]*>\s*)?([A-Za-z_]\w*)'),
    # Java / C# / C++ style method signatures: "<modifiers/type> name(...)" not ending in ';'
    re.compile(r'^\s*(?!(?:return|await|new|throw|else|case|yield|typeof|delete|void|goto)\b)'
               r'(?:(?:public|private|protected|internal|static|final|virtual|override|async|const|inline|unsigned)\s+)*'
               r'[A-Za-z_][\w<>\[\],:*&\s]*?\s+\**([A-Za-z_]\w*)\s*\([^;]*$'),
]
_NOT_SYMBOLS = {'if', 'for', 'while', 'switch', 'return', 'else', 'catch', 'do', 'new', 'sizeof', 'elif'}

_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`')


@dataclass
class Chunk:
    path: str
    index: int
    start_line: int
    end_line: int
    content: str
    symbol: str = None
    file_type: str = 'code'

    @property
    def chunk_id(self):
        # Path + position + content: identical boilerplate in two files (licence headers,
        # empty __init__.py, ...) no longer collides onto the same ID.
        path_hash = hashlib.sha1(self.path.encode()).hexdigest()[:16]
        content_hash = hashlib.sha1(self.content.encode()).hexdigest()[:12]
        return f"{path_hash}:{self.index}:{content_hash}"

    @property
    def header(self):
        header = f"File: {self.path}\n"
        if self.symbol:
            header += f"Symbol: {self.symbol}\n"
        header += f"Lines: {self.start_line}-{self.end_line}\n"
        return header

    @property
    def search_text(self):
        """Text used for embedding and keyword search: location header plus code."""
        return f"{self.header}\n{self.content}"

    def metadata(self):
        return {
            'filename': self.path,
            'chunk_index': self.index,
            'start_line': self.start_line,
            'end_line': self.end_line,
            'symbol': self.symbol or '',
            'file_type': self.file_type,
        }


def split_lines(content):
    lines = content.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return lines


def chunk_code(content, path, max_chars=1500, overlap_lines=5):
    """Split a file into structure-aware chunks."""
    lines = split_lines(content)
    if not any(line.strip() for line in lines):
        return []

    ext = PurePosixPath(path).suffix.lower()
    segments = None
    if ext == '.py':
        segments = _python_segments(lines, max_chars)
    elif ext in BRACE_EXTENSIONS:
        segments = _brace_segments(lines)
    elif ext == '.md':
        segments = _markdown_segments(lines)
    if not segments:
        segments = [(1, len(lines), None)]

    file_type = get_file_type(path)
    chunks = []
    for start, end, symbol in _pack(lines, segments, max_chars, overlap_lines):
        text = '\n'.join(lines[start - 1:end])
        if not text.strip():
            continue
        chunks.append(Chunk(path=path, index=len(chunks), start_line=start, end_line=end,
                            content=text, symbol=symbol, file_type=file_type))
    return chunks


# --- segmentation ---------------------------------------------------------------------

def _python_segments(lines, max_chars):
    try:
        tree = ast.parse('\n'.join(lines))
    except (SyntaxError, ValueError):
        return None
    return _python_body_segments(lines, tree.body, 1, len(lines), '', None, max_chars)


def _python_body_segments(lines, body, region_start, region_end, prefix, gap_symbol, max_chars):
    segments = []
    cursor = region_start
    for node in body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, 'decorator_list', [])])
        # Attach comment lines directly above a definition to it.
        while start - 1 >= cursor and lines[start - 2].strip().startswith('#'):
            start -= 1
        start = max(start, cursor)
        end = node.end_lineno
        if end < cursor:
            continue
        if start > cursor:
            segments.append((cursor, start - 1, gap_symbol))

        name = getattr(node, 'name', None)
        symbol = f"{prefix}{name}" if name else gap_symbol
        size = sum(len(line) + 1 for line in lines[start - 1:end])
        if isinstance(node, ast.ClassDef) and size > max_chars and node.body:
            # Large class: split into its header and one segment per method.
            segments.extend(_python_body_segments(lines, node.body, start, end,
                                                  f"{symbol}.", symbol, max_chars))
        else:
            segments.append((start, end, symbol))
        cursor = end + 1
    if cursor <= region_end:
        segments.append((cursor, region_end, gap_symbol))
    return segments


def _brace_segments(lines):
    segments = []
    depth = 0
    opened = False
    seg_start = 1
    in_block_comment = False
    for i, line in enumerate(lines, 1):
        code, in_block_comment = _strip_non_code(line, in_block_comment)
        for ch in code:
            if ch == '{':
                depth += 1
                opened = True
            elif ch == '}':
                depth = max(0, depth - 1)
        if opened and depth == 0:
            segments.append((seg_start, i, _find_symbol(lines[seg_start - 1:i])))
            seg_start = i + 1
            opened = False
    if seg_start <= len(lines):
        segments.append((seg_start, len(lines), _find_symbol(lines[seg_start - 1:])))
    return segments


def _strip_non_code(line, in_block_comment):
    """Remove string literals and comments so braces inside them are not counted."""
    out = []
    i = 0
    if in_block_comment:
        end = line.find('*/')
        if end == -1:
            return '', True
        i = end + 2
    rest = _STRING_RE.sub('""', line[i:])
    while rest:
        line_comment = rest.find('//')
        block_comment = rest.find('/*')
        if line_comment != -1 and (block_comment == -1 or line_comment < block_comment):
            out.append(rest[:line_comment])
            return ''.join(out), False
        if block_comment == -1:
            out.append(rest)
            return ''.join(out), False
        out.append(rest[:block_comment])
        end = rest.find('*/', block_comment + 2)
        if end == -1:
            return ''.join(out), True
        rest = rest[end + 2:]
    return ''.join(out), False


def _find_symbol(segment_lines, limit=3):
    found = []
    for line in segment_lines:
        for pattern in _SYMBOL_PATTERNS:
            match = pattern.match(line)
            if match and match.group(1) not in _NOT_SYMBOLS:
                if match.group(1) not in found:
                    found.append(match.group(1))
                break
        if len(found) >= limit:
            break
    return ', '.join(found) or None


def _markdown_segments(lines):
    segments = []
    seg_start = 1
    heading = None
    in_fence = False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
        if not in_fence and re.match(r'^#{1,6}\s', line) and i > seg_start:
            segments.append((seg_start, i - 1, heading))
            seg_start = i
        if not in_fence and re.match(r'^#{1,6}\s', line):
            heading = line.lstrip('#').strip()
    segments.append((seg_start, len(lines), heading))
    return segments


# --- packing --------------------------------------------------------------------------

def _pack(lines, segments, max_chars, overlap_lines):
    """Merge small adjacent segments and split oversized ones into line windows."""
    def size(start, end):
        return sum(len(line) + 1 for line in lines[start - 1:end])

    packed = []
    current = None  # [start, end, [symbols]]

    def flush():
        nonlocal current
        if current:
            symbols = [s for s in current[2] if s]
            packed.append((current[0], current[1], ', '.join(dict.fromkeys(symbols)) or None))
            current = None

    for start, end, symbol in segments:
        seg_size = size(start, end)
        if seg_size > max_chars:
            flush()
            packed.extend(_windows(lines, start, end, symbol, max_chars, overlap_lines))
            continue
        if current and size(current[0], end) <= max_chars:
            current[1] = end
            current[2].append(symbol)
        else:
            flush()
            current = [start, end, [symbol]]
    flush()
    return packed


def _windows(lines, start, end, symbol, max_chars, overlap_lines):
    windows = []
    win_start = start
    while win_start <= end:
        win_end = win_start
        total = len(lines[win_start - 1]) + 1
        while win_end < end and total + len(lines[win_end]) + 1 <= max_chars:
            total += len(lines[win_end]) + 1
            win_end += 1
        windows.append((win_start, win_end, symbol))
        if win_end >= end:
            break
        # Step back for overlap, but always make progress.
        win_start = max(win_end + 1 - overlap_lines, win_start + 1)
    return windows


def number_lines(content, start_line):
    """Prefix each line with its 1-based line number so the LLM can cite real lines."""
    lines = content.split('\n')
    width = len(str(start_line + len(lines) - 1))
    return '\n'.join(f"{start_line + i:>{width}} | {line}" for i, line in enumerate(lines))
