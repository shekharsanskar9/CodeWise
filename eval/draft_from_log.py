"""
Turn real questions logged by the server (CODEWISE_QUESTION_LOG) into a draft test set.

    CODEWISE_QUESTION_LOG=logs/questions.jsonl python backend.py   # use the app normally
    python eval/draft_from_log.py logs/questions.jsonl -o eval/answer_questions.draft.json

The draft pre-fills expected_files from the sources each answer used and keeps the answer
for reference. Every item is marked needs_review: check expected_files, add must_include
terms and a reference_answer, then merge the good ones into answer_questions.json.
"""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path(__file__).with_name('answer_questions.draft.json'))
    args = parser.parse_args()

    seen, items = set(), []
    for line in args.log.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = record['question'].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        files = list(dict.fromkeys(s['filename'] for s in record.get('sources', [])))
        items.append({
            'id': f"real-{len(items) + 1}",
            'origin': 'real',
            'needs_review': True,
            'question': record['question'],
            'expected_files': files[:2],
            'must_include': [],
            'reference_answer': '',
            'logged_answer': record.get('answer', ''),
            'answer_complete': record.get('complete', True),  # False if the user pressed Stop
            'logged_at': record.get('timestamp'),
        })

    args.output.write_text(json.dumps({'about': 'Draft from real questions; review before use.',
                                       'questions': items}, indent=2))
    print(f"Wrote {len(items)} questions to {args.output}")


if __name__ == '__main__':
    main()
