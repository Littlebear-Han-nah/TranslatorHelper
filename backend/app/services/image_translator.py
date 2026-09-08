import base64
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
import fitz
from PIL import Image
from .qwen_client import QwenClient

class ImageTranslator:
    """
    图片与截图双语对照翻译引擎
    核心特性：
    1. 视觉多模态大模型精翻：识别图片中的英文图表、架构图、流程图及课件排版；
    2. 原地无损排版替换：基于坐标原位擦除英文并填入中文，100% 保留原图中的模块边框、箭头及图形排版；
    3. 跨平台矢量渲染：采用 PyMuPDF 内置 china-s CJK 字体，彻底杜绝 Linux/Docker/Render 云端环境乱码；
    4. 左右无损对照拼图与双语 PDF 生成。
    """

    def __init__(self, qwen_client: QwenClient):
        """
        初始化图片翻译器
        :param qwen_client: 通义千问客户端
        """
        self.client = qwen_client

    def _sample_bg_color(self, img: Image.Image, x0: float, y0: float, x1: float, y1: float) -> Tuple[float, float, float]:
        """
        采样指定边界周围的背景底色，用于平滑擦除原英文文字
        """
        w, h = img.size
        # 围绕边界外侧微距取样
        pts = [
            (max(0, int(x0) - 2), max(0, min(h - 1, int((y0 + y1) / 2)))),
            (min(w - 1, int(x1) + 2), max(0, min(h - 1, int((y0 + y1) / 2)))),
            (max(0, min(w - 1, int((x0 + x1) / 2))), max(0, int(y0) - 2)),
            (max(0, min(w - 1, int((x0 + x1) / 2))), min(h - 1, int(y1) + 2)),
        ]
        samples = []
        for p in pts:
            try:
                rgb = img.getpixel(p)
                if isinstance(rgb, tuple) and len(rgb) >= 3:
                    samples.append(rgb[:3])
            except Exception:
                continue

        if not samples:
            return (1.0, 1.0, 1.0)

        avg_r = sum(c[0] for c in samples) / len(samples) / 255.0
        avg_g = sum(c[1] for c in samples) / len(samples) / 255.0
        avg_b = sum(c[2] for c in samples) / len(samples) / 255.0
        return (avg_r, avg_g, avg_b)

    async def _vision_translate_boxes(self, image_path: str, model: str = "qwen3.8-flash") -> Dict[str, Any]:
        """
        调用视觉多模态模型，提取图像中所有文本块及其坐标并翻译为中文
        """
        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        ext = Path(image_path).suffix.lower().lstrip(".")
        mime = f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else ext}"
        data_url = f"data:{mime};base64,{b64_data}"

        chosen_model = model if model in ["qwen3.8-flash", "qwen-vl-max", "qwen3.8-max", "qwen3.7-flash"] else "qwen3.8-flash"

        prompt = (
            "你是一个顶级的多模态课件与学术图表翻译专家。\n"
            "请识别此图像/截图中的所有英文内容（包括标题、正文、架构图、流程图、各个模块方框与数据标注），"
            "提取各文字块在图像中的归一化坐标 [ymin, xmin, ymax, xmax]（数值范围为 0 到 1000），并翻译为专业学术中文。\n"
            "请严格以 JSON 格式输出，不要输出任何额外的标记或寒暄，格式如下：\n"
            "{\n"
            '  "summary": "简明总结图表或课件的主题",\n'
            '  "items": [\n'
            '    {"text": "英文原词", "box_2d": [ymin, xmin, ymax, xmax], "translation": "中文专业译文"}\n'
            "  ]\n"
            "}"
        )

        payload = {
            "model": chosen_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ],
            "temperature": 0.1
        }

        try:
            res = await self.client._raw_post_chat(payload)
            content = res["choices"][0]["message"].get("content", "").strip()
        except Exception:
            payload["model"] = "qwen-vl-max"
            res = await self.client._raw_post_chat(payload)
            content = res["choices"][0]["message"].get("content", "").strip()

        # 解析 JSON 结果
        match = re.search(r"(\{.*\})", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and "items" in data:
                    return data
            except Exception:
                pass

        # 若未成功提取结构化 JSON，则回退为纯文本列表
        return {
            "summary": "双语对照翻译",
            "raw_text": content,
            "items": []
        }

    def _render_in_place_translated_image(
        self,
        orig_img_path: str,
        items: List[Dict[str, Any]],
        output_img_path: str
    ) -> bool:
        """
        在原图排版基础上原地擦除英文并插入中文，彻底保留图表和视觉设计
        """
        if not items:
            return False

        orig_pil = Image.open(orig_img_path).convert("RGB")
        w_px, h_px = orig_pil.size

        # 将点位画板尺寸设置为原图像素尺寸
        doc = fitz.open()
        page = doc.new_page(width=float(w_px), height=float(h_px))

        # 1. 完整铺底原图（保持 100% 原始图形、箭头、线条与颜色）
        page.insert_image(page.rect, filename=orig_img_path)

        # 2. 遍历每个文字块，原地擦除并填入中文
        for it in items:
            box = it.get("box_2d")
            trans_text = it.get("translation", "").strip()
            if not box or len(box) != 4 or not trans_text:
                continue

            ymin, xmin, ymax, xmax = box
            r_ymin = (ymin / 1000.0) * h_px
            r_xmin = (xmin / 1000.0) * w_px
            r_ymax = (ymax / 1000.0) * h_px
            r_xmax = (xmax / 1000.0) * w_px

            box_w = r_xmax - r_xmin
            box_h = r_ymax - r_ymin
            if box_w <= 2 or box_h <= 2:
                continue

            # 适度外扩 2 像素以确保完全覆盖英文笔画
            pad_x = max(2.0, box_w * 0.05)
            pad_y = max(2.0, box_h * 0.12)
            rect = fitz.Rect(
                max(0.0, r_xmin - pad_x),
                max(0.0, r_ymin - pad_y),
                min(float(w_px), r_xmax + pad_x),
                min(float(h_px), r_ymax + pad_y)
            )

            # 采样周边底色
            bg_rgb = self._sample_bg_color(orig_pil, rect.x0, rect.y0, rect.x1, rect.y1)

            # 擦除原有英文
            shape = page.new_shape()
            shape.draw_rect(rect)
            shape.finish(fill=bg_rgb)
            shape.commit()

            # 自适应计算合适字号并填入中文
            font_size = max(8.0, min(24.0, box_h * 0.78))
            page.insert_textbox(
                rect,
                trans_text,
                fontname="china-s",
                fontsize=font_size,
                color=(0.1, 0.1, 0.1),
                align=1 # 居中对齐
            )

        # 导出为高清晰度图像
        pix = page.get_pixmap(dpi=150)
        pix.save(output_img_path)
        doc.close()
        return True

    def _render_fallback_card(
        self,
        text: str,
        width: float,
        height: float,
        output_img_path: str
    ):
        """
        备用渲染：使用 PyMuPDF china-s 矢量字体生成优雅中文对照卡片
        """
        doc = fitz.open()
        page = doc.new_page(width=width, height=height)

        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(0, 0, width, height))
        shape.finish(fill=(0.97, 0.98, 1.0))

        shape.draw_rect(fitz.Rect(15, 12, width - 15, max(45, height * 0.12)))
        shape.finish(fill=(0.91, 0.94, 1.0), color=(0.2, 0.4, 0.8), width=1.5)

        shape.draw_rect(fitz.Rect(15, max(52, height * 0.14), width - 15, height - 15))
        shape.finish(fill=(1.0, 1.0, 1.0), color=(0.85, 0.88, 0.92), width=1.0)
        shape.commit()

        page.insert_textbox(
            fitz.Rect(25, 16, width - 25, max(42, height * 0.11)),
            "中文翻译与图表对照 (AI Bilingual Translation)",
            fontname="china-s",
            fontsize=max(11.0, min(16.0, height * 0.045)),
            color=(0.1, 0.25, 0.6)
        )

        content_rect = fitz.Rect(25, max(60, height * 0.16), width - 25, height - 25)
        clean_text = text.replace("**", "").replace("---", "").strip()

        page.insert_textbox(
            content_rect,
            clean_text,
            fontname="china-s",
            fontsize=max(9.0, min(13.0, height * 0.03)),
            color=(0.15, 0.15, 0.15)
        )

        pix = page.get_pixmap(dpi=150)
        pix.save(output_img_path)
        doc.close()

    async def translate_image(
        self,
        input_image_path: str,
        output_dir: str,
        task_id: str,
        model: str = "qwen3.8-flash",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        执行图片截图翻译流水线并生成左右高保真并排对照大图与 PDF
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
                "percent": 25,
                "message": f"正在使用 {model} 进行多模态视觉图表识别与版面解析..."
            })

        # 1. 调用多模态视觉模型提取坐标与翻译
        parsed_data = await self._vision_translate_boxes(input_image_path, model=model)
        items = parsed_data.get("items", [])

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "stitching",
                "current_page": 1,
                "total_pages": 1,
                "percent": 65,
                "message": "正在原图版面基础上进行原地无损中文排版..."
            })

        orig_pil = Image.open(input_image_path).convert("RGB")
        w_px, h_px = orig_pil.size
        trans_img_path = str(preview_dir / "trans_page_1.png")

        # 2. 优先尝试原图原位图表替换
        success = False
        if items:
            try:
                success = self._render_in_place_translated_image(
                    orig_img_path=input_image_path,
                    items=items,
                    output_img_path=trans_img_path
                )
            except Exception:
                success = False

        # 若无坐标或原位替换异常，则回退为优雅矢量卡片排版
        if not success:
            fallback_text = parsed_data.get("raw_text") or parsed_data.get("summary", "图表翻译已完成")
            self._render_fallback_card(
                text=fallback_text,
                width=float(w_px),
                height=float(h_px),
                output_img_path=trans_img_path
            )

        # 3. 保存原图预览
        orig_img_preview = str(preview_dir / "orig_page_1.png")
        orig_pil.save(orig_img_preview)

        # 4. 左右高清无损拼接
        trans_rendered_img = Image.open(trans_img_path).convert("RGB")
        target_h = max(orig_pil.height, trans_rendered_img.height)
        orig_scaled_w = int(orig_pil.width * (target_h / orig_pil.height))
        trans_scaled_w = int(trans_rendered_img.width * (target_h / trans_rendered_img.height))

        orig_resized = orig_pil.resize((orig_scaled_w, target_h), Image.Resampling.LANCZOS)
        trans_resized = trans_rendered_img.resize((trans_scaled_w, target_h), Image.Resampling.LANCZOS)

        bilingual_w = orig_scaled_w + trans_scaled_w + 4
        bilingual_img = Image.new("RGB", (bilingual_w, target_h), color=(203, 213, 225))
        bilingual_img.paste(orig_resized, (0, 0))
        bilingual_img.paste(trans_resized, (orig_scaled_w + 4, 0))

        side_by_side_img_path = str(out_path / f"{task_id}_bilingual.png")
        bilingual_img.save(side_by_side_img_path)

        # 5. 生成左右并排双语对照 PDF
        side_by_side_pdf_path = str(out_path / f"{task_id}_bilingual_side_by_side.pdf")
        pdf_doc = fitz.open()
        pdf_page = pdf_doc.new_page(width=(bilingual_w * 72.0 / 150.0), height=(target_h * 72.0 / 150.0))
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
                "message": "图片图表高保真双语对照已生成！"
            })

        # 组合纯文本说明
        display_trans_text = parsed_data.get("summary", "")
        if items:
            details = [f"- {it['text']} → {it['translation']}" for it in items]
            display_trans_text += "\n\n" + "\n".join(details)

        return {
            "task_id": task_id,
            "total_pages": 1,
            "side_by_side_pdf": f"/outputs/{task_id}_bilingual_side_by_side.pdf",
            "side_by_side_img": f"/outputs/{task_id}_bilingual.png",
            "pages": [{
                "page": 1,
                "orig_text": "（图片/截图原版）",
                "trans_text": display_trans_text,
                "orig_img": f"/outputs/previews/{task_id}/orig_page_1.png",
                "trans_img": f"/outputs/previews/{task_id}/trans_page_1.png",
            }],
        }
