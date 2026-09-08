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
    2. 无画框无痕文字替换：纯矢量级擦除原英文字形（不加任何实体色块遮挡），100% 保留背后的渐变与图形；
    3. 自适应字号清晰回填：依据原文字号与颜色自然填入中文，字号适中清晰，杜绝单字被挤压截断；
    4. 嵌入式图表多模态深度识别：提取图表与插图内各模块含义并在侧边对照栏中完整解析，绝不涂抹破坏原图；
    5. 纯图表/扫描件页面高清结构化重排：对无可选文本的扫描件，生成同尺寸专业高清中文视读画板；
    6. 左右双栏无损拼接：左原版图文英文，右原版图文中文，生成顶级双语对照 PDF；
    7. 高清预览图逐页生成，供网页端无缝双栏精读。
    """

    def __init__(self, qwen_client: QwenClient):
        """
        初始化 PDF 翻译器
        :param qwen_client: 通义千问客户端实例
        """
        self.client = qwen_client

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
            dom_color = spans_colors[0] if spans_colors else (0.12, 0.12, 0.12)

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
        在克隆的页面上执行无画框、纯矢量的自然原地替换：
        1. 绝不传入 fill 参数，利用 PyMuPDF 纯矢量移除原英文字形，消除所有遮盖框；
        2. 自适应计算合适字号，保证中文清晰、自然，绝不挤压成单字列。
        """
        # 1. 纯矢量移除英文字形（无画框遮挡，背景 100% 完整）
        for blk in blocks:
            r = blk["bbox"]
            target_page.add_redact_annot(r)

        target_page.apply_redactions()

        # 2. 自然填入中文
        page_w = target_page.rect.width
        page_h = target_page.rect.height

        for blk, trans_text in zip(blocks, translations):
            if not trans_text.strip():
                continue

            orig_rect = blk["bbox"]
            orig_size = blk["size"]
            orig_color = blk["color"]

            # 给中文自适应留足水平与垂直空间，避免单字强制换行
            fit_w = min(page_w - orig_rect.x0 - 8.0, max(orig_rect.width * 1.15, 120.0))
            fit_h = max(orig_rect.height * 1.25, orig_size * 1.6)
            fit_rect = fitz.Rect(
                orig_rect.x0,
                orig_rect.y0,
                orig_rect.x0 + fit_w,
                min(page_h - 6.0, orig_rect.y0 + fit_h)
            )

            # 字号微调：从原字号 100% 递减，保底不低于 10pt 保证清晰可读
            inserted = False
            for scale in [1.0, 0.95, 0.90, 0.85]:
                try_size = max(10.0, orig_size * scale)
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
                    fontsize=max(9.0, orig_size * 0.75),
                    color=orig_color,
                    align=0
                )

    async def _vision_translate_diagram(
        self,
        clip_png_bytes: bytes,
        model: str = "qwen3.8-flash"
    ) -> Dict[str, Any]:
        """
        针对页面内嵌的插图/架构图/流程图，调用多模态大模型提取图表内各模块含义与中文对照
        """
        b64_data = base64.b64encode(clip_png_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{b64_data}"

        chosen_model = model if model in ["qwen3.8-flash", "qwen-vl-max", "qwen3.8-max", "qwen3.7-flash"] else "qwen3.8-flash"
        prompt = (
            "请识别此插图/架构图中的所有英文模块、方框节点与箭头流转关系，"
            "将其准确翻译为专业学术中文。请以 JSON 格式输出：\n"
            "{\n"
            '  "diagram_title": "图表简明中文主题",\n'
            '  "elements": [\n'
            '    {"zh": "中文译名", "en": "英文原名", "desc": "功能或含义简述"}\n'
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
            match = re.search(r"(\{.*\})", content, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    async def _vision_translate_page(
        self,
        image_path: str,
        model: str = "qwen3.8-flash"
    ) -> str:
        """
        针对纯图片/扫描件课件页面，调用多模态大模型识别所有文字并翻译为中文。
        返回完整的自然中文翻译文本（而非结构化 JSON，避免解析失败导致空白内容）。
        """
        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        vl_models = {"qwen3.8-flash", "qwen-vl-max", "qwen3.8-max", "qwen3.7-flash", "qwen3.5-ocr"}
        chosen_model = model if model in vl_models else "qwen3.8-flash"

        prompt = (
            "你是顶级的学术课件与论文双语翻译专家。"
            "请仔细识别此图片中的所有文字内容（包括标题、正文、图例、注释和图表内的标签），"
            "并将全部英文翻译为专业、流畅的中文。\n\n"
            "输出要求：\n"
            "1. 按照原文的结构顺序（从标题到正文到注释）翻译所有内容；\n"
            "2. 图表中每个方框、节点、箭头旁的文字也必须翻译；\n"
            "3. 数学公式、代码原样保留，仅翻译周围的说明文字；\n"
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
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_data}"}}
                    ]
                }
            ],
            "temperature": 0.1
        }

        try:
            res = await self.client._raw_post_chat(payload)
            content = res["choices"][0]["message"].get("content", "").strip()
            if content:
                return content
        except Exception:
            pass

        # 备用：换 qwen-vl-max 再试一次
        try:
            payload["model"] = "qwen-vl-max"
            res = await self.client._raw_post_chat(payload)
            content = res["choices"][0]["message"].get("content", "").strip()
            if content:
                return content
        except Exception:
            pass

        return "（图片内容识别失败，请检查 API Key 与网络连接）"

    def _render_structured_page(self, target_page: fitz.Page, data: Dict[str, Any]):
        """
        为扫描件或纯图课件生成 1:1 媲美原版 PPT 设计的高清中文对照视读画板
        """
        w, h = target_page.rect.width, target_page.rect.height

        # 绘制背景
        shape = target_page.new_shape()
        shape.draw_rect(fitz.Rect(0, 0, w, h))
        shape.finish(fill=(0.965, 0.975, 0.995))

        # 顶部标题栏
        header_h = max(55.0, min(80.0, h * 0.14))
        shape.draw_rect(fitz.Rect(0, 0, w, header_h))
        shape.finish(fill=(1.0, 1.0, 1.0))
        shape.draw_line(fitz.Point(0, header_h), fitz.Point(w, header_h))
        shape.finish(color=(0.84, 0.88, 0.93), width=1.0)
        shape.commit()

        main_title = data.get("title", "双语对照精读").strip()
        target_page.insert_textbox(
            fitz.Rect(30.0, 12.0, w - 30.0, header_h - 10.0),
            main_title,
            fontname="china-s",
            fontsize=max(16.0, min(24.0, header_h * 0.38)),
            color=(0.08, 0.18, 0.42),
            align=0
        )

        content_top = header_h + 16.0
        content_bottom = h - 16.0
        content_h = content_bottom - content_top
        margin_x = 30.0
        available_w = w - margin_x * 2.0

        modules = data.get("modules", [])
        points = data.get("points", [])

        if modules:
            mod_area_h = content_h * 0.54
            points_area_top = content_top + mod_area_h + 12.0
            points_area_h = content_bottom - points_area_top

            num_mods = len(modules)
            cols = min(num_mods, 3)
            rows = (num_mods + cols - 1) // cols
            gap = 14.0
            card_w = (available_w - (cols - 1) * gap) / cols
            card_h = (mod_area_h - (rows - 1) * gap) / rows

            for idx, mod in enumerate(modules):
                r = idx // cols
                c = idx % cols
                x0 = margin_x + c * (card_w + gap)
                y0 = content_top + r * (card_h + gap)
                x1 = x0 + card_w
                y1 = y0 + card_h

                s = target_page.new_shape()
                s.draw_rect(fitz.Rect(x0, y0, x1, y1))
                s.finish(fill=(1.0, 1.0, 1.0), color=(0.78, 0.84, 0.92), width=1.2)
                header_box_h = min(30.0, card_h * 0.35)
                s.draw_rect(fitz.Rect(x0, y0, x1, y0 + header_box_h))
                s.finish(fill=(0.92, 0.95, 1.0))
                s.commit()

                zh_title = mod.get("title_zh", "").strip()
                en_title = mod.get("title_en", "").strip()
                header_text = f"{zh_title}"
                if en_title and len(header_text) < 18:
                    header_text += f" ({en_title})"

                target_page.insert_textbox(
                    fitz.Rect(x0 + 8.0, y0 + 5.0, x1 - 8.0, y0 + header_box_h),
                    header_text,
                    fontname="china-s",
                    fontsize=max(10.0, min(14.0, card_h * 0.16)),
                    color=(0.1, 0.22, 0.55),
                    align=0
                )

                desc = mod.get("desc", "").strip()
                if desc:
                    target_page.insert_textbox(
                        fitz.Rect(x0 + 10.0, y0 + header_box_h + 6.0, x1 - 10.0, y1 - 6.0),
                        desc,
                        fontname="china-s",
                        fontsize=max(8.5, min(11.5, card_h * 0.13)),
                        color=(0.2, 0.25, 0.35),
                        align=0
                    )

            if points:
                sp = target_page.new_shape()
                sp.draw_rect(fitz.Rect(margin_x, points_area_top, w - margin_x, content_bottom))
                sp.finish(fill=(1.0, 1.0, 1.0), color=(0.82, 0.86, 0.92), width=1.0)
                sp.commit()

                target_page.insert_textbox(
                    fitz.Rect(margin_x + 16.0, points_area_top + 10.0, w - margin_x - 16.0, points_area_top + 30.0),
                    "📌 核心技术要点与图表原理解析",
                    fontname="china-s",
                    fontsize=max(11.0, min(14.0, points_area_h * 0.16)),
                    color=(0.12, 0.22, 0.5)
                )

                points_text = "\n".join([f"•  {p}" for p in points if p.strip()])
                target_page.insert_textbox(
                    fitz.Rect(margin_x + 18.0, points_area_top + 33.0, w - margin_x - 18.0, content_bottom - 8.0),
                    points_text,
                    fontname="china-s",
                    fontsize=max(9.0, min(12.5, points_area_h * 0.12)),
                    color=(0.2, 0.2, 0.25),
                    align=0
                )
        else:
            s_full = target_page.new_shape()
            s_full.draw_rect(fitz.Rect(margin_x, content_top, w - margin_x, content_bottom))
            s_full.finish(fill=(1.0, 1.0, 1.0), color=(0.82, 0.86, 0.92), width=1.0)
            s_full.commit()

            target_page.insert_textbox(
                fitz.Rect(margin_x + 18.0, content_top + 12.0, w - margin_x - 18.0, content_top + 36.0),
                "📝 课件/论文正文专业对照精译",
                fontname="china-s",
                fontsize=max(12.0, min(16.0, content_h * 0.05)),
                color=(0.12, 0.22, 0.5)
            )

            full_text = "\n\n".join([p for p in points if p.strip()])
            target_page.insert_textbox(
                fitz.Rect(margin_x + 20.0, content_top + 42.0, w - margin_x - 20.0, content_bottom - 16.0),
                full_text,
                fontname="china-s",
                fontsize=max(10.5, min(14.5, content_h * 0.038)),
                color=(0.15, 0.18, 0.22),
                align=0
            )

    def _render_text_page(self, target_page: fitz.Page, translated_text: str):
        """
        将自然中文翻译文本渲染到目标页面（白底，字号适中，排版清晰）。
        用于轨道 B（扫描件/纯图页面）的翻译结果展示。
        :param target_page: 目标 PDF 页面（已创建）
        :param translated_text: 完整的中文翻译文本
        """
        w, h = target_page.rect.width, target_page.rect.height

        # 白底背景
        shape = target_page.new_shape()
        shape.draw_rect(fitz.Rect(0, 0, w, h))
        shape.finish(fill=(1.0, 1.0, 1.0))
        shape.commit()

        # 顶部浅蓝标题栏
        header_h = max(32.0, min(54.0, h * 0.09))
        sh = target_page.new_shape()
        sh.draw_rect(fitz.Rect(0, 0, w, header_h))
        sh.finish(fill=(0.90, 0.94, 1.0))
        sh.draw_line(fitz.Point(0, header_h), fitz.Point(w, header_h))
        sh.finish(color=(0.72, 0.82, 0.96), width=1.0)
        sh.commit()

        target_page.insert_textbox(
            fitz.Rect(18.0, 7.0, w - 18.0, header_h - 6.0),
            "中文翻译",
            fontname="china-s",
            fontsize=max(11.0, min(17.0, header_h * 0.40)),
            color=(0.08, 0.20, 0.52),
            align=0,
        )

        # 正文区域
        content_top = header_h + 12.0
        content_bottom = h - 12.0
        margin_x = 18.0
        body_font_size = max(10.0, min(14.0, w / 44.0))

        # 尝试插入，必要时缩小字号
        for scale in [1.0, 0.88, 0.76, 0.65]:
            rc = target_page.insert_textbox(
                fitz.Rect(margin_x, content_top, w - margin_x, content_bottom),
                translated_text,
                fontname="china-s",
                fontsize=max(9.0, body_font_size * scale),
                color=(0.06, 0.06, 0.08),
                align=0,
            )
            if rc >= 0:
                break

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
        右半侧：原版矢量页面（包含完全相同的图形、底色与无遮挡替换的中文！）
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

            # 1. 渲染原版页面高清缩略图 (用于 Web 端双栏对比)
            pix_orig = orig_page.get_pixmap(dpi=150)
            orig_img_name = f"orig_page_{page_idx+1}.png"
            orig_img_path = str(preview_dir / orig_img_name)
            pix_orig.save(orig_img_path)

            if progress_callback:
                await progress_callback({
                    "task_id": task_id,
                    "stage": "translating",
                    "current_page": page_idx + 1,
                    "total_pages": total_pages,
                    "percent": int(((page_idx) / total_pages) * 85),
                    "message": f"正在高保真翻译第 {page_idx + 1}/{total_pages} 页图文内容..."
                })

            # 2. 提取原页面的文本块
            blocks = self._extract_page_text_blocks(orig_page)
            full_orig_text = "\n\n".join([b["text"] for b in blocks])

            # 双轨策略：
            # 轨道 A：页面具备可选矢量文本块（标准课件与学术论文）
            if blocks and len(full_orig_text.strip()) >= 20:
                # 1:1 克隆原版画板
                trans_doc.insert_pdf(orig_doc, from_page=page_idx, to_page=page_idx)
                trans_page = trans_doc[page_idx]

                # 翻译整页文本块
                translated_blocks = await self._translate_page_blocks(
                    blocks=blocks,
                    model=model,
                    mode=mode
                )
                full_trans_text = "\n\n".join(translated_blocks)

                # 纯矢量无痕替换，杜绝任何实体画框遮盖
                self._apply_in_place_translations(trans_page, blocks, translated_blocks)

                # 若页面内包含嵌入式图表，进行多模态图表解析并补充于双语说明中
                try:
                    image_infos = orig_page.get_image_info(xrefs=True)
                    diag_notes = []
                    for img_info in image_infos:
                        bbox = fitz.Rect(img_info.get("bbox", [0, 0, 0, 0]))
                        if bbox.width >= 70 and bbox.height >= 50:
                            clip_pix = orig_page.get_pixmap(clip=bbox, dpi=150)
                            diag_data = await self._vision_translate_diagram(
                                clip_pix.tobytes("png"),
                                model=model
                            )
                            if diag_data and diag_data.get("elements"):
                                diag_title = diag_data.get("diagram_title", "内嵌图表架构解析")
                                diag_notes.append(f"\n【{diag_title}】：")
                                for el in diag_data["elements"]:
                                    diag_notes.append(f"• {el.get('zh')} ({el.get('en')}): {el.get('desc')}")

                    if diag_notes:
                        full_trans_text += "\n" + "\n".join(diag_notes)
                except Exception:
                    pass

            # 轨道 B：纯图表/扫描件页面（调用视觉大模型识别并翻译全部文字）
            else:
                full_trans_text = await self._vision_translate_page(orig_img_path, model=model)
                trans_page = trans_doc.new_page(width=orig_page.rect.width, height=orig_page.rect.height)
                self._render_text_page(trans_page, full_trans_text)

            # 3. 渲染中文翻译页面的高清缩略图
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

        # 4. 核心无损拼接：左右并排生成最终对照 PDF
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
