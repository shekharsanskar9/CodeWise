"""
Answer-quality evaluation: index a codebase, ask each labelled question through the real
pipeline (retrieval + code graph + LLM), and score the answers.

    python eval/answer_eval.py                      # CodeWise's own code, eval/answer_questions.json
    python eval/answer_eval.py --limit 3 -v         # quick check
    python eval/answer_eval.py --judge              # also ask the LLM to grade against reference answers
    python eval/answer_eval.py --root ../other --questions my_questions.json

Metrics per question
  source_hit   an expected file is among the returned sources (retrieval did its job)
  term_recall  share of `must_include` terms found in the answer (case-insensitive)
  forbidden    any `must_not_include` phrase appears (hallucination guard)
  citations    share of file paths cited in the answer that exist in the project
  refusal      for `expect_refusal` questions: did the answer say the code doesn't contain it
  judge        optional 1-5 grade vs `reference_answer`. The judge is the same local model,
               so treat it as a rough signal, not ground truth.

Results are written to eval/results/ as JSON so runs can be compared over time.
"""

import argparse
import json
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402
import ollama  # noqa: E402

from codewise.config import Config  # noqa: E402
from codewise.embeddings import make_embedder  # noqa: E402
from codewise.files import FileRejected, check_path  # noqa: E402
from codewise.index import ProjectIndex  # noqa: E402
from codewise.llm import OllamaLLM  # noqa: E402
from codewise.service import CodeWise  # noqa: E402
from codewise.sources import filter_uploads  # noqa: E402
from codewise.store import ProjectStore  # noqa: E402

_PATH_RE = re.compile(r'(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:py|jsx?|tsx?|java|go|rs|rb|php|cs|cpp|c|h|kt|swift|md|json|ya?ml|toml|sql|css|html))\b')
_REFUSAL_RE = re.compile(r"\b(does not|doesn't|do not|don't|no|not)\b[^.]{0,80}\b(contain|include|implement|have|find|found|support|exist|appear|mention)", re.I)

JUDGE_PROMPT = """You grade answers about a codebase. Compare the ANSWER to the REFERENCE.
Score 1-5: 5 = correct and complete, 4 = correct with minor gaps, 3 = partly correct,
2 = mostly wrong or vague, 1 = wrong or hallucinated. Reply with only the number."""


def collect(root, exclude):
    entries = []
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.split('/')[0] in exclude:
            continue
        if path.name != '.gitignore':
            try:
                check_path(rel)
            except FileRejected:
                continue
        entries.append((rel, path.read_bytes()))
    files, _, _ = filter_uploads(entries)
    return files


def score(item, result, project_files):
    answer = result['answer']
    lower = answer.lower()
    expected = set(item.get('expected_files', []))
    sources = [s['filename'] for s in result['sources']]
    terms = item.get('must_include', [])
    found_terms = [t for t in terms if t.lower() in lower]
    forbidden = [t for t in item.get('must_not_include', []) if t.lower() in lower]
    cited = set(_PATH_RE.findall(answer))
    basenames = {Path(f).name for f in project_files}
    valid = [c for c in cited if c in project_files or any(f.endswith('/' + c) for f in project_files)
             or c in basenames]
    row = {
        'id': item.get('id') or item['question'][:40],
        'source_hit': (bool(expected & set(sources)) if expected else None),
        'term_recall': (len(found_terms) / len(terms)) if terms else None,
        'missing_terms': [t for t in terms if t not in found_terms],
        'forbidden': forbidden,
        'citations': (len(valid) / len(cited)) if cited else None,
        'invalid_citations': sorted(cited - set(valid)),
        'refusal': (bool(_REFUSAL_RE.search(answer)) if item.get('expect_refusal') else None),
    }
    return row


