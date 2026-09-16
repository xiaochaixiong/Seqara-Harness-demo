"""Render the existing brand mark, without its wordmark, for Windows icons."""
import os,sys,io
from pathlib import Path
import xml.etree.ElementTree as ET
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QRectF,QBuffer,QIODevice
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
mark=ET.parse(ROOT/'assets/brand/seqara-mark.svg').getroot()
_,_,width,height=map(float,mark.attrib['viewBox'].split())
scale=484/height;left=(720-width*scale)/2;top=(720-height*scale)/2
paths=''.join(f'<path d="{node.attrib["d"]}"/>' for node in mark.findall('{http://www.w3.org/2000/svg}path'))
svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="720" viewBox="0 0 720 720">
<title>有序 Seqara</title>
<rect x="24" y="24" width="672" height="672" rx="144" fill="#202328"/>
<g fill="#f5f6f7" transform="translate({left} {top}) scale({scale})">{paths}</g>
</svg>'''
(ROOT/'assets/brand/seqara-app-icon.svg').write_text(svg,encoding='utf8')
app=QApplication.instance() or QApplication(sys.argv)
canvas=QImage(1440,1440,QImage.Format.Format_ARGB32_Premultiplied);canvas.fill(Qt.GlobalColor.transparent)
painter=QPainter(canvas);QSvgRenderer(svg.encode()).render(painter,QRectF(0,0,1440,1440));painter.end()
buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);canvas.save(buffer,'PNG')
master=Image.open(io.BytesIO(bytes(buffer.data()))).convert('RGBA').resize((512,512),Image.Resampling.LANCZOS)
for name in ['assets/app_icon.png','native/app_icon.png']:master.save(ROOT/name)
sizes=[16,20,24,28,32,40,48,64,96,128,256]
frames=[master.resize((n,n),Image.Resampling.LANCZOS) for n in sizes]
for name in ['assets/logo_rounded.ico','native/app_icon.ico','native/logo_rounded.ico']:
 master.save(ROOT/name,format='ICO',sizes=[(n,n) for n in sizes],append_images=frames)
print('Generated brand-only SVG, PNG and 11 Windows icon sizes.')
