import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import test_round2_repairs as fixtures


class FinalDeepWidgets(unittest.TestCase):
    setUpClass=fixtures.Round2WidgetRepairs.setUpClass

    def test_f14_briefing_tabs_fit_small_content_width(self):
        from PySide6.QtWidgets import QApplication,QScrollArea,QWidget,QVBoxLayout
        import toolkit,ui_design
        toolkit.ui_font=ui_design.font
        host=QWidget();host.setFixedSize(660,570)
        page=toolkit.BriefingPage(None)
        ui_design.normalize_page(page,3)
        layout=QVBoxLayout(host);layout.setContentsMargins(0,0,0,0);layout.addWidget(page)
        host.setStyleSheet(ui_design.stylesheet(False));host.show()
        scroll=page.findChild(QScrollArea,'page_scroll')
        for index in (0,1):
            page.tabs.setCurrentIndex(index)
            QApplication.processEvents()
            self.assertLessEqual(page.width(),660)
            self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
        page._brief_fetch_toggle.setChecked(True)
        from PySide6.QtTest import QTest
        QTest.qWait(450)
        self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
        host.close()


if __name__=='__main__':unittest.main(verbosity=2)
