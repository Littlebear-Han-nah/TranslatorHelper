"""Geometry-first PDF replacement with preflight layout and explicit review fallbacks."""
import html
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
import pymupdf as fitz
from PIL import Image, ImageStat
from ..config import MAX_PAGES

@dataclass
class Block:
    id: str
    text: str
    bbox: list[float]
    size: float = 11
    color: int = 0
    bold: bool = False
    italic: bool = False
    kind: str = 'text'
    spans: list = field(default_factory=list)
    status: str = 'pending'
    translation: str = ''
    reason: str = ''
    confidence: float = 100
    line_height: float = 1.2

MATH_FONT = re.compile(r'CMSY|CMEX|CMMI|Math|Symbol|MTMI|MSAM|MSBM', re.I)
MATH_SYMBOL = re.compile(r'[∑∫√∂∏∇∈∉≤≥≈≠∞→↦⊗]')

def translatable(text):
    return bool(re.search(r'[A-Za-z]{2,}', text)) and not bool(re.fullmatch(r'[\s\d.,%+−–()\[\]/:=_-]+', text))

def _extract_blocks(page, table_rects=()):
    blocks = []
    for raw in page.get_text('dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
        if raw['type'] != 0:
            continue
        # Split mixed prose/math into line groups; never erase math as part of prose.
        groups, group = [], []
        raw_lines = raw['lines']
        grid = any(abs(a['bbox'][1]-b['bbox'][1]) < 2 and abs(a['bbox'][0]-b['bbox'][0]) > 20 for i,a in enumerate(raw_lines) for b in raw_lines[i+1:])
        for line in raw['lines']:
            spans = [s for s in line['spans'] if s['text'].strip() and not any(fitz.Rect(s['bbox']).intersects(r) for r in table_rects)]
            line = {**line, 'spans': spans}
            if not spans:
                continue
            text = ''.join(s['text'] for s in spans)
            protected = any(MATH_FONT.search(s['font']) or s['flags'] & 9 for s in spans) or bool(MATH_SYMBOL.search(text)) or ('=' in text and len(text.split()) < 18) or line.get('dir', (1, 0)) != (1, 0)
            if protected:
                if group: groups.append((group, False)); group = []
                groups.append(([line], True))
            else:
                # Split a line when runs have a large horizontal gap (common for tables).
                chunks, chunk = [], []
                for span in spans:
                    if chunk and span['bbox'][0] - chunk[-1]['bbox'][2] > max(14, span['size'] * 1.6):
                        chunks.append(chunk); chunk = []
                    chunk.append(span)
                chunks.append(chunk)
                if len(chunks) > 1:
                    if group: groups.append((group, False)); group = []
                    for chunk in chunks:
                        groups.append(([{'spans': chunk}], False))
                elif grid:
                    groups.append(([line], False))
                else:
                    group.append(line)
        if group: groups.append((group, False))
        for lines, protected in groups:
            spans = [s for line in lines for s in line['spans'] if s['text'].strip()]
            raw_lines = [''.join(s['text'] for s in line['spans']).strip() for line in lines]
            text = raw_lines[0] if raw_lines else ''
            for next_line in raw_lines[1:]:
                if re.match(r'^(?:[•●▪]|\d+[.)])\s', next_line):
                    text += '\n' + next_line
                elif text.endswith('-') and next_line[:1].islower():
                    text = text[:-1] + next_line
                else:
                    text += ' ' + next_line
            bbox = fitz.Rect(spans[0]['bbox'])
            for span in spans[1:]: bbox |= fitz.Rect(span['bbox'])
            largest = max(spans, key=lambda s: s['size'])
            b = Block(f'p{page.number+1}-b{len(blocks)+1}', text, list(bbox), largest['size'], largest['color'], bool(largest['flags'] & 16), bool(largest['flags'] & 2), spans=[list(s['bbox']) for s in spans])
            if grid: b.kind = 'table'
            if len(lines) > 1:
                delta = (lines[-1]['spans'][0]['bbox'][1] - lines[0]['spans'][0]['bbox'][1]) / (len(lines)-1)
                b.line_height = max(1.12, min(1.6, delta / b.size))
            if protected:
                b.status, b.kind, b.reason = 'review' if translatable(text) else 'preserved', 'protected', '公式、上标或旋转文字区域保留原样'
            elif not translatable(text):
                b.status, b.reason = 'preserved', '数字、符号或非英文区域'
            blocks.append(b)
    return blocks

def extract_blocks(page):
    cells, table_rects = [], []
    try:
        tables = page.find_tables().tables
    except (ValueError, RuntimeError):
        tables = []
    for table in tables:
        table_rects.append(fitz.Rect(table.bbox))
        for row in table.rows:
            for bounds in row.cells:
                if bounds is None: continue
                rect = fitz.Rect(bounds)
                raw = page.get_text('dict', clip=rect, flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
                spans = [span for block in raw['blocks'] if block['type'] == 0 for line in block['lines'] for span in line['spans'] if span['text'].strip()]
                if not spans: continue
                text = page.get_text('text', clip=rect).strip()
                largest = max(spans, key=lambda span: span['size'])
                inner = fitz.Rect(min(span['bbox'][0] for span in spans), min(span['bbox'][1] for span in spans), rect.x1-2, rect.y1-1)
                b = Block('', text, list(inner), largest['size'], largest['color'], bool(largest['flags'] & 16), kind='table', spans=[list(span['bbox']) for span in spans])
                if any(MATH_FONT.search(span['font']) or span['flags'] & 9 for span in spans) or MATH_SYMBOL.search(text) or '=' in text:
                    b.status, b.kind, b.reason = 'review' if translatable(text) else 'preserved', 'protected', '表格中的公式或代码保留原样'
                elif not translatable(text):
                    b.status, b.reason = 'preserved', '数字或符号单元格'
                cells.append(b)
    blocks = _extract_blocks(page, table_rects) + cells
    blocks.sort(key=lambda b: (round(b.bbox[1]/5), b.bbox[0]))
    # MuPDF sometimes returns one block per line. Rejoin only adjacent, aligned
    # prose with the same styling; table cells and protected regions stay separate.
    merged = []
    for b in blocks:
        previous = next((candidate for candidate in reversed(merged) if abs(candidate.bbox[0]-b.bbox[0]) < 2), None)
        gap = b.bbox[1]-previous.bbox[3] if previous else -1
        can_merge = (previous and previous.kind == b.kind == 'text' and previous.status == b.status == 'pending'
                     and abs(previous.bbox[0]-b.bbox[0]) < 2 and abs(previous.size-b.size) < .2
                     and previous.color == b.color and previous.bold == b.bold
                     and 0 <= gap <= b.size*.65 and len(previous.text) > 16
                     and not re.match(r'^(?:[•●▪]|\d+[.)])\s', b.text))
        if can_merge:
            previous.text = previous.text[:-1]+b.text if previous.text.endswith('-') and b.text[:1].islower() else previous.text+' '+b.text
            previous.line_height = max(previous.line_height, min(1.6, (b.bbox[1]-previous.spans[-1][1])/b.size))
            previous.bbox = list(fitz.Rect(previous.bbox) | fitz.Rect(b.bbox))
            previous.spans.extend(b.spans)
        else:
            merged.append(b)
    blocks = merged
    for index, b in enumerate(blocks): b.id = f'p{page.number+1}-b{index+1}'
    return blocks

def add_ocr(page, blocks):
    """仅在扫描版页面（原生文本极少）时使用 Tesseract OCR，原生电子文本充足时直接跳过。"""
    images = [fitz.Rect(item['bbox']) for item in page.get_image_info()]
    native_length = sum(len(b.text) for b in blocks)

    large_images = any(r.get_area() > page.rect.get_area() * .15 for r in images)
    # Selectable text elsewhere on the page does not rule out English inside
    # a screenshot or diagram occupying a substantial part of the page.
    if native_length >= 50 and len(blocks) >= 2 and not large_images:
        return blocks, []
    if native_length >= 20 and not large_images:
        return blocks, []
    if not images and native_length >= 20:
        return blocks, []
    if not shutil.which('tesseract'):
        if images or native_length < 20:
            return blocks, ['本页可能包含扫描文字；未安装 Tesseract，未识别部分保留原样。']
        return blocks, []
    import pytesseract
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    del pix  # 及时释放内存
    data = pytesseract.image_to_data(img, lang='eng', config='--psm 3', output_type=pytesseract.Output.DICT, timeout=90)
    groups = defaultdict(list)
    for i, text in enumerate(data['text']):
        if text.strip(): groups[(data['block_num'][i], data['par_num'][i], data['line_num'][i])].append(i)
    chunks = []
    for indices in groups.values():
        chunk = []
        for i in sorted(indices, key=lambda i: data['left'][i]):
            if chunk:
                last = chunk[-1]
                gap = data['left'][i] - data['left'][last] - data['width'][last]
                if gap > max(24, data['height'][i] * 2):
                    chunks.append(chunk); chunk = []
            chunk.append(i)
        if chunk: chunks.append(chunk)
    for indices in chunks:
        x0 = min(data['left'][i] for i in indices) / 2
        y0 = min(data['top'][i] for i in indices) / 2
        x1 = max(data['left'][i] + data['width'][i] for i in indices) / 2
        y1 = max(data['top'][i] + data['height'][i] for i in indices) / 2
        rect = fitz.Rect(x0, y0, x1, y1)
        if any((rect & fitz.Rect(b.bbox)).get_area() > rect.get_area() * .1 for b in blocks):
            continue
        if native_length >= 20 and not any(r.contains(rect) for r in images):
            continue
        text = ' '.join(data['text'][i] for i in indices)
        if not translatable(text): continue
        confidence = sum(float(data['conf'][i]) for i in indices) / len(indices)
        b = Block(f'p{page.number+1}-b{len(blocks)+1}', text, list(rect), max(6, rect.height * .85), kind='ocr', confidence=round(confidence, 1))
        if confidence < 75 or MATH_SYMBOL.search(text):
            b.status, b.reason = 'review', 'OCR 置信度较低或含公式，保留原图'
        blocks.append(b)
    return blocks, ['扫描区域采用 OCR 定位与平色背景修复；低置信度和复杂背景保留原图并标记。'] if groups else ['OCR 未识别到文字，页面保留原样。']

def html_content(block, text):
    """构建用于原位排版的 HTML 内容片段。"""
    color = f'#{block.color:06x}'
    return f'<div style="font-family:sans-serif;font-size:{block.size}pt;line-height:{block.line_height};color:{color};font-weight:{"bold" if block.bold else "normal"};font-style:{"italic" if block.italic else "normal"}">{html.escape(text).replace(chr(10), "<br/>")}</div>'


def render_blocks(original, target, blocks):
    """将翻译后的文本原位渲染回目标 PDF，包含预检、原位擦除与自适应字号排版。"""
    plans = []
    # 在独立刮板页上先进行排版预检，确保文字能够平整收纳
    with fitz.open() as probe:
        scratch = probe.new_page(width=target.rect.width, height=target.rect.height)
        for b in blocks:
            plan_block(b, blocks, original, target, scratch, plans)

    for b, rect, content, bg, min_scale in plans:
        if b.kind != 'ocr':
            for span in b.spans:
                target.add_redact_annot(fitz.Rect(span), fill=False, cross_out=False)
    if any(b.kind != 'ocr' for b, *_ in plans):
        target.apply_redactions(images=0, graphics=0, text=0)

    for b, rect, content, bg, min_scale in plans:
        if bg is not None:
            target.draw_rect(rect, color=None, fill=bg, overlay=True)
        spare, _ = target.insert_htmlbox(rect, content, css='*{margin:0;padding:0}', scale_low=min_scale)
        if spare < 0:
            raise RuntimeError('排版预检与写入结果不一致')
        b.status = 'translated'
    return blocks


def plan_block(b, blocks, original, target, scratch, plans):
    # 如果未翻译或翻译内容为空，或者明确保留非英文，则跳过
    if b.status not in ('pending', 'review') or not b.translation or b.kind == 'protected':
        return
    if b.translation == b.text:
        b.status, b.reason = 'review', '模型返回与原文相同的文字，保留原样'
        return
    rect = fitz.Rect(b.bbox) & target.rect
    if rect.is_empty or rect.width < 3 or rect.height < 3:
        b.status, b.reason = 'review', '区域尺寸无效'
        return

    # 重叠检测：只有当重叠面积超过较小块面积的 60% 时，才视为严重冲突，避免课件中相邻紧凑的文字框被误判跳过
    is_heavily_overlapping = False
    rect_area = rect.get_area()
    for other in blocks:
        if other.id != b.id and other.status in ('pending', 'review') and other.translation:
            other_rect = fitz.Rect(other.bbox) & target.rect
            overlap_area = (rect & other_rect).get_area()
            min_area = min(rect_area, other_rect.get_area())
            if min_area > 0 and (overlap_area / min_area) > 0.6:
                is_heavily_overlapping = True
                break
    if is_heavily_overlapping:
        b.status, b.reason = 'review', '文字区域重叠，需人工检查'
        return

    bg = None
    if b.kind == 'ocr':
        pix = original.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        del pix
        x0, y0, x1, y1 = [int(v * 2) for v in b.bbox]
        strips = [(max(0,x0-2),max(0,y0-4),min(im.width,x1+2),max(1,y0-1)), (max(0,x0-2),min(im.height-1,y1+1),min(im.width,x1+2),min(im.height,y1+4))]
        samples = [im.crop(r) for r in strips if r[2]>r[0] and r[3]>r[1]]
        stats = [ImageStat.Stat(s) for s in samples]
        if not stats or any(max(s.stddev) > 18 for s in stats):
            b.status, b.reason = 'review', '扫描文字背景复杂，保留原图'
            return
        bg = tuple(sum(s.median[k] for s in stats)/len(stats)/255 for k in range(3))
        b.color = 0xffffff if sum(bg) < 1.5 else 0x20251f
        rect = fitz.Rect(rect.x0-1.5, rect.y0-1, rect.x1+1.5, rect.y1+1) & target.rect

    content = html_content(b, b.translation)

    # 排版预检与自适应弹性缩放：
    # 针对中文字形特点，先按常规字号测试；若微小溢出，自适应适度缩放并给予微小安全延伸
    final_rect = rect
    min_scale = min(1.0, max(0.6, 6.0 / b.size))
    spare, scale = scratch.insert_htmlbox(rect, content, css='*{margin:0;padding:0}', scale_low=min_scale)
    if spare < 0:
        # 给译文增加一点高度，并在可读范围内缩小字号。
        min_scale_retry = min(1.0, max(0.48, 4.5 / b.size))
        expanded_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, min(target.rect.height - 2, rect.y1 + max(3, b.size * 0.25)))
        spare, scale = scratch.insert_htmlbox(expanded_rect, content, css='*{margin:0;padding:0}', scale_low=min_scale_retry)
        if spare >= 0:
            final_rect = expanded_rect
            min_scale = min_scale_retry

    if spare < 0:
        b.status, b.reason = 'review', '完整译文无法在可读字号下放入原区域；保留原文，译文见文本精读'
        return

    b.reason = ''  # 成功排版，清除抽取时的初始保护标记
    plans.append((b, final_rect, content, bg, min_scale))


def pair_office_pdfs(original_path, translated_path, output, progress, cancel):
    """Build slide previews from the already translated PPTX conversion."""
    output = Path(output)
    pages, warnings = [], []
    with fitz.open(original_path) as original, fitz.open(translated_path) as translated:
        if not len(original) or len(original) != len(translated) or len(original) > MAX_PAGES:
            raise ValueError('原文与译文幻灯片页数不一致')
        page_count = len(original)
    # show_pdf_page retains imported images and fonts in the destination document.
    # A single 40-slide destination can exceed the 512 MiB worker limit. Close
    # all three PDF documents every two slides, then append incrementally.
    paired_path = output / 'bilingual.pdf'
    for start in range(0, page_count, 2):
        with fitz.open(original_path) as original, fitz.open(translated_path) as translated:
            with (fitz.open(paired_path) if start else fitz.open()) as paired:
                for index in range(start, min(start + 2, page_count)):
                    cancel()
                    left, right = original[index], translated[index]
                    if abs(left.rect.width - right.rect.width) > 2 or abs(left.rect.height - right.rect.height) > 2:
                        raise ValueError('原文与译文幻灯片尺寸不一致')
                    progress('rebuilding', 46 + int((index + 1) / page_count * 50),
                             f'生成第 {index + 1} / {page_count} 页课件预览')
                    for label, page in (('original', left), ('translated', right)):
                        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
                        pix.save(str(output / f'{label}-{index + 1}.png'))
                        del pix
                    width, height = left.rect.width, left.rect.height
                    pair = paired.new_page(width=width * 2, height=height)
                    if left.get_contents():
                        pair.show_pdf_page(fitz.Rect(0, 0, width, height), original, index)
                    if right.get_contents():
                        pair.show_pdf_page(fitz.Rect(width, 0, width * 2, height), translated, index)
                    source_text, target_text = left.get_text().strip(), right.get_text().strip()
                    blocks = []
                    if source_text or target_text:
                        target_lines = {line.strip() for line in target_text.splitlines()}
                        unchanged = [line.strip() for line in source_text.splitlines()
                                     if len(line.strip()) >= 8 and translatable(line)
                                     and line.strip() in target_lines]
                        if unchanged:
                            warnings.append(f'第 {index + 1} 页有 {len(unchanged)} 行英文仍与原文相同，请检查译文。')
                        blocks.append(asdict(Block(f'p{index + 1}-b1', source_text,
                                                   [0, 0, width, height],
                                                   status='review' if unchanged else 'translated',
                                                   translation=target_text,
                                                   reason='部分英文仍与原文相同' if unchanged else '')))
                    pages.append({'page': index + 1, 'width': width, 'height': height,
                                  'orig_img': f'original-{index + 1}.png',
                                  'trans_img': f'translated-{index + 1}.png', 'blocks': blocks})
                cancel()
                if start:
                    paired.saveIncr()
                else:
                    paired.save(paired_path, deflate=True)
    progress('rebuilding', 98, '双栏 PDF 已保存')
    return {'pages': pages, 'translated_pdf': 'translated.pdf',
            'bilingual_pdf': 'bilingual.pdf', 'warnings': warnings}

async def translate_pdf(source_path, output, adapter, model, mode, glossary, progress, cancel):
    """整本 PDF 无痕翻译与双栏排版拼接主流程。"""
    import gc
    output = Path(output)
    source = fitz.open(source_path)
    if source.needs_pass:
        source.close(); raise ValueError('PDF 已加密，请先解锁后上传')
    if not 0 < len(source) <= MAX_PAGES:
        source.close(); raise ValueError(f'文档页数须为 1–{MAX_PAGES}')
    # Open the input twice instead of holding an extra full-document byte copy.
    translated = fitz.open(source_path)
    for doc in (source, translated):
        for page in doc:
            if page.rotation: page.remove_rotation()
    paired = fitz.open()
    pages, warnings = [], []
    try:
        for index in range(len(source)):
            cancel()
            original, target = source[index], translated[index]
            if original.rect.get_area()*4 > 40_000_000:
                raise ValueError('页面尺寸过大，请缩小后上传')
            progress('parsing', 5 + int(index / len(source) * 80), f'解析第 {index+1} / {len(source)} 页')
            blocks = extract_blocks(original)
            blocks, notes = add_ocr(original, blocks)
            warnings.extend(f'第 {index+1} 页：{note}' for note in notes)
            candidates = [{'id': b.id, 'text': b.text} for b in blocks if b.status == 'pending' or (b.kind == 'protected' and b.status == 'review')]
            progress('translating', 5 + int((index+.25) / len(source) * 80), f'翻译第 {index+1} / {len(source)} 页 · {len(candidates)} 个区域')
            
            try:
                values = await adapter.translate(candidates, model, mode, glossary)
            except Exception as exc:
                from .model_adapter import ModelError
                if isinstance(exc, ModelError):
                    raise ModelError(f'第 {index + 1} 页翻译失败：{exc}') from exc
                raise

            cancel()
            for block in blocks: block.translation = values.get(block.id, '')
            progress('rebuilding', 5 + int((index+.6) / len(source) * 80), f'重建第 {index+1} / {len(source)} 页的原始版面')
            
            render_blocks(original, target, blocks)

            # 渲染页面预览图，显式清理 pixmap 避免多页内存暴涨导致容器 OOM
            for label, doc_page in [('original', original), ('translated', target)]:
                pix = doc_page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
                pix.save(str(output / f'{label}-{index+1}.png'))
                del pix

            width, height = original.rect.width, original.rect.height
            pages.append({'page': index+1, 'width': width, 'height': height, 'orig_img': f'original-{index+1}.png', 'trans_img': f'translated-{index+1}.png', 'blocks': [asdict(b) for b in blocks]})
            
            # 每隔 5 页触发一次垃圾回收，防止 Render 容器内存溢出
            if (index + 1) % 5 == 0:
                gc.collect()

        progress('rebuilding', 86, '整理译文字体并导出翻译 PDF')
        translated.subset_fonts()
        translated.save(output / 'translated.pdf', garbage=4, deflate=True)

        # 双栏左右对照拼接：左侧为原始页面，右侧为无痕翻译页面
        for index, page in enumerate(pages):
            cancel()
            progress('rebuilding', 89 + int(index / len(pages) * 9), f'生成第 {index+1} / {len(pages)} 页双栏 PDF')
            width, height = page['width'], page['height']
            pair = paired.new_page(width=width*2, height=height)
            if source[index].get_contents():
                pair.show_pdf_page(fitz.Rect(0, 0, width, height), source, index)
            if translated[index].get_contents():
                pair.show_pdf_page(fitz.Rect(width, 0, width*2, height), translated, index)
        progress('rebuilding', 98, '保存双栏 PDF')
        paired.subset_fonts()
        paired.save(output / 'bilingual.pdf', garbage=4, deflate=True)

        review = sum(b['status'] == 'review' for p in pages for b in p['blocks'])
        if review: warnings.append(f'{review} 个区域保留原文待检查，完整译文可在文本精读和质量报告中查看。')
        return {'pages': pages, 'translated_pdf': 'translated.pdf', 'bilingual_pdf': 'bilingual.pdf', 'warnings': warnings}
    finally:
        source.close(); translated.close(); paired.close()
