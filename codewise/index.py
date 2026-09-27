"""
Chroma-backed chunk index for a project, plus an in-memory keyword (BM25) index kept in sync.
"""

import threading

from .chunking import Chunk
from .embeddings import ChromaDefaultEmbedder
from .retrieval import BM25Index

LEGACY_EMBED_MODEL = ChromaDefaultEmbedder.name


class EmbeddingMismatch(RuntimeError):
    """The collection was built with a different embedding model than the one in use."""


class ProjectIndex:
    def __init__(self, chroma_client, embedder):
        self.chroma = chroma_client
        self.embedder = embedder
        self._bm25_cache = {}
        self._lock = threading.Lock()

    @staticmethod
    def collection_name(project_id):
        return f"project_{project_id}"

    def _collection(self, project_id, create=False):
        name = self.collection_name(project_id)
        if create:
            collection = self.chroma.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine", "embed_model": self.embedder.name},
                embedding_function=None,
            )
        else:
            collection = self.chroma.get_collection(name=name, embedding_function=None)
        # Collections from before embed_model was recorded used Chroma's default model.
        built_with = (collection.metadata or {}).get("embed_model", LEGACY_EMBED_MODEL)
        if built_with != self.embedder.name:
            raise EmbeddingMismatch(
                f"This project was indexed with {built_with}, but the server is using "
                f"{self.embedder.name}. Create a new project and re-upload the files."
            )
        return collection

    def exists(self, project_id):
        try:
            self.chroma.get_collection(name=self.collection_name(project_id), embedding_function=None)
            return True
        except Exception:
            return False

    def replace_file(self, project_id, path, chunks):
        """Index a file's chunks, first removing any chunks from a previous upload of it."""
        collection = self._collection(project_id, create=True)
        collection.delete(where={"filename": path})
        if chunks:
            collection.add(
                ids=[c.chunk_id for c in chunks],
                documents=[c.content for c in chunks],
                metadatas=[c.metadata() for c in chunks],
                embeddings=self.embedder.embed_documents([c.search_text for c in chunks]),
            )
        self._invalidate(project_id)

    def all_chunks(self, project_id):
        collection = self._collection(project_id)
        result = collection.get(include=["documents", "metadatas"])
        return [_to_chunk(doc, meta) for doc, meta in zip(result["documents"], result["metadatas"])]

    def file_chunks(self, project_id, path):
        collection = self._collection(project_id)
        result = collection.get(where={"filename": path}, include=["documents", "metadatas"])
        chunks = [_to_chunk(doc, meta) for doc, meta in zip(result["documents"], result["metadatas"])]
        return sorted(chunks, key=lambda c: (c.start_line, c.index))

    def file_text(self, project_id, path):
        """Rebuild a file's text from its chunks, dropping the overlap between windows."""
        lines = []
        last_end = 0
        for chunk in self.file_chunks(project_id, path):
            chunk_lines = chunk.content.split('\n')
            skip = max(0, last_end - chunk.start_line + 1)
            lines.extend(chunk_lines[skip:])
            last_end = max(last_end, chunk.end_line)
        return '\n'.join(lines)

    def vector_search(self, project_id, query, n_results):
        collection = self._collection(project_id)
        count = collection.count()
        if count == 0:
            return []
        result = collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=min(n_results, count),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for doc, meta, dist in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
            hits.append((_to_chunk(doc, meta), dist))
        return hits

    def keyword_index(self, project_id):
        with self._lock:
            index = self._bm25_cache.get(project_id)
        if index is None:
            index = BM25Index(self.all_chunks(project_id))
            with self._lock:
                self._bm25_cache[project_id] = index
        return index

    def _invalidate(self, project_id):
        with self._lock:
            self._bm25_cache.pop(project_id, None)


def _to_chunk(document, metadata):
    metadata = metadata or {}
    return Chunk(
        path=metadata.get('filename', 'unknown'),
        index=metadata.get('chunk_index', 0),
        start_line=metadata.get('start_line', 1),
        end_line=metadata.get('end_line', 1),
        content=document,
        symbol=metadata.get('symbol') or None,
        file_type=metadata.get('file_type', 'code'),
    )
