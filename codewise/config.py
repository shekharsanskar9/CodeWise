"""
Runtime configuration, overridable through environment variables (or a .env file).
"""

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env_int(name, default):
    return int(os.environ.get(name, default))


def _env_float(name, default):
    return float(os.environ.get(name, default))


def _env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    # Storage
    chroma_path: str = field(default_factory=lambda: os.environ.get("CODEWISE_CHROMA_PATH", "./chroma_data"))
    db_path: str = field(default_factory=lambda: os.environ.get("CODEWISE_DB_PATH", "./codewise.db"))

    # Models
    ollama_host: str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    chat_model: str = field(default_factory=lambda: os.environ.get("CODEWISE_CHAT_MODEL", "qwen2.5-coder:7b"))
    embed_model: str = field(default_factory=lambda: os.environ.get("CODEWISE_EMBED_MODEL", "nomic-embed-text"))
    # Context window passed to Ollama. Ollama's default is small (2k-4k) and silently
    # truncates longer prompts from the front, so this must be set explicitly.
    num_ctx: int = field(default_factory=lambda: _env_int("CODEWISE_NUM_CTX", 8192))
    # Tokens reserved for the model's answer inside num_ctx.
    answer_reserve_tokens: int = field(default_factory=lambda: _env_int("CODEWISE_ANSWER_RESERVE", 1536))
    llm_timeout: float = field(default_factory=lambda: _env_float("CODEWISE_LLM_TIMEOUT", 300))
    rewrite_queries: bool = field(default_factory=lambda: _env_bool("CODEWISE_REWRITE_QUERIES", True))

    # Chunking
    # nomic-embed-text handles ~2k tokens; ~1500 chars of code stays well inside it.
    chunk_max_chars: int = field(default_factory=lambda: _env_int("CODEWISE_CHUNK_MAX_CHARS", 1500))
    chunk_overlap_lines: int = field(default_factory=lambda: _env_int("CODEWISE_CHUNK_OVERLAP_LINES", 5))

    # Retrieval
    top_k: int = field(default_factory=lambda: _env_int("CODEWISE_TOP_K", 5))
    candidate_k: int = field(default_factory=lambda: _env_int("CODEWISE_CANDIDATE_K", 20))
    # Cosine distance above which a vector hit is considered irrelevant (0 = identical, 2 = opposite).
    max_distance: float = field(default_factory=lambda: _env_float("CODEWISE_MAX_DISTANCE", 0.75))

    # Uploads
    max_file_bytes: int = field(default_factory=lambda: _env_int("CODEWISE_MAX_FILE_BYTES", 1_000_000))
    max_request_bytes: int = field(default_factory=lambda: _env_int("CODEWISE_MAX_REQUEST_BYTES", 100_000_000))
    # Zip uploads and GitHub imports
    max_archive_bytes: int = field(default_factory=lambda: _env_int("CODEWISE_MAX_ARCHIVE_BYTES", 100_000_000))
    max_archive_files: int = field(default_factory=lambda: _env_int("CODEWISE_MAX_ARCHIVE_FILES", 20_000))
    max_archive_source_bytes: int = field(default_factory=lambda: _env_int("CODEWISE_MAX_ARCHIVE_SOURCE_BYTES", 200_000_000))
    github_token: str = field(default_factory=lambda: os.environ.get("CODEWISE_GITHUB_TOKEN", ""))

    # Opt-in log of real questions/answers, used to build answer-quality test sets.
    question_log_path: str = field(default_factory=lambda: os.environ.get("CODEWISE_QUESTION_LOG", ""))

    # Server
    debug: bool = field(default_factory=lambda: _env_bool("CODEWISE_DEBUG", False))
    host: str = field(default_factory=lambda: os.environ.get("CODEWISE_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("CODEWISE_PORT", 8000))
    cors_origins: list = field(default_factory=lambda: [
        o.strip() for o in os.environ.get(
            "CODEWISE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",") if o.strip()
    ])
