import hashlib
import io
import math
import sys
from pathlib import Path

import chromadb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codewise.app import create_app  # noqa: E402
from codewise.config import Config  # noqa: E402
from codewise.index import ProjectIndex  # noqa: E402
from codewise.retrieval import tokenize  # noqa: E402
from codewise.service import CodeWise  # noqa: E402
from codewise.store import ProjectStore  # noqa: E402


class FakeEmbedder:
    """Deterministic hashed bag-of-words embeddings: no model download needed."""

    name = "fake:bow"
    dims = 64

    def _vec(self, text):
        v = [0.0] * self.dims
        for token in tokenize(text):
            v[int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dims] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


class FakeLLM:
    model = "fake-llm"

    def __init__(self):
        self.calls = []
        self.rewrite_answer = None

    def chat(self, messages, num_predict=None, temperature=None):
        self.calls.append(messages)
        if 'standalone search queries' in messages[0]['content'] and self.rewrite_answer:
            return self.rewrite_answer, {'input_tokens': 1, 'output_tokens': 1}
        return "fake answer", {'input_tokens': 10, 'output_tokens': 2}

    def stream(self, messages):
        self.calls.append(messages)
        yield "fake "
        yield "answer"


@pytest.fixture
def config(tmp_path):
    return Config(chroma_path=str(tmp_path / "chroma"), db_path=str(tmp_path / "db.sqlite"),
                  max_distance=2.0)


@pytest.fixture
def service(config):
    index = ProjectIndex(chromadb.PersistentClient(path=config.chroma_path), FakeEmbedder())
    return CodeWise(config, ProjectStore(config.db_path), index, FakeLLM())


@pytest.fixture
def client(config, service):
    app = create_app(config, service)
    app.testing = True
    return app.test_client()


def upload(client, project_id, *files):
    data = {'files': [(io.BytesIO(content.encode() if isinstance(content, str) else content), name)
                      for name, content in files]}
    return client.post(f'/api/projects/{project_id}/upload', data=data,
                       content_type='multipart/form-data')
