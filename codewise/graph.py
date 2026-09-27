"""
Static code relationships: definitions, calls and imports.

Python is analysed with the ast module (precise scopes and calls). JavaScript/TypeScript
and other brace languages use line-based patterns with brace matching for scopes.
Call resolution is name-based ("who calls `save`" matches every `save(...)`), which is
the honest limit of static analysis without type information; results say so.
"""

import ast
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .chunking import BRACE_EXTENSIONS, _SYMBOL_PATTERNS, _NOT_SYMBOLS, _strip_non_code, split_lines


@dataclass
class Definition:
    name: str
    qualname: str
    kind: str          # function | class | method
    start_line: int
    end_line: int


@dataclass
class Call:
    name: str          # simple name of what is called, e.g. "replace_file"
    line: int
    caller: str        # qualname of the enclosing definition, or "<module>"
    expr: str          # how it was written, e.g. "self.index.replace_file"


@dataclass
class Import:
    module: str        # dotted module (python), "path:<file w/o ext>" (relative JS), or package name
    name: str          # imported name, or "" for whole-module imports
    line: int


@dataclass
class FileGraph:
    definitions: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    imports: list = field(default_factory=list)


JS_EXTENSIONS = {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'}
_CALL_KEYWORDS = _NOT_SYMBOLS | {'function', 'typeof', 'await', 'super', 'this', 'constructor',
                                 'import', 'require', 'async', 'with', 'assert', 'print', 'not',
                                 'and', 'or', 'in', 'is', 'lambda', 'yield', 'def', 'class'}


def extract_graph(content, path):
    ext = PurePosixPath(path).suffix.lower()
    if ext == '.py':
        graph = _python_graph(content, path)
        if graph is not None:
            return graph
    if ext in BRACE_EXTENSIONS or ext in JS_EXTENSIONS:
        return _brace_graph(content, path, ext)
    return FileGraph()


# --- Python ---------------------------------------------------------------------------

def python_module_name(path):
    """codewise/chunking.py -> codewise.chunking ; pkg/__init__.py -> pkg"""
    p = PurePosixPath(path)
    parts = list(p.with_suffix('').parts)
    if parts and parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts)


def _python_graph(content, path):
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return None
    graph = FileGraph()
    package = python_module_name(path)
    if not path.endswith('__init__.py'):
        package = package.rpartition('.')[0]

    def visit(node, scope, in_class):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualname = f"{scope}.{child.name}" if scope else child.name
                if isinstance(child, ast.ClassDef):
                    kind = 'class'
                else:
                    kind = 'method' if in_class else 'function'
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                graph.definitions.append(Definition(child.name, qualname, kind, start, child.end_lineno))
                visit(child, qualname, isinstance(child, ast.ClassDef))
            elif isinstance(child, ast.Call):
                record_call(child, scope)
                visit(child, scope, in_class)
            elif isinstance(child, ast.Import):
                for alias in child.names:
                    graph.imports.append(Import(alias.name, '', child.lineno))
            elif isinstance(child, ast.ImportFrom):
                module = _resolve_relative(package, child.module, child.level)
                for alias in child.names:
                    graph.imports.append(Import(module, alias.name if alias.name != '*' else '', child.lineno))
            else:
                visit(child, scope, in_class and not isinstance(child, ast.expr))

    def record_call(call, scope):
        func = call.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            return
        try:
            expr = ast.unparse(func)
        except Exception:
            expr = name
        graph.calls.append(Call(name, call.lineno, scope or '<module>', expr[:120]))

    visit(tree, '', False)
    return graph