def judge(llm, item, answer):
    reference = item.get('reference_answer')
    if not reference:
        return None
    reply, _ = llm.chat([
        {'role': 'system', 'content': JUDGE_PROMPT},
        {'role': 'user', 'content': f"QUESTION: {item['question']}\n\nREFERENCE: {reference}\n\nANSWER: {answer}"},
    ], num_predict=5, temperature=0)
    m = re.search(r'[1-5]', reply)
    return int(m.group()) if m else None


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--questions', type=Path, default=Path(__file__).with_name('answer_questions.json'))
    parser.add_argument('--exclude', nargs='*', default=['eval', 'tests', 'frontend', 'logs'])
    parser.add_argument('--limit', type=int)
    parser.add_argument('--judge', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    data = json.loads(args.questions.read_text())
    questions = data['questions'] if isinstance(data, dict) else data
    questions = questions[:args.limit] if args.limit else questions

    with tempfile.TemporaryDirectory() as tmp:
        config = Config(chroma_path=f"{tmp}/chroma", db_path=f"{tmp}/db.sqlite", question_log_path="")
        client = ollama.Client(host=config.ollama_host, timeout=config.llm_timeout)
        embedder = make_embedder(config, client)
        llm = OllamaLLM(client, config.chat_model, config.num_ctx)
        service = CodeWise(config, ProjectStore(config.db_path),
                           ProjectIndex(chromadb.PersistentClient(path=config.chroma_path), embedder), llm)
        project_id = service.create_project()
        files = collect(args.root, set(args.exclude))
        indexed = [r for r in service._ingest_entries(project_id, files) if r['success']]
        project_files = {r['filename'] for r in indexed}
        print(f"Indexed {len(indexed)} files | chat={config.chat_model} embed={embedder.name} | "
              f"{len(questions)} questions\n")

        rows = []
        for item in questions:
            started = time.monotonic()
            result = service.ask(project_id, {'question': item['question']})
            row = score(item, result, project_files)
            row['seconds'] = round(time.monotonic() - started, 1)
            row['output_tokens'] = result['usage']['output_tokens']
            if args.judge:
                row['judge'] = judge(llm, item, result['answer'])
            row['answer'] = result['answer']
            row['sources'] = [f"{s['filename']}:{s['lines']}" for s in result['sources']]
            rows.append(row)

            flags = []
            if row['source_hit'] is False:
                flags.append('source-miss')
            if row['missing_terms']:
                flags.append('missing=' + ','.join(row['missing_terms']))
            if row['forbidden']:
                flags.append('FORBIDDEN=' + ','.join(row['forbidden']))
            if row['invalid_citations']:
                flags.append('bad-cite=' + ','.join(row['invalid_citations']))
            if row['refusal'] is False:
                flags.append('no-refusal')
            print(f"{row['id']:<28} {row['seconds']:>6.1f}s  {' '.join(flags) or 'ok'}"
                  + (f"  judge={row['judge']}" if args.judge else ''))
            if args.verbose:
                print('    ' + result['answer'][:600].replace('\n', '\n    ') + '\n')

    summary = {
        'source_hit_rate': mean([None if r['source_hit'] is None else float(r['source_hit']) for r in rows]),
        'term_recall': mean([r['term_recall'] for r in rows]),
        'forbidden_rate': mean([float(bool(r['forbidden'])) for r in rows]),
        'citation_validity': mean([r['citations'] for r in rows]),
        'refusal_rate': mean([None if r['refusal'] is None else float(r['refusal']) for r in rows]),
        'judge_mean': mean([r.get('judge') for r in rows]) if args.judge else None,
        'mean_seconds': mean([r['seconds'] for r in rows]),
        'mean_output_tokens': mean([r['output_tokens'] for r in rows]),
    }
    print("\nSummary")
    for key, value in summary.items():
        if value is not None:
            print(f"  {key:<20} {value:.2f}")

    out_dir = Path(__file__).with_name('results')
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"answer_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps({'config': {'chat_model': config.chat_model, 'embed_model': embedder.name,
                                          'num_ctx': config.num_ctx, 'top_k': config.top_k},
                               'summary': summary, 'rows': rows}, indent=2))
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == '__main__':
    main()
