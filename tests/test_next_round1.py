"""Next-stage round 1: adversarial business files, verified before and after repairs."""
import unittest
from unittest.mock import patch
from pathlib import Path
import openpyxl
import pandas as pd
from openpyxl.styles import Font
from docx import Document
import test_round2_repairs as fixtures

biz=fixtures.biz
invoices=fixtures.invoices


class NextRound1(unittest.TestCase):
    setUp=fixtures.Round2Repairs.setUp
    frame=fixtures.Round2Repairs.frame
    book=fixtures.Round2Repairs.book
    read=fixtures.Round2Repairs.read
    invoice=fixtures.Round2Repairs.invoice
    stat=fixtures.Round2Repairs.stat

    def clean(self, reim_rows, app_rows=None):
        p=self.frame('申请.xlsx',app_rows or [fixtures.APP])
        r=self.frame('报销.xlsx',reim_rows)
        result=biz.match_and_clean(p,r,self.home/'clean',None)
        self.assertIsNotNone(result,self.errors)
        return pd.read_excel(result)

    def test_n1_01_duplicate_reimbursement_prefers_available_news(self):
        common={'活动名称':'同名培训','关联申请单':'202609010001','学校名称':'甲大学'}
        df=self.clean([{**common,'新闻链接':None},{**common,'新闻链接':'https://example.invalid/latest'}])
        self.assertEqual(df.iloc[0]['新闻链接'],'https://example.invalid/latest')

    def test_n1_02_name_matching_without_reimbursement_id(self):
        df=self.clean([{'活动名称':'同名培训','关联申请单':None,'学校名称':'甲大学','新闻链接':'https://example.invalid/name'}])
        self.assertEqual(df.iloc[0]['新闻链接'],'https://example.invalid/name')

    def test_n1_03_missing_application_id_is_not_silently_dropped(self):
        p=self.frame('申请.xlsx',[fixtures.APP,{**fixtures.APP,'审批编号':None,'活动名称':'缺编号活动'}])
        r=self.frame('报销.xlsx',[{'活动名称':'同名培训','关联申请单':'202609010001','新闻链接':''}])
        result=biz.match_and_clean(p,r,self.home/'clean',None)
        self.assertIsNone(result)
        self.assertIn('审批编号',str(self.errors))
        self.assertIn('3',str(self.errors))

    def test_n1_04_invoice_subtotal_in_first_column(self):
        p=self.book('发票.xlsx',{'数据':[['序号','发票项目','金额'],[1,'住宿费',100],[2,'住宿费',200],['合计',None,300]]})
        rows=self.read(self.invoice(p))['分组统计']
        self.assertEqual(rows[1][2],300)

    def test_n1_05_invoice_preserves_header_and_width(self):
        p=self.book('发票.xlsx',{'数据':[['序号','发票项目','金额'],[1,'很长的发票项目名称住宿费',100]]})
        w=openpyxl.load_workbook(p);w.active.column_dimensions['B'].width=55
        w.active['B1'].font=Font(bold=True,size=16);w.save(p);w.close()
        output=self.invoice(p);w=openpyxl.load_workbook(output)
        try:
            self.assertEqual(w['分类&分组'].column_dimensions['B'].width,55)
            self.assertTrue(w['分类&分组']['B1'].font.bold)
        finally:w.close()

    def test_n1_06_split_long_school_name(self):
        p=self.frame('总表.xlsx',[{'学校名称':'某某大学'+('非常长的院系名称'*35),'活动名称':'培训'}])
        result=fixtures.ExcelSplitter(lambda _:None).split(p,self.home/'split')
        self.assertEqual(result['success'],1,result)

    def test_n1_07_briefing_reserved_or_long_activity_name(self):
        p=self.frame('简报.xlsx',[{'学校名称':'甲大学','活动名称':name,'活动内容':'正文'} for name in ('CON','长活动名称'*70)])
        result=fixtures.ReportGenerator(lambda _:None,row_delay_sec=0,split_by_activity=True).generate(p,self.home/'brief')
        self.assertEqual(result['success'],2,result)
        self.assertTrue(all(Path(p).stat().st_size>0 for p in result['artifacts']))

    def test_n1_08_unknown_labels_count_activity_once(self):
        table=self.stat([{**fixtures.BASE,'活动类型':'未知甲、未知乙'}])['表3_类型分布统计']
        self.assertEqual(table[1][-1],1)

    def test_n1_09_failed_style_write_leaves_no_partial_outputs(self):
        p=self.frame('申请.xlsx',[fixtures.APP]);r=self.frame('报销.xlsx',[{'活动名称':'同名培训','关联申请单':'202609010001','新闻链接':''}])
        with patch.object(biz,'style_excel',side_effect=PermissionError('模拟保存失败')):
            result=biz.match_and_clean(p,r,self.home/'clean',None)
        self.assertIsNone(result)
        self.assertEqual(list((self.home/'clean').glob('*')),[])

    def test_n1_10_xls_conversion_does_not_overwrite_existing_file(self):
        p=self.home/'旧发票.xls';p.write_bytes(b'mocked xls')
        existing=self.home/'旧发票_converted.xlsx';existing.write_bytes(b'user workbook')
        data=pd.DataFrame([['发票项目','金额'],['住宿费',100]])
        with patch.object(pd,'read_excel',return_value={'数据':data}):
            output=self.invoice(p)
        self.assertEqual(existing.read_bytes(),b'user workbook')
        self.assertTrue(output.is_file())


if __name__=='__main__': unittest.main(verbosity=2)
