from codewise.chunking import chunk_code, number_lines

PYTHON_SOURCE = '''import os


def alpha():
    return 1


# helper comment
@decorator
def beta(x):
    return x * 2


class Gamma:
    def one(self):
        return 1
'''


def lines_of(content):
    return content.split('\n')


def test_line_numbers_are_one_based_and_inclusive():
    chunks = chunk_code("a = 1\nb = 2\nc = 3\n", "x.py")
    assert len(chunks) == 1
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 3)


def test_python_chunks_follow_definitions():
    chunks = chunk_code(PYTHON_SOURCE, "mod.py", max_chars=60)
    by_symbol = {c.symbol: c for c in chunks}
    beta = by_symbol['beta']
    # decorator and the comment above it belong to the function
    assert beta.content.startswith('# helper comment\n@decorator\ndef beta')
    assert beta.start_line == 8
    assert 'Gamma' in by_symbol


def test_chunks_cover_file_and_match_line_numbers():
    chunks = chunk_code(PYTHON_SOURCE, "mod.py", max_chars=60)
    src = lines_of(PYTHON_SOURCE)
    for c in chunks:
        assert c.content == '\n'.join(src[c.start_line - 1:c.end_line])
    covered = set()
    for c in chunks:
        covered.update(range(c.start_line, c.end_line + 1))
    non_blank = {i for i, line in enumerate(src, 1) if line.strip()}
    assert non_blank <= covered


def test_large_python_class_is_split_by_method():
    methods = '\n'.join(f"    def method_{i}(self):\n        return {'x' * 80!r}\n" for i in range(10))
    source = f"class Big:\n    '''doc'''\n{methods}"
    chunks = chunk_code(source, "big.py", max_chars=300)
    assert len(chunks) > 1
    assert any('Big.method_' in (c.symbol or '') for c in chunks)


def test_small_definitions_are_packed_together():
    chunks = chunk_code(PYTHON_SOURCE, "mod.py", max_chars=2000)
    assert len(chunks) == 1
    assert 'alpha' in chunks[0].symbol and 'beta' in chunks[0].symbol


def test_brace_language_splits_on_top_level_blocks():
    source = (
        "import x from 'x';\n\n"
        "export function first() {\n  const s = '}';\n  return 1;\n}\n\n"
        "const second = async (a) => {\n  // } not a real brace\n  return a;\n};\n\n"
        "class Third {\n  run() { return 3; }\n}\n"
    )
    chunks = chunk_code(source, "a.js", max_chars=60)
    symbols = [c.symbol for c in chunks]
    assert any(s and 'first' in s for s in symbols)
    assert any(s and 'second' in s for s in symbols)
    assert any(s and 'Third' in s for s in symbols)


def test_oversized_block_uses_overlapping_windows_and_progresses():
    source = '\n'.join(f"line_{i} = {i}" for i in range(200))
    chunks = chunk_code(source, "data.txt", max_chars=200, overlap_lines=3)
    assert len(chunks) > 1
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start_line > prev.start_line
        assert nxt.start_line <= prev.end_line + 1
    assert chunks[-1].end_line == 200


def test_markdown_splits_on_headings():
    source = "# Title\nintro\n\n## Setup\n" + "step\n" * 50 + "## Usage\nrun it\n"
    chunks = chunk_code(source, "README.md", max_chars=120)
    assert any(c.symbol == 'Setup' for c in chunks)
    assert any(c.symbol == 'Usage' for c in chunks)


def test_empty_file_produces_no_chunks():
    assert chunk_code("\n\n  \n", "empty.py") == []


def test_chunk_ids_differ_for_identical_content_in_different_files():
    a = chunk_code("x = 1\n", "a/__init__.py")[0]
    b = chunk_code("x = 1\n", "b/__init__.py")[0]
    assert a.chunk_id != b.chunk_id


def test_search_text_includes_location_header():
    chunk = chunk_code("def foo():\n    pass\n", "pkg/mod.py")[0]
    assert chunk.search_text.startswith("File: pkg/mod.py\nSymbol: foo\nLines: 1-2\n")


def test_number_lines():
    assert number_lines("a\nb", 9) == " 9 | a\n10 | b"
