# Build using a Python environment with the project requirements + PyInstaller.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all
root=Path(SPECPATH).parent
names=['ui_tokens.json','seqara_shell.json','stitch_fold_anim.qml','app_icon.ico','app_icon.png','industry_delivery_cover_template.docx','invoice_classify_defaults.json','project_company_schools.json','ticket_company_schools.json']
datas=[(str(root/'native'/n),'.') for n in names]
binaries=[];hiddenimports=['PySide6.QtCharts','PySide6.QtWebEngineWidgets']
for name in ['docxtpl','docxcompose']:
 d,b,h=collect_all(name);datas+=d;binaries+=b;hiddenimports+=h
a=Analysis([str(root/'native/desktop.py')],pathex=[str(root/'native'),str(root/'build-python')],binaries=binaries,datas=datas,hiddenimports=hiddenimports)
# Qt Windows uses OS ICU exports without version suffix. An unrelated ICU 78
# found through PATH has different exports and prevents QtCore from loading.
a.binaries=[v for v in a.binaries if Path(v[0]).name.lower() not in ('icuuc.dll','icuin.dll','icudt.dll')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='有序 Seqara',console=False,icon=str(root/'assets/logo_rounded.ico'))
coll=COLLECT(exe,a.binaries,a.datas,name='有序 Seqara')
