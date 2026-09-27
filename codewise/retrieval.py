"""
Hybrid retrieval: vector search + BM25 keyword search, fused with Reciprocal Rank Fusion.

Pure vector search is weak at exact identifiers ("where is chunk_code called?"), and
keyword search is weak at paraphrases; combining both covers each other's blind spots.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath

_IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*|\d+')
_CAMEL_RE = re.compile(r'[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|[A-Z]+|\d+')
_STOPWORDS = {'the', 'a', 'an', 'is', 'are', 'was', 'of', 'to', 'in', 'on', 'for', 'and', 'or',
              'how', 'what', 'where', 'why', 'does', 'do', 'it', 'this', 'that', 'with', 'be',
              'can', 'i', 'me', 'my', 'you', 'which', 'when', 'by', 'from', 'as', 'at', 'file'}

RRF_K = 60
KEYWORD_RELATIVE_CUTOFF = 0.25


def tokenize(text):
    """Lower-cased identifiers plus their snake_case / camelCase parts."""
    tokens = []
    for ident in _IDENT_RE.findall(text):
        lower = ident.lower()
        if lower in _STOPWORDS:
            continue
        tokens.append(lower)
        parts = [p.lower() for piece in ident.split('_') for p in _CAMEL_RE.findall(piece)]
        if len(parts) > 1:
            tokens.extend(p for p in parts if p not in _STOPWORDS and len(p) > 1)
    return tokens


class BM25Index:
    def __init__(self, chunks, k1=1.5, b=0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.term_freqs = [Counter(tokenize(c.search_text)) for c in chunks]
        self.lengths = [sum(tf.values()) for tf in self.term_freqs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0
        df = Counter()
        for tf in self.term_freqs:
            df.update(tf.keys())
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def score(self, i, query_terms):
        tf = self.term_freqs[i]
        norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg_len or 1))
        total = 0.0
        for term in query_terms:
            f = tf.get(term)
            if f:
                total += self.idf[term] * f * (self.k1 + 1) / (f + norm)
        return total

    def search(self, query, n_results, paths=None):
        """Top chunks by BM25; with ``paths``, only chunks from those files (zero scores allowed)."""
        terms = set(tokenize(query))
        scored = []
        for i, chunk in enumerate(self.chunks):
            if paths is not None and chunk.path not in paths:
                continue
            s = self.score(i, terms)
            if s > 0 or paths is not None:
                scored.append((chunk, s))
        scored.sort(key=lambda x: (-x[1], x[0].path, x[0].start_line))
        return scored[:n_results]


@dataclass
class RetrievedChunk:
    chunk: object
    score: float           # fused RRF score, higher is better
    similarity: float      # 1 - cosine distance, or None if only found by keyword search
    matched_by: list


def mentioned_files(query, paths):
    """Files the question names explicitly, by full path or by base name."""
    q = query.lower()
    found = set()
    for path in paths:
        name = PurePosixPath(path).name.lower()
        if path.lower() in q or re.search(rf'(?<![\w.]){re.escape(name)}(?![\w])', q):
            found.add(path)
    return found


def chunks_at(chunks, locations):
    """The chunk containing each (path, line), in order, without duplicates."""
    by_path = {}
    for chunk in chunks:
        by_path.setdefault(chunk.path, []).append(chunk)
    found = {}
    for path, line in locations:
        for chunk in by_path.get(path, []):
            if chunk.start_line <= line <= chunk.end_line:
                found.setdefault(chunk.chunk_id, chunk)
                break
    return list(found.values())


def hybrid_retrieve(index, project_id, query, top_k=5, candidate_k=20, max_distance=0.75, locations=None):
    """
    ``locations`` are (path, line) pairs from the code graph (definitions and call sites
    of symbols named in the question); their chunks join the fusion as a third signal.
    """
    keyword_index = index.keyword_index(project_id)
    ranked_lists = {}

    vector_hits = [(c, d) for c, d in index.vector_search(project_id, query, candidate_k)
                   if d <= max_distance]
    ranked_lists['vector'] = [c for c, _ in vector_hits]
    distances = {c.chunk_id: d for c, d in vector_hits}

    keyword_hits = keyword_index.search(query, candidate_k)
    if keyword_hits:
        # Drop the long tail of chunks that only share a common word with the query.
        cutoff = keyword_hits[0][1] * KEYWORD_RELATIVE_CUTOFF
        keyword_hits = [(c, s) for c, s in keyword_hits if s >= cutoff]
    ranked_lists['keyword'] = [c for c, _ in keyword_hits]

    all_paths = {c.path for c in keyword_index.chunks}
    named = mentioned_files(query, all_paths)
    if named:
        ranked_lists['filename'] = [c for c, _ in keyword_index.search(query, 3 * len(named), paths=named)]

    if locations:
        ranked_lists['graph'] = chunks_at(keyword_index.chunks, locations)[:candidate_k]

    fused = {}
    for source, chunks in ranked_lists.items():
        for rank, chunk in enumerate(chunks):
            entry = fused.setdefault(chunk.chunk_id, RetrievedChunk(
                chunk=chunk, score=0.0,
                similarity=round(1 - distances[chunk.chunk_id], 4) if chunk.chunk_id in distances else None,
                matched_by=[],
            ))
            entry.score += 1 / (RRF_K + rank + 1)
            entry.matched_by.append(source)

    results = sorted(fused.values(), key=lambda r: -r.score)[:top_k]
    for r in results:
        r.score = round(r.score, 5)
    return results
