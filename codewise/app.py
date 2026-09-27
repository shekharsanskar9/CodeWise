"""
Flask routes. Kept thin: all logic lives in service.CodeWise.
"""

import json
import logging
from datetime import datetime

import chromadb
import ollama
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from .config import Config
from .embeddings import make_embedder
from .index import EmbeddingMismatch, ProjectIndex
from .llm import LLMError, OllamaLLM
from .service import BadRequest, CodeWise, NotFound
from .store import ProjectStore

log = logging.getLogger(__name__)


def build_service(config):
    client = ollama.Client(host=config.ollama_host, timeout=config.llm_timeout)
    embedder = make_embedder(config, client)
    index = ProjectIndex(chromadb.PersistentClient(path=config.chroma_path), embedder)
    return CodeWise(config, ProjectStore(config.db_path), index,
                    OllamaLLM(client, config.chat_model, config.num_ctx))


def create_app(config=None, service=None):
    config = config or Config()
    service = service or build_service(config)

    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = config.max_request_bytes
    CORS(app, origins=config.cors_origins)

    def error(message, status):
        return jsonify({'success': False, 'error': message}), status

    @app.errorhandler(NotFound)
    def handle_not_found(e):
        return error(str(e), 404)

    @app.errorhandler(BadRequest)
    def handle_bad_request(e):
        return error(str(e), 400)

    @app.errorhandler(EmbeddingMismatch)
    def handle_embedding_mismatch(e):
        return error(str(e), 409)

    @app.errorhandler(LLMError)
    def handle_llm_error(e):
        return error(str(e), 502)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(e):
        return error(f"Upload too large (limit {config.max_request_bytes:,} bytes)", 413)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error(e.description, e.code)
        log.exception("Unhandled error")
        return error("Internal server error", 500)

    @app.route('/api/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'chat_model': config.chat_model,
            'embed_model': service.index.embedder.name,
        })

    @app.route('/api/projects/create', methods=['POST'])
    def create_project():
        """Create a new project"""
        project_id = service.create_project()
        return jsonify({
            'success': True,
            'project_id': project_id,
            'message': 'Project created successfully'
        }), 201

    @app.route('/api/projects/<project_id>/upload', methods=['POST'])
    def upload_files(project_id):
        """Upload files to a project"""
        files = request.files.getlist('files')
        if not files:
            raise BadRequest('No files provided')

        results = service.upload_files(project_id, files)
        succeeded = sum(r['success'] for r in results)
        # 200 if everything was indexed, 207 for partial success, 400 if nothing was.
        status = 200 if succeeded == len(results) else (207 if succeeded else 400)
        return jsonify({
            'success': succeeded > 0,
            'project_id': project_id,
            'uploads': results,
            'metadata': service.store.metadata(project_id),
            **({} if succeeded else {'error': '; '.join(r['message'] for r in results)}),
        }), status

    @app.route('/api/projects/<project_id>/ask', methods=['POST'])
    def ask_question(project_id):
        """Ask a question about the project codebase"""
        result = service.ask(project_id, request.get_json(silent=True))
        return jsonify({'success': True, **result}), 200

    @app.route('/api/projects/<project_id>/ask/stream', methods=['POST'])
    def ask_question_stream(project_id):
        """
        Same as /ask, streamed as Server-Sent Events:
        `sources` (once), then `token` events, then `done` (or `error`).
        """
        prepared = service.prepare_question(project_id, request.get_json(silent=True))

        def sse(event, data):
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        def generate():
            yield sse('sources', {
                'sources': prepared['sources'],
                'search_query': prepared['search_query'],
                'context_found': prepared['context_found'],
            })
            try:
                for piece in service.llm.stream(prepared['messages']):
                    yield sse('token', {'content': piece})
                yield sse('done', {'model': service.llm.model})
            except LLMError as e:
                yield sse('error', {'error': str(e)})

        return Response(stream_with_context(generate()), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.route('/api/projects/<project_id>/analyze', methods=['GET'])
    def analyze_project(project_id):
        """Get AI-powered analysis of the project"""
        result = service.analyze(project_id)
        return jsonify({'success': True, 'project_id': project_id, **result}), 200

    @app.route('/api/projects/<project_id>/info', methods=['GET'])
    def get_project_info(project_id):
        """Get project information"""
        metadata = service.require_project(project_id)
        return jsonify({'success': True, 'project_id': project_id, 'metadata': metadata}), 200

    return app
