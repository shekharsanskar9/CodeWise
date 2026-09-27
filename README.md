# 🚀 CodeWise – Intelligent Code Mentor AI

CodeWise is a Retrieval-Augmented Generation (RAG) powered AI assistant that understands an entire codebase instead of answering questions from a single file.

Developers can upload source code, ask questions in natural language, and receive context-aware explanations generated using **Qwen2.5-Coder** running locally through **Ollama**. Relevant code snippets are retrieved from **ChromaDB**, allowing the model to answer based on the uploaded project rather than relying only on its pre-trained knowledge.

---

# ✨ Features

- 📂 Upload complete software projects
- 🔍 Semantic code search using ChromaDB
- 🤖 Local LLM inference using Ollama
- 💬 Natural language Q&A over code
- 📄 Source file and line references
- 📊 AI-powered project analysis
- ⚡ Fast Flask REST API
- 🎨 Modern React interface

---

# 🏗 System Architecture

```
                User Question
                      │
                      ▼
              React Frontend
                      │
               HTTP REST API
                      │
                      ▼
                Flask Backend
                      │
                      ▼
                 ChromaDB
          (Semantic Retrieval)
                      │
                      ▼
          Retrieve Relevant Chunks
                      │
                      ▼
               Ollama Server
                      │
                      ▼
          Qwen2.5-Coder 7B Model
                      │
                      ▼
               AI Generated Answer
```

---

# 🧠 RAG Pipeline

```
User uploads code
        │
        ▼
File Processing
        │
        ▼
Code Chunking
        │
        ▼
Store Chunks in ChromaDB
        │
        ▼
─────────────────────────────────
        │
User asks a question
        │
        ▼
Semantic Search
        │
        ▼
Retrieve Top Code Chunks
        │
        ▼
Prompt Construction
        │
        ▼
Qwen2.5-Coder (Ollama)
        │
        ▼
AI Response + Sources
```

---

# ⚙ Technology Stack

## Backend

- Python
- Flask
- ChromaDB
- Ollama
- Qwen2.5-Coder
- REST APIs

## Frontend

- React
- JavaScript
- Tailwind CSS
- Lucide React

---

# 📂 Project Workflow

### 1. Upload Code

The user uploads one or multiple source files.

↓

### 2. Intelligent Chunking

Files are split along the code's structure: Python by AST (functions, classes, and methods of large classes), C-like languages by top-level brace blocks, Markdown by headings. Small neighbours are packed together, and oversized blocks fall back to overlapping line windows. Each chunk records its 1-based line range and symbol name.

Lockfiles, minified bundles, binaries and directories such as `node_modules/`, `dist/` and `venv/` are rejected at upload.

↓

### 3. Vector Storage

Each chunk is embedded with a code-aware model (`nomic-embed-text` via Ollama) together with a `File / Symbol / Lines` header, and stored in ChromaDB. Re-uploading a file replaces its old chunks. Project metadata is persisted in SQLite (`codewise.db`).

↓

### 4. Ask Questions

The user asks questions about the uploaded project.

↓

### 5. Semantic Retrieval

Follow-up questions are first rewritten into standalone queries using the chat history. Retrieval is hybrid: vector search plus BM25 keyword search (identifier-aware, splits `snake_case`/`camelCase`), fused with Reciprocal Rank Fusion. Files named in the question are boosted, and low-relevance hits are dropped.

↓

### 6. AI Reasoning

Retrieved chunks, with real line numbers on every line, are sent with the question and trimmed history to Qwen2.5-Coder through Ollama. The prompt is token-budgeted to fit `num_ctx`, so nothing is silently truncated.

↓

### 7. Response Generation

The model generates an answer grounded in the retrieved code and returns the corresponding source files.

---

# 📌 Supported Languages

- Python
- Java
- JavaScript
- TypeScript
- C
- C++
- C#
- Go
- PHP
- Kotlin
- Swift
- Rust
- HTML
- CSS
- SQL
- JSON
- Markdown
- YAML
- XML

---

# 🎯 Example

### User

> Explain the authentication flow.

↓

### ChromaDB retrieves

```
auth.py
login.py
jwt.py
middleware.py
```

↓

### Qwen2.5-Coder answers

