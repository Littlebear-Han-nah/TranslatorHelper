"""Opt-in integration check; sends only synthetic fixtures to the configured model."""
import asyncio
import json
from pathlib import Path
from backend.app.services.layout_engine import translate_pdf
from backend.app.services.office_engine import translate_office
from backend.app.services.model_adapter import CompatibleAdapter
import pymupdf as fitz
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
async def main():
    adapter=CompatibleAdapter()
    summary=[]
    for name in ['layout.pdf','scan.png','document.docx','slides.pptx','sheet.xlsx']:
        source=ROOT/'artifacts'/'fixtures'/name
        output=ROOT/'artifacts'/'live'/source.stem
        output.mkdir(parents=True,exist_ok=True)
        def progress(stage,percent,message):print(name,percent,message,flush=True)
        try:
            if source.suffix=='.png':
                converted=output/'source.pdf'
                with fitz.open() as doc:
                    with Image.open(source) as im:
                        page=doc.new_page(width=im.width/2,height=im.height/2)
                        page.insert_image(page.rect,filename=str(source))
                    doc.save(converted)
                source=converted
            engine=translate_pdf if source.suffix=='.pdf' else translate_office
            result=await engine(source,output,adapter,'qwen3.7-flash','academic','attention = 注意力',progress,lambda:None)
            (output/'quality-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            row={'file':name,'pages':len(result['pages']),'translated':sum(b['status']=='translated' for p in result['pages'] for b in p['blocks']),'review':sum(b['status']=='review' for p in result['pages'] for b in p['blocks']),'native':bool(result.get('native_file')),'warnings':result['warnings']}
        except Exception as exc:
            row={'file':name,'error':str(exc)}
        summary.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    (ROOT/'artifacts'/'live'/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
asyncio.run(main())
