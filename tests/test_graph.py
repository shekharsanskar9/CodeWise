from codewise.graph import extract_graph, resolve_imports
from codewise.relations import symbol_candidates

PY = '''import os
from .store import ProjectStore
from . import helpers


def load(path):
    return os.path.exists(path)


class Service:
    @cached
    def run(self):
        data = load("x")
        return helpers.clean(data)

    def other(self):
        self.run()
'''

JS = '''import React, { useState } from "react";
import {
  parse,
  format as fmt,
} from "./utils/text";
const lib = require("../lib");

export function Upload({ onDone }) {
  const [files, setFiles] = useState([]);
  const submit = async () => {
    await api.post("/upload", parse(files));
    onDone();
  };
  return <Button onClick={submit} />;
}

class Store {
  save(item) {
    return fmt(item);
  }
}
'''


def names(items, attr='qualname'):
    return [getattr(i, attr) for i in items]


def test_python_definitions_and_scopes():
    g = extract_graph(PY, "pkg/service.py")
    assert names(g.definitions) == ["load", "Service", "Service.run", "Service.other"]
    assert [d.kind for d in g.definitions] == ["function", "class", "method", "method"]
    run = g.definitions[2]
    assert run.start_line == 11  # decorator line included


def test_python_calls_have_callers():
    g = extract_graph(PY, "pkg/service.py")
    calls = {(c.name, c.caller) for c in g.calls}
    assert ("load", "Service.run") in calls
    assert ("clean", "Service.run") in calls
    assert ("run", "Service.other") in calls
    assert ("exists", "load") in calls


def test_python_relative_imports_resolve_to_files():
    g = extract_graph(PY, "pkg/service.py")
    assert [(i.module, i.name) for i in g.imports] == [("os", ""), ("pkg.store", "ProjectStore"), ("pkg", "helpers")]
    files = ["pkg/__init__.py", "pkg/store.py", "pkg/helpers.py", "pkg/service.py"]
    assert resolve_imports(g.imports, files) == [None, "pkg/store.py", "pkg/helpers.py"]


def test_python_imports_resolve_under_a_top_level_folder():
    g = extract_graph("from codewise.chunking import chunk_code\n", "MyRepo/codewise/service.py")
    assert resolve_imports(g.imports, ["MyRepo/codewise/chunking.py"]) == ["MyRepo/codewise/chunking.py"]


def test_js_definitions_imports_and_calls():
    g = extract_graph(JS, "src/Upload.jsx")
    assert ("Upload", "function") in [(d.qualname, d.kind) for d in g.definitions]
    assert "Store.save" in names(g.definitions)
    assert "submit" in names(g.definitions)

    imports = [(i.module, i.name) for i in g.imports]
    assert ("react", "useState") in imports
    assert ("path:src/utils/text", "parse") in imports
    assert ("path:src/utils/text", "format") in imports   # multi-line import, alias resolved to original
    assert ("path:lib", "lib") in imports

    calls = {(c.name, c.caller) for c in g.calls}
    assert ("parse", "submit") in calls
    assert ("post", "submit") in calls
    assert ("Button", "Upload") in calls  # JSX usage
    assert ("fmt", "Store.save") in calls


def test_js_relative_import_resolves_with_extension_and_index():
    g = extract_graph('import a from "./utils";\nimport b from "./text";\n', "src/App.jsx")
    assert resolve_imports(g.imports, ["src/utils/index.js", "src/text.ts"]) == ["src/utils/index.js", "src/text.ts"]


def test_js_call_lines_are_not_definitions():
    g = extract_graph("async function go() {\n  await load(x)\n  return build(y)\n}\n", "a.js")
    assert names(g.definitions) == ["go"]


def test_other_languages_imports():
    java = extract_graph("import com.acme.util.Strings;\nclass A {\n  void f() { Strings.trim(x); }\n}\n", "A.java")
    assert java.imports[0].module == "com.acme.util.Strings"
    assert resolve_imports(java.imports, ["src/com/acme/util/Strings.java"]) == ["src/com/acme/util/Strings.java"]
    c = extract_graph('#include "util.h"\nint main() { helper(); }\n', "src/main.c")
    assert resolve_imports(c.imports, ["include/util.h"]) == ["include/util.h"]


def test_unparseable_python_falls_back_without_crashing():
    g = extract_graph("def broken(:\n", "x.py")
    assert g.definitions == []


def test_symbol_candidates_prefers_code_like_names():
    cands = symbol_candidates("Who calls `replace_file` and ProjectIndex.search() or the upload thing?")
    assert cands[:3] == ["replace_file", "ProjectIndex.search", "search"]
    assert "upload" in cands  # plain words come after code-like ones
    assert "who" not in [c.lower() for c in cands]
