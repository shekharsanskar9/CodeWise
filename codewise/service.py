"""
Application logic: ingestion, question answering and project analysis.
"""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import PurePosixPath

from . import llm as prompts
from .chunking import chunk_code, split_lines
from .files import FileRejected, check_path, decode_content, normalize_path
from .graph import extract_graph
from .index import LEGACY_EMBED_MODEL
from .llm import (build_context, estimate_tokens, fence_for, fit_history, sanitize_history,
                  truncate_to_tokens)
from .relations import CodeRelations, render_relations
from .retrieval import hybrid_retrieve
from .sources import (SourceError, download_github_zip, filter_uploads, parse_github_url,
                      read_zip)

log = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 4000
MAX_MAP_FILES = 8

README_NAMES = {'readme.md', 'readme.txt', 'readme'}
DEPENDENCY_FILES = {'requirements.txt', 'pyproject.toml', 'package.json', 'go.mod', 'cargo.toml',
                    'pom.xml', 'build.gradle', 'gemfile', 'composer.json'}
ENTRYPOINT_STEMS = {'main', 'app', 'backend', 'server', 'index', 'manage', 'program', 'cli', 'wsgi', 'asgi'}


class NotFound(LookupError):
    pass


class BadRequest(ValueError):
    pass


def valid_project_id(project_id):
    try:
        return str(uuid.UUID(project_id)) == project_id
    except (ValueError, TypeError, AttributeError):
        return False


