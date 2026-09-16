"""Build a fresh release using tracked sources and freshly installed dependencies."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import importlib.metadata

ROOT=Path(__file__).resolve().parents[1]

def main():
    subprocess.run([sys.executable,str(ROOT/'scripts/audit-public.py')],cwd=ROOT,check=True)
    version=json.loads((ROOT/'package.json').read_text('utf-8'))['version']
    destination=ROOT/'release'/('Seqara-v'+version)
    if destination.exists():raise RuntimeError('Release already exists; move it aside before a new build.')
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0')
    if 'README.md' not in tracked:raise RuntimeError('Commit the reviewed public sources before packaging.')
    destination.mkdir(parents=True)
    shutil.copy2(ROOT/'native-bin/有序 Seqara/有序 Seqara.exe',destination)
    shutil.copytree(ROOT/'native-bin/有序 Seqara/_internal',destination/'_internal')
    shutil.copytree(ROOT/'backend-bin',destination/'backend-bin')
    for rel in tracked:
        if rel.startswith(('runtime/','desktop/','docs/')) or rel in {'README.md','LICENSE','NOTICE','THIRD_PARTY_NOTICES.md'} or rel.startswith('scripts/patch-'):
            target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/rel,target)
    npm=shutil.which('npm.cmd')
    node=shutil.which('node.exe')
    if not npm or not node:raise RuntimeError('Node.js and npm are required')
    subprocess.run([npm,'ci','--prefix',str(destination/'runtime')],check=True)
    for name in ['patch-pdf-compat.cjs','patch-workspace-menus.cjs','patch-error-messages.cjs']:
        subprocess.run([node,str(destination/'scripts'/name)],check=True)
    (destination/'node-runtime').mkdir()
    shutil.copy2(node,destination/'node-runtime/node.exe')
    # Node license file includes bundled third-party notices.
    node_license=Path(node).parent/'LICENSE'
    if node_license.exists():
        shutil.copy2(node_license,destination/'node-runtime/LICENSE')
    else:
        node_version=subprocess.check_output([node,'--version'],text=True).strip()
        if not __import__('re').fullmatch(r'v\d+\.\d+\.\d+',node_version):raise RuntimeError('Unknown Node version')
        (destination/'node-runtime/LICENSE').write_bytes(urllib.request.urlopen(f'https://raw.githubusercontent.com/nodejs/node/{node_version}/LICENSE',timeout=30).read())
    # Include installed Python license files separately from the executable.
    licenses=destination/'licenses/python'
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file():raise RuntimeError('Python LICENSE.txt is required for binary redistribution')
    licenses.mkdir(parents=True,exist_ok=True)
    shutil.copy2(python_license,licenses/'Python-LICENSE.txt')
    for distribution in importlib.metadata.distributions():
        name=distribution.metadata['Name']
        for entry in distribution.files or []:
            if any(part.lower().startswith(('license','copying','notice','copyright')) for part in entry.parts):
                source=Path(distribution.locate_file(entry))
                if source.is_file():
                    target=licenses/name/str(entry).replace('..','_')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source,target)
    print(destination)

if __name__=='__main__':main()
