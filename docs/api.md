# API reference

The backend is a JSON REST API, by default at `http://127.0.0.1:8000`. The React frontend uses these endpoints, and you can call them directly with `curl` or from your own scripts.

- [Conventions](#conventions)
- [Health](#health) · [Upload rules](#upload-rules)
- Projects: [Create](#create-a-project) · [Info](#project-info)
- Adding code: [Upload](#upload-files-folders-or-zip) · [Import from GitHub](#import-a-github-repository)
- Asking: [Ask](#ask-a-question) · [Ask (streaming)](#ask-a-question-streaming)
- [Code graph](#code-graph) · [Analyze](#analyze-the-project)

---

## Conventions

- **Project IDs** are UUIDs returned by *Create*. Anything that isn't a valid UUID gets **404**.
- **Errors** always have this shape:
  ```json
  { "success": false, "error": "Human-readable message" }
  ```

| Status | Meaning |
|---|---|
| 400 | Invalid input (missing question, bad URL, nothing could be indexed, …) |
| 404 | Project or file not found |
| 409 | The project was indexed with a different embedding model; create a new project |
| 413 | Upload larger than `CODEWISE_MAX_REQUEST_BYTES` |
| 502 | Ollama failed or is unreachable |
| 500 | Unexpected server error (details in the backend log) |

- **CORS:** browsers may only call the API from origins listed in `CODEWISE_CORS_ORIGINS` (default: the Vite dev server on port 5173).
- **Authentication:** none. CodeWise is meant to run on your own machine; don't expose it to a network you don't trust.

---

## Health

`GET /api/health`

```json
{
  "status": "healthy",
  "timestamp": "2026-09-29T10:15:00.123456",
  "chat_model": "qwen2.5-coder:7b",
  "embed_model": "ollama:nomic-embed-text"
}
```

`embed_model` is `chroma:all-MiniLM-L6-v2` if the Ollama embedding model wasn't available when the server started.

---

## Upload rules

`GET /api/upload-rules`

What the server will index, so clients can skip other files *before* uploading them. The frontend uses this.

```json
{
  "supported_extensions": [".c", ".cpp", ".css", ".go", ".h", ".py", "..."],
  "ignored_dirs": [".git", "node_modules", "venv", "dist", "..."],
  "ignored_filenames": ["package-lock.json", "yarn.lock", "..."],
  "ignored_suffixes": [".min.js", ".min.css", ".map", ".bundle.js"],
  "max_file_bytes": 1000000,
  "max_request_bytes": 100000000,
  "max_archive_bytes": 100000000
}
```

---

## Create a project

`POST /api/projects/create` → **201**

```json
{ "success": true, "project_id": "1bd7ce58-827c-4c55-b1d0-41be02aa5c73", "message": "Project created successfully" }
```

---

## Project info

`GET /api/projects/<id>/info`

```json
{
  "success": true,
  "project_id": "1bd7ce58-...",
  "metadata": {
    "created_at": "2026-09-27T20:12:25.455257",
    "embed_model": "ollama:nomic-embed-text",
    "total_lines": 1034,
    "files": [
      { "filename": "backend/main.py", "chunks": 6, "size": 4210, "lines": 134, "uploaded_at": "2026-09-27T20:13:02.1" }
    ]
  }
}
```

---

## Upload files, folders or zip

`POST /api/projects/<id>/upload`, sent as `multipart/form-data` with one or more `files` fields.

- **The filename carries the path.** Send `src/utils.py`, not just `utils.py`, so files with the same name in different folders stay separate. Leading `/` and `..` are stripped.
- **`.zip` files are unpacked** on the server. A single top-level folder (as in GitHub downloads) is removed from the paths.
- **`.gitignore` files** in the same request (or inside the zip) are applied to the other files.
- **Re-uploading a path replaces it**: its old chunks and code graph are deleted first.

```bash
curl -F "files=@src/app.py;filename=src/app.py" \
     -F "files=@project.zip" \
     http://127.0.0.1:8000/api/projects/$PID/upload
```

**Status:** 200 if every file was indexed, **207** if some were, **400** if none were.

```json
{
  "success": true,
  "project_id": "1bd7ce58-...",
  "summary": { "indexed": 40, "skipped": 3, "failed": 0 },
  "uploads": [
    { "filename": "src/app.py", "success": true, "message": "Successfully processed src/app.py with 4 chunks" },
    { "filename": "package-lock.json", "success": false, "skipped": true, "message": "Ignored generated file: package-lock.json" }
  ],
  "metadata": { "...": "same as Project info" }
}
```

- `skipped` means the file was filtered out on purpose: ignored folder, `.gitignore`, unsupported type, too large, binary, minified or empty.
- `failed` means something went wrong while processing it.
- When nothing was indexed, `error` summarizes the reasons.

**Limits** (see [Configuration](configuration.md)):
- 1 MB per file;
- 100 MB per request;
- zip archives: 100 MB compressed, 20,000 entries, 200 MB of source after unpacking.

Symlinks and paths that escape the project are ignored.

---

## Import a GitHub repository

`POST /api/projects/<id>/import/github`

```json
{ "url": "https://github.com/pallets/click", "ref": "main" }
```

- **`url`** accepts `https://github.com/owner/repo`, the same with `.git`, `…/tree/<branch>`, or just `owner/repo`. Other hosts are rejected, so the server never fetches arbitrary URLs.
- **`ref`** (optional) is a branch, tag or commit. Without it, the repository's default branch is used.
- **Private repositories** and higher rate limits need `CODEWISE_GITHUB_TOKEN`.

The response is the same as *Upload*, plus:

```json
{ "repository": { "owner": "pallets", "repo": "click", "ref": "main" } }
```

**Errors (400):** repository not found or private, GitHub rate limit, archive too large, or an invalid URL.

---

## Ask a question

`POST /api/projects/<id>/ask`

```json
{
  "question": "Who calls replace_file?",
  "history": [
    { "role": "user", "content": "What does the index module do?" },
    { "role": "assistant", "content": "It stores code chunks in ChromaDB..." }
  ]
}
```

- `question` is required, 4,000 characters at most.
- `history` is optional. Only `user` and `assistant` roles are kept (`ai` is accepted as an alias for `assistant`); anything else is dropped. The server trims history to fit the model's context window.

```json
{
  "success": true,
  "question": "Who calls replace_file?",
  "answer": "`replace_file` is called from `CodeWise._ingest` in codewise/service.py (line 156)...",
  "search_query": "Who calls replace_file?",
  "context_found": true,
  "relations": ["replace_file"],
  "sources": [
    {
      "filename": "codewise/index.py",
      "lines": "55-66",
      "symbol": "ProjectIndex.replace_file",
      "score": 0.04918,
      "similarity": 0.61,
      "matched_by": ["vector", "keyword", "graph"]
    }
  ],
  "model": "qwen2.5-coder:7b",
  "usage": { "input_tokens": 2384, "output_tokens": 243 }
}
```

| Field | Meaning |
|---|---|
| `search_query` | What was actually searched. It differs from `question` when a follow-up was rewritten |
| `context_found` | `false` if no relevant code was found; the model was told to say so |
| `relations` | Symbols and files the code-relationships section covered |
| `sources[].score` | Fused ranking score (higher is better) |
| `sources[].similarity` | `1 − cosine distance` from vector search, or `null` if the chunk wasn't found by vector search |
| `sources[].matched_by` | Which searches found it: `vector`, `keyword`, `graph`, `filename` |

---

## Ask a question (streaming)

`POST /api/projects/<id>/ask/stream` takes the same request body as *Ask*. It replies with `text/event-stream` (Server-Sent Events):

```
event: sources
data: {"sources": [...], "search_query": "...", "context_found": true, "relations": ["replace_file"]}

event: token
data: {"content": "`replace_file` is"}

event: token
data: {"content": " called from"}

event: done
data: {"model": "qwen2.5-coder:7b"}
```

- `sources` arrives once, before any text.
- `token` events carry the answer piece by piece; join their `content` values.
- The stream ends with `done`, or with `error` (`{"error": "..."}`) if the model fails partway through.
- Invalid input (missing question, unknown project) is rejected **before** streaming starts, with a normal JSON error and status code.
- Closing the connection stops generation.

```bash
curl -N -X POST http://127.0.0.1:8000/api/projects/$PID/ask/stream \
     -H "Content-Type: application/json" -d '{"question": "How does upload work?"}'
```

---

## Code graph

`GET /api/projects/<id>/graph?symbol=<name>`

`name` can be a plain name (`save`) or a qualified one (`ProjectStore.save`).

```json
{
  "success": true,
  "symbol": {
    "name": "replace_file",
    "definitions": [
      { "path": "codewise/index.py", "name": "replace_file", "qualname": "ProjectIndex.replace_file",
        "kind": "method", "start_line": 55, "end_line": 66 }
    ],
    "callers": [
      { "path": "codewise/service.py", "line": 156, "caller": "CodeWise._ingest", "expr": "self.index.replace_file" }
    ],
    "callees": [
      { "path": "codewise/index.py", "line": 58, "name": "delete", "expr": "collection.delete" }
    ],
    "importers": []
  }
}
```

`GET /api/projects/<id>/graph?file=<path>`

```json
{
  "success": true,
  "file": {
    "path": "codewise/store.py",
    "imports": [],
    "external": ["contextlib", "datetime", "sqlite3"],
    "imported_by": ["codewise/app.py"]
  },
  "symbols": [
    { "name": "ProjectStore", "qualname": "ProjectStore", "kind": "class", "start_line": 60, "end_line": 184 }
  ]
}
```

- Without `symbol` or `file`, the endpoint returns **400**; an unknown file returns **404**.
- Calls are matched by name, so callers of different functions that share a name are combined.
- Each list is capped at 200 rows.

---

## Analyze the project

`GET /api/projects/<id>/analyze`

```json
{
  "success": true,
  "project_id": "1bd7ce58-...",
  "analysis": "## Architecture overview\n...",
  "mode": "full",
  "files_analyzed": ["README.md", "requirements.txt", "backend/main.py", "..."],
  "metadata": { "...": "same as Project info" },
  "usage": { "input_tokens": 5120, "output_tokens": 812 }
}
```

- `mode` is `full` when the whole project fit in one prompt, or `map_reduce` when large files were summarized first (about 10 model calls, which can take minutes).
- Returns **400** if the project has no files.
