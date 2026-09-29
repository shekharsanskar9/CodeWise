# CodeWise frontend

The React app for CodeWise: the upload panel, the chat with streamed answers, and the source chips. Built with Vite, Tailwind CSS and Lucide icons.

## Running

```bash
npm install
npm run dev        # http://localhost:5173
```

The backend must be running at `http://127.0.0.1:8000`; see the [project README](../README.md). To point the app at a different backend, change the `API` constant at the top of `src/App.jsx`, and add the frontend's address to the backend's `CODEWISE_CORS_ORIGINS`.

```bash
npm run build      # production build into dist/
npx oxlint src     # lint
```

## Code layout

| File | What it does |
|---|---|
| `src/App.jsx` | The whole UI: sidebar (project, uploads, GitHub import, indexed files), chat, streaming, source chips |
| `src/lib/uploads.js` | Collects files from inputs and drag-and-drop (walking dropped folders), filters them with the server's `/api/upload-rules`, and uploads them in batches under the request size limit |
| `src/lib/stream.js` | Reads streamed answers: Server-Sent Events over a `POST` request, which the browser's `EventSource` can't do |
| `src/main.jsx` | Mounts the app |

## How the main flows work

**Uploading a folder**
1. Dropped folders are walked recursively; ignored folders such as `node_modules` are never opened.
2. Unsupported and ignored files are filtered out in the browser.
3. The remaining files are sent in batches, with each file's relative path as its name. `.gitignore` files go in every batch so the server can apply them.

**Asking a question**
1. The question and the chat history are posted to `/api/projects/<id>/ask/stream`.
2. The `sources` event fills in the source chips, and each `token` event appends text to the answer.
3. **Stop** aborts the request, which also stops generation on the server.

The API is documented in [docs/api.md](../docs/api.md).
