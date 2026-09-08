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
    图片与文档截图高保真双语对照翻译引擎
    核心设计：
    1. 坚决摒弃“在原图上画实体色块膏药贴（画框遮挡）”的粗糙做法；
    2. 左侧完整呈现 100% 原始高清截图（无任何涂抹或遮盖）；
    3. 右侧 1:1 生成媲美原版 PPT 设计的高清结构化中文对照视读画板；
    4. 针对图表中的各模块、流程节点与正文要点生成大字号、清晰美观的中文卡片；
    5. 使用 PyMuPDF 内置 china-s CJK 字体，彻底杜绝 Linux/Docker 云端乱码。
    """

    def __init__(self, qwen_client: QwenClient):
        """
        初始化图片翻译器
        :param qwen_client: 通义千问客户端
        """
        self.client = qwen_client

    async def _vision_translate_structured(self, image_path: str, model: str = "qwen3.8-flash") -> Dict[str, Any]:
        """
        调用视觉多模态大模型，深度解析图像中的标题、架构图/流程图模块与正文要点
        """
        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        ext = Path(image_path).suffix.lower().lstrip(".")
        mime = f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else ext}"
        data_url = f"data:{mime};base64,{b64_data}"

        chosen_model = model if model in ["qwen3.8-flash", "qwen-vl-max", "qwen3.8-max", "qwen3.7-flash"] else "qwen3.8-flash"

        prompt = (
            "你是一个顶级的学术课件与技术图表双语翻译专家。请识别并翻译此课件/论文截图中的全部内容。\n"
            "请以严格的 JSON 格式输出，字段如下：\n"
            "{\n"
            '  "title": "页面主标题的专业中文翻译（若无则根据内容提炼简明标题）",\n'
            '  "subtitle": "副标题、章节标识或所属模块（无则填空字符串）",\n'
            '  "modules": [\n'
            '    {\n'
            '      "title_zh": "图表中某方框/节点的中文译名",\n'
            '      "title_en": "英文原名",\n'
            '      "desc": "该节点或模块的核心功能、含义或对应数据说明"\n'
            "    }\n"
            "  ],\n"
            '  "points": [\n'
            '    "正文段落要点1或流程说明1",\n'
            '    "正文段落要点2或流程说明2"\n'
            "  ]\n"
            "}\n"
            "要求：\n"
            "1. 专业术语使用业界权威中文译名，公式与代码原样保留；\n"
            "2. 仅输出合法的 JSON 字符串，切勿包含任何引言或 Markdown 外部注释。"
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

        # 正则提取 JSON
        match = re.search(r"(\{.*\})", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

        # 容错降级纯文本
        return {
            "title": "课件与图表双语精翻",
            "subtitle": "",
            "modules": [],
            "points": [content] if content else ["（已完成识别翻译）"]
        }

    def _render_structured_slide_canvas(
        self,
        data: Dict[str, Any],
        width: float,
        height: float,
        output_img_path: str
    ):
        """
        生成 1:1 媲美原版设计的专业高清中文课件视读画板，
        字号大、排版美观、层次分明，绝不使用画框遮挡
        """
        doc = fitz.open()
        page = doc.new_page(width=width, height=height)

        # 1. 绘制全局背景（优雅浅灰蓝科技底色）
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(0, 0, width, height))
        shape.finish(fill=(0.965, 0.975, 0.995))

        # 2. 绘制顶部大标题横幅（白色底条 + 极细下分割线）
        header_h = max(55.0, min(85.0, height * 0.14))
        shape.draw_rect(fitz.Rect(0, 0, width, header_h))
        shape.finish(fill=(1.0, 1.0, 1.0))
        shape.draw_line(fitz.Point(0, header_h), fitz.Point(width, header_h))
        shape.finish(color=(0.84, 0.88, 0.93), width=1.0)
        shape.commit()

        # 主标题文本
        main_title = data.get("title", "双语课件与图表对照精读").strip()
        subtitle = data.get("subtitle", "").strip()
        title_font_size = max(15.0, min(24.0, header_h * 0.38))

        if subtitle:
            page.insert_textbox(
                fitz.Rect(35.0, 10.0, width - 35.0, header_h * 0.62),
                main_title,
                fontname="china-s",
                fontsize=title_font_size,
                color=(0.08, 0.18, 0.42),
                align=0
            )
            page.insert_textbox(
                fitz.Rect(35.0, header_h * 0.62, width - 35.0, header_h - 6.0),
                subtitle,
                fontname="china-s",
                fontsize=max(9.0, title_font_size * 0.55),
                color=(0.4, 0.45, 0.55),
                align=0
            )
        else:
            page.insert_textbox(
                fitz.Rect(35.0, (header_h - title_font_size) / 2.0 - 2.0, width - 35.0, header_h - 8.0),
                main_title,
                fontname="china-s",
                fontsize=title_font_size,
                color=(0.08, 0.18, 0.42),
                align=0
            )

        # 3. 布局正文区域
        content_top = header_h + 16.0
        content_bottom = height - 16.0
        content_h = content_bottom - content_top
        margin_x = 35.0
        available_w = width - margin_x * 2.0

        modules = data.get("modules", [])
        points = data.get("points", [])

        # 分支 A：包含图表/架构图模块
        if modules:
            # 模块卡片区域分配 55% 高度，要点区域分配 40% 高度
            mod_area_h = content_h * 0.54
            points_area_top = content_top + mod_area_h + 12.0
            points_area_h = content_bottom - points_area_top

            # 计算模块卡片排布
            num_mods = len(modules)
            cols = min(num_mods, 3) if num_mods <= 4 else 3
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

                # 绘制卡片白底与精致边框
                s = page.new_shape()
                s.draw_rect(fitz.Rect(x0, y0, x1, y1))
                s.finish(fill=(1.0, 1.0, 1.0), color=(0.78, 0.84, 0.92), width=1.2)
                # 顶部微蓝标头底色
                header_box_h = min(32.0, card_h * 0.35)
                s.draw_rect(fitz.Rect(x0, y0, x1, y0 + header_box_h))
                s.finish(fill=(0.92, 0.95, 1.0))
                s.commit()

                # 模块标题（中文加粗感 + 英文原名）
                zh_title = mod.get("title_zh", "").strip()
                en_title = mod.get("title_en", "").strip()
                mod_title_size = max(10.0, min(14.0, card_h * 0.16))

                header_text = f"{zh_title}"
                if en_title and len(header_text) < 18:
                    header_text += f" ({en_title})"

                page.insert_textbox(
                    fitz.Rect(x0 + 8.0, y0 + 5.0, x1 - 8.0, y0 + header_box_h),
                    header_text,
                    fontname="china-s",
                    fontsize=mod_title_size,
                    color=(0.1, 0.22, 0.55),
                    align=0
                )

                # 模块功能解析正文
                desc = mod.get("desc", "").strip()
                if desc:
                    page.insert_textbox(
                        fitz.Rect(x0 + 10.0, y0 + header_box_h + 6.0, x1 - 10.0, y1 - 6.0),
                        desc,
                        fontname="china-s",
                        fontsize=max(8.5, min(11.5, card_h * 0.13)),
                        color=(0.2, 0.25, 0.35),
                        align=0
                    )

            # 绘制底部核心要点卡片
            if points:
                sp = page.new_shape()
                sp.draw_rect(fitz.Rect(margin_x, points_area_top, width - margin_x, content_bottom))
                sp.finish(fill=(1.0, 1.0, 1.0), color=(0.82, 0.86, 0.92), width=1.0)
                sp.commit()

                # 要点卡片标题
                page.insert_textbox(
                    fitz.Rect(margin_x + 16.0, points_area_top + 10.0, width - margin_x - 16.0, points_area_top + 32.0),
                    "📌 核心技术要点与图表原理解析",
                    fontname="china-s",
                    fontsize=max(11.0, min(14.0, points_area_h * 0.16)),
                    color=(0.12, 0.22, 0.5)
                )

                # 要点内容
                points_text = "\n".join([f"•  {p}" for p in points if p.strip()])
                page.insert_textbox(
                    fitz.Rect(margin_x + 18.0, points_area_top + 35.0, width - margin_x - 18.0, content_bottom - 8.0),
                    points_text,
                    fontname="china-s",
                    fontsize=max(9.0, min(12.5, points_area_h * 0.12)),
                    color=(0.2, 0.2, 0.25),
                    align=0
                )

        # 分支 B：纯文本/论文段落型截图（无独立模块）
        else:
            s_full = page.new_shape()
            s_full.draw_rect(fitz.Rect(margin_x, content_top, width - margin_x, content_bottom))
            s_full.finish(fill=(1.0, 1.0, 1.0), color=(0.82, 0.86, 0.92), width=1.0)
            s_full.commit()

            page.insert_textbox(
                fitz.Rect(margin_x + 20.0, content_top + 14.0, width - margin_x - 20.0, content_top + 40.0),
                "📝 课件/论文正文专业对照精译",
                fontname="china-s",
                fontsize=max(12.0, min(16.0, content_h * 0.05)),
                color=(0.12, 0.22, 0.5)
            )

            full_text = "\n\n".join([p for p in points if p.strip()])
            page.insert_textbox(
                fitz.Rect(margin_x + 22.0, content_top + 48.0, width - margin_x - 22.0, content_bottom - 16.0),
                full_text,
                fontname="china-s",
                fontsize=max(10.5, min(14.5, content_h * 0.038)),
                color=(0.15, 0.18, 0.22),
                align=0
            )

        # 导出高清预览图
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
        执行图片截图翻译流水线，生成左原版·右高清专业中文画板的双语对照大图与 PDF
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
                "message": f"正在使用 {model} 进行多模态视觉图表深度识别与精翻..."
            })

        # 1. 结构化大模型视觉精翻
        data = await self._vision_translate_structured(input_image_path, model=model)

        if progress_callback:
            await progress_callback({
                "task_id": task_id,
                "stage": "stitching",
                "current_page": 1,
                "total_pages": 1,
                "percent": 65,
                "message": "正在生成 1:1 高清专业排版中文视读画板..."
            })

        orig_pil = Image.open(input_image_path).convert("RGB")
        w_px, h_px = orig_pil.size

        # 将点位画板比例设置为与原图 1:1
        w_pt = max(600.0, float(w_px) * 72.0 / 150.0)
        h_pt = max(400.0, float(h_px) * 72.0 / 150.0)

        trans_img_path = str(preview_dir / "trans_page_1.png")
        self._render_structured_slide_canvas(
            data=data,
            width=w_pt,
            height=h_pt,
            output_img_path=trans_img_path
        )

        # 2. 保存原图清晰预览
        orig_img_preview = str(preview_dir / "orig_page_1.png")
        orig_pil.save(orig_img_preview)

        # 3. 左右高清无损并排拼接 (左原版 · 右中文版)
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

        # 4. 生成左右并排双语对照 PDF
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
                "message": "高清双语对照已生成完毕！"
            })

        # 组合文本展示说明
        summary_lines = [f"【页面主题】：{data.get('title', '')}"]
        if data.get("subtitle"):
            summary_lines.append(f"【副标题】：{data.get('subtitle')}")
        if data.get("modules"):
            summary_lines.append("\n【架构与图表模块对照】：")
            for m in data.get("modules"):
                summary_lines.append(f"• {m.get('title_zh')} ({m.get('title_en')}): {m.get('desc')}")
        if data.get("points"):
            summary_lines.append("\n【核心要点与说明】：")
            for p in data.get("points"):
                summary_lines.append(f"- {p}")

        full_trans_summary = "\n".join(summary_lines)

        return {
            "task_id": task_id,
            "total_pages": 1,
            "side_by_side_pdf": f"/outputs/{task_id}_bilingual_side_by_side.pdf",
            "side_by_side_img": f"/outputs/{task_id}_bilingual.png",
            "pages": [{
                "page": 1,
                "orig_text": "（原版清晰截图）",
                "trans_text": full_trans_summary,
                "orig_img": f"/outputs/previews/{task_id}/orig_page_1.png",
                "trans_img": f"/outputs/previews/{task_id}/trans_page_1.png",
            }],
        }
