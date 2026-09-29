# Development guide

How to set up CodeWise for development, run the tests, and extend it.

---

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.10 or newer (developed on 3.13) | Backend |
| Node.js | 20.19+ or 22.12+ | Frontend (Vite 8) |
| [Ollama](https://ollama.com) | recent | Runs the models |

```bash
ollama pull qwen2.5-coder:7b      # chat model, about 4.7 GB
ollama pull nomic-embed-text      # embedding model, about 270 MB
```

---

## Setup

```bash
git clone https://github.com/shekharsanskar9/CodeWise.git
cd CodeWise

# Backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

# Frontend
cd frontend && npm install && cd ..
```

## Running

Use two terminals, both started from the project folder:

```bash
# Terminal 1: backend on http://127.0.0.1:8000
source venv/bin/activate
python backend.py

# Terminal 2: frontend on http://localhost:5173
cd frontend
npm run dev
```

The frontend reloads automatically when you edit it. The backend doesn't: restart it after changing Python code.

Check the backend is up with:

```bash
curl http://127.0.0.1:8000/api/health
```

---

## Tests

```bash
pytest               # about 90 tests, runs in under a second
pytest -k graph      # only tests whose names contain "graph"
pytest -x -v         # stop at the first failure, show each test
```

**The tests don't need Ollama.** `tests/conftest.py` provides:
- `FakeEmbedder`: deterministic bag-of-words vectors, so search behaves predictably;
- `FakeLLM`: returns `"fake answer"` and records every prompt, so tests can assert on what was sent to the model;
- temporary ChromaDB and SQLite storage for each test.

| File | Covers |
|---|---|
| `test_chunking.py` | Structure-aware chunking, line numbers, chunk IDs |
| `test_units.py` | File filtering, decoding, BM25, history sanitizing, token budgets |
| `test_graph.py` | Definitions, calls and imports for Python, JS/TS, Java, C |
| `test_sources.py` | Zip safety limits, `.gitignore`, GitHub URL validation and downloads (mocked) |
| `test_api.py` | Core endpoints: upload, ask, analyze, streaming, errors |
| `test_features_api.py` | Zip, folder and GitHub import, graph endpoint, relationship answers, question log |

**Frontend checks:**

```bash
cd frontend
npx oxlint src      # lint
npm run build       # make sure it compiles
```

---

## Where to make common changes

**Support a new file type.** Add the extension to `SUPPORTED_EXTENSIONS` in `codewise/files.py`. If it's a brace language, also add it to `BRACE_EXTENSIONS` in `codewise/chunking.py` so it's chunked by blocks rather than line windows.

**Ignore more folders or files.** Edit `IGNORED_DIRS`, `IGNORED_FILENAMES` or `IGNORED_SUFFIXES` in `codewise/files.py`. The frontend picks these up automatically through `/api/upload-rules`.

**Better code-graph support for a language.** Extraction lives in `codewise/graph.py`:
- Python uses `_python_graph` (built on `ast`);
- JS/TS and other brace languages use `_brace_graph` (patterns plus brace matching);
- import resolution is in `module_candidates` and `resolve_imports`.

Add a test in `tests/test_graph.py` with a small sample file.

**Change how answers are written.** The prompts are at the top of `codewise/llm.py`: `QA_SYSTEM_PROMPT`, `REWRITE_SYSTEM_PROMPT`, `ANALYZE_SYSTEM_PROMPT` and `SUMMARIZE_FILE_PROMPT`. Measure the effect with `python eval/answer_eval.py` (see [Evaluation](evaluation.md)).

**Change how search ranks results.** Fusion is in `hybrid_retrieve` in `codewise/retrieval.py`. Run `python eval/retrieval_eval.py` before and after, and compare the numbers.

**Add an endpoint:**
1. Put the logic in a method on `CodeWise` in `codewise/service.py`.
2. Add a thin route in `codewise/app.py`.
3. Raise `BadRequest` or `NotFound` for invalid input; they're turned into 400 and 404 responses automatically.
4. Add a test using the `client` fixture.
5. Document it in [api.md](api.md).

**Use a different model provider.** Everything that talks to the chat model goes through `OllamaLLM` in `codewise/llm.py` (`chat` and `stream`). A class with the same two methods can replace it in `build_service` in `codewise/app.py`.

---

## Conventions

- **Keep `app.py` thin.** HTTP concerns only; logic goes in `service.py` or the modules it uses.
- **Line numbers are 1-based and inclusive** everywhere: chunks, sources, code graph.
- **File paths are relative POSIX paths** as uploaded (`src/app.py`), never absolute.
- **New behaviour comes with a test.** Retrieval or prompt changes come with before/after eval numbers.
- **Config goes in `codewise/config.py`** as a `CODEWISE_*` environment variable with a default, and gets added to `.env.example` and [configuration.md](configuration.md).

---

## Git workflow and releases

```bash
git checkout main && git pull
git checkout -b my-change
# ...edit, then run pytest and npm run build...
git add -A && git commit -m "Describe what changed and why"
git push -u origin my-change
```

Open a pull request on GitHub, then merge it.

**Releases** are git tags with GitHub Release notes. Past releases: `v2.0` (RAG pipeline rework) and `v3.0` (import, streaming, code relationships).

```bash
git tag -a v3.1 -m "CodeWise 3.1 - short summary"
git push origin v3.1
```

Then write release notes on GitHub (**Releases → Draft a new release**), covering what changed, anything users must do when upgrading, and known limitations.
