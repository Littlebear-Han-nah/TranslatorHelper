import fitz  # PyMuPDF 核心库
import os
import re
import json
import base64
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List, Tuple
from PIL import Image
from .qwen_client import QwenClient

class PDFTranslator:
    """
    PDF 课件与学术论文高保真双语对照翻译引擎
    核心能力：
    1. 1:1 原版图文画板克隆：100% 完整保留原版课件/论文中的所有图片、插图、矢量图表、流程图线条与几何底色；
    2. 精准坐标提取与原地文字擦除：精确定位每个英文文字块，无损擦除英文内容；
    3. 自适应字号原位中文填入：在原坐标区域内自适应匹配字号与原版字体颜色填入中文；
    4. 嵌入式图表与插图视觉精翻：自动识别页面内嵌入的架构图、流程图或模块图，定位图内英文并原位替换为中文；
    5. 纯图表/扫描件页面多模态视觉翻译：对无可选文本的扫描件或纯图课件，自动提取坐标原位精翻，杜绝遮盖底图；
    6. 左右双栏无损拼接：左原版图文英文，右原版图文中文，生成顶级双语对照 PDF；
    7. 高清预览图逐页生成，供网页端无缝双栏精读。
    """

    def __init__(self, qwen_client: QwenClient):
        """
        初始化 PDF 翻译器
        :param qwen_client: 通义千问客户端实例
        """
        self.client = qwen_client

    def _sample_background_color(self, page: fitz.Page, rect: fitz.Rect) -> Tuple[float, float, float]:
        """
        智能采样文字区域背后的底色（用于无痕遮盖原英文，保留背景卡片色彩）
        """
        try:
            x = max(1.0, min(page.rect.width - 3.0, rect.x0 - 2.0))
            y = max(1.0, min(page.rect.height - 3.0, rect.y0 - 2.0))
            pix = page.get_pixmap(clip=fitz.Rect(x, y, x + 2.0, y + 2.0))
            if pix.width > 0 and pix.height > 0:
                pixel = pix.pixel(0, 0)
                return (pixel[0] / 255.0, pixel[1] / 255.0, pixel[2] / 255.0)
        except Exception:
            pass
        return (1.0, 1.0, 1.0)  # 默认纯白背景

    def _sample_pil_color(self, pil_img: Image.Image, x: float, y: float) -> Tuple[float, float, float]:
        """
        从 PIL 图像中采样坐标点颜色并归一化为 0-1 的 RGB 元组
        """
        w, h = pil_img.size
        px = max(0, min(w - 1, int(x)))
        py = max(0, min(h - 1, int(y)))
        try:
            rgb = pil_img.getpixel((px, py))
            if isinstance(rgb, tuple) and len(rgb) >= 3:
                return (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
        except Exception:
            pass
        return (1.0, 1.0, 1.0)

    def _extract_page_text_blocks(self, page: fitz.Page) -> List[Dict[str, Any]]:
        """
        细粒度提取当前页面的所有文本块，包括外接矩形、文本内容、建议字号与文字颜色
        """
        text_dict = page.get_text("dict")
        extracted_blocks = []

        for b in text_dict.get("blocks", []):
            if b.get("type") != 0:  # 0 为文本块，1 为图像块
                continue

            block_text = ""
            spans_sizes = []
            spans_colors = []

            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    span_t = span.get("text", "")
                    block_text += span_t
                    if span_t.strip():
                        spans_sizes.append(span.get("size", 12.0))
                        c = span.get("color", 0)
                        r = ((c >> 16) & 255) / 255.0
                        g = ((c >> 8) & 255) / 255.0
                        b_col = (c & 255) / 255.0
                        spans_colors.append((r, g, b_col))
                block_text += "\n"

            clean_text = block_text.strip()
            if not clean_text:
                continue

            dom_size = max(spans_sizes) if spans_sizes else 12.0
            dom_color = spans_colors[0] if spans_colors else (0.15, 0.15, 0.15)

            extracted_blocks.append({
                "bbox": fitz.Rect(b["bbox"]),
                "text": clean_text,
                "size": dom_size,
                "color": dom_color,
            })

        return extracted_blocks

    async def _translate_page_blocks(
        self,
        blocks: List[Dict[str, Any]],
        model: str = "qwen3.8-flash",
        mode: str = "courseware"
    ) -> List[str]:
        """
        将整页的所有文本块通过通义千问大模型进行批量上下文翻译
        """
        if not blocks:
            return []

        prompt_parts = [
            "请将以下文档页面中的每个文本块准确翻译为专业中文。\n"
            "翻译要求：\n"
            "1. 必须严格保留各块的编号标记（如 [1], [2]），不可合并、拆分或遗漏任何一个序号；\n"
            "2. 保持块内的原有分行与项目符号（如 • 或序号）；\n"
            "3. 严谨保留文中的 LaTeX 公式（如 $...$ 或 $$...$$）、数学变量、代码及专业术语；\n"
            "4. 只输出带对应序号的翻译结果，不要输出任何引言或解释。\n\n"
            "待翻译内容：\n"
        ]

        for idx, blk in enumerate(blocks):
            prompt_parts.append(f"[{idx + 1}] {blk['text']}\n")

        full_prompt = "".join(prompt_parts)
        translated_reply = await self.client.translate_text(
            text=full_prompt,
            model=model,
            mode=mode
        )

        result_map: Dict[int, str] = {}
        pattern = re.compile(r"\[(\d+)\]\s*(.*?)(?=\[\d+\]|\Z)", re.DOTALL)
        matches = pattern.findall(translated_reply)

        for num_str, content in matches:
            try:
                num = int(num_str)
                result_map[num] = content.strip()
            except ValueError:
                continue

        final_translations = []
        for idx in range(len(blocks)):
            block_idx = idx + 1
            if block_idx in result_map:
                final_translations.append(result_map[block_idx])
            else:
                final_translations.append(blocks[idx]["text"])

        return final_translations

    def _apply_in_place_translations(
        self,
        target_page: fitz.Page,
        blocks: List[Dict[str, Any]],
        translations: List[str]
    ):
        """
        在克隆的页面上执行高保真原地替换：
        1. 针对每个文本块擦除原有英文（保留背后的图表与底色）；
        2. 自适应计算最佳字号并原位回填中文。
        """
        for blk in blocks:
            r = blk["bbox"]
            bg_color = self._sample_background_color(target_page, r)
            target_page.add_redact_annot(r, fill=bg_color)

        target_page.apply_redactions()

        for blk, trans_text in zip(blocks, translations):
            if not trans_text.strip():
                continue

            orig_rect = blk["bbox"]
            orig_size = blk["size"]
            orig_color = blk["color"]

            extended_w = min(target_page.rect.width - orig_rect.x0 - 5.0, orig_rect.width * 1.05)
            fit_rect = fitz.Rect(orig_rect.x0, orig_rect.y0, orig_rect.x0 + extended_w, orig_rect.y1)

            inserted = False
            for scale in [1.0, 0.92, 0.85, 0.78, 0.72]:
                try_size = max(8.0, orig_size * scale)
                rc = target_page.insert_textbox(
                    fit_rect,
                    trans_text,
                    fontname="china-s",
                    fontsize=try_size,
                    color=orig_color,
                    align=0
                )
                if rc >= 0:
                    inserted = True
                    break

            if not inserted:
                target_page.insert_textbox(
                    fit_rect,
                    trans_text,
                    fontname="china-s",
                    fontsize=max(7.5, orig_size * 0.7),
                    color=orig_color,
                    align=0
                )

    async def _vision_translate_diagram_clip(
        self,
        clip_png_bytes: bytes,
        model: str = "qwen3.8-flash"
    ) -> List[Dict[str, Any]]:
        """
        针对页面内嵌的插图/架构图/流程图，调用多模态大模型提取图表内英文文字坐标与译文
        """
        b64_data = base64.b64encode(clip_png_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{b64_data}"

        chosen_model = model if model in ["qwen3.8-flash", "qwen-vl-max", "qwen3.8-max", "qwen3.7-flash"] else "qwen3.8-flash"
        prompt = (
            "请识别此插图/架构图中的所有英文词语或短语及其在图中的归一化坐标 [ymin, xmin, ymax, xmax]（0-1000），"
            "并翻译为专业学术中文。请严格以 JSON 列表格式输出，若无英文文字则输出空列表 []：\n"
            "[\n"
            '  {"text": "英文原词", "box_2d": [ymin, xmin, ymax, xmax], "translation": "中文译文"}\n'
            "]"
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
            match = re.search(r"(\[.*\])", content, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    def _apply_diagram_translations(
        self,
        target_page: fitz.Page,
        page_pil: Image.Image,
        img_rect: fitz.Rect,
        items: List[Dict[str, Any]]
    ):
        """
        将内嵌插图/架构图内的英文文字在原图区域中原地擦除并填入中文
        """
        scale_x = page_pil.width / target_page.rect.width
        scale_y = page_pil.height / target_page.rect.height

        for it in items:
            box = it.get("box_2d")
            trans_text = it.get("translation", "").strip()
            if not box or len(box) != 4 or not trans_text:
                continue

            ymin, xmin, ymax, xmax = box
            # 映射归一化坐标至 PDF 页面上的实际点位坐标
            item_x0 = img_rect.x0 + (xmin / 1000.0) * img_rect.width
            item_y0 = img_rect.y0 + (ymin / 1000.0) * img_rect.height
            item_x1 = img_rect.x0 + (xmax / 1000.0) * img_rect.width
            item_y1 = img_rect.y0 + (ymax / 1000.0) * img_rect.height

            box_w = item_x1 - item_x0
            box_h = item_y1 - item_y0
            if box_w <= 1 or box_h <= 1:
                continue

            pad_x = max(1.5, box_w * 0.06)
            pad_y = max(1.5, box_h * 0.12)
            fit_rect = fitz.Rect(
                max(img_rect.x0, item_x0 - pad_x),
                max(img_rect.y0, item_y0 - pad_y),
                min(img_rect.x1, item_x1 + pad_x),
                min(img_rect.y1, item_y1 + pad_y)
            )

            # 采样周边底色
            sample_px = (fit_rect.x0) * scale_x
            sample_py = max(0.0, (fit_rect.y0 - 2.0)) * scale_y
            bg_color = self._sample_pil_color(page_pil, sample_px, sample_py)

            # 擦除原有英文
            shape = target_page.new_shape()
            shape.draw_rect(fit_rect)
            shape.finish(fill=bg_color)
            shape.commit()

            # 自适应填入中文
            font_size = max(7.0, min(14.0, box_h * 0.78))
            target_page.insert_textbox(
                fit_rect,
                trans_text,
                fontname="china-s",
                fontsize=font_size,
                color=(0.12, 0.12, 0.12),
                align=1
            )

    async def _vision_translate_page_boxes(
        self,
        image_path: str,
        model: str = "qwen3.8-flash"
    ) -> Dict[str, Any]:
        """
        针对整页为纯图片/扫描件的课件页面，提取所有文字块坐标并翻译
        """
        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        chosen_model = model if model in ["qwen3.8-flash", "qwen-vl-max", "qwen3.8-max", "qwen3.7-flash"] else "qwen3.8-flash"
        prompt = (
            "你是一个顶级的多模态课件与学术图表翻译专家。\n"
            "请识别此文档页面中的所有英文文本（包括标题、架构图方框、流程图箭头与数据说明），"
            "提取各文本块的归一化坐标 [ymin, xmin, ymax, xmax]（0 到 1000），并翻译为专业中文。\n"
            "严格以 JSON 格式输出：\n"
            "{\n"
            '  "summary": "简明主题概述",\n'
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
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_data}"}}
                    ]
                }
            ],
            "temperature": 0.1
        }

        try:
            res = await self.client._raw_post_chat(payload)
            content = res["choices"][0]["message"].get("content", "").strip()
            match = re.search(r"(\{.*\})", content, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and "items" in data:
                    return data
        except Exception:
            pass
        return {"summary": "图文页面翻译", "items": []}

    def _apply_vision_page_translations(
        self,
        target_page: fitz.Page,
        page_pil: Image.Image,
        items: List[Dict[str, Any]]
    ) -> bool:
        """
        在纯图片/扫描件页面画板上执行原地无损中文替换，保留底色和全部图像结构
        """
        if not items:
            return False

        w, h = target_page.rect.width, target_page.rect.height
        scale_x = page_pil.width / w
        scale_y = page_pil.height / h

        for it in items:
            box = it.get("box_2d")
            trans_text = it.get("translation", "").strip()
            if not box or len(box) != 4 or not trans_text:
                continue

            ymin, xmin, ymax, xmax = box
            r_ymin = (ymin / 1000.0) * h
            r_xmin = (xmin / 1000.0) * w
            r_ymax = (ymax / 1000.0) * h
            r_xmax = (xmax / 1000.0) * w

            box_w = r_xmax - r_xmin
            box_h = r_ymax - r_ymin
            if box_w <= 2 or box_h <= 2:
                continue

            pad_x = max(2.0, box_w * 0.05)
            pad_y = max(2.0, box_h * 0.12)
            rect = fitz.Rect(
                max(0.0, r_xmin - pad_x),
                max(0.0, r_ymin - pad_y),
                min(w, r_xmax + pad_x),
                min(h, r_ymax + pad_y)
            )

            # 采样周边底色
            sample_px = rect.x0 * scale_x
            sample_py = max(0.0, rect.y0 - 2.0) * scale_y
            bg_color = self._sample_pil_color(page_pil, sample_px, sample_py)

            # 原地擦除英文
            shape = target_page.new_shape()
            shape.draw_rect(rect)
            shape.finish(fill=bg_color)
            shape.commit()

            # 填入中文
            font_size = max(8.0, min(22.0, box_h * 0.78))
            target_page.insert_textbox(
                rect,
                trans_text,
                fontname="china-s",
                fontsize=font_size,
                color=(0.1, 0.1, 0.1),
                align=1
            )
        return True

    def stitch_side_by_side_pdf(
        self,
        original_pdf_path: str,
        translated_pdf_path: str,
        output_pdf_path: str
    ):
        """
        核心算法：左右并排拼接 PDF
        左半侧：原版矢量页面（包含原版图形与英文）
        中间：高质感分割中线
        右半侧：原版矢量页面（包含完全相同的图形、底色与原位替换的中文！）
        """
        orig_doc = fitz.open(original_pdf_path)
        trans_doc = fitz.open(translated_pdf_path)
        merged_doc = fitz.open()

        total_pages = min(len(orig_doc), len(trans_doc))
        for i in range(total_pages):
            p_orig = orig_doc[i]
            p_trans = trans_doc[i]

            w_orig, h_orig = p_orig.rect.width, p_orig.rect.height
            w_trans, h_trans = p_trans.rect.width, p_trans.rect.height

            target_w = w_orig + w_trans
            target_h = max(h_orig, h_trans)
            merged_page = merged_doc.new_page(width=target_w, height=target_h)

            # 1. 绘制左侧原版
            merged_page.show_pdf_page(fitz.Rect(0, 0, w_orig, h_orig), orig_doc, i)

            # 2. 绘制中缝分割线
            shape = merged_page.new_shape()
            shape.draw_line(fitz.Point(w_orig, 0), fitz.Point(w_orig, target_h))
            shape.finish(color=(0.82, 0.85, 0.90), width=1.5)
            shape.commit()

            # 3. 绘制右侧高保真排版中文版
            merged_page.show_pdf_page(fitz.Rect(w_orig, 0, target_w, h_trans), trans_doc, i)

        merged_doc.save(output_pdf_path, garbage=4, deflate=True)
        orig_doc.close()
        trans_doc.close()
        merged_doc.close()

    async def translate_pdf(
        self,
        input_pdf_path: str,
        output_dir: str,
        task_id: str,
        model: str = "qwen3.8-flash",
        mode: str = "courseware",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        执行高保真 PDF 双语对照翻译流水线
        """
        out_path = Path(output_dir)
        preview_dir = out_path / "previews" / task_id
        preview_dir.mkdir(parents=True, exist_ok=True)

        orig_doc = fitz.open(input_pdf_path)
        total_pages = len(orig_doc)

        trans_doc = fitz.open()
        page_results = []

        for page_idx in range(total_pages):
            orig_page = orig_doc[page_idx]

            # 1. 克隆原版第 page_idx 页到翻译文档（所有图像、线条、背景 100% 完整保留）
            trans_doc.insert_pdf(orig_doc, from_page=page_idx, to_page=page_idx)
            trans_page = trans_doc[page_idx]

            # 2. 渲染原版页面高清缩略图 (用于 Web 端双栏对比与底色采样)
            pix_orig = orig_page.get_pixmap(dpi=150)
            orig_img_name = f"orig_page_{page_idx+1}.png"
            orig_img_path = str(preview_dir / orig_img_name)
            pix_orig.save(orig_img_path)
            orig_pil = Image.open(orig_img_path).convert("RGB")

            if progress_callback:
                await progress_callback({
                    "task_id": task_id,
                    "stage": "translating",
                    "current_page": page_idx + 1,
                    "total_pages": total_pages,
                    "percent": int(((page_idx) / total_pages) * 85),
                    "message": f"正在高保真翻译第 {page_idx + 1}/{total_pages} 页图文与插图..."
                })

            # 3. 提取原页面的文本块
            blocks = self._extract_page_text_blocks(orig_page)
            full_orig_text = "\n\n".join([b["text"] for b in blocks])

            # 双轨智能策略：
            # 轨道 A：页面具备可选文本块（标准课件/论文）
            if blocks and len(full_orig_text.strip()) >= 20:
                translated_blocks = await self._translate_page_blocks(
                    blocks=blocks,
                    model=model,
                    mode=mode
                )
                full_trans_text = "\n\n".join(translated_blocks)
                self._apply_in_place_translations(trans_page, blocks, translated_blocks)

                # 深入检查页面中是否有内嵌插图/架构图（例如尺寸大于 70x50 的图片块）
                try:
                    image_infos = orig_page.get_image_info(xrefs=True)
                    diag_notes = []
                    for img_info in image_infos:
                        bbox = fitz.Rect(img_info.get("bbox", [0, 0, 0, 0]))
                        if bbox.width >= 70 and bbox.height >= 50:
                            # 提取插图区域的像素图像
                            clip_pix = orig_page.get_pixmap(clip=bbox, dpi=150)
                            diagram_items = await self._vision_translate_diagram_clip(
                                clip_pix.tobytes("png"),
                                model=model
                            )
                            if diagram_items:
                                self._apply_diagram_translations(
                                    trans_page,
                                    orig_pil,
                                    bbox,
                                    diagram_items
                                )
                                for it in diagram_items:
                                    diag_notes.append(f"【图表译文】{it['text']} → {it['translation']}")

                    if diag_notes:
                        full_trans_text += "\n\n" + "\n".join(diag_notes)
                except Exception:
                    pass

            # 轨道 B：纯图表/扫描件页面（字数少或无矢量文本）
            else:
                parsed_vision = await self._vision_translate_page_boxes(orig_img_path, model=model)
                v_items = parsed_vision.get("items", [])
                if v_items:
                    self._apply_vision_page_translations(trans_page, orig_pil, v_items)
                    full_trans_text = parsed_vision.get("summary", "纯图表/扫描页面视觉精翻")
                    details = [f"- {it['text']} → {it['translation']}" for it in v_items]
                    full_trans_text += "\n\n" + "\n".join(details)
                else:
                    full_trans_text = "（本页包含复杂图表或图形）"

            # 4. 渲染中文翻译页面的高清缩略图 (与原版完全一样的排版结构！)
            pix_trans = trans_page.get_pixmap(dpi=150)
            trans_img_name = f"trans_page_{page_idx+1}.png"
            trans_img_path = str(preview_dir / trans_img_name)
            pix_trans.save(trans_img_path)

            page_results.append({
                "page": page_idx + 1,
                "orig_text": full_orig_text or "（原版纯图表/图片页面）",
                "trans_text": full_trans_text,
                "orig_img": f"/outputs/previews/{task_id}/{orig_img_name}",
                "trans_img": f"/outputs/previews/{task_id}/{trans_img_name}",
            })

        # 保存纯中文版 PDF
        pure_trans_pdf_path = str(out_path / f"{task_id}_chinese_only.pdf")
        trans_doc.save(pure_trans_pdf_path, garbage=4, deflate=True)
        trans_doc.close()
        orig_doc.close()

        # 5. 核心无损拼接：左右并排生成最终对照 PDF
        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "stitching",
                "current_page": total_pages,
                "total_pages": total_pages,
                "percent": 95,
                "message": "正在无损合并生成左右双栏对照 PDF..."
            })

        side_by_side_pdf_path = str(out_path / f"{task_id}_bilingual_side_by_side.pdf")
        self.stitch_side_by_side_pdf(
            original_pdf_path=input_pdf_path,
            translated_pdf_path=pure_trans_pdf_path,
            output_pdf_path=side_by_side_pdf_path
        )

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "completed",
                "current_page": total_pages,
                "total_pages": total_pages,
                "percent": 100,
                "message": "高保真图文对照翻译已完成！"
            })

        return {
            "task_id": task_id,
            "total_pages": total_pages,
            "side_by_side_pdf": f"/outputs/{task_id}_bilingual_side_by_side.pdf",
            "pure_trans_pdf": f"/outputs/{task_id}_chinese_only.pdf",
            "pages": page_results,
        }