```
Authentication starts inside login.py where the user
credentials are verified.

After validation,
a JWT token is generated in jwt.py.

The middleware checks the token
before protected routes are executed.
```

↓

### Sources

```
login.py (Lines 45-80)

jwt.py (Lines 12-38)

middleware.py (Lines 20-60)
```

---

# 🛠 Running the Backend

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text      # code-aware embeddings (falls back to all-MiniLM-L6-v2 if missing)
python backend.py                 # http://127.0.0.1:5000
```

Projects indexed with one embedding model can't be queried with another. If you switch models, create a new project and re-upload.

## Configuration

Set via environment variables or a `.env` file:

| Variable | Default | Purpose |
|----------|---------|---------|
| `CODEWISE_CHAT_MODEL` | `qwen2.5-coder:7b` | Ollama chat model |
| `CODEWISE_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `CODEWISE_NUM_CTX` | `8192` | Context window passed to Ollama |
| `CODEWISE_ANSWER_RESERVE` | `1536` | Tokens kept free for the answer |
| `CODEWISE_TOP_K` | `5` | Chunks sent to the model |
| `CODEWISE_MAX_DISTANCE` | `0.75` | Cosine distance cutoff for vector hits |
| `CODEWISE_CHUNK_MAX_CHARS` | `1500` | Max chunk size |
| `CODEWISE_REWRITE_QUERIES` | `true` | Rewrite follow-up questions before search |
| `CODEWISE_MAX_FILE_BYTES` | `1000000` | Per-file upload limit |
| `CODEWISE_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed frontend origins |
| `CODEWISE_DEBUG` | `false` | Flask debug mode. Never enable on a reachable host |

## API

| Method | Endpoint | Notes |
|--------|----------|-------|
| POST | `/api/projects/create` | Returns `project_id` |
| POST | `/api/projects/<id>/upload` | Multipart `files`. Returns 200 if all files were indexed, 207 if some were, 400 if none |
| POST | `/api/projects/<id>/ask` | `{question, history}`. Sources include line range, symbol and scores |
| POST | `/api/projects/<id>/ask/stream` | Same as `/ask`, as Server-Sent Events (`sources`, `token`, `done`) |
| GET | `/api/projects/<id>/analyze` | Analyzes the whole project, or map-reduces per-file summaries if it's too large |
| GET | `/api/projects/<id>/info` | Project metadata |

## Tests and Retrieval Evaluation

```bash
pip install -r requirements-dev.txt
pytest                              # unit + API tests (no Ollama needed)
python eval/retrieval_eval.py -v    # hit@k / MRR for vector vs keyword vs hybrid retrieval
```

`eval/questions.json` holds question → expected-file pairs. Extend it or point `--root` and `--questions` at another project to measure whether a retrieval change helps.

---

# 💡 Applications

- Understanding unfamiliar codebases
- Project documentation
- AI-assisted code review
- Debugging support
- Architecture explanation
- Learning open-source projects
- Developer onboarding

---

# 🚀 Highlights

- Retrieval-Augmented Generation (RAG)
- Local AI execution (No paid APIs)
- Semantic vector search
- Context-aware code understanding
- Multi-file reasoning
- Source attribution
- Modern React UI
- RESTful backend

---

# 📊 Architecture Components

| Component | Purpose |
|-----------|----------|
| React | User Interface |
| Flask | Backend API |
| ChromaDB | Vector Database |
| Ollama | Local Model Runtime |
| Qwen2.5-Coder | Code LLM |
| File Chunker | Splits source code |
| Semantic Search | Retrieves relevant code |
| RAG Pipeline | Generates contextual answers |

---

# 🎯 Future Improvements

- GitHub repository integration
- Drag-and-drop project upload
- VS Code Extension
- Repository summarization
- Code visualization
- Streaming responses in the UI (backend already exposes `/ask/stream`)
- Multi-user support
- Docker deployment
- Authentication system

---

# 👨‍💻 Author

**Sanskar Shekhar**

Computer Science Engineer

AI • Machine Learning • Full Stack Development

---

# ⭐ Project Goal

The objective of CodeWise is to enable developers to interact with their codebase using natural language. By combining Retrieval-Augmented Generation with semantic search and a locally hosted LLM, CodeWise delivers accurate, context-aware answers grounded in the uploaded source code.