import base64
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, Callable
import fitz
from PIL import Image
from .qwen_client import QwenClient


class ImageTranslator:
    """
    图片/截图高保真双语对照翻译引擎。
    设计原则：
    1. 调用视觉大模型识别图片中的所有文字（含图表内文字），输出完整中文翻译；
    2. 左侧：100% 原始高清图片，无任何涂抹遮挡；
    3. 右侧：清晰白底中文译文区，字号大、排版自然，完全可读；
    4. 使用 PyMuPDF 内置 china-s CJK 矢量字体，彻底避免云端乱码；
    5. 生成可下载的左右双栏双语 PDF 与预览图。
    """

    def __init__(self, qwen_client: QwenClient):
        """
        初始化图片翻译器
        :param qwen_client: 通义千问客户端实例
        """
        self.client = qwen_client

    async def _vision_translate_full(self, image_path: str, model: str = "qwen3.8-flash") -> str:
        """
        调用视觉多模态大模型，识别图片中所有文字并给出完整中文翻译。
        返回格式：纯中文翻译文本，保留原有段落结构。
        如果 JSON 格式解析可用，优先以结构化方式提取；否则直接使用模型输出的纯文本。
        """
        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        ext = Path(image_path).suffix.lower().lstrip(".")
        mime = f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else ext}"
        data_url = f"data:{mime};base64,{b64_data}"

        # 支持视觉输入的模型列表
        vl_models = {"qwen3.8-flash", "qwen-vl-max", "qwen3.8-max",
                     "qwen3.7-flash", "qwen3.5-ocr", "qwen3.8-max-0902"}
        chosen_model = model if model in vl_models else "qwen3.8-flash"

        prompt = (
            "你是顶级的学术课件与论文双语翻译专家。"
            "请仔细识别此图片中的所有文字内容（包括标题、正文、图例、注释、图表中的标签等），"
            "并将全部英文翻译为专业、流畅的中文。\n\n"
            "输出要求：\n"
            "1. 按照原文的结构顺序（从标题到正文到注释）翻译所有内容；\n"
            "2. 图表中每个方框、节点、箭头旁的文字也必须翻译；\n"
            "3. 数学公式、代码、变量名原样保留，仅翻译周围的说明文字；\n"
            "4. 保留原有的层次结构（标题用【】标注，列表用 • 开头）；\n"
            "5. 只输出中文翻译内容，不要输出任何说明或引导语。"
        )

        payload = {
            "model": chosen_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.1,
        }

        try:
            res = await self.client._raw_post_chat(payload)
            content = res["choices"][0]["message"].get("content", "").strip()
            if content:
                return content
        except Exception as e:
            # 尝试备用模型
            try:
                payload["model"] = "qwen-vl-max"
                res = await self.client._raw_post_chat(payload)
                content = res["choices"][0]["message"].get("content", "").strip()
                if content:
                    return content
            except Exception:
                pass

        return "（图片内容识别失败，请检查网络连接或 API Key）"

    def _render_translation_canvas(
        self,
        translated_text: str,
        width: float,
        height: float,
        output_img_path: str,
    ):
        """
        将翻译文本渲染为高清白底中文画板，字号大、排版清晰。
        :param translated_text: 完整的中文翻译文本
        :param width: 画板宽度（PDF 点，与原图等比）
        :param height: 画板高度（PDF 点，与原图等比）
        :param output_img_path: 输出 PNG 文件路径
        """
        doc = fitz.open()
        page = doc.new_page(width=width, height=height)

        # 白底背景
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(0, 0, width, height))
        shape.finish(fill=(1.0, 1.0, 1.0))
        shape.commit()

        # 顶部浅蓝色标题栏
        header_h = max(36.0, min(60.0, height * 0.10))
        sh = page.new_shape()
        sh.draw_rect(fitz.Rect(0, 0, width, header_h))
        sh.finish(fill=(0.90, 0.94, 1.0))
        sh.draw_line(fitz.Point(0, header_h), fitz.Point(width, header_h))
        sh.finish(color=(0.72, 0.82, 0.96), width=1.2)
        sh.commit()

        page.insert_textbox(
            fitz.Rect(20.0, 8.0, width - 20.0, header_h - 6.0),
            "中文翻译",
            fontname="china-s",
            fontsize=max(12.0, min(18.0, header_h * 0.40)),
            color=(0.08, 0.20, 0.52),
            align=0,
        )

        # 正文区域：自动换行，字号适中
        content_top = header_h + 14.0
        content_bottom = height - 14.0
        margin_x = 22.0
        body_font_size = max(10.5, min(15.0, width / 42.0))

        page.insert_textbox(
            fitz.Rect(margin_x, content_top, width - margin_x, content_bottom),
            translated_text,
            fontname="china-s",
            fontsize=body_font_size,
            color=(0.08, 0.08, 0.10),
            align=0,
        )

        # 如果文字超出范围，缩小字号再插入一次
        # insert_textbox 返回负数表示内容溢出
        rc = page.insert_textbox(
            fitz.Rect(margin_x, content_top, width - margin_x, content_bottom),
            translated_text,
            fontname="china-s",
            fontsize=body_font_size,
            color=(0.08, 0.08, 0.10),
            align=0,
        )
        if rc < 0:
            # 内容溢出：缩小字号至 9pt 保底
            for scale in [0.85, 0.75, 0.65]:
                rc2 = page.insert_textbox(
                    fitz.Rect(margin_x, content_top, width - margin_x, content_bottom),
                    translated_text,
                    fontname="china-s",
                    fontsize=max(9.0, body_font_size * scale),
                    color=(0.08, 0.08, 0.10),
                    align=0,
                )
                if rc2 >= 0:
                    break

        pix = page.get_pixmap(dpi=150)
        pix.save(output_img_path)
        doc.close()

    async def translate_image(
        self,
        input_image_path: str,
        output_dir: str,
        task_id: str,
        model: str = "qwen3.8-flash",
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        执行图片翻译流水线：
        1. 调用多模态大模型识别图片中所有文字并翻译；
        2. 生成清晰白底中文画板；
        3. 左右无缝拼接为双语对照 PDF 与预览图。
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
                "percent": 20,
                "message": f"正在使用 {model} 识别图片中的所有文字并翻译...",
            })

        # 第一步：多模态视觉大模型识别 + 翻译
        translated_text = await self._vision_translate_full(input_image_path, model=model)

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "rendering",
                "current_page": 1,
                "total_pages": 1,
                "percent": 60,
                "message": "正在生成高清中文翻译画板...",
            })

        # 第二步：读取原图尺寸
        orig_pil = Image.open(input_image_path).convert("RGB")
        w_px, h_px = orig_pil.size

        # 将原图尺寸从像素转换为 PDF 点（假设原图 96dpi）
        # 画板与原图等宽等高，确保 1:1 对照
        w_pt = max(500.0, float(w_px) * 72.0 / 96.0)
        h_pt = max(350.0, float(h_px) * 72.0 / 96.0)

        # 第三步：渲染中文翻译画板
        trans_img_path = str(preview_dir / "trans_page_1.png")
        self._render_translation_canvas(
            translated_text=translated_text,
            width=w_pt,
            height=h_pt,
            output_img_path=trans_img_path,
        )

        # 第四步：保存原图预览
        orig_img_preview = str(preview_dir / "orig_page_1.png")
        orig_pil.save(orig_img_preview)

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "stitching",
                "current_page": 1,
                "total_pages": 1,
                "percent": 80,
                "message": "正在合并左右对照双语图...",
            })

        # 第五步：左右无损并排拼接
        trans_rendered = Image.open(trans_img_path).convert("RGB")

        # 统一高度（取两图中较大的高度）
        target_h = max(orig_pil.height, trans_rendered.height)
        orig_w_scaled = int(orig_pil.width * target_h / orig_pil.height)
        trans_w_scaled = int(trans_rendered.width * target_h / trans_rendered.height)

        orig_resized = orig_pil.resize((orig_w_scaled, target_h), Image.Resampling.LANCZOS)
        trans_resized = trans_rendered.resize((trans_w_scaled, target_h), Image.Resampling.LANCZOS)

        # 中间细线分隔（2px 灰色）
        sep = 2
        bilingual_w = orig_w_scaled + trans_w_scaled + sep
        bilingual_img = Image.new("RGB", (bilingual_w, target_h), color=(180, 196, 220))
        bilingual_img.paste(orig_resized, (0, 0))
        bilingual_img.paste(trans_resized, (orig_w_scaled + sep, 0))

        side_by_side_img_path = str(out_path / f"{task_id}_bilingual.png")
        bilingual_img.save(side_by_side_img_path, quality=95)

        # 第六步：生成 PDF（将合并大图嵌入）
        side_by_side_pdf_path = str(out_path / f"{task_id}_bilingual_side_by_side.pdf")
        pdf_doc = fitz.open()
        pdf_w = bilingual_w * 72.0 / 150.0
        pdf_h = target_h * 72.0 / 150.0
        pdf_page = pdf_doc.new_page(width=pdf_w, height=pdf_h)
        pdf_page.insert_image(pdf_page.rect, filename=side_by_side_img_path)
        pdf_doc.save(side_by_side_pdf_path)
        pdf_doc.close()

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "completed",
                "current_page": 1,
                "total_pages": 1,
                "percent": 100,
                "message": "图片双语对照翻译完成！",
            })

        return {
            "task_id": task_id,
            "total_pages": 1,
            "side_by_side_pdf": f"/outputs/{task_id}_bilingual_side_by_side.pdf",
            "side_by_side_img": f"/outputs/{task_id}_bilingual.png",
            "pages": [
                {
                    "page": 1,
                    "orig_text": "（原始图片）",
                    "trans_text": translated_text,
                    "orig_img": f"/outputs/previews/{task_id}/orig_page_1.png",
                    "trans_img": f"/outputs/previews/{task_id}/trans_page_1.png",
                }
            ],
        }
