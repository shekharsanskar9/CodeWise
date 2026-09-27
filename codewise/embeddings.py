"""
Embedding backends. Embeddings are computed here and passed to Chroma explicitly, so the
text that is embedded (location header + code) can differ from the stored document.
"""

import logging

log = logging.getLogger(__name__)


class OllamaEmbedder:
    """Code-aware embeddings served by Ollama (default: nomic-embed-text)."""

    def __init__(self, client, model, batch_size=32):
        self.client = client
        self.model = model
        self.batch_size = batch_size
        # nomic-embed-text is trained with task prefixes; other models don't need them.
        self._nomic = 'nomic' in model
        self.name = f"ollama:{model}"

    def _embed(self, texts):
        vectors = []
        for i in range(0, len(texts), self.batch_size):
            response = self.client.embed(model=self.model, input=texts[i:i + self.batch_size])
            vectors.extend(response['embeddings'])
        return vectors

    def embed_documents(self, texts):
        if self._nomic:
            texts = [f"search_document: {t}" for t in texts]
        return self._embed(texts)

    def embed_query(self, text):
        if self._nomic:
            text = f"search_query: {text}"
        return self._embed([text])[0]


class ChromaDefaultEmbedder:
    """
    Fallback: Chroma's bundled all-MiniLM-L6-v2. It is an English sentence model that
    reads at most 256 tokens, so retrieval quality on code is noticeably worse.
    """

    name = "chroma:all-MiniLM-L6-v2"

    def __init__(self):
        from chromadb.utils import embedding_functions
        self._fn = embedding_functions.DefaultEmbeddingFunction()

    def embed_documents(self, texts):
        return [list(map(float, v)) for v in self._fn(texts)]

    def embed_query(self, text):
        return self.embed_documents([text])[0]


def make_embedder(config, client):
    """Use the configured Ollama embedding model, falling back to Chroma's default."""
    try:
        client.show(config.embed_model)
        return OllamaEmbedder(client, config.embed_model)
    except Exception as e:
        log.warning(
            "Embedding model %r unavailable via Ollama (%s). Falling back to %s; "
            "run `ollama pull %s` for much better code retrieval.",
            config.embed_model, e, ChromaDefaultEmbedder.name, config.embed_model,
        )
        return ChromaDefaultEmbedder()
