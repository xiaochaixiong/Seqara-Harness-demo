import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from presentation_reference import inspect_reference


class ReferenceTest(unittest.TestCase):
    def test_local_render_pagination_measurement_and_cache(self):
        from PyPDF2 import PdfWriter
        from PyPDF2.generic import NameObject, DictionaryObject, DecodedStreamObject
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'reference.pdf'
            writer=PdfWriter()
            for _ in range(2):
                writer.add_blank_page(width=960,height=540)
                page=writer.pages[-1]
                font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
                page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
                stream=DecodedStreamObject();stream.set_data(b'BT /F1 24 Tf 30 450 Td (Reference heading) Tj 0 -40 Td (1 / 37) Tj ET')
                page[NameObject('/Contents')]=writer._add_object(stream)
            with source.open('wb') as f:writer.write(f)
            args={'source':str(source),'output_dir':str(Path(tmp)/'output')}
            result=inspect_reference(args)
            self.assertEqual(result['page_count'],2)
            self.assertTrue(result['warnings'])
            self.assertTrue(result['measured_style']['fonts'])
            self.assertIn('Reference heading',result['pages'][0]['text'])
            self.assertTrue(Path(result['pages'][0]['render']).exists())
            self.assertEqual(inspect_reference(args)['sha256'],result['sha256'])


if __name__=='__main__':unittest.main()
