# Troubleshooting

Problems people actually run into, and how to fix them. When something fails, check two places first:
- **the backend terminal**, which logs every request and error;
- **the browser console** (Cmd+Option+J on Mac, Ctrl+Shift+J on Windows/Linux).

---

## The app won't start or connect

**"Create Project" does nothing / "Backend offline"**
The backend isn't running, or the page is talking to the wrong address.
1. Start the backend from the project folder: `source venv/bin/activate && python backend.py`. Keep that terminal open.
2. Check it with `curl http://127.0.0.1:8000/api/health`.
3. Hard-refresh the page (Cmd+Shift+R) so it loads the current frontend code.

**`ModuleNotFoundError: No module named 'flask'`** (or `pathspec`, `chromadb`, …)
The virtual environment isn't active, or dependencies are missing:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**`Address already in use`**
Something else is using port 8000. Find and stop it, or pick another port:
```bash
lsof -ti tcp:8000 | xargs kill          # stop whatever is on 8000
CODEWISE_PORT=8001 python backend.py    # or use another port (then update API in frontend/src/App.jsx)
```

**Requests hit port 5000 and fail with 403**
On macOS, AirPlay Receiver uses port 5000. CodeWise uses 8000 for this reason. If your page still calls 5000, it's an old cached version: hard-refresh.

**Browser console shows a CORS error**
The page's address isn't allowed. Open the frontend at `http://localhost:5173`, or add your address to `CODEWISE_CORS_ORIGINS` and restart the backend.

---

## Asking questions

**"Error getting response" / 502 errors**
Ollama isn't running or can't be reached. Open the Ollama app, or run `ollama serve`, then check with `ollama list`.

**409: "This project was indexed with …"**
The project was built with a different embedding model than the one the server uses now. This happens after pulling `nomic-embed-text` for the first time, or after changing `CODEWISE_EMBED_MODEL`. Create a new project and upload the code again.

**`/api/health` shows `chroma:all-MiniLM-L6-v2`**
The embedding model wasn't available when the backend started, so it fell back to the weaker built-in model:
1. Run `ollama pull nomic-embed-text`.
2. Make sure Ollama is running.
3. Restart the backend.

**Answers are slow**
This is expected with a 7B model on a laptop: about 10 seconds before text appears and 20–40 seconds in total on an M4 MacBook with 16 GB. To speed things up:
- lower `CODEWISE_TOP_K` to 3;
- set `CODEWISE_REWRITE_QUERIES=false` to skip the extra call on follow-ups;
- use a smaller model such as `qwen2.5-coder:3b` (weaker answers).

The first question after the model has been idle is slower, because Ollama has to load it into memory.

**Answers ignore my code or make things up**
- Check the source chips under the answer. If they point to the wrong files, the search missed; rephrase using exact names (`` `function_name` ``) or file names.
- Make sure the relevant files were actually indexed; they're listed under *Indexed Files*.
- If the log shows the fallback embedding model, fix that first (see above).

**"Who calls X?" lists callers of a different function**
Calls are matched by name, so two functions both called `save` are combined. Ask with the qualified name (`ProjectStore.save`) to see the right definition; the caller list is still name-based.

**Relationship questions don't work on an older project**
Projects uploaded before v3.0 have no code graph. Upload their files again.

---

## Uploads and imports

**Files are "skipped"**
That's usually on purpose: unsupported type, an ignored folder (`node_modules`, `venv`, `.git`, …), a lockfile, a minified or binary file, a file over 1 MB, or a `.gitignore` match. Each skipped file shows its reason in the upload response. Supported types and ignored folders are listed at `GET /api/upload-rules`.

**Folder upload is slow or huge**
The frontend already skips ignored folders before uploading. If a folder is still large, zip only the source code, or import from GitHub instead.

**413: "Upload too large"**
The request is over `CODEWISE_MAX_REQUEST_BYTES` (100 MB). Folder uploads are batched automatically; for a single large zip, raise the limit or import from GitHub.

**GitHub import: "not found"**
Check the URL. Private repositories need `CODEWISE_GITHUB_TOKEN`.

**GitHub import: "rate limit"**
Without a token, GitHub allows 60 requests per hour. Set `CODEWISE_GITHUB_TOKEN`.

---

## Data

**My projects disappeared**
The data is stored relative to the folder you start the backend from (`chroma_data/`, `codewise.db`). Starting it from a different folder gives a new, empty database. Always start it from the project folder.

**Start completely fresh**
Stop the backend, delete `chroma_data/` and `codewise.db`, and start it again.

**The page lost my project after a refresh**
The frontend doesn't remember the current project between page loads yet. The data is still on the backend; its ID is in `codewise.db`, and you can look it up with `GET /api/projects/<id>/info`.

---

## GitHub CLI (for maintainers)

**`HTTP 403: Resource not accessible by personal access token`**
Your fine-grained token is missing a permission, or doesn't include the repository:
- publishing releases needs **Contents: Read and write**;
- editing the About panel and topics needs **Administration: Read and write**.

Edit the token at https://github.com/settings/personal-access-tokens, and check **Repository access** includes the repo. Alternatively, `gh auth login --web` logs in with your full account access.

**Topics: "must start with a lowercase letter or number…"**
In the GitHub web editor, add topics one at a time (type one and press Enter). Pasting a space-separated list creates a single invalid topic.
