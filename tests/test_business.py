import unittest, json, subprocess, sys, os, hashlib
from pathlib import Path
import pandas as pd
from docx import Document
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs'/'business-tests'

class BusinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True,exist_ok=True)
        cls.source=OUT/'activities.xlsx'
        pd.DataFrame([
            {'学校名称':'示例大学','活动名称':'设计工作坊','活动类型':'工作坊','活动时间':'2026年9月1日','服务教师（人数）':5,'服务学生（人数）':30,'新闻链接':''},
            {'学校名称':'示例学院','活动名称':'师资培训','活动类型':'师资培训','活动时间':'2026年8月1日','服务教师（人数）':8,'服务学生（人数）':0,'新闻链接':''}
        ]).to_excel(cls.source,index=False)
        cls.invoice=OUT/'invoices.xlsx'
        pd.DataFrame([{'发票项目':'*住宿服务*住宿费','金额（元）':1200,'发票号码':'TEST001'},
            {'发票项目':'*餐饮服务*餐费','金额（元）':300,'发票号码':'TEST002'}]).to_excel(cls.invoice,index=False)
    def invoke(self,name,args,ok=True):
        env={**os.environ,'NV_TOOLKIT_DATA_DIR':str(OUT/'state'),'PYTHONIOENCODING':'utf-8'}
        exe=ROOT/'backend-bin/worker/worker.exe'
        cmd=[str(exe)] if os.environ.get('NV_TEST_PACKAGED') else [sys.executable,str(ROOT/'backend/worker.py')]
        r=subprocess.run(cmd,input=json.dumps({'name':name,'args':args}),capture_output=True,text=True,encoding='utf-8',env=env,timeout=120)
        events=[json.loads(s) for s in r.stdout.splitlines() if s.startswith('{')]
        self.assertTrue(events,r.stderr)
        last=events[-1]
        if ok:self.assertEqual(last['type'],'result',last)
        else:self.assertEqual(last['type'],'error',last)
        return last.get('value',last)
    def test_invoice_real_output_and_unchanged_source(self):
        before=hashlib.sha256(self.invoice.read_bytes()).hexdigest()
        result=self.invoke('invoices',{'source':str(self.invoice),'company':'测试公司','project':'测试项目','base':1000,'jitter':0})
        self.assertTrue(result['artifacts'])
        book=pd.ExcelFile(result['artifacts'][0]);self.assertGreater(len(book.sheet_names),2)
        self.assertEqual(before,hashlib.sha256(self.invoice.read_bytes()).hexdigest())
    def test_dashboard_month_and_coverage(self):
        result=self.invoke('dashboard',{'source':str(self.source),'start':'2026-09','end':'2026-09'})['dashboard']
        self.assertEqual(result['activities'],1);self.assertEqual(result['teachers'],5);self.assertEqual(result['students'],30)
    def test_statistics(self):
        result=self.invoke('statistics',{'source':str(self.source)})
        self.assertGreaterEqual(len(pd.ExcelFile(result['artifacts'][0]).sheet_names),3)
    def test_split(self):
        result=self.invoke('split',{'source':str(self.source)});self.assertEqual(result['count'],2)
    def test_activity_word(self):
        result=self.invoke('activity-plan',{'project':'测试项目','school':'示例大学','activity_type':'工作坊','period':'2026年9月','body':'# 活动目标\n提升设计能力。\n## 实施安排\n开展工作坊与成果展示。'})
        doc=Document(result['artifacts'][0]);self.assertIn('提升设计能力','\n'.join(p.text for p in doc.paragraphs))
    def test_delivery_word(self):
        result=self.invoke('delivery',{'school':'示例大学','year':'2026','period':'上半年','body':'# 交付成果\n完成课程共建。\n## 后续计划\n持续完善教学材料。'})
        self.assertTrue(Path(result['artifacts'][0]).is_file())
    def test_invalid_source_error(self):
        self.invoke('statistics',{'source':str(OUT/'missing.xlsx')},ok=False)
    def test_print_requires_confirmation(self):
        p=OUT/'dummy.pdf';p.write_bytes(b'%PDF-1.4')
        self.invoke('print',{'source':str(p),'mode':'print'},ok=False)
    def test_clean_errors_propagate(self):
        self.invoke('clean',{'source':str(self.source),'reimbursement':str(self.source)},ok=False)
    def test_unknown_tool(self):
        self.invoke('shell',{},ok=False)

if __name__=='__main__':unittest.main(verbosity=2)