class CodeWise:
    def __init__(self, config, store, index, llm):
        self.config = config
        self.store = store
        self.index = index
        self.llm = llm
        self.relations = CodeRelations(store)
        self._log_lock = threading.Lock()

    # --- projects -----------------------------------------------------------------------

    def create_project(self):
        project_id = str(uuid.uuid4())
        self.store.create_project(project_id, self.index.embedder.name)
        return project_id

    def require_project(self, project_id):
        """Return project metadata or raise NotFound. Adopts collections created before metadata was persisted."""
        if not valid_project_id(project_id):
            raise NotFound("Project not found")
        metadata = self.store.metadata(project_id)
        if metadata is None and self.index.exists(project_id):
            self._recover_project(project_id)
            metadata = self.store.metadata(project_id)
        if metadata is None:
            raise NotFound("Project not found")
        return metadata

    def _recover_project(self, project_id):
        collection = self.index.chroma.get_collection(
            name=self.index.collection_name(project_id), embedding_function=None)
        embed_model = (collection.metadata or {}).get('embed_model', LEGACY_EMBED_MODEL)
        result = collection.get(include=['documents', 'metadatas'])
        per_file = {}
        for doc, meta in zip(result['documents'], result['metadatas']):
            name = (meta or {}).get('filename', 'unknown')
            info = per_file.setdefault(name, {'chunks': 0, 'size': 0, 'lines': 0})
            info['chunks'] += 1
            info['size'] += len(doc)
            info['lines'] = max(info['lines'], (meta or {}).get('end_line', 0))
        self.store.create_project(project_id, embed_model, created_at=datetime.now().isoformat())
        for name, info in per_file.items():
            self.store.upsert_file(project_id, name, info['chunks'], info['size'], info['lines'])
        log.info("Recovered metadata for project %s (%d files)", project_id, len(per_file))

    # --- ingestion ----------------------------------------------------------------------

    def upload_files(self, project_id, files):
        """
        Ingest uploaded files. Zip archives are expanded; folder uploads send relative paths
        plus their .gitignore files, which are applied to the rest of the batch.
        """
        self.require_project(project_id)
        entries, results = [], []
        for file in files:
            raw_name = file.filename or ''
            if raw_name.lower().endswith('.zip'):
                try:
                    extracted, skipped = self._read_zip(file.read())
                except SourceError as e:
                    results.append({'filename': raw_name, 'success': False, 'message': str(e)})
                    continue
                entries.extend(extracted)
                results.extend(skipped)
                continue
            try:
                entries.append((normalize_path(raw_name), file.read()))
            except FileRejected as e:
                results.append({'filename': raw_name, 'success': False, 'message': str(e)})
        return results + self._ingest_entries(project_id, entries)

    def import_github(self, project_id, data):
        self.require_project(project_id)
        if not isinstance(data, dict):
            raise BadRequest("Request body must be a JSON object")
        try:
            owner, repo, ref = parse_github_url(data.get('url'), data.get('ref') or None)
            archive = download_github_zip(owner, repo, ref, self.config.max_archive_bytes,
                                          token=self.config.github_token or None)
            extracted, skipped = self._read_zip(archive)
        except SourceError as e:
            raise BadRequest(str(e))
        results = skipped + self._ingest_entries(project_id, extracted)
        return {'owner': owner, 'repo': repo, 'ref': ref}, results

    def _read_zip(self, data):
        if len(data) > self.config.max_archive_bytes:
            raise SourceError(f"Archive too large (limit {self.config.max_archive_bytes:,} bytes)")
        return read_zip(data, self.config.max_archive_files,
                        self.config.max_archive_source_bytes, self.config.max_file_bytes)

    def _ingest_entries(self, project_id, entries):
        files, skipped, _ = filter_uploads(entries)
        return skipped + [self._ingest(project_id, path, raw) for path, raw in files]

    def _ingest(self, project_id, path, raw):
        try:
            check_path(path)
            content = decode_content(raw, self.config.max_file_bytes)
            chunks = chunk_code(content, path, max_chars=self.config.chunk_max_chars,
                                overlap_lines=self.config.chunk_overlap_lines)
            if not chunks:
                raise FileRejected("File is empty")
            self.index.replace_file(project_id, path, chunks)
            self.store.replace_file_graph(project_id, path, extract_graph(content, path))
            self.store.upsert_file(project_id, path, chunks=len(chunks), size=len(content),
                                   lines=len(split_lines(content)))
            return {'filename': path, 'success': True,
                    'message': f"Successfully processed {path} with {len(chunks)} chunks"}
        except FileRejected as e:
            return {'filename': path, 'success': False, 'skipped': True, 'message': str(e)}
        except Exception as e:
            log.exception("Failed to ingest %s", path)
            return {'filename': path, 'success': False, 'message': f"Error processing file: {e}"}

    # --- question answering -------------------------------------------------------------

    def prepare_question(self, project_id, data):
        """Retrieve context and build the chat messages for a question."""
        self.require_project(project_id)
        if not isinstance(data, dict):
            raise BadRequest("Request body must be a JSON object")
        question = data.get('question')
        if not isinstance(question, str) or not question.strip():
            raise BadRequest("Question is required")
        question = question.strip()
        if len(question) > MAX_QUESTION_CHARS:
            raise BadRequest(f"Question is too long (max {MAX_QUESTION_CHARS} characters)")
        history = sanitize_history(data.get('history', []))

        search_query = self._standalone_query(question, history)
        files = [f['filename'] for f in self.store.list_files(project_id)]
        # The rewritten query may name the symbol a follow-up refers to ("it").
        relations = self.relations.for_question(project_id, f"{question}\n{search_query}", files)
        retrieved = hybrid_retrieve(
            self.index, project_id, search_query,
            top_k=self.config.top_k, candidate_k=self.config.candidate_k,
            max_distance=self.config.max_distance, locations=relations.locations(),
        )

        # Token budget: the prompt must fit in num_ctx with room left for the answer,
        # otherwise Ollama silently drops the start of the prompt (system prompt first).
        available = (self.config.num_ctx - self.config.answer_reserve_tokens
                     - estimate_tokens(prompts.QA_SYSTEM_PROMPT) - estimate_tokens(question) - 64)
        relations_str = render_relations(relations, int(available * 0.15))
        context_str, used = build_context(retrieved, int(available * 0.7) - estimate_tokens(relations_str))
        context_str = relations_str + context_str
        history_budget = available - estimate_tokens(context_str)
        history = fit_history(history, max(history_budget, 0))

        messages = [{'role': 'system', 'content': prompts.QA_SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({'role': 'user', 'content': f"{context_str}\n\nQuestion: {question}"})

        sources = [{
            'filename': r.chunk.path,
            'lines': f"{r.chunk.start_line}-{r.chunk.end_line}",
            'symbol': r.chunk.symbol,
            'score': r.score,
            'similarity': r.similarity,
            'matched_by': r.matched_by,
        } for r in used]
        return {
            'question': question,
            'search_query': search_query,
            'messages': messages,
            'sources': sources,
            'context_found': bool(used),
            'relations': [s.name for s in relations.symbols] + [f.path for f in relations.files],
            'started': time.monotonic(),
        }

    def ask(self, project_id, data):
        prepared = self.prepare_question(project_id, data)
        answer, usage = self.llm.chat(prepared['messages'])
        self.log_interaction(project_id, prepared, answer, usage)
        return {
            'question': prepared['question'],
            'answer': answer,
            'sources': prepared['sources'],
            'search_query': prepared['search_query'],
            'context_found': prepared['context_found'],
            'relations': prepared['relations'],
            'model': self.llm.model,
            'usage': usage,
        }

    def log_interaction(self, project_id, prepared, answer, usage=None, complete=True):
        """Append a real question/answer to the opt-in JSONL log (CODEWISE_QUESTION_LOG)."""
        path = self.config.question_log_path
        if not path:
            return
        record = {
            'timestamp': datetime.now().isoformat(),
            'project_id': project_id,
            'question': prepared['question'],
            'search_query': prepared['search_query'],
            'sources': prepared['sources'],
            'relations': prepared['relations'],
            'answer': answer,
            'complete': complete,
            'usage': usage,
            'seconds': round(time.monotonic() - prepared['started'], 2),
            'model': self.llm.model,
        }
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with self._log_lock, open(path, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(record) + '\n')
        except OSError as e:
            log.warning("Could not write question log: %s", e)

    def _standalone_query(self, question, history):
        """Rewrite a follow-up ("how does it handle errors?") into a self-contained search query."""
        if not history or not self.config.rewrite_queries:
            return question
        transcript = '\n'.join(
            f"{m['role']}: {truncate_to_tokens(m['content'], 200)}" for m in history[-6:]
        )
        try:
            rewritten, _ = self.llm.chat([
                {'role': 'system', 'content': prompts.REWRITE_SYSTEM_PROMPT},
                {'role': 'user', 'content': f"Conversation:\n{transcript}\n\nLatest question: {question}"},
            ], num_predict=80, temperature=0)
        except prompts.LLMError as e:
            log.warning("Query rewrite failed, using original question: %s", e)
            return question
        rewritten = rewritten.strip().splitlines()[0].strip().strip('"\'') if rewritten.strip() else ''
        if not rewritten or len(rewritten) > 500:
            return question
        return rewritten

    # --- code graph ---------------------------------------------------------------------

    def graph(self, project_id, symbol=None, path=None):
        self.require_project(project_id)
        if symbol:
            return {'symbol': asdict(self.relations.symbol(project_id, symbol))}
        if path:
            files = [f['filename'] for f in self.store.list_files(project_id)]
            if path not in files:
                raise NotFound(f"File not found: {path}")
            return {'file': asdict(self.relations.file(project_id, path, files)),
                    'symbols': self.store.file_symbols(project_id, path)}
        raise BadRequest("Pass ?symbol=<name> or ?file=<path>")

    # --- project analysis ---------------------------------------------------------------

    def analyze(self, project_id):
        metadata = self.require_project(project_id)
        files = metadata['files']
        if not files:
            raise BadRequest("No files uploaded yet")

        tree = "## Project files\n" + '\n'.join(f"- {f['filename']} ({f['lines']} lines)" for f in files)
        ordered = _prioritize(files)
        budget = (self.config.num_ctx - self.config.answer_reserve_tokens
                  - estimate_tokens(prompts.ANALYZE_SYSTEM_PROMPT) - estimate_tokens(tree) - 100)

        texts = {f['filename']: self.index.file_text(project_id, f['filename']) for f in ordered}
        blocks = {name: _file_block(name, text) for name, text in texts.items()}
        total = sum(estimate_tokens(b) for b in blocks.values())

        if total <= budget:
            # Everything fits: analyse the actual code in one pass.
            mode = 'full'
            body = ''.join(blocks[f['filename']] for f in ordered)
            analyzed = [f['filename'] for f in ordered]
        else:
            # Map-reduce: README/dependency files verbatim, key source files summarised first.
            mode = 'map_reduce'
            key_budget = budget // 4
            body, analyzed, used = '', [], 0
            for f in ordered:
                name = f['filename']
                if _is_key_file(name) and used + estimate_tokens(blocks[name]) <= key_budget:
                    body += blocks[name]
                    analyzed.append(name)
                    used += estimate_tokens(blocks[name])
            code_files = [f['filename'] for f in ordered
                          if f['filename'] not in analyzed and f['filename'].lower().endswith(_CODE_SUFFIXES)]
            per_file_tokens = self.config.num_ctx - 600 - estimate_tokens(prompts.SUMMARIZE_FILE_PROMPT) - 100
            summaries = ''
            for name in code_files[:MAX_MAP_FILES]:
                summary, _ = self.llm.chat([
                    {'role': 'system', 'content': prompts.SUMMARIZE_FILE_PROMPT},
                    {'role': 'user', 'content': truncate_to_tokens(blocks[name], per_file_tokens)},
                ], num_predict=500)
                entry = f"### Summary of {name}\n{summary.strip()}\n\n"
                if used + estimate_tokens(entry) > budget:
                    break
                summaries += entry
                analyzed.append(name)
                used += estimate_tokens(entry)
            body += summaries

        analysis, usage = self.llm.chat([
            {'role': 'system', 'content': prompts.ANALYZE_SYSTEM_PROMPT},
            {'role': 'user', 'content': f"Analyze this project.\n\n{tree}\n\n{body}"},
        ])
        return {
            'metadata': metadata,
            'analysis': analysis,
            'files_analyzed': analyzed,
            'mode': mode,
            'usage': usage,
        }


_CODE_SUFFIXES = ('.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp', '.cs',
                  '.go', '.rb', '.php', '.swift', '.kt', '.rs', '.sql')


def _is_key_file(path):
    return PurePosixPath(path).name.lower() in README_NAMES | DEPENDENCY_FILES


def _prioritize(files):
    """README and dependency manifests first, then entry points, then larger source files."""
    def rank(f):
        p = PurePosixPath(f['filename'])
        name = p.name.lower()
        if name in README_NAMES:
            group = 0
        elif name in DEPENDENCY_FILES:
            group = 1
        elif p.stem.lower() in ENTRYPOINT_STEMS and name.endswith(_CODE_SUFFIXES):
            group = 2
        elif name.endswith(_CODE_SUFFIXES):
            group = 3
        else:
            group = 4
        return (group, len(p.parts), -f['lines'], f['filename'])
    return sorted(files, key=rank)


def _file_block(name, text):
    fence = fence_for(text)
    return f"### {name}\n{fence}\n{text}\n{fence}\n\n"
