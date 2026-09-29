# Configuration

Every setting has a sensible default, so CodeWise runs without any configuration. To change something, set an environment variable, or put it in a `.env` file in the project folder, which the backend reads at startup:

```bash
cp .env.example .env     # then edit .env
python backend.py
```

Settings are read once, when the backend starts. **Restart it after changing anything.**

---

## Models

| Variable | Default | What it does |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Where Ollama runs. Point it at another machine to use its GPU |
| `CODEWISE_CHAT_MODEL` | `qwen2.5-coder:7b` | The model that writes answers. Any chat model you've pulled in Ollama works |
| `CODEWISE_EMBED_MODEL` | `nomic-embed-text` | The model that turns code into vectors for search |
| `CODEWISE_NUM_CTX` | `8192` | Context window in tokens: how much text the model can read at once |
| `CODEWISE_ANSWER_RESERVE` | `1536` | Part of the context window kept free for the answer |
| `CODEWISE_LLM_TIMEOUT` | `300` | Seconds to wait for Ollama before giving up |
| `CODEWISE_REWRITE_QUERIES` | `true` | Rewrite follow-up questions into standalone searches (one extra model call per follow-up) |

**Changing the chat model.** Bigger models give better answers but need more memory and are slower. On a 16 GB Mac, 7B–8B models run comfortably; 14B is tight. Run `ollama pull <model>` first.

**Changing the embedding model.** Vectors from different models can't be mixed. Existing projects return **409** after a change, and you need to create new projects and upload again.

**Raising `CODEWISE_NUM_CTX`** lets more code fit into each answer, but uses more memory. `qwen2.5-coder:7b` supports up to 32,768. Keep `CODEWISE_NUM_CTX` minus `CODEWISE_ANSWER_RESERVE` comfortably above 4,000, or there's little room left for code.

If the embedding model isn't installed when the backend starts, CodeWise logs a warning and falls back to ChromaDB's built-in `all-MiniLM-L6-v2`, which is noticeably worse on code. `/api/health` shows which one is active.

---

## Retrieval

| Variable | Default | What it does |
|---|---|---|
| `CODEWISE_TOP_K` | `5` | Code chunks sent to the model per question |
| `CODEWISE_CANDIDATE_K` | `20` | Candidates each search method returns before the rankings are fused |
| `CODEWISE_MAX_DISTANCE` | `0.75` | Vector matches farther than this cosine distance are ignored (0 = identical, 2 = opposite) |
| `CODEWISE_CHUNK_MAX_CHARS` | `1500` | Maximum chunk size when splitting files |
| `CODEWISE_CHUNK_OVERLAP_LINES` | `5` | Overlap between line windows when a single function is too big for one chunk |

**Tuning tips**
- **Answers miss relevant code:** raise `CODEWISE_TOP_K` to 7 or 8, and `CODEWISE_NUM_CTX` if needed.
- **Answers are slow:** lower `CODEWISE_TOP_K` to 3. Each chunk adds reading time.
- **Irrelevant files show up as sources:** lower `CODEWISE_MAX_DISTANCE` to 0.6.

Chunking settings apply to files uploaded *after* the change; re-upload to rechunk existing files. Check the effect of any change with the [retrieval evaluation](evaluation.md).

---

## Uploads and imports

| Variable | Default | What it does |
|---|---|---|
| `CODEWISE_MAX_FILE_BYTES` | `1000000` | Largest single file that gets indexed (1 MB) |
| `CODEWISE_MAX_REQUEST_BYTES` | `100000000` | Largest upload request (100 MB). The frontend splits folders into batches under this |
| `CODEWISE_MAX_ARCHIVE_BYTES` | `100000000` | Largest zip or GitHub download (compressed) |
| `CODEWISE_MAX_ARCHIVE_FILES` | `20000` | Most entries a zip may contain |
| `CODEWISE_MAX_ARCHIVE_SOURCE_BYTES` | `200000000` | Most source a zip may expand to; protects against zip bombs |
| `CODEWISE_GITHUB_TOKEN` | *(empty)* | GitHub token for private repositories and higher rate limits |

**GitHub token.** Without one, GitHub allows 60 API requests per hour from your IP address. For private repositories, create a fine-grained token with **Contents: Read-only** access to them.

The list of supported file types and ignored folders is in `codewise/files.py`, and is exposed at `GET /api/upload-rules`.

---

## Storage

| Variable | Default | What it does |
|---|---|---|
| `CODEWISE_CHROMA_PATH` | `./chroma_data` | Folder for the vector index |
| `CODEWISE_DB_PATH` | `./codewise.db` | SQLite file for projects, files and the code graph |
| `CODEWISE_QUESTION_LOG` | *(off)* | If set, every question and answer is appended to this JSON Lines file |

Relative paths are resolved from the folder you start the backend in, so always start it from the project folder. Otherwise you'll get a new, empty database.

**Back up** by copying `chroma_data/` and `codewise.db` together while the backend is stopped. **Start fresh** by stopping the backend and deleting both.

**The question log** records the question, rewritten query, sources, answer, timing and whether the answer finished (`"complete": false` if you pressed Stop). It's for building test sets from real use; see [Evaluation](evaluation.md). It contains your questions and answers, so treat it as private.

---

## Server

| Variable | Default | What it does |
|---|---|---|
| `CODEWISE_HOST` | `127.0.0.1` | Address the backend listens on. `127.0.0.1` means only this machine can reach it |
| `CODEWISE_PORT` | `8000` | Backend port. (5000 is avoided because macOS AirPlay Receiver uses it) |
| `CODEWISE_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated browser origins allowed to call the API |
| `CODEWISE_DEBUG` | `false` | Flask debug mode |

**Changing the port.** Also update the frontend's API address in `frontend/src/App.jsx` (the `API` constant).

**Frontend on another port or host.** Add its address to `CODEWISE_CORS_ORIGINS`, or the browser will block its requests.

**Never enable `CODEWISE_DEBUG`** on a machine others can reach. The Flask debugger lets anyone who can open the page run code on your computer.

**No login.** CodeWise has no user accounts. Keep `CODEWISE_HOST=127.0.0.1` unless you've put it behind something that handles authentication.
