"""Surgical OOXML editing: keep every ZIP part, relationship, image and equation."""
import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from .layout_engine import translatable, translate_pdf

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS = {'w': W, 'a': A, 's': S}
PARSER = lambda: etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)

def office_binary():
    configured = os.getenv('LIBREOFFICE_BIN')
    return configured or shutil.which('libreoffice') or shutil.which('soffice') or ('/Applications/LibreOffice.app/Contents/MacOS/soffice' if Path('/Applications/LibreOffice.app/Contents/MacOS/soffice').exists() else None)

def validate_office(path):
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 250 * 1024 * 1024:
                raise ValueError('Office 文件解压后过大')
            required = {'.docx': 'word/document.xml', '.pptx': 'ppt/presentation.xml', '.xlsx': 'xl/workbook.xml'}.get(Path(path).suffix.lower())
            if required and required not in archive.namelist():
                raise ValueError('Office 文件内容与扩展名不符')
            if '[Content_Types].xml' not in archive.namelist():
                raise ValueError('不是有效的 Office 文档')
            for item in entries:
                if item.filename.endswith('.rels'):
                    root = etree.fromstring(archive.read(item), PARSER())
                    for relationship in root:
                        if relationship.get('TargetMode') == 'External' and not relationship.get('Type', '').endswith('/hyperlink'):
                            raise ValueError('Office 文件含外部数据链接，请断开链接后上传')
                if 'vbaProject' in item.filename:
                    raise ValueError('请移除宏后上传 Office 文件')
    except (zipfile.BadZipFile, etree.XMLSyntaxError):
        raise ValueError('Office 文件损坏或格式不正确') from None

def office_nodes(archive, extension):
    parts, entries, literal_strings = {}, [], set()
    if extension == '.xlsx':
        for name in archive.namelist():
            if re.match(r'xl/worksheets/sheet\d+\.xml$', name):
                tree = etree.fromstring(archive.read(name), PARSER())
                for formula in tree.findall('.//s:f', NS):
                    literal_strings.update(re.findall(r'"([^"\n]*)"', formula.text or ''))
    for name in archive.namelist():
        if not name.endswith('.xml'):
            continue
        if extension == '.docx' and name.startswith('word/'):
            tree = etree.fromstring(archive.read(name), PARSER())
            nodes, field_depth = [], 0
            for node in tree.iter():
                if node.tag == f'{{{W}}}fldChar':
                    value = node.get(f'{{{W}}}fldCharType')
                    if value == 'begin': field_depth += 1
                    elif value == 'end': field_depth = max(0, field_depth-1)
                if node.tag in (f'{{{W}}}t', f'{{{A}}}t') and not field_depth and not any(p.tag == f'{{{W}}}fldSimple' for p in node.iterancestors()):
                    nodes.append(node)
        elif extension == '.pptx' and re.match(r'ppt/(slides/slide\d+|notesSlides/notesSlide\d+|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+)\.xml$', name):
            tree = etree.fromstring(archive.read(name), PARSER())
            nodes = tree.findall('.//a:t', NS)
        elif extension == '.xlsx' and (name == 'xl/sharedStrings.xml' or re.match(r'xl/worksheets/sheet\d+\.xml$', name)):
            tree = etree.fromstring(archive.read(name), PARSER())
            nodes = tree.findall('.//s:si//s:t', NS) + tree.findall('.//s:c[@t="inlineStr"]//s:t', NS)
        else:
            continue
        parts[name] = tree
        for node in nodes:
            if node.text and translatable(node.text) and node.text not in literal_strings:
                entries.append({'id': f'n{len(entries)+1}', 'text': node.text, 'node': node, 'part': name})
    return parts, entries

async def translate_native(source, target, adapter, model, mode, glossary, progress, cancel):
    extension = Path(source).suffix.lower()
    with zipfile.ZipFile(source) as archive:
        parts, entries = office_nodes(archive, extension)
        report = []
        for start in range(0, len(entries), 24):
            cancel()
            batch = entries[start:start+24]
            values = await adapter.translate([{'id': e['id'], 'text': e['text']} for e in batch], model, mode, glossary)
            for entry in batch:
                translation = values[entry['id']]
                entry['node'].text = translation
                entry['node'].set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                report.append({'id': entry['id'], 'text': entry['text'], 'translation': translation, 'part': entry['part']})
            progress('translating', 10 + int((start+len(batch))/max(1,len(entries))*35), f'翻译 Office 文字节点 {start+len(batch)} / {len(entries)}')
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as result:
            for item in archive.infolist():
                result.writestr(item, etree.tostring(parts[item.filename], xml_declaration=True, encoding='UTF-8', standalone=True) if item.filename in parts else archive.read(item.filename))
    return report

def to_pdf(source, output):
    binary = office_binary()
    if not binary:
        return None
    # Private process profile prevents cross-job collisions; ZIPs are never extracted.
    with tempfile.TemporaryDirectory(prefix='translator-office-') as profile:
        registry = Path(profile) / 'user'
        registry.mkdir()
        (registry / 'registrymodifications.xcu').write_text('''<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>''')
        try:
            completed = subprocess.run([binary, f'-env:UserInstallation={Path(profile).as_uri()}', '--headless', '--nologo', '--nodefault', '--nolockcheck', '--norestore', '--convert-to', 'pdf', '--outdir', str(output), str(source)], capture_output=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise ValueError('Office 预览转换超时，请缩小文档后重试') from None
        expected = Path(output) / (Path(source).stem + '.pdf')
        if completed.returncode != 0 or not expected.exists():
            raise ValueError('Office 预览转换失败，原格式译文已保留')
        return expected

async def translate_office(source, output, adapter, model, mode, glossary, progress, cancel):
    native_name = 'translated' + Path(source).suffix.lower()
    report = await translate_native(source, Path(output)/native_name, adapter, model, mode, glossary, progress, cancel)
    cancel()
    warnings = ['Office 原格式译文保留原有 XML 结构、图片、公式、表格及文字样式；不同字体和中英文长度可能导致原生 Office 分页或行高变化。', 'Office 按文字样式节点翻译；跨样式长句、图表内文字与特殊对象请结合原文复核。']
    try:
        pdf = to_pdf(source, output)
    except ValueError as exc:
        pdf = None
        warnings.append(str(exc))
    if pdf:
        def pdf_progress(stage, percent, message): progress(stage, 45+int(percent*.5), message)
        result = await translate_pdf(pdf, output, adapter, model, mode, glossary, pdf_progress, cancel)
        warnings.append('对照 PDF 以原文 Office 转换出的页面为基准进行原位翻译，与原格式译文的自动分页可能不同。')
        result['warnings'].extend(warnings)
    else:
        result = {'pages': [], 'warnings': warnings + ['当前环境缺少可用的 LibreOffice 转换，已生成原格式译文；双栏 PDF 预览暂不可用。']}
    result.update(native_file=native_name, native_blocks=report)
    return result
