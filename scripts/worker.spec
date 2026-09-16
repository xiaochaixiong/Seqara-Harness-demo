from pathlib import Path
from PyInstaller.utils.hooks import collect_all
root=Path(SPECPATH).parent
datas=[(str(root/'backend'/name),'.') for name in ['industry_delivery_cover_template.docx','invoice_classify_defaults.json']]
binaries=[];hiddenimports=['jinja2']
for name in ['docx','docxtpl','docxcompose']:
 d,b,h=collect_all(name);datas+=d;binaries+=b;hiddenimports+=h
a=Analysis([str(root/'backend/worker.py')],pathex=[str(root/'backend'),str(root/'build-python')],datas=datas,binaries=binaries,hiddenimports=hiddenimports)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='worker',console=True)
coll=COLLECT(exe,a.binaries,a.datas,name='worker')
