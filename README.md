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

Large files are divided into overlapping chunks while preserving context.

↓

### 3. Vector Storage

Each chunk is embedded and stored inside ChromaDB.

↓

### 4. Ask Questions

The user asks questions about the uploaded project.

↓

### 5. Semantic Retrieval

Relevant code chunks are retrieved using similarity search.

↓

### 6. AI Reasoning

Retrieved chunks and the user question are sent to Qwen2.5-Coder through Ollama.

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
- Streaming AI responses
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