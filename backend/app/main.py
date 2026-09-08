import os
import uuid
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import UPLOAD_DIR, OUTPUT_DIR, DEFAULT_API_KEY, DEFAULT_BASE_URL, SUPPORTED_MODELS
from .services.qwen_client import QwenClient
from .services.pdf_translator import PDFTranslator
from .services.docx_translator import DocxTranslator
from .services.md_translator import MarkdownTranslator
from .services.image_translator import ImageTranslator

# 配置日志格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("translator_app")

app = FastAPI(title="课件/论文智能对照翻译系统", version="1.0.0")

# 启用 CORS 跨域支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态资源服务（提供预览缩略图和下载文件直链访问）
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# 全局任务状态存储与事件队列
tasks_db: Dict[str, Dict[str, Any]] = {}
task_event_queues: Dict[str, list] = {}

@app.get("/api/config")
async def get_system_config():
    """
    获取系统支持的模型列表与默认配置
    """
    return {
        "models": SUPPORTED_MODELS,
        "default_model": "qwen3.8-flash",
        "has_default_key": bool(DEFAULT_API_KEY),
        "default_base_url": DEFAULT_BASE_URL,
    }

@app.post("/api/test-key")
async def test_api_key(
    api_key: Optional[str] = Form(None),
    model: str = Form("qwen3.8-flash")
):
    """
    测试 API Key 连通性
    """
    client = QwenClient(api_key=api_key or DEFAULT_API_KEY)
    result = await client.test_connection(model=model)
    return result

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    上传待翻译的文件（支持 PDF, DOCX, MD, PNG, JPG, JPEG, WEBP）
    """
    ext = Path(file.filename).suffix.lower()
    allowed_exts = {".pdf", ".docx", ".md", ".png", ".jpg", ".jpeg", ".webp"}
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}，仅支持 PDF, Word, Markdown, 图片。")

    file_id = str(uuid.uuid4())
    saved_filename = f"{file_id}_{file.filename}"
    saved_path = UPLOAD_DIR / saved_filename

    with open(saved_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {
        "file_id": file_id,
        "filename": file.filename,
        "saved_path": str(saved_path),
        "extension": ext,
        "size": len(content),
    }

async def run_translation_pipeline(
    task_id: str,
    file_path: str,
    ext: str,
    model: str,
    mode: str,
    api_key: Optional[str]
):
    """
    后台执行各格式的翻译与左右对照拼接流水线
    """
    client = QwenClient(api_key=api_key or DEFAULT_API_KEY)

    async def update_progress(event_data: Dict[str, Any]):
        """
        更新任务进度并推送到事件队列
        """
        tasks_db[task_id].update(event_data)
        if task_id in task_event_queues:
            for q in task_event_queues[task_id]:
                await q.put(event_data)

    try:
        if ext == ".pdf":
            engine = PDFTranslator(client)
            result = await engine.translate_pdf(
                input_pdf_path=file_path,
                output_dir=str(OUTPUT_DIR),
                task_id=task_id,
                model=model,
                mode=mode,
                progress_callback=update_progress
            )
        elif ext == ".docx":
            engine = DocxTranslator(client)
            result = await engine.translate_docx(
                input_docx_path=file_path,
                output_dir=str(OUTPUT_DIR),
                task_id=task_id,
                model=model,
                mode=mode,
                progress_callback=update_progress
            )
        elif ext == ".md":
            engine = MarkdownTranslator(client)
            result = await engine.translate_markdown(
                input_md_path=file_path,
                output_dir=str(OUTPUT_DIR),
                task_id=task_id,
                model=model,
                mode=mode,
                progress_callback=update_progress
            )
        elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
            engine = ImageTranslator(client)
            # 图片默认使用视觉/OCR 模型
            img_model = "qwen3.5-ocr" if "ocr" in model.lower() else model
            result = await engine.translate_image(
                input_image_path=file_path,
                output_dir=str(OUTPUT_DIR),
                task_id=task_id,
                model=img_model,
                progress_callback=update_progress
            )
        else:
            raise ValueError(f"未知的格式: {ext}")

        tasks_db[task_id].update({
            "stage": "completed",
            "percent": 100,
            "message": "翻译已完成！",
            "result": result
        })
        # 广播完成事件
        if task_id in task_event_queues:
            for q in task_event_queues[task_id]:
                await q.put(tasks_db[task_id])

    except Exception as e:
        logger.error(f"任务 {task_id} 发生异常: {e}", exc_info=True)
        err_data = {
            "stage": "failed",
            "percent": 0,
            "message": f"处理失败: {str(e)}",
            "error": str(e)
        }
        tasks_db[task_id].update(err_data)
        if task_id in task_event_queues:
            for q in task_event_queues[task_id]:
                await q.put(err_data)

@app.post("/api/translate")
async def start_translation(
    background_tasks: BackgroundTasks,
    file_id: str = Form(...),
    saved_path: str = Form(...),
    extension: str = Form(...),
    model: str = Form("qwen3.8-flash"),
    mode: str = Form("courseware"),
    api_key: Optional[str] = Form(None)
):
    """
    创建并启动文档双语对照翻译任务
    """
    if not Path(saved_path).exists():
        raise HTTPException(status_code=404, detail="上传文件未找到")

    task_id = str(uuid.uuid4())
    tasks_db[task_id] = {
        "task_id": task_id,
        "stage": "starting",
        "percent": 0,
        "message": "任务初始化中...",
        "current_page": 0,
        "total_pages": 1,
        "result": None,
    }
    task_event_queues[task_id] = []

    background_tasks.add_task(
        run_translation_pipeline,
        task_id=task_id,
        file_path=saved_path,
        ext=extension.lower(),
        model=model,
        mode=mode,
        api_key=api_key
    )

    return {"task_id": task_id, "status": "started"}

@app.get("/api/tasks/{task_id}/status")
async def get_task_status(task_id: str):
    """
    轮询获取任务最新进度与结果
    """
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="任务不存在")
    return tasks_db[task_id]

@app.get("/api/tasks/{task_id}/events")
async def stream_task_events(task_id: str):
    """
    SSE 实时事件流，推送逐页翻译与拼接进度
    """
    if task_id not in tasks_db:
        raise HTTPException(status_code=404, detail="任务不存在")

    q = asyncio.Queue()
    task_event_queues.setdefault(task_id, []).append(q)

    # 首次进入先推送当前最新状态
    await q.put(tasks_db[task_id])

    async def event_generator():
        try:
            while True:
                data = await q.get()
                import json
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("stage") in ["completed", "failed"]:
                    break
        finally:
            if task_id in task_event_queues and q in task_event_queues[task_id]:
                task_event_queues[task_id].remove(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """
    文件下载接口（包含左右并排对照 PDF、纯中文版或双语源文件）
    """
    target = OUTPUT_DIR / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        path=str(target),
        filename=filename,
        media_type="application/octet-stream"
    )

# 挂载前端打包文件（单服务一体化启动）
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

