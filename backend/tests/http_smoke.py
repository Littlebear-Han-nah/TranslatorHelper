"""Opt-in smoke test against a locally running app (one real translation request)."""
import httpx
import time
import json
from pathlib import Path
with httpx.Client(base_url='http://127.0.0.1:8010',trust_env=False,timeout=30) as client:
    config=client.get('/api/config').json()
    print('Dependencies:', {key:config[key] for key in ['has_default_key','ocr_available','office_preview_available']},flush=True)
    with Path('artifacts/fixtures/layout.pdf').open('rb') as stream:
        upload=client.post('/api/files',files={'file':('layout.pdf',stream,'application/pdf')})
    upload.raise_for_status()
    response=client.post('/api/tasks',json={'file_id':upload.json()['file_id'],'model':'qwen3.7-flash','mode':'academic','glossary':''})
    response.raise_for_status();task=response.json()
    print('HTTP task created',flush=True)
    for _ in range(180):
        task=client.get('/api/tasks/'+task['task_id']).json()
        if task['stage'] in ('completed','failed','cancelled'):break
        time.sleep(1)
    print('HTTP task:',task['stage'],task['message'],flush=True)
    assert task['stage']=='completed',task['message']
    result=task['result']
    assert client.get(result['translated_pdf']).status_code==200
    assert client.get(result['pages'][0]['trans_img']).status_code==200
    with httpx.Client(base_url='http://127.0.0.1:8010',trust_env=False) as other:
        other.get('/api/config')
        assert other.get(result['translated_pdf']).status_code==404
    print('Download, preview and cross-session isolation: PASS',flush=True)
    Path('artifacts/http-smoke.json').write_text(json.dumps({'stage':task['stage'],'downloads':True,'isolation':True}))
