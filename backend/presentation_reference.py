"""Local, measured reference inspection. PDF contents never become instructions."""
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re


def inspect_reference(args):
    import pdfplumber
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw

    source = Path(args['source']).resolve(strict=True)
    if source.suffix.lower() != '.pdf' or not source.is_file() or source.stat().st_size > 80_000_000:
        raise ValueError('参考稿须是小于 80MB 的 PDF')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    out = Path(args['output_dir']).resolve() / ('ref-' + digest[:16])
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / 'reference.json'
    if report_path.exists():
        return json.loads(report_path.read_text(encoding='utf-8'))
    fonts, colors, assets = Counter(), Counter(), {}
    pages = []
    with pdfplumber.open(source) as pdf, pdfium.PdfDocument(source) as raster:
        if not 1 <= len(pdf.pages) <= 100:
            raise ValueError('参考稿支持 1–100 页，请先选取相关章节')
        for index, page in enumerate(pdf.pages, 1):
            if page.width <= 0 or page.height <= 0 or max(page.width, page.height) > 3840:
                raise ValueError('参考 PDF 页面尺寸超出支持范围')
            words = page.extract_words(extra_attrs=['size', 'fontname', 'non_stroking_color'])
            text = page.extract_text() or ''
            page_fonts = Counter((c['fontname'].split('+')[-1], round(c['size'], 1)) for c in page.chars)
            fonts.update(page_fonts)
            for c in page.chars:
                rgb = c.get('non_stroking_color')
                if isinstance(rgb, (tuple, list)) and len(rgb) == 3:
                    colors['#' + ''.join(f'{max(0,min(255,round(v*255))):02X}' for v in rgb)] += 1
            render_path = out / f'page-{index:02d}.png'
            with closing(raster[index-1]) as rp:
                bitmap = rp.render(scale=min(1280/page.width, 720/page.height))
                bitmap.to_pil().save(render_path)
                bitmap.close()
                page_assets = []
                for obj in rp.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE], max_depth=3):
                    try:
                        bitmap = obj.get_bitmap(render=True)
                        im = bitmap.to_pil().copy()
                        bitmap.close()
                        if im.width * im.height > 30_000_000:
                            continue
                        asset_hash = hashlib.sha256(im.tobytes()).hexdigest()[:20]
                        dest = out / f'asset-{asset_hash}.png'
                        if not dest.exists():
                            im.save(dest)
                        box = [round(v, 2) for v in obj.get_bounds()]
                        item = {'id': asset_hash, 'path': str(dest), 'size': list(im.size)}
                        assets[asset_hash] = item
                        page_assets.append({**item, 'pdf_bounds_bottom_origin': box})
                    except Exception:
                        # Some PDF image encodings cannot be extracted; full-page render still exists.
                        page_assets.append({'unavailable': True})
            page_number = re.search(r'(?m)^\s*(\d{1,3})\s*/\s*(\d{1,3})\s*$', text)
            # Text coordinates are observations, not reconstructed reading order or semantics.
            pages.append({'page': index, 'size': [page.width, page.height], 'text': text,
                          'render': str(render_path), 'assets': page_assets,
                          'printed_number': list(map(int, page_number.groups())) if page_number else None,
                          'text_blocks': [{'text': w['text'], 'bounds': [round(w['x0'],1), round(w['top'],1), round(w['x1']-w['x0'],1), round(w['bottom']-w['top'],1)],
                                           'font': w['fontname'].split('+')[-1], 'font_size': round(w['size'],1)} for w in words]})
    contacts = []
    for start in range(0, len(pages), 8):
        batch = pages[start:start+8]
        board = Image.new('RGB', (1280, ((len(batch)+1)//2)*384), '#e5e7eb')
        draw = ImageDraw.Draw(board)
        for n, page in enumerate(batch):
            with Image.open(page['render']) as im:
                im.thumbnail((620,350))
                x,y=(n%2)*640+10,(n//2)*384+25
                board.paste(im, (x,y))
                draw.text((x,y-19), str(page['page']), fill='black')
        target = out / f'contact-{start//8+1:02d}.png'
        board.save(target); contacts.append(str(target))
    warnings = []
    numbering = [(p['page'],p['printed_number']) for p in pages if p['printed_number']]
    if any(den != len(pages) or num != real for real,(num,den) in numbering):
        warnings.append('印刷页码与 PDF 实际页序/总页数不一致；引用请使用 PDF 实际页序')
    if not any(p['text'].strip() for p in pages):
        warnings.append('扫描参考稿无可提取文字，需要视觉阅读/OCR；不得声称已完成内容解析')
    report = {'id': 'ref-'+digest[:16], 'label': source.name, 'sha256': digest, 'source_path': str(source),
              'page_count': len(pages), 'pages': pages, 'assets': list(assets.values()), 'contact_sheets': contacts,
              'measured_style': {'fonts': [{'family': f,'size':s,'characters':n} for (f,s),n in fonts.most_common(24)],
                                 'text_colors': [{'color':c,'characters':n} for c,n in colors.most_common(12)]},
              'warnings': warnings, 'report_path': str(report_path),
              'limitations': ['字体、颜色、坐标是测量值；逻辑、照片含义与审美需要审阅。参考稿不等于原始业务数据。',
                              '提取素材只保留可解码图片，裁切/遮罩可能与页面显示不同，使用前检查。']}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
