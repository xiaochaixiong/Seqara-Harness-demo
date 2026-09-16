"""Scan public files and Office XML without printing secret values."""
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', 'node_modules', 'outputs', 'release', 'node-runtime', 'backend-bin', 'native-bin', '__pycache__'}
PATTERNS = {
    'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'access-token': r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|LTAI[A-Za-z0-9]{16,})',
    'personal-path': r'(?i)[A-Z]:[\\/]+Users[\\/]+(?!Public(?:[\\/]|$)|Default(?:[\\/]|$))[^\s<>"\\/]+',
}
BLOCKED = {'api_config.json', 'credentials.json', '.env', 'reference.pptx'}

def audit(files):
    errors = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if p.name in BLOCKED or '/assets/cases/' in '/' + rel or '/vendor/editor/' in '/' + rel:
            errors.append((rel, 'restricted-file'))
        payloads = [p.read_bytes()]
        if p.suffix.lower() in {'.docx', '.xlsx', '.pptx', '.zip'}:
            try:
                with zipfile.ZipFile(p) as z:
                    payloads += [z.read(n) for n in z.namelist() if n.endswith(('.xml', '.rels', '.txt', '.json'))]
            except zipfile.BadZipFile:
                errors.append((rel, 'invalid-archive'))
        for data in payloads:
            text = data.decode('utf-8', errors='ignore')
            for name, pattern in PATTERNS.items():
                if re.search(pattern, text):
                    errors.append((rel, name))
    return sorted(set(errors))

def public_files():
    try:
        result = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT, capture_output=True, check=True)
        return [ROOT / p for p in result.stdout.decode('utf-8').split('\0') if p and (ROOT / p).is_file()]
    except subprocess.CalledProcessError:
        return [p for p in ROOT.rglob('*') if p.is_file() and not any(x in EXCLUDED for x in p.relative_to(ROOT).parts)]

if __name__ == '__main__':
    files = public_files()
    errors = audit(files)
    for path, kind in errors:
        print(f'{path}: {kind}')
    print(f'Public audit: {len(files)} files; {len(errors)} findings')
    sys.exit(bool(errors))
