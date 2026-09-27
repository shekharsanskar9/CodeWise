import io
import json
import zipfile

from conftest import upload

from codewise import sources

STORE = '''class ProjectStore:
    def save(self, item):
        return write(item)
'''

SERVICE = '''from .store import ProjectStore


def ingest(item):
    store = ProjectStore()
    store.save(item)


def reindex(items):
    for item in items:
        ingest(item)
'''


def zip_bytes(files, root="demo-main/"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        for name, content in files.items():
            zf.writestr(root + name, content)
    return buffer.getvalue()


def create(client):
    return client.post('/api/projects/create').get_json()['project_id']


def project_with_code(client):
    pid = create(client)
    upload(client, pid, ("app/store.py", STORE), ("app/service.py", SERVICE), ("app/__init__.py", ""))
    return pid


def test_zip_upload_is_expanded_and_filtered(client):
    pid = create(client)
    data = zip_bytes({".gitignore": "tmp/\n", "src/a.py": "x = 1\n", "tmp/b.py": "y = 2\n",
                      "node_modules/x/index.js": "z\n"})
    res = upload(client, pid, ("demo.zip", data))
    body = res.get_json()
    assert res.status_code == 207
    assert body['summary'] == {'indexed': 1, 'skipped': 2, 'failed': 0}
    assert [f['filename'] for f in body['metadata']['files']] == ["src/a.py"]


def test_bad_zip_reports_failure(client):
    pid = create(client)
    res = upload(client, pid, ("broken.zip", b"nope"))
    assert res.status_code == 400
    assert "zip" in res.get_json()['error']


def test_folder_upload_applies_batch_gitignore(client):
    pid = create(client)
    res = upload(client, pid, ("proj/.gitignore", "build/\n"), ("proj/build/gen.py", "x = 1\n"),
                 ("proj/src/main.py", "print(1)\n"))
    body = res.get_json()
    assert body['summary'] == {'indexed': 1, 'skipped': 1, 'failed': 0}
    assert [f['filename'] for f in body['metadata']['files']] == ["proj/src/main.py"]


def test_github_import(client, monkeypatch):
    pid = create(client)
    archive = zip_bytes({"README.md": "# Demo\n", "lib/core.py": "def core():\n    return 1\n"})
    seen = {}

    def fake_download(owner, repo, ref, max_bytes, token=None):
        seen.update(owner=owner, repo=repo, ref=ref)
        return archive

    monkeypatch.setattr("codewise.service.download_github_zip", fake_download)
    res = client.post(f'/api/projects/{pid}/import/github',
                      json={'url': 'https://github.com/acme/demo/tree/dev'})
    body = res.get_json()
    assert res.status_code == 200, body
    assert seen == {'owner': 'acme', 'repo': 'demo', 'ref': 'dev'}
    assert body['repository'] == {'owner': 'acme', 'repo': 'demo', 'ref': 'dev'}
    assert {f['filename'] for f in body['metadata']['files']} == {"README.md", "lib/core.py"}


def test_github_import_rejects_non_github_urls(client):
    pid = create(client)
    res = client.post(f'/api/projects/{pid}/import/github', json={'url': 'http://169.254.169.254/'})
    assert res.status_code == 400


def test_github_import_surfaces_download_errors(client, monkeypatch):
    pid = create(client)

    def fail(*a, **kw):
        raise sources.SourceError("Repository acme/nope not found")

    monkeypatch.setattr("codewise.service.download_github_zip", fail)
    res = client.post(f'/api/projects/{pid}/import/github', json={'url': 'acme/nope'})
    assert res.status_code == 400
    assert "not found" in res.get_json()['error']


def test_graph_endpoint_symbol_and_file(client):
    pid = project_with_code(client)
    body = client.get(f'/api/projects/{pid}/graph?symbol=save').get_json()
    symbol = body['symbol']
    assert symbol['definitions'][0]['qualname'] == 'ProjectStore.save'
    assert [(c['path'], c['caller']) for c in symbol['callers']] == [("app/service.py", "ingest")]

    body = client.get(f'/api/projects/{pid}/graph?file=app/store.py').get_json()
    assert body['file']['imported_by'] == ["app/service.py"]
    assert [s['qualname'] for s in body['symbols']] == ["ProjectStore", "ProjectStore.save"]

    assert client.get(f'/api/projects/{pid}/graph').status_code == 400
    assert client.get(f'/api/projects/{pid}/graph?file=nope.py').status_code == 404


def test_reupload_replaces_graph_rows(client, service):
    pid = project_with_code(client)
    upload(client, pid, ("app/service.py", "def unrelated():\n    pass\n"))
    body = client.get(f'/api/projects/{pid}/graph?symbol=save').get_json()
    assert body['symbol']['callers'] == []


def test_usage_question_gets_relationships_and_call_site_chunks(client, service):
    pid = project_with_code(client)
    body = client.post(f'/api/projects/{pid}/ask', json={'question': 'Who calls ingest?'}).get_json()
    assert body['relations'] == ['ingest']
    prompt = service.llm.calls[-1][-1]['content']
    assert "## Code relationships" in prompt
    assert "app/service.py:11 in reindex" in prompt
    graph_sources = [s for s in body['sources'] if 'graph' in s['matched_by']]
    assert graph_sources and graph_sources[0]['filename'] == "app/service.py"


def test_plain_words_do_not_trigger_relationships_without_usage_intent(client):
    pid = project_with_code(client)
    body = client.post(f'/api/projects/{pid}/ask', json={'question': 'explain the ingest flow'}).get_json()
    assert body['relations'] == []
    body = client.post(f'/api/projects/{pid}/ask', json={'question': 'explain `ingest`'}).get_json()
    assert body['relations'] == ['ingest']


def test_file_question_lists_dependencies(client, service):
    pid = project_with_code(client)
    body = client.post(f'/api/projects/{pid}/ask', json={'question': 'what depends on store.py?'}).get_json()
    assert "app/store.py" in body['relations']
    prompt = service.llm.calls[-1][-1]['content']
    assert "Imported by: app/service.py" in prompt


def test_upload_rules(client):
    body = client.get('/api/upload-rules').get_json()
    assert '.py' in body['supported_extensions'] and 'node_modules' in body['ignored_dirs']


def test_question_log(client, service, tmp_path):
    log_path = tmp_path / "logs" / "questions.jsonl"
    service.config.question_log_path = str(log_path)
    pid = project_with_code(client)
    client.post(f'/api/projects/{pid}/ask', json={'question': 'what does save do?'})
    res = client.post(f'/api/projects/{pid}/ask/stream', json={'question': 'who calls save?'})
    res.get_data()  # drain the stream
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [r['question'] for r in records] == ['what does save do?', 'who calls save?']
    assert records[1]['answer'] == 'fake answer'
    assert records[0]['complete'] and records[1]['complete']
    assert records[0]['sources'] and 'seconds' in records[0]


def test_question_log_off_by_default(client, service, tmp_path):
    pid = project_with_code(client)
    client.post(f'/api/projects/{pid}/ask', json={'question': 'hi'})
    assert not list(tmp_path.glob('**/*.jsonl'))
