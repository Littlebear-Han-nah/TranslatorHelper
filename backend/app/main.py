import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import shutil
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Request, Response, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, UnidentifiedImageError
import pymupdf as fitz
from . import store
from .config import UPLOAD_DIR, OUTPUT_DIR, BASE_DIR, DEFAULT_API_KEY, DEFAULT_MODEL, SUPPORTED_MODELS, APP_ACCESS_TOKEN, MAX_UPLOAD_BYTES
from .services.model_adapter import CompatibleAdapter, ModelError
from .services.layout_engine import translate_pdf
from .services.office_engine import validate_office, translate_office, office_binary

logger = logging.getLogger('translator')
ACTIVE = set()
WORKER_LOCK = asyncio.Semaphore(1)
TERMINAL = ('completed', 'failed', 'cancelled')

@asynccontextmanager
async def lifespan(app):
    store.initialize()
    yield
    # Running tasks are marked interrupted on the next startup.

app = FastAPI(title='译页 TranslatorHelper', version='2.0.0', lifespan=lifespan)

def owner(request: Request):
    value = request.cookies.get('translator_session', '')
    if not re.fullmatch(r'[a-f0-9]{64}', value):
        raise HTTPException(401, '请刷新页面以建立文档会话')
    return hashlib.sha256(value.encode()).hexdigest()

def authorized(request):
    if not APP_ACCESS_TOKEN: return True
    expected = hmac.new(APP_ACCESS_TOKEN.encode(), request.cookies.get('translator_session', '').encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(request.cookies.get('translator_access', ''), expected)

def authenticated(request: Request):
    if not authorized(request): raise HTTPException(401, '请在模型设置中输入平台访问口令')
    return owner(request)

@app.get('/api/health')
def health(): return {'status': 'ok', 'version': '2.0.0'}

@app.get('/api/config')
def config(request: Request, response: Response):
    if not re.fullmatch(r'[a-f0-9]{64}', request.cookies.get('translator_session', '')):
        response.set_cookie('translator_session', secrets.token_hex(32), httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=60*60*24*30)
    response.headers['Cache-Control'] = 'no-store'
    return {'models': SUPPORTED_MODELS, 'default_model': DEFAULT_MODEL, 'has_default_key': bool(DEFAULT_API_KEY), 'authorized': authorized(request), 'ocr_available': bool(shutil.which('tesseract')), 'office_preview_available': bool(office_binary()), 'max_upload_mb': 50}

class Login(BaseModel): token: str = Field(max_length=256)

@app.post('/api/session')
def login(body: Login, request: Request, response: Response):
    owner(request)
    if APP_ACCESS_TOKEN and not hmac.compare_digest(body.token.encode(), APP_ACCESS_TOKEN.encode()):
        raise HTTPException(401, '访问口令不正确')
    signed = hmac.new(APP_ACCESS_TOKEN.encode(), request.cookies['translator_session'].encode(), hashlib.sha256).hexdigest()
    response.set_cookie('translator_access', signed, httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=86400)
    return {'ok': True}

class ModelRequest(BaseModel): model: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_.:/-]+$')

@app.post('/api/models/test')
async def test_model(body: ModelRequest, user=Depends(authenticated)):
    try:
        await CompatibleAdapter().chat(body.model, [{'role': 'user', 'content': 'Reply only OK.'}], max_tokens=256)
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from None
    return {'message': f'{body.model} 连接成功'}