def _resolve_relative(package, module, level):
    if not level:
        return module or ''
    parts = package.split('.') if package else []
    if level > 1:
        parts = parts[:len(parts) - (level - 1)]
    base = '.'.join(parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


# --- JavaScript / TypeScript / other brace languages ----------------------------------

_JS_IMPORT_FROM = re.compile(r'''^\s*(?:import|export)\s+(?:type\s+)?(.*?)\s+from\s+['"]([^'"]+)['"]''')
_JS_IMPORT_BARE = re.compile(r'''^\s*import\s+['"]([^'"]+)['"]''')
_JS_REQUIRE = re.compile(r'''(?:const|let|var)\s+(.+?)\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)''')
_JAVA_IMPORT = re.compile(r'^\s*import\s+(?:static\s+)?([\w.]+?)(?:\.\*)?\s*;?\s*$')
_C_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"')
_GO_IMPORT = re.compile(r'^\s*(?:import\s+)?(?:[\w.]+\s+)?"([\w./-]+)"\s*$')
_RUST_USE = re.compile(r'^\s*(?:pub\s+)?use\s+([\w:]+)')
_CSHARP_USING = re.compile(r'^\s*using\s+(?:static\s+)?([\w.]+)\s*;')
_CALL_RE = re.compile(r'(?<![\w$])((?:[A-Za-z_$][\w$]*\s*(?:\?\.|\.)\s*)*)([A-Za-z_$][\w$]*)\s*(?:<[^<>()]*>)?\s*\(')
_JS_METHOD = re.compile(r'^\s+(?:(?:static|async|get|set|public|private|protected|readonly)\s+)*\*?#?'
                        r'([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\([^;]*\)\s*(?::[^={]+)?\{\s*$')
_JSX_RE = re.compile(r'<([A-Z][\w$]*)[\s/>]')


def _js_import_names(clause):
    """Names bound by an import clause: `Foo, { a, b as c }`, `* as ns`, `{ a }` (require)."""
    names = []
    clause = clause.strip()
    braces = re.search(r'\{([^}]*)\}', clause)
    if braces:
        for part in braces.group(1).split(','):
            part = part.strip()
            if part:
                names.append(re.split(r'\s+as\s+|\s*:\s*', part)[0].replace('type ', '').strip())
        clause = clause.replace(braces.group(0), '')
    for part in clause.split(','):
        part = part.strip()
        if not part:
            continue
        star = re.match(r'\*\s+as\s+([\w$]+)', part)
        if star:
            names.append(star.group(1))
        elif re.fullmatch(r'[\w$]+', part):
            names.append(part)
    return [n for n in names if n]


def _js_module(spec, path):
    if spec.startswith('.'):
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
        return f"path:{PurePosixPath(target).with_suffix('') if PurePosixPath(target).suffix in JS_EXTENSIONS else target}"
    return spec


def _brace_graph(content, path, ext):
    lines = split_lines(content)
    graph = FileGraph()
    is_js = ext in JS_EXTENSIONS

    # Definitions with their brace-matched extent.
    stripped = []
    in_comment = False
    for line in lines:
        code, in_comment = _strip_non_code(line, in_comment)
        stripped.append(code)

    # The Java/C#-style "type name(" pattern misfires on JS call lines like `await load(x)`.
    patterns = _SYMBOL_PATTERNS[:-1] if is_js else _SYMBOL_PATTERNS
    defs = []
    for i, line in enumerate(lines, 1):
        for pattern in patterns:
            m = pattern.match(line)
            if m and m.group(1) not in _NOT_SYMBOLS:
                kind = 'class' if re.search(r'\b(class|interface|struct|enum|trait|record|impl)\b', line.split(m.group(1))[0]) else 'function'
                defs.append([m.group(1), kind, i, _block_end(stripped, i)])
                break

    if is_js:
        # Method shorthand inside class bodies: `save(item) {`, `async load() {`, `static of(x) {`
        known = {d[2] for d in defs}
        for cls in [d for d in defs if d[1] == 'class']:
            for i in range(cls[2] + 1, cls[3]):
                if i in known:
                    continue
                m = _JS_METHOD.match(lines[i - 1])
                if m and m.group(1) not in _CALL_KEYWORDS:
                    defs.append([m.group(1), 'function', i, _block_end(stripped, i)])
        defs.sort(key=lambda d: d[2])

    # Qualify nested definitions (methods inside classes) by containment.
    for d in defs:
        parents = [p for p in defs if p is not d and p[2] < d[2] and p[3] >= d[3] and p[1] == 'class']
        parent = max(parents, key=lambda p: p[2]) if parents else None
        qualname = f"{parent[0]}.{d[0]}" if parent else d[0]
        kind = 'method' if parent and d[1] == 'function' else d[1]
        graph.definitions.append(Definition(d[0], qualname, kind, d[2], d[3]))

    def enclosing(line_no):
        inside = [d for d in graph.definitions if d.start_line <= line_no <= d.end_line]
        return max(inside, key=lambda d: d.start_line).qualname if inside else '<module>'

    def_lines = {d.start_line: d.name for d in graph.definitions}
    statements = _join_js_imports(lines) if is_js else {}
    for i, (raw, code) in enumerate(zip(lines, stripped), 1):
        # Imports
        if is_js:
            if i in statements:
                raw = statements[i]
            m = _JS_IMPORT_FROM.match(raw)
            if m:
                module = _js_module(m.group(2), path)
                names = _js_import_names(m.group(1)) or ['']
                graph.imports.extend(Import(module, n, i) for n in names)
                continue
            m = _JS_IMPORT_BARE.match(raw)
            if m:
                graph.imports.append(Import(_js_module(m.group(1), path), '', i))
                continue
            m = _JS_REQUIRE.search(raw)
            if m:
                module = _js_module(m.group(2), path)
                graph.imports.extend(Import(module, n, i) for n in (_js_import_names(m.group(1)) or ['']))
        elif ext in {'.java', '.kt'}:
            m = _JAVA_IMPORT.match(raw)
            if m:
                graph.imports.append(Import(m.group(1), '', i))
                continue
        elif ext in {'.c', '.cpp', '.h', '.hpp'}:
            m = _C_INCLUDE.match(raw)
            if m:
                target = posixpath.normpath(posixpath.join(posixpath.dirname(path), m.group(1)))
                graph.imports.append(Import(f"file:{target}", '', i))
                continue
        elif ext == '.go':
            m = _GO_IMPORT.match(raw)
            if m and ('import' in raw or _in_go_import_block(lines, i)):
                graph.imports.append(Import(m.group(1), '', i))
                continue
        elif ext == '.rs':
            m = _RUST_USE.match(raw)
            if m:
                graph.imports.append(Import(m.group(1), '', i))
                continue
        elif ext == '.cs':
            m = _CSHARP_USING.match(raw)
            if m:
                graph.imports.append(Import(m.group(1), '', i))
                continue

        # Calls (and JSX component usage, which is React's way of "calling" a component)
        caller = enclosing(i)
        for m in _CALL_RE.finditer(code):
            name = m.group(2)
            if name in _CALL_KEYWORDS or (def_lines.get(i) == name):
                continue
            expr = (m.group(1) + name).replace(' ', '')
            graph.calls.append(Call(name, i, caller, expr[:120]))
        if ext in {'.jsx', '.tsx'}:
            for m in _JSX_RE.finditer(code):
                graph.calls.append(Call(m.group(1), i, caller, f"<{m.group(1)}>"))
    return graph


def _join_js_imports(lines):
    """Multi-line `import {\n a,\n b\n} from 'x'` statements, joined onto their first line."""
    joined = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^\s*(?:import|export)\s+(?:type\s+)?\{[^}]*$', line):
            parts = [line]
            j = i + 1
            while j < len(lines) and j < i + 200:
                parts.append(lines[j])
                if re.search(r'from\s+[\'"][^\'"]+[\'"]', lines[j]):
                    joined[i + 1] = ' '.join(p.strip() for p in parts)
                    break
                j += 1
            i = j
        i += 1
    return joined


def _block_end(stripped, start):
    """Last line of the brace block opened on/after `start`; the start line if none opens."""
    depth = 0
    opened = False
    for j in range(start - 1, min(len(stripped), start - 1 + 5000)):
        for ch in stripped[j]:
            if ch == '{':
                depth += 1
                opened = True
            elif ch == '}':
                depth -= 1
        if opened and depth <= 0:
            return j + 1
        # A declaration without a body (e.g. `function f();`, arrow fn without braces)
        if not opened and j > start - 1 + 2:
            return start
        if not opened and stripped[j].rstrip().endswith(';'):
            return j + 1
    return start


def _in_go_import_block(lines, line_no):
    for j in range(line_no - 2, -1, -1):
        s = lines[j].strip()
        if s.startswith('import ('):
            return True
        if s == ')' or (s and not s.startswith('"') and not s.startswith('//') and not re.match(r'^[\w.]+\s+"', s)):
            return False
    return False


# --- resolving imports to project files -----------------------------------------------

def module_candidates(path):
    """Keys under which other files may import `path`."""
    p = PurePosixPath(path)
    keys = set()
    if p.suffix == '.py':
        dotted = python_module_name(path)
        parts = dotted.split('.')
        # Allow imports relative to any source root: a/b/c.py is importable as b.c or c.
        for i in range(len(parts)):
            keys.add('.'.join(parts[i:]))
    no_ext = str(p.with_suffix(''))
    keys.add(f"path:{no_ext}")
    if p.stem == 'index':
        keys.add(f"path:{p.parent}")
    keys.add(f"file:{path}")
    if p.suffix in {'.java', '.kt'}:
        parts = list(p.with_suffix('').parts)
        for i in range(len(parts)):
            keys.add('.'.join(parts[i:]))
    return keys


def resolve_imports(imports, files):
    """Map each import's module to a project file path (or None for external packages)."""
    lookup = {}
    # Prefer shorter (more specific) matches: register longer keys last so exact paths win.
    for path in sorted(files, key=lambda f: -len(f)):
        for key in module_candidates(path):
            lookup[key] = path
    resolved = []
    for imp in imports:
        target = None
        if imp.name:
            # `from pkg import module` imports a submodule, which beats pkg/__init__.py
            target = lookup.get(f"{imp.module}.{imp.name}" if imp.module else imp.name)
        if target is None:
            target = lookup.get(imp.module)
        if target is None and imp.module.startswith('file:'):
            # #include "x.h" relative to include paths: fall back to basename match
            base = posixpath.basename(imp.module[5:])
            matches = [f for f in files if posixpath.basename(f) == base]
            target = matches[0] if len(matches) == 1 else None
        resolved.append(target)
    return resolved
