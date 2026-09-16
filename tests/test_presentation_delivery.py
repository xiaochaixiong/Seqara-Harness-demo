import unittest
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'native'))
from presentation_io import verify_chart_data
from seqara_navigation import navigation_target

class DeliveryTest(unittest.TestCase):
    def test_chart_value_label_and_order_mismatches_are_detected(self):
        xml='<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:ser><c:cat><c:strLit><c:pt idx="0"><c:v>A</c:v></c:pt></c:strLit></c:cat><c:val><c:numLit><c:pt idx="0"><c:v>25</c:v></c:pt></c:numLit></c:val></c:ser></c:chart>'
        element={'data':{'cols':['label','value'],'rows':[['A',25]]},'series':[{'type':'bar','encode':{'x':'value','y':'label'}}],'yAxis':{'type':'category'}}
        self.assertEqual(verify_chart_data(ET.fromstring(xml),element)[0],[])
        self.assertTrue(verify_chart_data(ET.fromstring(xml.replace('>25<','>75<')),element)[0])
        self.assertTrue(verify_chart_data(ET.fromstring(xml.replace('>A<','>B<')),element)[0])

    def test_local_preview_does_not_replace_trusted_conversation(self):
        origin='http://127.0.0.1:8000'
        self.assertEqual(navigation_target(origin+'/chat',origin),'embedded')
        self.assertEqual(navigation_target('http://127.0.0.1:9000/s/token',origin,True),'external')
        self.assertEqual(navigation_target('https://example.com',origin,True),'blocked')
        self.assertEqual(navigation_target('https://example.com',origin),'external')
        self.assertEqual(navigation_target('file:///C:/test.exe',origin),'blocked')

if __name__=='__main__': unittest.main()
