"""
Answering relationship questions ("who calls X?", "what does X depend on?") from the
static code graph, and feeding those locations into retrieval and the prompt.
"""

import re
from dataclasses import dataclass, field

from .graph import Import, resolve_imports
from .llm import estimate_tokens
from .retrieval import _STOPWORDS, mentioned_files

_CANDIDATE_RE = re.compile(r'`([^`]+)`|([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)(\s*\()?')
_USAGE_INTENT = re.compile(
    r'\b(callers?|usages?|dependents?|references?|depends?\s+on|who\s+\w+|where\s+(?:is|are)\s+\S+\s+'
    r'(?:used|called|imported|referenced|invoked))\b|\b(?:call|calls|called|calling|use|uses|used|using|import|'
    r'imports|imported|invoke|invokes|invoked|reference|references|referenced)\b',
    re.IGNORECASE)

MAX_SYMBOLS = 3
MAX_FILES = 2
MAX_LISTED = 25

NOTE = ("Static analysis: calls are matched by name, so functions that share a name may be "
        "conflated, and dynamic calls (callbacks, reflection) are not seen.")


@dataclass
class SymbolRelations:
    name: str
    definitions: list
    callers: list
    callees: list
    importers: list


@dataclass
class FileRelations:
    path: str
    imports: list          # project files this file imports
    external: list         # external packages/modules
    imported_by: list      # project files importing this file


@dataclass
class Relations:
    symbols: list = field(default_factory=list)
    files: list = field(default_factory=list)
    usage_intent: bool = False

    def __bool__(self):
        return bool(self.symbols or self.files)

    def locations(self):
        """(path, line) pairs worth retrieving, most relevant first for this kind of question."""
        definitions = [(d['path'], d['start_line']) for s in self.symbols for d in s.definitions]
        call_sites = [(c['path'], c['line']) for s in self.symbols for c in s.callers]
        call_sites += [(i['path'], i['line']) for s in self.symbols for i in s.importers]
        call_sites += [(p, 1) for f in self.files for p in f.imported_by]
        ordered = call_sites + definitions if self.usage_intent else definitions + call_sites
        return list(dict.fromkeys(ordered))


def symbol_candidates(text):
    """Identifier-like strings from a question, code-looking ones first."""
    code_like, plain = _split_candidates(text)
    return code_like + [p for p in plain if p not in code_like]


def _split_candidates(text):
    """(code-looking identifiers, plain words). Backticks, calls(), snake_case, camelCase and dots count as code."""
    code_like, plain = [], []
    for m in _CANDIDATE_RE.finditer(text):
        if m.group(1):  # `backticked`
            ident = re.sub(r'\(.*$', '', m.group(1).strip())
            code_like.append(ident)
            continue
        ident = m.group(2)
        looks_like_code = bool(m.group(3)) or '_' in ident or '.' in ident or re.search(r'[a-z][A-Z]', ident)
        if looks_like_code:
            code_like.append(ident)
        elif len(ident) >= 4 and ident.lower() not in _STOPWORDS:
            plain.append(ident)
    def expand(idents):
        out = []
        for ident in idents:
            out.append(ident)
            if '.' in ident:
                out.append(ident.rsplit('.', 1)[1])
        return [c for c in dict.fromkeys(out) if len(c) >= 3]
    return expand(code_like), expand(plain)