@app.post('/api/files', status_code=201)
async def upload(file: UploadFile = File(...), user=Depends(authenticated)):
    name = Path((file.filename or 'document').replace('\\', '/')).name
    extension = Path(name).suffix.lower()
    if extension not in {'.pdf', '.png', '.jpg', '.jpeg', '.docx', '.pptx', '.xlsx'}:
        raise HTTPException(400, '不支持此文件格式')
    file_id, size = secrets.token_hex(16), 0
    target = UPLOAD_DIR / f'{file_id}{extension}'
    try:
        with target.open('wb') as stream:
            while chunk := await file.read(1024*1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES: raise HTTPException(413, '文件不能超过 50 MB')
                stream.write(chunk)
        if not size: raise ValueError('文件为空')
        if extension == '.pdf':
            with fitz.open(target) as doc:
                if doc.needs_pass: raise ValueError('请先解锁加密 PDF')
                if not doc.is_pdf: raise ValueError('文件内容不是 PDF')
        elif extension in {'.docx', '.pptx', '.xlsx'}:
            validate_office(target)
        else:
            with Image.open(target) as img:
                if img.width * img.height > 40_000_000: raise ValueError('图片超过 4000 万像素，请缩小后上传')
                img.verify()
        store.save_file(file_id, user, name, extension)
    except HTTPException:
        target.unlink(missing_ok=True); raise
    except (ValueError, RuntimeError, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        target.unlink(missing_ok=True)
        # Do not return local paths or parser internals.
        message = str(exc) if type(exc) is ValueError else '文档损坏或内容与扩展名不符'
        raise HTTPException(400, message) from None
    finally:
        await file.close()
    return {'file_id': file_id, 'filename': name, 'size': size, 'extension': extension}

class TranslationRequest(ModelRequest):
    file_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    mode: str = Field(default='academic', pattern=r'^(academic|courseware|general)$')
    glossary: str = Field(default='', max_length=8000)

class Cancelled(Exception): pass

def run_pipeline(task_id, path, body):
    def cancel():
        if store.get_task(task_id)['stage'] == 'cancelled': raise Cancelled()
    last_percent = 0
    last_message = '初始化文档处理'
    def progress(stage, percent, message):
        nonlocal last_percent, last_message
        cancel()
        last_percent = max(last_percent, min(percent, 99))
        last_message = message
        store.update(task_id, stage=stage, percent=last_percent, message=message)
    async def execute():
        output = OUTPUT_DIR / task_id
        output.mkdir(exist_ok=True)
        adapter = CompatibleAdapter()
        try:
            cancel()
            progress('parsing', 2, '解析文档并识别文件结构')
            source = path
            if path.suffix in {'.png', '.jpg', '.jpeg'}:
                with Image.open(path) as im:
                    image = ImageOps.exif_transpose(im).convert('RGB')
                    import io
                    data = io.BytesIO(); image.save(data, format='PNG')
                    with fitz.open() as doc:
                        page = doc.new_page(width=image.width*.75, height=image.height*.75)
                        page.insert_image(page.rect, stream=data.getvalue())
                        source = output / 'source.pdf'
                        doc.save(source)
            engine = translate_office if path.suffix in {'.docx', '.pptx', '.xlsx'} else translate_pdf
            result = await engine(source, output, adapter, body.model, body.mode, body.glossary, progress, cancel)
            cancel()
            result['model'] = body.model
            (output/'quality-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            result['report'] = 'quality-report.json'
            prefix = f'/api/tasks/{task_id}/artifacts/'
            for key in ('translated_pdf', 'bilingual_pdf', 'native_file', 'report'):
                if result.get(key): result[key] = prefix + result[key]
            for page in result['pages']:
                page['orig_img'], page['trans_img'] = prefix + page['orig_img'], prefix + page['trans_img']
            store.update(task_id, stage='completed', percent=100, message='翻译完成，请查看质量提示', result=result)
        except Cancelled:
            pass
        except (ModelError, ValueError) as exc:
            store.update(task_id, stage='failed', message=str(exc))
        except Exception as exc:
            # Frame locations diagnose engine errors without logging document text,
            # exception payloads, request bodies, or local variables containing keys.
            frames = ' -> '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
                                 for frame in traceback.extract_tb(exc.__traceback__))
            logger.error('Translation %s failed: %s; stage=%s; frames=%s',
                         task_id, type(exc).__name__, last_message, frames)
            store.update(task_id, stage='failed', message=f'文档处理失败：{last_message}（{type(exc).__name__}；任务 {task_id[:8]}）。请提供此错误信息以便排查。')
    asyncio.run(execute())

async def run_job(task_id, path, body):
    async with WORKER_LOCK:
        await asyncio.to_thread(run_pipeline, task_id, path, body)

@app.post('/api/tasks', status_code=202)
async def start(body: TranslationRequest, user=Depends(authenticated)):
    file = store.get_file(body.file_id, user)
    if not file: raise HTTPException(404, '上传文件不存在')
    if not DEFAULT_API_KEY: raise HTTPException(503, '请先配置服务端 DASHSCOPE_API_KEY')
    if sum(t['stage'] not in TERMINAL for t in store.list_tasks(user)) >= 3 or len(ACTIVE) >= 12:
        raise HTTPException(429, '任务队列已满，请等待当前任务完成')
    task_id = secrets.token_hex(16)
    task = {'task_id': task_id, 'filename': file['name'], 'created_at': time.time(), 'stage': 'queued', 'percent': 0, 'message': '已加入翻译队列', 'model': body.model, 'result': None}
    store.put_task(task, user)
    job = asyncio.create_task(run_job(task_id, UPLOAD_DIR / (body.file_id+file['extension']), body))
    ACTIVE.add(job); job.add_done_callback(ACTIVE.discard)
    return task

@app.get('/api/tasks')
def list_tasks(user=Depends(authenticated)): return store.list_tasks(user)

@app.get('/api/tasks/{task_id}')
def status(task_id: str, user=Depends(authenticated)):
    task = store.get_task(task_id, user)
    if not task: raise HTTPException(404, '任务不存在')
    return task

@app.post('/api/tasks/{task_id}/cancel')
def cancel_task(task_id: str, user=Depends(authenticated)):
    task = status(task_id, user)
    if task['stage'] not in TERMINAL: store.update(task_id, stage='cancelled', message='任务已取消')
    return store.get_task(task_id, user)

@app.get('/api/tasks/{task_id}/artifacts/{filename}')
def artifact(task_id: str, filename: str, user=Depends(authenticated)):
    task = status(task_id, user)
    if task['stage'] != 'completed': raise HTTPException(409, '文件尚未准备好')
    result = task['result']
    urls = [result.get(k) for k in ('translated_pdf', 'bilingual_pdf', 'native_file', 'report')]
    for page in result['pages']: urls.extend([page['orig_img'], page['trans_img']])
    if f'/api/tasks/{task_id}/artifacts/{filename}' not in urls:
        raise HTTPException(404, '文件不存在')
    path = OUTPUT_DIR / task_id / filename
    if not path.is_file(): raise HTTPException(404, '文件已过期或被清理')
    response = FileResponse(path, filename=filename if not filename.endswith('.png') else None)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

FRONTEND_DIST = BASE_DIR / 'frontend' / 'dist'
if FRONTEND_DIST.exists(): app.mount('/', StaticFiles(directory=FRONTEND_DIST, html=True), name='frontend')
