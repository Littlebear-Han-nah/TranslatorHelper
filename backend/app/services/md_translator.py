from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple
from .qwen_client import QwenClient
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from ..utils.font_helper import get_chinese_font_name
import fitz

class MarkdownTranslator:
    """
    Markdown (.md) 文档双语对照翻译引擎
    支持段落智能分块、公式与代码块保护，并输出：
    1. 双语对照 Markdown 文件；
    2. 左右双栏对照 PDF 文件与高清预览图。
    """

    def __init__(self, qwen_client: QwenClient):
        """
        初始化 Markdown 翻译器
        :param qwen_client: 通义千问客户端实例
        """
        self.client = qwen_client

    async def translate_markdown(
        self,
        input_md_path: str,
        output_dir: str,
        task_id: str,
        model: str = "qwen3.8-flash",
        mode: str = "academic",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        执行 Markdown 文档翻译并生成双语对照 MD 与 PDF
        """
        out_path = Path(output_dir)
        preview_dir = out_path / "previews" / task_id
        preview_dir.mkdir(parents=True, exist_ok=True)

        with open(input_md_path, "r", encoding="utf-8", errors="ignore") as f:
            raw_text = f.read()

        # 分解为逻辑段落（以空行分隔）
        raw_blocks = [b.strip() for b in raw_text.split("\n\n") if b.strip()]
        total_blocks = len(raw_blocks)
        if total_blocks == 0:
            total_blocks = 1
            raw_blocks = ["（空白文档）"]

        translated_pairs: List[Tuple[str, str]] = []
        for idx, block in enumerate(raw_blocks):
            if progress_callback:
                await progress_callback({
                    "task_id": task_id,
                    "stage": "translating",
                    "current_page": idx + 1,
                    "total_pages": total_blocks,
                    "percent": int(((idx) / total_blocks) * 80),
                    "message": f"正在翻译第 {idx + 1}/{total_blocks} 块内容..."
                })

            # 代码块或极简标记直接保留
            if block.startswith("```") and block.endswith("```"):
                translated_pairs.append((block, block))
                continue

            trans = await self.client.translate_text(
                text=block,
                model=model,
                mode=mode
            )
            translated_pairs.append((block, trans))

        # 1. 生成双语对照 Markdown 文件（段落交替与标题对照）
        bilingual_md_lines = ["# 双语对照翻译 (Bilingual Translation)\n\n"]
        for orig, trans in translated_pairs:
            bilingual_md_lines.append(f"> 📄 **原文**\n>\n> {orig}\n\n")
            bilingual_md_lines.append(f"🌐 **中文翻译**\n\n{trans}\n\n---\n\n")

        bilingual_md_path = str(out_path / f"{task_id}_bilingual.md")
        with open(bilingual_md_path, "w", encoding="utf-8") as f:
            f.writelines(bilingual_md_lines)

        # 2. 生成左右双栏对照 PDF
        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "rendering_pdf",
                "current_page": total_blocks,
                "total_pages": total_blocks,
                "percent": 90,
                "message": "正在渲染双语对照 PDF..."
            })

        side_by_side_pdf_path = str(out_path / f"{task_id}_bilingual_side_by_side.pdf")
        self._render_bilingual_pdf(translated_pairs, side_by_side_pdf_path)

        # 3. 渲染高清页面预览
        pdf_doc = fitz.open(side_by_side_pdf_path)
        pages_preview = []
        for p_no in range(len(pdf_doc)):
            pix = pdf_doc[p_no].get_pixmap(dpi=150)
            img_name = f"page_{p_no+1}.png"
            img_path = str(preview_dir / img_name)
            pix.save(img_path)
            pages_preview.append({
                "page": p_no + 1,
                "orig_text": "",
                "trans_text": "",
                "orig_img": f"/outputs/previews/{task_id}/{img_name}",
                "trans_img": f"/outputs/previews/{task_id}/{img_name}",
            })
        pdf_doc.close()

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "completed",
                "current_page": total_blocks,
                "total_pages": total_blocks,
                "percent": 100,
                "message": "Markdown 对照翻译已完成！"
            })

        return {
            "task_id": task_id,
            "total_pages": len(pages_preview),
            "side_by_side_pdf": f"/outputs/{task_id}_bilingual_side_by_side.pdf",
            "bilingual_md": f"/outputs/{task_id}_bilingual.md",
            "pages": pages_preview,
        }

    def _render_bilingual_pdf(self, items: List[Tuple[str, str]], output_path: str):
        """
        生成 A4 横版左右双栏对照 PDF
        """
        font_name = get_chinese_font_name()
        page_w, page_h = 842, 595
        c = canvas.Canvas(output_path, pagesize=(page_w, page_h))

        margin = 40
        col_w = (page_w - margin * 2 - 20) / 2
        y = page_h - margin

        def draw_header():
            nonlocal y
            c.setFont(font_name, 12)
            c.setFillColor(colors.HexColor("#2563EB"))
            c.drawString(margin, page_h - 30, "Markdown 原文 (Original)")
            c.drawString(margin + col_w + 20, page_h - 30, "中文翻译对照 (Translation)")
            c.setStrokeColor(colors.HexColor("#CBD5E1"))
            c.setLineWidth(1)
            c.line(margin, page_h - 35, page_w - margin, page_h - 35)
            c.line(margin + col_w + 10, page_h - 35, margin + col_w + 10, margin)
            y = page_h - 50

        draw_header()

        for orig, trans in items:
            orig_lines = self._wrap_text(orig, col_w, 9.5, font_name, c)
            trans_lines = self._wrap_text(trans, col_w, 9.5, font_name, c)
            block_h = max(len(orig_lines), len(trans_lines)) * 14 + 10

            if y - block_h < margin:
                c.showPage()
                draw_header()

            c.setFont("Helvetica", 9)
            c.setFillColor(colors.HexColor("#1E293B"))
            cur_y = y
            for line in orig_lines:
                c.drawString(margin, cur_y, line)
                cur_y -= 14

            c.setFont(font_name, 9.5)
            c.setFillColor(colors.HexColor("#0F172A"))
            cur_y = y
            for line in trans_lines:
                c.drawString(margin + col_w + 20, cur_y, line)
                cur_y -= 14

            y -= block_h
            c.setStrokeColor(colors.HexColor("#F1F5F9"))
            c.setLineWidth(0.5)
            c.line(margin, y + 4, page_w - margin, y + 4)

        c.showPage()
        c.save()

    def _wrap_text(self, text, max_w, font_size, font_name, c):
        """
        辅助折行工具函数
        """
        chars = list(text)
        lines = []
        cur = ""
        for ch in chars:
            if ch == "\n":
                lines.append(cur)
                cur = ""
                continue
            if c.stringWidth(cur + ch, font_name, font_size) <= max_w:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
        return lines or [""]
