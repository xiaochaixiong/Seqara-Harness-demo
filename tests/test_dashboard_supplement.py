import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native'))
from nv_activity_types import ACTIVITY_TYPE_MAP, normalize_activity_types
from nv_dashboard_core import build_dashboard_snapshot, filter_dashboard_snapshot, DashboardFilter, APP_REQUIRED, REIM_REQUIRED


class SupplementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main = self.root / 'main.xlsx'
        self.supp = self.root / 'supp.xlsx'
        self.state = self.root / 'state.sqlite3'
        pd.DataFrame([{'活动名称': '主表活动', '学校名称': '示例大学', '活动类型': '双师赋能',
            '活动时间': '2026-09-01', '服务教师（人数）': 5, '服务学生（人数）': 20}]).to_excel(self.main, index=False)
        pd.DataFrame([{'活动名称': '线下赛事', '学校名称': '示例大学', '活动类型': '学科竞赛、产业赛事',
            '活动时间': 46267, '服务教师（人数）': 999, '服务学生（人数）': 888},
            {'活动名称': '线下品牌', '学校名称': '另一大学', '活动类型': '论坛', '活动时间': '2026-08-01'}
        ]).to_excel(self.supp, index=False)

    def test_cleaned_optional_counts_and_refresh(self):
        base = build_dashboard_snapshot(self.main, None, self.state)
        result = build_dashboard_snapshot(self.main, None, self.state, self.supp)
        self.assertEqual(base.activity_count, 1)
        self.assertEqual(result.activity_count, 3)
        self.assertEqual((result.teacher_total, result.student_total), (5, 20))
        self.assertEqual(result.unreimbursed, base.unreimbursed)
        self.assertEqual(result.experts, base.experts)
        self.assertEqual(result.school_type_counts['示例大学']['赛事'], 1)
        self.assertEqual(result.school_type_counts['示例大学']['师资培训'], 1)
        self.assertEqual(len([a for a in result.activities if a.status == '已报销']), 2)
        self.assertEqual(build_dashboard_snapshot(self.main, None, self.state, self.supp).activities, result.activities)
        self.assertEqual(build_dashboard_snapshot(self.main, None, self.state).activity_count, 1)
        view = filter_dashboard_snapshot(result, DashboardFilter(start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)))
        self.assertEqual(len(view.activities), 1)
        self.assertEqual(view.activities[0].activity_types, ('品牌活动',))
        self.assertEqual(view.teacher_total, 0)

    def test_raw_reimbursement_unchanged(self):
        raw, reim = self.root / 'raw.xlsx', self.root / 'reim.xlsx'
        row = dict.fromkeys(APP_REQUIRED, '')
        row.update({'审批编号': '202609010001', '申请人部门': '示例大学', '活动名称': '需报销',
            '活动类型': '设计工坊', '开始时间': '2026-09-01', '结束时间': '2026-09-02', '当前审批状态': '已通过'})
        pd.DataFrame([row]).to_excel(raw, index=False)
        pd.DataFrame(columns=sorted(REIM_REQUIRED)).to_excel(reim, index=False)
        base = build_dashboard_snapshot(raw, reim, self.state)
        result = build_dashboard_snapshot(raw, reim, self.state, self.supp)
        self.assertEqual(result.activity_count, base.activity_count + 2)
        self.assertEqual(result.unreimbursed, base.unreimbursed)
        self.assertEqual(len(result.unreimbursed), 1)
        self.assertEqual(result.unreimbursed[0].activity_types, ('实训营',))

    def test_invalid_supplement(self):
        pd.DataFrame([{'活动名称': '缺列'}]).to_excel(self.supp, index=False)
        with self.assertRaisesRegex(ValueError, '补充表格缺少字段'):
            build_dashboard_snapshot(self.main, None, self.state, self.supp)

    def test_mapping(self):
        for source, expected in ACTIVITY_TYPE_MAP.items():
            self.assertEqual(normalize_activity_types(source), expected)
        self.assertEqual(normalize_activity_types('学科竞赛，产业赛事、赛事;论坛/展览'), '赛事、品牌活动')
        self.assertEqual(normalize_activity_types('课程、走出去'), '课程、走出去')

    def test_cleaning_output_uses_new_categories(self):
        import nv_business_core as business
        raw, reim = self.root / 'raw.xlsx', self.root / 'reim.xlsx'
        records, reimbursements = [], []
        for index, source_type in enumerate(ACTIVITY_TYPE_MAP):
            approval = str(202609010001 + index)
            name = f'活动{index}'
            records.append({'活动名称': name, '学院名称': '学院', '活动类型': source_type,
                '开始时间': '2026-09-01', '服务教师（人数）': 1, '服务学生（人数）': 2,
                '活动总额': 0, '申请人部门': '示例大学', '审批编号': approval})
            reimbursements.append({'活动名称': name, '新闻链接': f'https://example.com/{index}', '关联申请单': approval})
        pd.DataFrame(records).to_excel(raw, index=False)
        pd.DataFrame(reimbursements).to_excel(reim, index=False)
        business.match_and_clean(raw, reim, self.root, None, output_basename='cleaned')
        cleaned = pd.read_excel(self.root / 'cleaned.xlsx').set_index('活动名称')
        for index, expected in enumerate(ACTIVITY_TYPE_MAP.values()):
            self.assertEqual(cleaned.loc[f'活动{index}', '活动类型'], expected)

    def test_upload_ui(self):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont, QFontDatabase
        from nv_dashboard_widgets import DashboardPage
        app = QApplication.instance() or QApplication([])
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        app.setFont(QFont('Microsoft YaHei', 10))
        page = DashboardPage(None, self.state)
        page.set_source_paths(str(self.main), '', str(self.supp))
        snapshot = build_dashboard_snapshot(self.main, None, self.state, self.supp)
        page._on_loaded(snapshot)
        self.assertEqual(page._loaded_source_paths, (str(self.main), '', str(self.supp)))
        self.assertIn('补充表格', page.source_summary_label.text())
        page._refresh_coverage_detail()
        self.assertEqual(len(page._coverage_rows), 1)
        page._set_source_expanded(True)
        page.resize(1200, 900)
        page.show()
        app.processEvents()
        out = ROOT / 'outputs' / 'dashboard-supplement-check'
        out.mkdir(parents=True, exist_ok=True)
        page.grab().save(str(out / 'upload.png'))
        page.supplementary_row.set_path('')
        self.assertIn('数据来源已更改', page.status_label.text())
        page.close()


if __name__ == '__main__':
    unittest.main()
