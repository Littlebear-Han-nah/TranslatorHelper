import base64
import httpx
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from PIL import Image, ImageDraw, ImageFont
import fitz
from .qwen_client import QwenClient
from ..config import DEFAULT_BASE_URL

class ImageTranslator:
    """
    图片/文档截图双语对照翻译引擎
    支持 JPG、PNG、WEBP 等图片格式，利用通义千问多模态/OCR 能力：
    1. 提取并翻译图片中的英文图表/课件幻灯片/论文截屏；
    2. 生成左右拼接大图（左原图、右中文翻译）；
    3. 生成左右并排双语对照 PDF 与高清预览图。
    """

    def __init__(self, qwen_client: QwenClient):
        """
        初始化图片翻译器
        :param qwen_client: 通义千问客户端
        """
        self.client = qwen_client

    async def _ocr_and_translate(self, image_path: str, model: str = "qwen3.5-ocr") -> str:
        """
        调用通义千问视觉大模型识别并翻译图片文本
        """
        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        # 判断 mime 类型
        ext = Path(image_path).suffix.lower().lstrip(".")
        mime = f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else ext}"
        data_url = f"data:{mime};base64,{b64_data}"

        url = f"{self.client.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.client.api_key}",
            "Content-Type": "application/json",
        }

        # 优先使用用户提供的 qwen3.5-ocr 或 qwen-vl 模型
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请识别并翻译此课件/论文图片中的所有文字内容，并将其翻译为专业准确的中文。请保持原有的段落层级与项目列表，直接输出中文翻译内容。"
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url}
                        }
                    ]
                }
            ]
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "")
            return content.strip()

    async def translate_image(
        self,
        input_image_path: str,
        output_dir: str,
        task_id: str,
        model: str = "qwen3.5-ocr",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        执行图片翻译并输出左右拼接大图与 PDF
        """
        out_path = Path(output_dir)
        preview_dir = out_path / "previews" / task_id
        preview_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "ocr",
                "current_page": 1,
                "total_pages": 1,
                "percent": 30,
                "message": f"正在使用 {model} 进行多模态视觉识别与翻译..."
            })

        # 1. 调用 OCR 与翻译
        try:
            trans_text = await self._ocr_and_translate(input_image_path, model=model)
        except Exception:
            # 若专用 OCR 模型异常，自动降级尝试常用多模态模型
            trans_text = await self._ocr_and_translate(input_image_path, model="qwen-vl-max")

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "stitching",
                "current_page": 1,
                "total_pages": 1,
                "percent": 75,
                "message": "正在生成左右拼接大图与双语对照 PDF..."
            })

        # 2. 生成右侧中文渲染图片
        orig_img = Image.open(input_image_path).convert("RGB")
        w, h = orig_img.size

        # 创建同尺寸右侧中文卡片画板
        trans_img = Image.new("RGB", (w, h), color=(255, 255, 255))
        draw = ImageDraw.Draw(trans_img)

        # 尝试加载中文字体，若缺失则使用默认
        font_candidates = [
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
        ]
        font_obj = None
        for fc in font_candidates:
            if Path(fc).exists():
                try:
                    font_obj = ImageFont.truetype(fc, size=max(16, int(h * 0.03)))
                    break
                except Exception:
                    continue
        if not font_obj:
            font_obj = ImageFont.load_default()

        # 绘制浅灰顶部标题条
        draw.rectangle([(0, 0), (w, int(h * 0.08))], fill=(241, 245, 249))
        draw.text((20, int(h * 0.02)), "中文翻译对照 (AI Translation)", fill=(37, 99, 235), font=font_obj)

        # 绘制正文折行
        margin = int(w * 0.05)
        cur_y = int(h * 0.12)
        line_height = int(h * 0.045)
        max_line_chars = max(15, int(w / 22))

        lines = [l.strip() for l in trans_text.split("\n") if l.strip()]
        for line in lines:
            if cur_y > h - margin:
                break
            # 简单自适应分词折行
            for i in range(0, len(line), max_line_chars):
                sub = line[i:i+max_line_chars]
                draw.text((margin, cur_y), sub, fill=(15, 23, 42), font=font_obj)
                cur_y += line_height
            cur_y += int(line_height * 0.3)

        # 3. 核心拼接：生成左右拼接大图 (宽为 2*W, 高为 H)
        bilingual_img = Image.new("RGB", (w * 2, h), color=(255, 255, 255))
        bilingual_img.paste(orig_img, (0, 0))
        bilingual_img.paste(trans_img, (w, 0))
        
        # 中间分割线
        draw_b = ImageDraw.Draw(bilingual_img)
        draw_b.line([(w, 0), (w, h)], fill=(203, 213, 225), width=3)

        side_by_side_img_path = str(out_path / f"{task_id}_bilingual.png")
        bilingual_img.save(side_by_side_img_path)

        # 4. 同时将拼接大图转存为 PDF 方便用户一键下载与打印
        side_by_side_pdf_path = str(out_path / f"{task_id}_bilingual_side_by_side.pdf")
        pdf_doc = fitz.open()
        # 尺寸转为 72 DPI 点位
        pdf_w = (w * 2) * 72 / 150
        pdf_h = h * 72 / 150
        page = pdf_doc.new_page(width=pdf_w, height=pdf_h)
        page.insert_image(page.rect, filename=side_by_side_img_path)
        pdf_doc.save(side_by_side_pdf_path)
        pdf_doc.close()

        # 5. 存储用于前端预览的图片
        preview_orig_path = str(preview_dir / "page_1_orig.png")
        orig_img.save(preview_orig_path)
        preview_trans_path = str(preview_dir / "page_1_trans.png")
        trans_img.save(preview_trans_path)

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "completed",
                "current_page": 1,
                "total_pages": 1,
                "percent": 100,
                "message": "图片识别与左右并排对照已生成！"
            })

        return {
            "task_id": task_id,
            "total_pages": 1,
            "side_by_side_pdf": f"/outputs/{task_id}_bilingual_side_by_side.pdf",
            "side_by_side_img": f"/outputs/{task_id}_bilingual.png",
            "pages": [{
                "page": 1,
                "orig_text": "",
                "trans_text": trans_text,
                "orig_img": f"/outputs/previews/{task_id}/page_1_orig.png",
                "trans_img": f"/outputs/previews/{task_id}/page_1_trans.png",
            }],
        }
