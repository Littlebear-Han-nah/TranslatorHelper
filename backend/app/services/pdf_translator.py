import fitz  # PyMuPDF 核心库
import os
import re
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List, Tuple
from .qwen_client import QwenClient
from ..utils.font_helper import get_chinese_font_name

class PDFTranslator:
    """
    PDF 课件与学术论文高保真双语对照翻译引擎
    核心能力：
    1. 1:1 原版图文画板克隆：100% 完整保留原版课件/论文中的所有图片、插图、矢量图表、流程图线条、几何卡片与底色；
    2. 精准坐标提取与原地文字擦除：精准定位每个英文文字块，无损擦除英文内容；
    3. 自适应字号原位中文填入：在原坐标区域内自适应匹配字号与原版字体颜色填入中文；
    4. 左右双栏无损拼接：左原版图文英文，右原版图文中文，生成顶级双语对照 PDF；
    5. 高清预览图逐页生成，供网页端无缝双栏精读。
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
            # 采样矩形左上角稍靠外或区域内的像素
            x = max(1.0, min(page.rect.width - 3.0, rect.x0 - 2.0))
            y = max(1.0, min(page.rect.height - 3.0, rect.y0 - 2.0))
            pix = page.get_pixmap(clip=fitz.Rect(x, y, x + 2.0, y + 2.0))
            if pix.width > 0 and pix.height > 0:
                pixel = pix.pixel(0, 0)
                return (pixel[0] / 255.0, pixel[1] / 255.0, pixel[2] / 255.0)
        except Exception:
            pass
        return (1.0, 1.0, 1.0)  # 默认纯白背景

    def _extract_page_text_blocks(self, page: fitz.Page) -> List[Dict[str, Any]]:
        """
        细粒度提取当前页面的所有文本块，包括外接矩形、文本内容、建议字号与文字颜色
        """
        text_dict = page.get_text("dict")
        extracted_blocks = []

        for b in text_dict.get("blocks", []):
            if b.get("type") != 0:  # 0 为文本块，1 为图像块（图像块自动原样保留）
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
                        # RGB 颜色解析
                        r = ((c >> 16) & 255) / 255.0
                        g = ((c >> 8) & 255) / 255.0
                        b_col = (c & 255) / 255.0
                        spans_colors.append((r, g, b_col))
                block_text += "\n"

            clean_text = block_text.strip()
            if not clean_text:
                continue

            # 计算主导字号与主导颜色
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
        使用带标签的分块机制，既保证学术上下文连贯，又能精确映射回原坐标
        """
        if not blocks:
            return []

        # 构建结构化分块 Prompt
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

        # 正则解析带编号的翻译结果
        result_map: Dict[int, str] = {}
        pattern = re.compile(r"\[(\d+)\]\s*(.*?)(?=\[\d+\]|\Z)", re.DOTALL)
        matches = pattern.findall(translated_reply)

        for num_str, content in matches:
            try:
                num = int(num_str)
                result_map[num] = content.strip()
            except ValueError:
                continue

        # 整理输出，若大模型偶发遗漏某个编号则使用原文作为兜底保障
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
        font_name = get_chinese_font_name()

        # 步骤 1：添加擦除区域并执行擦除（此时原版页面中的图形、图像完全不受影响）
        for blk in blocks:
            r = blk["bbox"]
            bg_color = self._sample_background_color(target_page, r)
            target_page.add_redact_annot(r, fill=bg_color)

        target_page.apply_redactions()

        # 步骤 2：在原位置写入翻译后的中文
        for blk, trans_text in zip(blocks, translations):
            if not trans_text.strip():
                continue

            orig_rect = blk["bbox"]
            orig_size = blk["size"]
            orig_color = blk["color"]

            # 为了更好地适应中文字符，适当将右侧边距略微拓宽 3%~5%（若未越界）
            extended_w = min(target_page.rect.width - orig_rect.x0 - 5.0, orig_rect.width * 1.05)
            fit_rect = fitz.Rect(orig_rect.x0, orig_rect.y0, orig_rect.x0 + extended_w, orig_rect.y1)

            # 自适应动态字号计算：从原字号的 100% 逐渐微调至 70%，直到文字完全填入
            inserted = False
            for scale in [1.0, 0.92, 0.85, 0.78, 0.72]:
                try_size = max(8.0, orig_size * scale)
                rc = target_page.insert_textbox(
                    fit_rect,
                    trans_text,
                    fontname="china-s",
                    fontsize=try_size,
                    color=orig_color,
                    align=0  # 左对齐
                )
                if rc >= 0:
                    inserted = True
                    break

            # 若仍超出则以最小字号强行写入
            if not inserted:
                target_page.insert_textbox(
                    fit_rect,
                    trans_text,
                    fontname="china-s",
                    fontsize=max(7.5, orig_size * 0.7),
                    color=orig_color,
                    align=0
                )

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

            # 新建宽度为原版两倍的画板
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

        # 创建用于存放中文翻译的全新 PDF 文档（通过克隆每一页来保留全部图像和几何图形）
        trans_doc = fitz.open()
        page_results = []

        for page_idx in range(total_pages):
            orig_page = orig_doc[page_idx]

            # 1. 克隆原版第 page_idx 页到翻译文档（所有图像、线条、背景 100% 完整保留）
            trans_doc.insert_pdf(orig_doc, from_page=page_idx, to_page=page_idx)
            trans_page = trans_doc[page_idx]

            # 2. 渲染原版页面高清缩略图 (用于 Web 端双栏对比)
            pix_orig = orig_page.get_pixmap(dpi=150)
            orig_img_name = f"orig_page_{page_idx+1}.png"
            orig_img_path = str(preview_dir / orig_img_name)
            pix_orig.save(orig_img_path)

            # 进度回调通知
            if progress_callback:
                await progress_callback({
                    "task_id": task_id,
                    "stage": "translating",
                    "current_page": page_idx + 1,
                    "total_pages": total_pages,
                    "percent": int(((page_idx) / total_pages) * 85),
                    "message": f"正在使用 {model} 进行第 {page_idx + 1}/{total_pages} 页高保真图文对照翻译..."
                })

            # 3. 提取原页面的文本块
            blocks = self._extract_page_text_blocks(orig_page)
            full_orig_text = "\n\n".join([b["text"] for b in blocks])

            if blocks:
                # 4. 调用通义千问进行整页结构化翻译
                translated_blocks = await self._translate_page_blocks(
                    blocks=blocks,
                    model=model,
                    mode=mode
                )
                full_trans_text = "\n\n".join(translated_blocks)

                # 5. 原位替换克隆页面上的文字（擦除原英文，自适应填入中文）
                self._apply_in_place_translations(trans_page, blocks, translated_blocks)
            else:
                full_trans_text = "（本页主要包含图表或无可选文本）"

            # 6. 渲染中文翻译页面的高清缩略图 (与原版完全一样的排版结构！)
            pix_trans = trans_page.get_pixmap(dpi=150)
            trans_img_name = f"trans_page_{page_idx+1}.png"
            trans_img_path = str(preview_dir / trans_img_name)
            pix_trans.save(trans_img_path)

            page_results.append({
                "page": page_idx + 1,
                "orig_text": full_orig_text,
                "trans_text": full_trans_text,
                "orig_img": f"/outputs/previews/{task_id}/{orig_img_name}",
                "trans_img": f"/outputs/previews/{task_id}/{trans_img_name}",
            })

        # 保存纯中文版 PDF
        pure_trans_pdf_path = str(out_path / f"{task_id}_chinese_only.pdf")
        trans_doc.save(pure_trans_pdf_path, garbage=4, deflate=True)
        trans_doc.close()
        orig_doc.close()

        # 7. 核心无损拼接：左右并排生成最终对照 PDF
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
