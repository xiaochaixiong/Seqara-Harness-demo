"""Dashboard restart regression tests using isolated data and real Qt pages."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native'))
import pandas as pd
from PySide6.QtWidgets import QApplication
from nv_dashboard_core import DashboardStateStore, build_dashboard_snapshot, APP_REQUIRED, REIM_REQUIRED
from nv_dashboard_widgets import DashboardPage


class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / 'state.sqlite3'
        self.main = self.root / 'activities.xlsx'
        self.supp = self.root / 'supp.xlsx'
        row = {'活动名称': '主表活动', '学校名称': '示例大学', '活动类型': '论坛',
               '活动时间': '2026-09-01', '服务教师（人数）': 5, '服务学生（人数）': 20}
        pd.DataFrame([row]).to_excel(self.main, index=False)
        pd.DataFrame([dict(row, 活动名称='补充活动')]).to_excel(self.supp, index=False)

    def page(self, **kwargs):
        page = DashboardPage(None, self.db, **kwargs)
        self.addCleanup(page.close)
        return page

    def test_restart_without_source_files_and_failed_update(self):
        page = self.page()
        self.assertIsNone(page.snapshot)
        snapshot = build_dashboard_snapshot(self.main, None, self.db, self.supp)
        page._on_loaded(snapshot)
        page._on_failed('模拟解析失败')
        page.close()
        self.main.unlink()
        self.supp.unlink()
        ended = []
        restored = self.page(task_end=lambda: ended.append(True))
        self.assertEqual(restored.snapshot, snapshot)
        self.assertEqual(restored.view.teacher_total, 5)
        self.assertEqual(len(restored.view.activities), 2)
        self.assertEqual(restored.supplementary_row.path, str(self.supp))
        self.assertEqual(restored.application_row.path, str(self.main))
        self.assertIs(restored.content_stack.currentWidget(), restored.tabs)
        self.assertIn('已恢复上次看板', restored.status_label.text())
        self.assertEqual(ended, [])

    def test_raw_experts_and_dates_roundtrip(self):
        raw, reim = self.root / 'raw.xlsx', self.root / 'reim.xlsx'
        row = dict.fromkeys(APP_REQUIRED, '')
        row.update({'审批编号': '202609010001', '申请人部门': '示例大学', '活动名称': '活动',
                    '活动类型': '论坛', '开始时间': '2026-09-01', '结束时间': '2026-09-02',
                    '当前审批状态': '已通过', '专家费-专家姓名': '张老师',
                    '专家费-专家简介': '教授', '专家费-专家费（元）': 1000})
        pd.DataFrame([row]).to_excel(raw, index=False)
        pd.DataFrame(columns=sorted(REIM_REQUIRED)).to_excel(reim, index=False)
        snapshot = build_dashboard_snapshot(raw, reim, self.db)
        self.assertTrue(snapshot.experts)
        self.assertTrue(snapshot.unreimbursed)
        DashboardStateStore(self.db).save_snapshot(snapshot)
        self.assertEqual(DashboardStateStore(self.db).load_snapshot(), snapshot)
        self.assertEqual(self.page().snapshot, snapshot)

    def test_save_failure_keeps_previous_snapshot(self):
        page = self.page()
        first = build_dashboard_snapshot(self.main, None, self.db)
        page._on_loaded(first)
        second = build_dashboard_snapshot(self.main, None, self.db, self.supp)
        with patch.object(page.state_store, 'save_snapshot', side_effect=OSError('磁盘不可写')):
            page._on_loaded(second)
        self.assertEqual(page.snapshot, second)
        self.assertIn('自动保存失败', page.status_label.text())
        self.assertEqual(DashboardStateStore(self.db).load_snapshot(), first)
        page._on_loaded(second)
        self.assertEqual(self.page().snapshot, second)

    def test_bad_cache_does_not_block_startup_and_can_be_replaced(self):
        store = DashboardStateStore(self.db)
        for version, payload in [(1, '{broken'), (999, '{}')]:
            with store._db() as db:
                db.execute('INSERT OR REPLACE INTO dashboard_snapshot VALUES (1, ?, ?)', (version, payload))
            page = self.page()
            self.assertIsNone(page.snapshot)
            self.assertIn('恢复失败', page.status_label.text())
            snapshot = build_dashboard_snapshot(self.main, None, self.db)
            page._on_loaded(snapshot)
            self.assertEqual(store.load_snapshot(), snapshot)


if __name__ == '__main__':
    unittest.main()
