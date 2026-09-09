import base64
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
import fitz
import numpy as np
from PIL import Image
from .qwen_client import QwenClient


class ImageTranslator:
    """
    图片与文档截图高保真无痕双语对照翻译引擎
    核心设计：
    1. 无痕原位替换：100% 完整保留原图的所有图形、架构图节点、边框、线条与背景；
    2. 多模态坐标定位：精确定位图片中所有文字区域的外接矩形（box_2d）及其对应的中文翻译；
    3. 自适应背景采样：自动采样文字周边的背景色，消除原英文并原位自然填入居中清晰的中文；
    4. 左右双栏对照并排导出：生成左原图、右原位中文对照的高清图与 PDF；
    5. 使用 PyMuPDF 内置 china-s CJK 矢量字体，彻底杜绝云端乱码与空白问题。
    """

    def __init__(self, qwen_client: QwenClient):
        """
        初始化图片翻译器
        :param qwen_client: 通义千问客户端
        """
        self.client = qwen_client

    async def _vision_detect_and_translate(
        self,
        image_path: str,
        model: str = "qwen3.8-flash"
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        调用多模态视觉模型，识别图片中全部文字位置（归一化坐标）并提供高质量中文翻译
        返回：(检测到的文本块列表, 完整摘要文本)
        """
        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        ext = Path(image_path).suffix.lower().lstrip(".")
        mime = f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else ext}"
        data_url = f"data:{mime};base64,{b64_data}"

        vl_models = {"qwen3.8-flash", "qwen-vl-max", "qwen3.8-max", "qwen3.7-flash", "qwen3.5-ocr", "qwen3.8-max-0902"}
        chosen_model = model if model in vl_models else "qwen3.8-flash"

        prompt = (
            "你是一个顶级的学术课件与技术图表视觉定位与翻译专家。"
            "请定位图中所有需要翻译的英文文字（包括标题、正文段落、图表方框内文字、箭头标注、说明文字等），"
            "并翻译为地道严谨的中文。\n\n"
            "请严格以 JSON 列表格式输出：\n"
            "[\n"
            '  {"box_2d": [ymin, xmin, ymax, xmax], "en": "英文原文", "zh": "中文翻译"}\n'
            "]\n\n"
            "要求：\n"
            "1. box_2d 为 0-1000 的归一化整数坐标 [ymin, xmin, ymax, xmax]；\n"
            "2. 务必覆盖图中全部英文标签与节点文字，切勿遗漏；\n"
            "3. 仅输出合法 JSON 列表，切勿添加任何 Markdown 外部注释或寒暄。"
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

        content = ""
        try:
            res = await self.client._raw_post_chat(payload)
            content = res["choices"][0]["message"].get("content", "").strip()
        except Exception:
            try:
                payload["model"] = "qwen-vl-max"
                res = await self.client._raw_post_chat(payload)
                content = res["choices"][0]["message"].get("content", "").strip()
            except Exception:
                pass

        # 解析 JSON 列表
        items: List[Dict[str, Any]] = []
        match = re.search(r"(\[.*\])", content, re.DOTALL)
        if match:
            try:
                raw_items = json.loads(match.group(1))
                if isinstance(raw_items, list):
                    for it in raw_items:
                        if not isinstance(it, dict):
                            continue
                        box = it.get("box_2d")
                        zh = it.get("zh", "").strip()
                        if not zh or not isinstance(box, list) or len(box) < 4:
                            continue
                        items.append({
                            "box_2d": [int(x) for x in box[:4]],
                            "en": it.get("en", ""),
                            "zh": zh
                        })
            except Exception:
                pass

        # 生成摘要文本
        if items:
            summary = "\n".join([f"• {it['zh']} ({it['en']})" for it in items])
        else:
            summary = content or "（未检测到文本内容）"

        return items, summary

    def _render_inplace_translated_image(
        self,
        input_image_path: str,
        items: List[Dict[str, Any]],
        output_img_path: str,
    ):
        """
        在原图基础上进行无痕原位翻译：
        1. 以原图为底层画板，100% 保留所有几何图表、连线、边框与底色；
        2. 采样每个文字块周边背景色，擦除原英文；
        3. 原位居中填入中文，字号根据区域高宽自适应。
        """
        orig_pil = Image.open(input_image_path).convert("RGB")
        w_px, h_px = orig_pil.size
        arr = np.array(orig_pil)

        scale = 72.0 / 150.0
        doc = fitz.open()
        page = doc.new_page(width=w_px * scale, height=h_px * scale)

        # 1. 铺设原图底板（保留全部图形）
        page.insert_image(page.rect, filename=input_image_path)

        # 2. 原位替换文字
        for it in items:
            ymin, xmin, ymax, xmax = it["box_2d"]
            px0 = int(xmin * w_px / 1000.0)
            py0 = int(ymin * h_px / 1000.0)
            px1 = int(xmax * w_px / 1000.0)
            py1 = int(ymax * h_px / 1000.0)

            # 外扩 2 像素边缘，确保完全覆盖原英文字形
            pad = 2
            bx0 = max(0, px0 - pad)
            by0 = max(0, py0 - pad)
            bx1 = min(w_px, px1 + pad)
            by1 = min(h_px, py1 + pad)

            # 采样周边背景色
            border_pixels = []
            if by0 > 0:
                border_pixels.extend(arr[by0, bx0:bx1])
            if by1 < h_px:
                border_pixels.extend(arr[by1 - 1, bx0:bx1])
            if bx0 > 0:
                border_pixels.extend(arr[by0:by1, bx0])
            if bx1 < w_px:
                border_pixels.extend(arr[by0:by1, bx1 - 1])

            if border_pixels:
                bg_rgb = np.median(border_pixels, axis=0).astype(int)
            else:
                bg_rgb = np.array([255, 255, 255])

            # 采样文字颜色（取原框内最深像素）
            box_pixels = arr[py0:py1, px0:px1]
            if box_pixels.size > 0:
                lums = 0.299 * box_pixels[:, :, 0] + 0.587 * box_pixels[:, :, 1] + 0.114 * box_pixels[:, :, 2]
                min_idx = np.unravel_index(np.argmin(lums), lums.shape)
                text_rgb = box_pixels[min_idx[0], min_idx[1]]
            else:
                text_rgb = np.array([30, 30, 30])

            rect_pdf = fitz.Rect(bx0 * scale, by0 * scale, bx1 * scale, by1 * scale)
            bg_norm = (bg_rgb[0] / 255.0, bg_rgb[1] / 255.0, bg_rgb[2] / 255.0)
            text_norm = (text_rgb[0] / 255.0, text_rgb[1] / 255.0, text_rgb[2] / 255.0)

            # 覆盖原英文
            s = page.new_shape()
            s.draw_rect(rect_pdf)
            s.finish(fill=bg_norm, stroke_opacity=0)
            s.commit()

            # 填入中文
            zh = it["zh"]
            font_size = max(7.5, min(15.0, rect_pdf.height * 0.90))

            # 适度自适应宽度避免换行
            text_len = len(zh)
            needed_w = text_len * font_size * 1.05
            if needed_w > rect_pdf.width:
                expand = (needed_w - rect_pdf.width) / 2.0
                rect_insert = fitz.Rect(
                    max(0, rect_pdf.x0 - expand),
                    rect_pdf.y0,
                    min(page.rect.width, rect_pdf.x1 + expand),
                    rect_pdf.y1
                )
            else:
                rect_insert = rect_pdf

            page.insert_textbox(
                rect_insert,
                zh,
                fontname="china-s",
                fontsize=font_size,
                color=text_norm,
                align=1  # 居中对齐
            )

        pix = page.get_pixmap(dpi=150)
        pix.save(output_img_path)
        doc.close()

    def _render_fallback_card(
        self,
        translated_text: str,
        width: float,
        height: float,
        output_img_path: str,
    ):
        """
        容错后备方案：当未能精确定位坐标时，渲染清晰排版的中文精读卡片
        """
        doc = fitz.open()
        page = doc.new_page(width=width, height=height)

        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(0, 0, width, height))
        shape.finish(fill=(1.0, 1.0, 1.0))
        shape.commit()

        header_h = max(36.0, min(56.0, height * 0.10))
        sh = page.new_shape()
        sh.draw_rect(fitz.Rect(0, 0, width, header_h))
        sh.finish(fill=(0.92, 0.95, 1.0))
        sh.draw_line(fitz.Point(0, header_h), fitz.Point(width, header_h))
        sh.finish(color=(0.75, 0.84, 0.95), width=1.0)
        sh.commit()

        page.insert_textbox(
            fitz.Rect(20.0, 8.0, width - 20.0, header_h - 6.0),
            "中文翻译对照",
            fontname="china-s",
            fontsize=max(12.0, min(17.0, header_h * 0.40)),
            color=(0.08, 0.20, 0.52),
            align=0,
        )

        content_top = header_h + 14.0
        content_bottom = height - 14.0
        margin_x = 22.0
        body_font_size = max(10.5, min(14.5, width / 42.0))

        for scale in [1.0, 0.85, 0.72, 0.60]:
            rc = page.insert_textbox(
                fitz.Rect(margin_x, content_top, width - margin_x, content_bottom),
                translated_text,
                fontname="china-s",
                fontsize=max(9.0, body_font_size * scale),
                color=(0.1, 0.1, 0.12),
                align=0,
            )
            if rc >= 0:
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
        执行高保真无痕图片翻译流水线：
        1. 视觉大模型定位图片中所有文字及坐标；
        2. 原图基础上执行无痕原位翻译（原图背景 100% 保留，文字原位替换）；
        3. 左右无缝拼接生成双语对照图与 PDF。
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
                "message": f"正在使用 {model} 进行多模态图文识别与坐标定位...",
            })

        # 第一步：多模态视觉识别与位置检测
        items, summary_text = await self._vision_detect_and_translate(input_image_path, model=model)

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "rendering",
                "current_page": 1,
                "total_pages": 1,
                "percent": 60,
                "message": "正在原位替换中文，100% 保留原图排版与背景...",
            })

        orig_pil = Image.open(input_image_path).convert("RGB")
        w_px, h_px = orig_pil.size
        trans_img_path = str(preview_dir / "trans_page_1.png")

        # 第二步：无痕原位渲染
        if items:
            self._render_inplace_translated_image(
                input_image_path=input_image_path,
                items=items,
                output_img_path=trans_img_path,
            )
        else:
            w_pt = max(500.0, float(w_px) * 72.0 / 96.0)
            h_pt = max(350.0, float(h_px) * 72.0 / 96.0)
            self._render_fallback_card(
                translated_text=summary_text,
                width=w_pt,
                height=h_pt,
                output_img_path=trans_img_path,
            )

        # 第三步：保存原图高清预览
        orig_img_preview = str(preview_dir / "orig_page_1.png")
        orig_pil.save(orig_img_preview)

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "stitching",
                "current_page": 1,
                "total_pages": 1,
                "percent": 80,
                "message": "正在合并左右无痕对照双语图...",
            })

        # 第四步：左右无损并排拼接
        trans_rendered = Image.open(trans_img_path).convert("RGB")
        target_h = max(orig_pil.height, trans_rendered.height)
        orig_w_scaled = int(orig_pil.width * target_h / orig_pil.height)
        trans_w_scaled = int(trans_rendered.width * target_h / trans_rendered.height)

        orig_resized = orig_pil.resize((orig_w_scaled, target_h), Image.Resampling.LANCZOS)
        trans_resized = trans_rendered.resize((trans_w_scaled, target_h), Image.Resampling.LANCZOS)

        sep = 3
        bilingual_w = orig_w_scaled + trans_w_scaled + sep
        bilingual_img = Image.new("RGB", (bilingual_w, target_h), color=(180, 196, 220))
        bilingual_img.paste(orig_resized, (0, 0))
        bilingual_img.paste(trans_resized, (orig_w_scaled + sep, 0))

        side_by_side_img_path = str(out_path / f"{task_id}_bilingual.png")
        bilingual_img.save(side_by_side_img_path, quality=95)

        # 第五步：生成双语对照 PDF
        side_by_side_pdf_path = str(out_path / f"{task_id}_bilingual_side_by_side.pdf")
        pdf_doc = fitz.open()
        pdf_w = bilingual_w * 72.0 / 150.0
        pdf_h = target_h * 72.0 / 150.0
        pdf_page = pdf_doc.new_page(width=pdf_w, height=pdf_h)
        pdf_page.insert_image(pdf_page.rect, filename=side_by_side_img_path)
        pdf_doc.save(side_by_side_pdf_path)
        pdf_doc.close()

        # 第六步：生成纯中文原位 PDF
        pure_trans_pdf_path = str(out_path / f"{task_id}_chinese_only.pdf")
        pure_doc = fitz.open()
        pure_w = trans_rendered.width * 72.0 / 150.0
        pure_h = trans_rendered.height * 72.0 / 150.0
        pure_page = pure_doc.new_page(width=pure_w, height=pure_h)
        pure_page.insert_image(pure_page.rect, filename=trans_img_path)
        pure_doc.save(pure_trans_pdf_path)
        pure_doc.close()

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "completed",
                "current_page": 1,
                "total_pages": 1,
                "percent": 100,
                "message": "无痕图文对照翻译已完成！",
            })

        return {
            "task_id": task_id,
            "total_pages": 1,
            "side_by_side_pdf": f"/outputs/{task_id}_bilingual_side_by_side.pdf",
            "pure_trans_pdf": f"/outputs/{task_id}_chinese_only.pdf",
            "side_by_side_img": f"/outputs/{task_id}_bilingual.png",
            "pages": [
                {
                    "page": 1,
                    "orig_text": "（原版图文）",
                    "trans_text": summary_text,
                    "orig_img": f"/outputs/previews/{task_id}/orig_page_1.png",
                    "trans_img": f"/outputs/previews/{task_id}/trans_page_1.png",
                }
            ],
        }
