import base64
import json
import re
import io
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
import fitz
from PIL import Image
from .qwen_client import QwenClient


class ImageTranslator:
    """
    图片与文档截图高保真无痕双语对照翻译引擎
    核心设计：
    1. 无痕原位替换：100% 完整保留原图的所有图形、架构图节点、边框、线条与背景；
    2. 多模态坐标定位：精确定位图片中所有文字区域的外接矩形（box_2d）及其对应的中文翻译；
    3. 自适应背景采样：采用纯 PIL 像素算法自动采样文字周边的背景色，消除原英文并原位自然填入居中清晰的中文；
    4. 左右双栏对照并排导出：生成左原图、右原位中文对照的高清图与 PDF；
    5. 无第三方复杂依赖：无需 numpy 即可高性能运行，彻底杜绝云端 ModuleNotFoundError 与内存溢出。
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
            "3. 仅输出合法 JSON 列表，切勿添加任何外部注释或寒暄。"
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
        在原图基础上进行无痕原位翻译（使用纯 PIL 像素算法，无需外部科学计算库）
        1. 以原图为底层画板，100% 保留所有几何图表、连线、边框与底色；
        2. 采样每个文字块周边背景色，擦除原英文；
        3. 原位居中填入中文，字号根据区域高宽自适应。
        """
        orig_pil = Image.open(input_image_path).convert("RGB")
        w_px, h_px = orig_pil.size

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

            # 外扩 3 像素边缘，确保完全覆盖原英文字形
            pad = 3
            bx0 = max(0, px0 - pad)
            by0 = max(0, py0 - pad)
            bx1 = min(w_px, px1 + pad)
            by1 = min(h_px, py1 + pad)

            # 纯 PIL 采样周边背景色（周长像素中位数）
            border_pixels = []
            for x in range(bx0, bx1):
                if by0 > 0:
                    border_pixels.append(orig_pil.getpixel((x, by0)))
                if by1 < h_px:
                    border_pixels.append(orig_pil.getpixel((x, by1 - 1)))
            for y in range(by0, by1):
                if bx0 > 0:
                    border_pixels.append(orig_pil.getpixel((bx0, y)))
                if bx1 < w_px:
                    border_pixels.append(orig_pil.getpixel((bx1 - 1, y)))

            if border_pixels:
                mid_idx = len(border_pixels) // 2
                r_med = sorted(p[0] for p in border_pixels)[mid_idx]
                g_med = sorted(p[1] for p in border_pixels)[mid_idx]
                b_med = sorted(p[2] for p in border_pixels)[mid_idx]
                bg_rgb = (r_med, g_med, b_med)
            else:
                bg_rgb = (255, 255, 255)

            bg_lum = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]

            # 纯 PIL 最大对比度文字颜色采样算法（深底配高亮白字，浅底配深字，杜绝隐形）
            best_diff = -1.0
            text_rgb = (20, 25, 30) if bg_lum > 128 else (250, 250, 250)
            step_x = max(1, (px1 - px0) // 12)
            step_y = max(1, (py1 - py0) // 12)
            for y in range(py0, py1, step_y):
                for x in range(px0, px1, step_x):
                    pv = orig_pil.getpixel((x, y))
                    lum = 0.299 * pv[0] + 0.587 * pv[1] + 0.114 * pv[2]
                    diff = abs(lum - bg_lum)
                    if diff > best_diff:
                        best_diff = diff
                        text_rgb = pv[:3]

            # 若反差不足 40，强制使用高对比度深色/浅色
            if best_diff < 40:
                text_rgb = (20, 25, 30) if bg_lum > 128 else (250, 250, 250)

            rect_pdf = fitz.Rect(bx0 * scale, by0 * scale, bx1 * scale, by1 * scale)
            bg_norm = (bg_rgb[0] / 255.0, bg_rgb[1] / 255.0, bg_rgb[2] / 255.0)
            text_norm = (text_rgb[0] / 255.0, text_rgb[1] / 255.0, text_rgb[2] / 255.0)

            # 覆盖原英文
            s = page.new_shape()
            s.draw_rect(rect_pdf)
            s.finish(fill=bg_norm, stroke_opacity=0)
            s.commit()

            # 填入中文（改用 insert_text 避免 insert_textbox 边界溢出静默丢弃文字）
            zh = it.get("zh", "").strip()
            if not zh:
                continue

            font_size = max(7.0, min(14.0, rect_pdf.height * 1.15))
            cx = (rect_pdf.x0 + rect_pdf.x1) / 2.0
            cy = (rect_pdf.y0 + rect_pdf.y1) / 2.0

            lines = [l.strip() for l in zh.split("\n") if l.strip()]
            if not lines:
                lines = [zh]

            line_h = font_size * 1.2
            start_y = cy - (len(lines) - 1) * line_h / 2.0 + font_size * 0.35

            for i, line in enumerate(lines):
                cur_font_size = font_size
                tl = fitz.get_text_length(line, fontname="china-s", fontsize=cur_font_size)
                if tl > (page.rect.width - 4.0):
                    cur_font_size = max(6.0, cur_font_size * ((page.rect.width - 4.0) / tl))
                    tl = fitz.get_text_length(line, fontname="china-s", fontsize=cur_font_size)

                x_pt = max(2.0, min(page.rect.width - tl - 2.0, cx - tl / 2.0))
                y_pt = start_y + i * line_h
                page.insert_text(
                    fitz.Point(x_pt, y_pt),
                    line,
                    fontname="china-s",
                    fontsize=cur_font_size,
                    color=text_norm
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

        # 第五步：生成双语对照 PDF（使用 JPEG 格式编码，速度快、体积小、杜绝内存溢出）
        side_by_side_pdf_path = str(out_path / f"{task_id}_bilingual_side_by_side.pdf")
        pdf_doc = fitz.open()
        pdf_w = bilingual_w * 72.0 / 150.0
        pdf_h = target_h * 72.0 / 150.0
        pdf_page = pdf_doc.new_page(width=pdf_w, height=pdf_h)

        buf = io.BytesIO()
        bilingual_img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        pdf_page.insert_image(pdf_page.rect, stream=buf.read())
        pdf_doc.save(side_by_side_pdf_path, garbage=3, deflate=True)
        pdf_doc.close()

        # 第六步：生成纯中文原位 PDF
        pure_trans_pdf_path = str(out_path / f"{task_id}_chinese_only.pdf")
        pure_doc = fitz.open()
        pure_w = trans_rendered.width * 72.0 / 150.0
        pure_h = trans_rendered.height * 72.0 / 150.0
        pure_page = pure_doc.new_page(width=pure_w, height=pure_h)

        buf_pure = io.BytesIO()
        trans_rendered.save(buf_pure, format="JPEG", quality=90)
        buf_pure.seek(0)
        pure_page.insert_image(pure_page.rect, stream=buf_pure.read())
        pure_doc.save(pure_trans_pdf_path, garbage=3, deflate=True)
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
