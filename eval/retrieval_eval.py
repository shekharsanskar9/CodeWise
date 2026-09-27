"""
Retrieval evaluation: index a set of files, run labelled questions, report hit@k and MRR
for vector-only, keyword-only and hybrid retrieval.

    python eval/retrieval_eval.py                       # evaluates on CodeWise's own code
    python eval/retrieval_eval.py --root ../other --questions my_questions.json

A question counts as a hit if any of its "expected" files appears in the top k results.
Use it to check whether a chunking/embedding/retrieval change actually helps.
"""

import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402
import ollama  # noqa: E402

from codewise.chunking import chunk_code  # noqa: E402
from codewise.config import Config  # noqa: E402
from codewise.embeddings import make_embedder  # noqa: E402
from codewise.files import FileRejected, check_path, decode_content  # noqa: E402
from codewise.index import ProjectIndex  # noqa: E402
from codewise.retrieval import hybrid_retrieve  # noqa: E402


def index_directory(index, project_id, root, config, exclude=()):
    count = 0
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.split('/')[0] in exclude:
            continue
        try:
            check_path(rel)
            content = decode_content(path.read_bytes(), config.max_file_bytes)
        except FileRejected:
            continue
        chunks = chunk_code(content, rel, config.chunk_max_chars, config.chunk_overlap_lines)
        if chunks:
            index.replace_file(project_id, rel, chunks)
            count += 1
    return count


def rank_of_first_hit(paths, expected):
    for rank, path in enumerate(paths, 1):
        if path in expected:
            return rank
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--questions', type=Path, default=Path(__file__).with_name('questions.json'))
    parser.add_argument('--exclude', nargs='*', default=['eval', 'tests', 'frontend'],
                        help="top-level directories to skip (the questions file itself must not be indexed)")
    parser.add_argument('-k', type=int, default=5)
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    config = Config()
    client = ollama.Client(host=config.ollama_host)
    embedder = make_embedder(config, client)
    questions = json.loads(args.questions.read_text())

    with tempfile.TemporaryDirectory() as tmp:
        index = ProjectIndex(chromadb.PersistentClient(path=tmp), embedder)
        project_id = str(uuid.uuid4())
        n_files = index_directory(index, project_id, args.root, config, set(args.exclude))
        print(f"Indexed {n_files} files with {embedder.name}; {len(questions)} questions, k={args.k}\n")

        keyword_index = index.keyword_index(project_id)
        modes = {
            'vector': lambda q: [c.path for c, _ in index.vector_search(project_id, q, args.k)],
            'keyword': lambda q: [c.path for c, _ in keyword_index.search(q, args.k)],
            'hybrid': lambda q: [r.chunk.path for r in hybrid_retrieve(
                index, project_id, q, top_k=args.k, candidate_k=config.candidate_k,
                max_distance=config.max_distance)],
        }

        print(f"{'mode':<8} {'hit@' + str(args.k):>7} {'MRR':>6}")
        for mode, search in modes.items():
            hits, rr = 0, 0.0
            for item in questions:
                rank = rank_of_first_hit(search(item['question']), set(item['expected']))
                if rank:
                    hits += 1
                    rr += 1 / rank
                elif args.verbose:
                    print(f"  [{mode}] miss: {item['question']}")
            print(f"{mode:<8} {hits / len(questions):>7.2%} {rr / len(questions):>6.3f}")


if __name__ == '__main__':
    main()
