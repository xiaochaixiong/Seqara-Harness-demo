import importlib.util
import json
from pathlib import Path
import re
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_audit',ROOT/'scripts/audit-public.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class PublicEditionTests(unittest.TestCase):
    def test_public_files_pass_scan(self):
        self.assertEqual(audit.audit(audit.public_files()),[])

    def test_scanner_recognizes_synthetic_credentials(self):
        self.assertRegex('sk-'+'a'*25,audit.PATTERNS['access-token'])
        self.assertRegex('-----BEGIN '+'PRIVATE KEY-----',audit.PATTERNS['private-key'])
        self.assertRegex('C:'+'/'+'Users'+'/'+'someone'+'/secret',audit.PATTERNS['personal-path'])

    def test_fresh_data_root_and_empty_company_maps(self):
        source=(ROOT/'native/desktop.py').read_text('utf-8')
        self.assertIn("/'SeqaraHarnessDemo'",source)
        self.assertNotIn("/'Seqara'",source)
        for name in ['project_company_schools.json','ticket_company_schools.json']:
            self.assertEqual(json.loads((ROOT/'native'/name).read_text('utf-8')),{})
        for folder in ['native','backend']:
            self.assertIn('TICKET_COMPANY_SCHOOLS: CompanySchoolsMap = {}',(ROOT/folder/'nv_cover_fill_core.py').read_text('utf-8'))

    def test_office_templates_have_no_embedded_media_or_external_links(self):
        for folder in ['native','backend']:
            with zipfile.ZipFile(ROOT/folder/'industry_delivery_cover_template.docx') as z:
                self.assertFalse(any(n.startswith('word/media/') for n in z.namelist()))
                for n in z.namelist():
                    if n.endswith('.rels'):self.assertNotIn(b'TargetMode="External"',z.read(n))
                self.assertIn(b'Seqara contributors',z.read('docProps/core.xml'))

    def test_readme_local_images_and_links_exist(self):
        text=(ROOT/'README.md').read_text('utf-8')
        images=re.findall(r'!\[[^\]]*\]\(([^)]+)\)',text)
        self.assertGreaterEqual(len(images),3)
        for link in re.findall(r'\]\(([^)]+)\)',text):
            if '://' not in link and not link.startswith('#'):
                self.assertTrue((ROOT/link.split('#')[0]).is_file(),link)

    def test_build_manifest_only_references_available_native_resources(self):
        source=(ROOT/'scripts/native.spec').read_text('utf-8')
        import ast
        module=ast.parse(source)
        names=next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='names' for t in n.targets))
        for name in names:self.assertTrue((ROOT/'native'/name).is_file(),name)
        self.assertNotIn("root/'native/qml'",source)

if __name__=='__main__':unittest.main()
