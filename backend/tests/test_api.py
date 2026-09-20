import hashlib
import io
import secrets
from fastapi.testclient import TestClient
import pymupdf as fitz
import pytest
from backend.app import main, store

@pytest.fixture
def api(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DB_PATH',tmp_path/'test.sqlite3')
    monkeypatch.setattr(main,'UPLOAD_DIR',tmp_path)
    monkeypatch.setattr(main,'APP_ACCESS_TOKEN','')
    with TestClient(main.app) as client:
        client.get('/api/config')
        yield client

def test_upload_hides_paths_and_checks_content(api):
    response=api.post('/api/files',files={'file':('../../secret.pdf',b'not a pdf','application/pdf')})
    assert response.status_code==400
    doc=fitz.open();doc.new_page();content=doc.tobytes();doc.close()
    response=api.post('/api/files',files={'file':('../../paper.pdf',content,'application/pdf')})
    assert response.status_code==201
    assert response.json()['filename']=='paper.pdf'
    assert 'saved_path' not in response.json()

def test_sessions_cannot_access_other_tasks(api):
    session=api.cookies.get('translator_session');owner=hashlib.sha256(session.encode()).hexdigest()
    task={'task_id':'a'*32,'stage':'completed','filename':'private.pdf','result':None}
    store.put_task(task,owner)
    assert api.get('/api/tasks/'+'a'*32).status_code==200
    api.cookies.clear();api.get('/api/config')
    assert api.get('/api/tasks/'+'a'*32).status_code==404
    assert api.get('/api/tasks').json()==[]

def test_access_token_and_config_never_reveal_key(api,monkeypatch):
    monkeypatch.setattr(main,'APP_ACCESS_TOKEN','test-access-only')
    monkeypatch.setattr(main,'DEFAULT_API_KEY','test-key-only')
    response=api.get('/api/config')
    assert 'test-key-only' not in response.text
    assert not response.json()['authorized']
    assert api.get('/api/tasks').status_code==401
    assert api.post('/api/session',json={'token':'wrong'}).status_code==401
    assert api.post('/api/session',json={'token':'test-access-only'}).status_code==200
    assert api.get('/api/tasks').status_code==200


def test_model_catalog_matches_available_model_ids(api):
    ids = [model['id'] for model in api.get('/api/config').json()['models']]
    assert ids == [
        'qwen3.8-27b', 'qwen3.7-flash-2026-07-15', 'kimi-k3',
        'deepseek-v4-flash-0731', 'qwen3.8-max-0902', 'glm-5.3',
        'deepseek-v4-pro-0813', 'qwen3.8-2.4t-a95b', 'qwen3.8-max',
        'qwen3.7-flash',
    ]

def test_cancel_is_terminal_and_restart_preserves_completed(api):
    user=hashlib.sha256(api.cookies.get('translator_session').encode()).hexdigest()
    store.put_task({'task_id':'b'*32,'stage':'translating','filename':'p.pdf'},user)
    assert api.post('/api/tasks/'+'b'*32+'/cancel').json()['stage']=='cancelled'
    store.update('b'*32,stage='completed',message='late worker update')
    assert store.get_task('b'*32)['stage']=='cancelled'
    store.initialize()
    assert store.get_task('b'*32)['stage']=='cancelled'

def test_client_cannot_supply_arbitrary_filesystem_path(api):
    response=api.post('/api/tasks',json={'file_id':'../../etc/passwd','model':'test','saved_path':'/etc/passwd'})
    assert response.status_code==422

def test_pipeline_reports_page_and_safe_stack_without_exception_payload(api, monkeypatch, tmp_path, caplog):
    task_id = 'c'*32
    store.put_task({'task_id': task_id, 'stage': 'queued', 'filename': 'slides.pdf'}, 'test-owner')
    monkeypatch.setattr(main, 'OUTPUT_DIR', tmp_path)
    monkeypatch.setattr(main, 'CompatibleAdapter', lambda: object())
    async def fail(source, output, adapter, model, mode, glossary, progress, cancel):
        progress('rebuilding', 29, '重建第 2 / 10 页的原始版面')
        raise RuntimeError('private-provider-payload-do-not-log')
    monkeypatch.setattr(main, 'translate_pdf', fail)
    body = main.TranslationRequest(file_id='d'*32, model='test')
    main.run_pipeline(task_id, tmp_path/'slides.pdf', body)
    task = store.get_task(task_id)
    assert task['stage'] == 'failed'
    assert '第 2 / 10 页' in task['message'] and task_id[:8] in task['message']
    assert 'RuntimeError' in caplog.text and 'test_api.py:' in caplog.text
    assert 'private-provider-payload' not in caplog.text + task['message']