class CodeRelations:
    def __init__(self, store):
        self.store = store

    def for_question(self, project_id, text, files):
        usage = bool(_USAGE_INTENT.search(text))
        code_like, plain = _split_candidates(text)
        candidates = code_like + [p for p in plain if p not in code_like]
        known = self.store.known_symbol_names(project_id, candidates)
        # Plain English words ("upload", "config") only count when the question is about usage;
        # capitalised words may be class names.
        code_like = set(code_like) | {p for p in plain if not p.islower()}
        chosen = [c for c in candidates if c in known and (usage or c in code_like)]
        # Prefer qualified names; drop a simple name already covered by "Class.name".
        chosen = [c for c in chosen if not any(o != c and o.endswith('.' + c) for o in chosen)]

        relations = Relations(usage_intent=usage)
        for name in chosen[:MAX_SYMBOLS]:
            relations.symbols.append(self.symbol(project_id, name))
        for path in sorted(mentioned_files(text, files))[:MAX_FILES]:
            relations.files.append(self.file(project_id, path, files))
        return relations

    def symbol(self, project_id, name):
        simple = name.rsplit('.', 1)[-1]
        definitions = self.store.find_definitions(project_id, name)
        callers = [c for c in self.store.find_callers(project_id, simple)
                   if not any(c['path'] == d['path'] and c['line'] == d['start_line'] for d in definitions)]
        callees = []
        for d in definitions:
            callees.extend(self.store.find_callees(project_id, d['qualname']))
        internal = self.store.known_symbol_names(project_id, [c['name'] for c in callees])
        # Project-internal calls first; library calls after.
        callees.sort(key=lambda c: (c['name'] not in internal, c['line']))
        importers = self.store.find_name_importers(project_id, simple)
        return SymbolRelations(name, definitions, callers, callees, importers)

    def file(self, project_id, path, files):
        imports = self.store.all_imports(project_id)
        resolved = resolve_imports(_as_imports(imports), files)
        own, external, imported_by = [], [], []
        for imp, target in zip(imports, resolved):
            if imp['path'] == path:
                if target and target != path:
                    own.append(target)
                elif not target:
                    external.append(imp['module'] or imp['name'])
            elif target == path:
                imported_by.append(imp['path'])
        return FileRelations(path, sorted(set(own)), sorted(set(external)), sorted(set(imported_by)))


def _as_imports(rows):
    return [Import(r['module'], r['name'], r['line']) for r in rows]


def _listing(items, fmt):
    lines = [fmt(i) for i in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        lines.append(f"... and {len(items) - MAX_LISTED} more")
    return lines


def render_relations(relations, budget_tokens):
    if not relations:
        return ''
    out = [f"## Code relationships\n_{NOTE}_\n"]
    for s in relations.symbols:
        out.append(f"### `{s.name}`")
        if s.definitions:
            out.append("Defined in:")
            out += _listing(s.definitions, lambda d: f"- {d['path']}:{d['start_line']}-{d['end_line']} "
                                                     f"({d['kind']} {d['qualname']})")
        out.append(f"Called from ({len(s.callers)}{'+' if len(s.callers) >= 200 else ''} sites):"
                   if s.callers else "Called from: no call sites found in the uploaded files.")
        out += _listing(s.callers, lambda c: f"- {c['path']}:{c['line']} in {c['caller']} — `{c['expr']}`")
        if s.importers:
            out.append("Imported by:")
            out += _listing(s.importers, lambda i: f"- {i['path']}:{i['line']} (from {i['module']})")
        if s.callees:
            names = list(dict.fromkeys(c['expr'] for c in s.callees))
            out.append("It calls: " + ', '.join(f"`{n}`" for n in names[:MAX_LISTED])
                       + (f" ... (+{len(names) - MAX_LISTED})" if len(names) > MAX_LISTED else ''))
        out.append('')
    for f in relations.files:
        out.append(f"### File `{f.path}`")
        out.append("Imports project files: " + (', '.join(f.imports) or 'none'))
        if f.external:
            out.append("External imports: " + ', '.join(f.external[:MAX_LISTED]))
        out.append("Imported by: " + (', '.join(f.imported_by) or 'no uploaded file'))
        out.append('')
    text = '\n'.join(out) + '\n'
    if estimate_tokens(text) > budget_tokens:
        text = text[:budget_tokens * 3].rsplit('\n', 1)[0] + "\n... [relationships truncated]\n\n"
    return text
