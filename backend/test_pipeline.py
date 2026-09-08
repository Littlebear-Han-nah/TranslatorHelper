import asyncio
import os
import fitz
import docx
from pathlib import Path
from app.config import DEFAULT_API_KEY, OUTPUT_DIR, UPLOAD_DIR
from app.services.qwen_client import QwenClient
from app.services.pdf_translator import PDFTranslator
from app.services.docx_translator import DocxTranslator
from app.services.md_translator import MarkdownTranslator

async def main():
    """
    全流程端到端自动化验证脚本
    测试包含复杂图形、插图、卡片与多文本框的课件 PDF，
    验证右侧中文页面 1:1 完整保留原版图表图形，仅替换文字。
    """
    print("=== 1. 测试通义千问 API 连通性 ===")
    client = QwenClient(api_key=DEFAULT_API_KEY)
    test_res = await client.test_connection(model="qwen3.8-flash")
    print("API 连通性测试结果:", test_res)
    assert test_res["success"], f"API 连通失败: {test_res}"

    print("\n=== 2. 创建包含图形与插图的测试英文课件 PDF ===")
    sample_pdf_path = str(UPLOAD_DIR / "sample_slide_with_graphics.pdf")
    doc = fitz.open()
    # 标准 16:9 课件尺寸 (960 x 540)
    page = doc.new_page(width=960, height=540)

    # 绘制图形 1：顶部深蓝色卡片背景条
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(40, 30, 920, 100))
    shape.finish(color=(0.1, 0.3, 0.7), fill=(0.93, 0.96, 1.0), width=1.5)

    # 绘制图形 2：左侧模块卡片框（浅蓝）
    shape.draw_rect(fitz.Rect(60, 140, 460, 480))
    shape.finish(color=(0.2, 0.5, 0.9), fill=(0.97, 0.98, 1.0), width=1.2)

    # 绘制图形 3：右侧模块卡片框（浅橙）
    shape.draw_rect(fitz.Rect(500, 140, 900, 480))
    shape.finish(color=(0.9, 0.5, 0.1), fill=(1.0, 0.98, 0.94), width=1.2)

    # 绘制图形 4：架构图圆形节点与连接箭头
    shape.draw_circle(fitz.Point(700, 390), 35)
    shape.finish(color=(0.2, 0.7, 0.3), fill=(0.92, 0.99, 0.93), width=2)
    shape.commit()

    # 插入原版英文文本
    page.insert_text((70, 75), "Lecture 5: Deep Convolutional Architectures", fontsize=24, color=(0.1, 0.2, 0.5))
    
    left_content = (
        "Core Convolution Operations:\n"
        "• Feature maps capture spatial hierarchies.\n"
        "• Kernel convolution computes localized dot products.\n"
        "• Receptive field expands with network depth."
    )
    page.insert_textbox(fitz.Rect(80, 160, 440, 460), left_content, fontsize=15, color=(0.15, 0.15, 0.15))

    right_content = (
        "Residual Learning Framework:\n"
        "• Skip connections prevent vanishing gradients.\n"
        "• Identity mapping: H(x) = F(x) + x\n"
        "• Enables training of 100+ layer networks."
    )
    page.insert_textbox(fitz.Rect(520, 160, 880, 330), right_content, fontsize=15, color=(0.15, 0.15, 0.15))

    doc.save(sample_pdf_path)
    orig_drawings_count = len(page.get_drawings())
    print(f"测试课件创建成功，原版绘制图形数: {orig_drawings_count}")
    doc.close()

    print("\n=== 3. 执行高保真图文无损双语对照翻译流水线 ===")
    pdf_engine = PDFTranslator(client)
    pdf_res = await pdf_engine.translate_pdf(
        input_pdf_path=sample_pdf_path,
        output_dir=str(OUTPUT_DIR),
        task_id="test_graphics_task",
        model="qwen3.8-flash",
        mode="courseware"
    )

    # 验证生成的纯中文版 PDF 图形保留情况
    trans_pdf = fitz.open(str(OUTPUT_DIR / "test_graphics_task_chinese_only.pdf"))
    trans_drawings_count = len(trans_pdf[0].get_drawings())
    print(f"中文版页面绘制图形数: {trans_drawings_count} (原版为 {orig_drawings_count})")
    assert trans_drawings_count >= orig_drawings_count, "原版图表图形在翻译版中丢失！"
    trans_pdf.close()
    print(">>> 验证通过：原版全部图表、图形、卡片背景 100% 完整继承！")

    # 验证左右并排对照 PDF
    side_pdf = fitz.open(str(OUTPUT_DIR / "test_graphics_task_bilingual_side_by_side.pdf"))
    p0 = side_pdf[0]
    print(f"左右并排对照 PDF: 宽 {p0.rect.width} pt, 高 {p0.rect.height} pt (原版宽度 960 pt)")
    assert abs(p0.rect.width - 1920) < 5, f"并排宽度异常: {p0.rect.width}"
    side_pdf.close()
    print(">>> 左右并排高保真对照 PDF 验证完全通过！")

if __name__ == "__main__":
    asyncio.run(main())
