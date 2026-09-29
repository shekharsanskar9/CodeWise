# Evaluation

Tests tell you the code *works*. Evaluation tells you whether answers are *good*, and whether a change made them better or worse. CodeWise has two evaluations: one for search (fast, no chat model needed) and one for full answers (slower, uses the real model).

---

## 1. Retrieval evaluation: does search find the right code?

```bash
python eval/retrieval_eval.py        # evaluates on CodeWise's own code
python eval/retrieval_eval.py -v     # also lists every miss
```

It indexes a folder, runs each question in `eval/questions.json`, and checks whether an expected file appears in the top *k* results. It reports three search modes side by side:

```
mode       hit@5    MRR
vector   100.00%  0.756
keyword   95.24%  0.754
hybrid   100.00%  0.806
```

- **hit@5:** share of questions where a correct file is somewhere in the top 5.
- **MRR** (mean reciprocal rank): rewards putting the correct file *first*. It's 1.0 if always first, 0.5 if always second.

The numbers above come from CodeWise's own backend with 21 questions, using the fallback MiniLM embeddings. The question set is small and was written by the developer, so treat it as a regression check (did a change make things worse?), not as a benchmark.

**Evaluate on your own code**

```bash
python eval/retrieval_eval.py --root ../MyProject --questions my_questions.json -k 5
```

`my_questions.json` is a list of questions with the file(s) that should be found:

```json
[
  { "question": "Where are PDFs turned into text?", "expected": ["backend/ingestion/pdf_extractor.py"] },
  { "question": "How are embeddings generated?", "expected": ["backend/vector_store/qdrant_client.py"] }
]
```

`--exclude` skips top-level folders (by default `eval`, `tests` and `frontend`). Never index the questions file itself: its wording matches the questions exactly and inflates the score.

---

## 2. Answer evaluation: are the answers correct?

```bash
python eval/answer_eval.py --limit 3 -v     # quick check, prints the answers
python eval/answer_eval.py                   # all questions (several minutes)
python eval/answer_eval.py --judge           # also grade against reference answers
```

It runs each question in `eval/answer_questions.json` through the real pipeline (search, code graph, prompt and the local model), and scores the answer:

| Metric | Question it answers |
|---|---|
| `source_hit_rate` | Did search return an expected file? |
| `term_recall` | Share of required terms (`must_include`) that appear in the answer |
| `forbidden_rate` | Did the answer contain a phrase it shouldn't (`must_not_include`)? Catches known wrong answers |
| `citation_validity` | Share of file paths mentioned in the answer that actually exist. Catches made-up paths |
| `refusal_rate` | For questions about things that aren't in the code: did the answer say so instead of inventing? |
| `judge_mean` | With `--judge`: the model grades the answer 1–5 against `reference_answer` |
| `mean_seconds` | Average time per answer |

Results are saved to `eval/results/answer_eval_<timestamp>.json`, so you can compare runs over time.

**About `--judge`:** the judge is the same local model that wrote the answers, so it tends to be lenient with itself. Use it as a rough signal, and read the answers yourself for anything important.

**Question format:**

```json
{
  "id": "who-calls-replace-file",
  "question": "Who calls replace_file?",
  "expected_files": ["codewise/service.py"],
  "must_include": ["_ingest", "service.py"],
  "must_not_include": [],
  "reference_answer": "CodeWise._ingest in codewise/service.py calls self.index.replace_file after chunking a file."
}
```

Add `"expect_refusal": true` for questions whose answer *isn't* in the code, such as "How does this project do OAuth login?". For those, a good answer says the code doesn't contain it.

---

## 3. Building a test set from real questions

The included questions were written while building the features, so they favour things known to work. Real questions are a better test.

**Step 1: log real use.** Start the backend with the question log on, and use CodeWise normally:

```bash
CODEWISE_QUESTION_LOG=logs/questions.jsonl python backend.py
```

Each question is saved with its sources and answer. Answers stopped early are marked `"complete": false`.

**Step 2: turn the log into a draft:**

```bash
python eval/draft_from_log.py logs/questions.jsonl -o eval/answer_questions.draft.json
```

Duplicates are removed, and `expected_files` is pre-filled from the sources each answer used.

**Step 3: review by hand.** For each draft question:
- fix `expected_files` if search found the wrong files;
- add `must_include` terms and a `reference_answer`;
- delete anything too vague.

Then move the good ones into `eval/answer_questions.json`.

`logs/`, `eval/results/` and the draft file are git-ignored, because they contain your questions and code snippets.

---

## A good habit

Before changing prompts, chunking, retrieval or the model:

```bash
python eval/retrieval_eval.py > before.txt
python eval/answer_eval.py
# ...make the change...
python eval/retrieval_eval.py > after.txt
python eval/answer_eval.py
```

Keep the change only if the numbers hold up. Note them in the pull request.
