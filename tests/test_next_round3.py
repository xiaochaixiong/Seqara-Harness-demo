"""Round 3: native widget input and rendered cached sidebar regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import json
import unittest
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'native'))


class NextRound3(unittest.TestCase):
    def test_n3_04_initial_window_fits_high_scale_work_area(self):
        from PySide6.QtWidgets import QApplication,QWidget
        from PySide6.QtCore import QRect
        from seqara_chrome import fit_initial_window
        app=QApplication.instance() or QApplication([])
        class Screen:
            def availableGeometry(self):return QRect(0,0,960,608)
        class Window(QWidget):
            def screen(self):return Screen()
        window=Window();window.setMinimumSize(900,620);window.resize(1440,900)
        fit_initial_window(window)
        self.assertLessEqual(window.width(),960)
        self.assertLessEqual(window.height(),608)
        self.assertTrue(Screen().availableGeometry().contains(window.geometry()))
        window.close()

    def test_n3_03_both_themes_keep_bar_labels_readable(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QColor
        from nv_dashboard_widgets import _HorizontalBarChart,_contrast_ratio
        app=QApplication.instance() or QApplication([])
        tokens=json.loads((ROOT/'native/ui_tokens.json').read_text(encoding='utf8'))
        for theme in ('light','dark'):
            chart=_HorizontalBarChart();chart.set_palette({'panel':tokens[theme]['canvas'],'focus':tokens[theme]['focus']})
            chart.set_data({'测试院校':10},'')
            self.assertGreaterEqual(_contrast_ratio(chart._bar_set.labelColor(),QColor(tokens[theme]['focus'])),4.5,theme)
            chart.close()

    def test_n3_01_compact_cache_restores_brand_and_labels(self):
        result=subprocess.run([sys.executable,str(ROOT/'tests/sidebar_cache_probe.py')],capture_output=True,
            encoding='utf8',timeout=30,env={**os.environ,'PYTHONIOENCODING':'utf8','QTWEBENGINE_CHROMIUM_FLAGS':'--disable-gpu'})
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))
        self.assertTrue(data['brandVisible'],data)
        self.assertEqual(data['label'],'新建会话')
        self.assertGreater(data['labelWidth'],20)
        self.assertTrue(data['collapsedFirst'])
        self.assertEqual(data['width'],280)

    def test_n3_02_wheel_scroll_does_not_change_closed_selector(self):
        from PySide6.QtWidgets import QApplication,QWidget,QScrollArea,QVBoxLayout,QComboBox
        from PySide6.QtCore import QPoint,QPointF,Qt
        from PySide6.QtGui import QWheelEvent
        import seqara_chrome
        app=QApplication.instance() or QApplication([]);seqara_chrome.install()
        area=QScrollArea();content=QWidget();layout=QVBoxLayout(content)
        combo=QComboBox();combo.addItems(['自动兼容','全部使用 WPS','其他方式']);layout.addWidget(combo)
        content.setMinimumHeight(1200);area.setWidget(content);area.resize(400,300);area.show();app.processEvents()
        wheel=QWheelEvent(QPointF(5,5),QPointF(5,5),QPoint(),QPoint(0,-120),
            Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
        app.sendEvent(combo,wheel)
        self.assertEqual(combo.currentIndex(),0)
        self.assertGreater(area.verticalScrollBar().value(),0);area.close()


if __name__=='__main__':unittest.main(verbosity=2)
