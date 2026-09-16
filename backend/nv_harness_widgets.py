"""Harness desktop entry; inherits the existing app's widgets and visual system."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTabWidget, QTextEdit, QListWidget, QListWidgetItem, QFileDialog, QSplitter)

from nv_harness_core import HarnessController, PINNED_VERSION, installed_version
from nv_harness_skills import import_skill, set_enabled


def create_page(main, ui, resource_dir, data_dir):
    class HarnessPage(ui.BasePage):
        def __init__(self):
            super().__init__(main)
            self.controller = HarnessController(resource_dir, data_dir, self)
            self._close_requested = False
            self._workbench_view = None
            # A web workspace needs the full page height, not another scrollable page header.
            root = QVBoxLayout(self)
            root.setContentsMargins(12, 8, 12, 12)
            root.setSpacing(8)
            self.tabs = QTabWidget()
            self.tabs.setObjectName("settings_tabs")
            root.addWidget(self.tabs, 1)
            self.workbench_page = QWidget()
            self.workbench_layout = QVBoxLayout(self.workbench_page)
            self.workbench_layout.setContentsMargins(0, 0, 0, 0)
            self.empty_state = QWidget()
            empty_layout = QVBoxLayout(self.empty_state)
            empty_layout.setContentsMargins(24, 24, 24, 24)
            empty_layout.setSpacing(12)
            empty_layout.addStretch(1)
            self.placeholder = QLabel("Agent工作台")
            self.placeholder.setObjectName("hero_title")
            self.placeholder.setWordWrap(True)
            self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading = QHBoxLayout()
            heading.setSpacing(10)
            heading.addStretch(1)
            heading.addWidget(self.placeholder)
            self.harness_badge = QLabel("Harness")
            self.harness_badge.setObjectName("harness_badge")
            heading.addWidget(self.harness_badge, 0, Qt.AlignmentFlag.AlignVCenter)
            heading.addStretch(1)
            empty_layout.addLayout(heading)
            empty_hint = QLabel("启动后即可创建会话；工作文件夹可在“运行设置”中选择。")
            empty_hint.setObjectName("muted")
            empty_hint.setWordWrap(True)
            empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(empty_hint)
            self.launch_button = ui.AnimatedButton("启动工作台", "primary")
            self.launch_button.clicked.connect(self._open)
            empty_layout.addWidget(self.launch_button, 0, Qt.AlignmentFlag.AlignCenter)
            empty_layout.addStretch(1)
            self.workbench_layout.addWidget(self.empty_state, 1)
            self.tabs.addTab(self.workbench_page, "工作台")
            service = QWidget()
            service.setObjectName("harness_tab")
            layout = QVBoxLayout(service)
            layout.setContentsMargins(16, 16, 16, 16)
            self.status = QLabel()
            self.status.setWordWrap(True)
            self.status.setFont(ui.ui_font("title"))
            layout.addWidget(self.status)
            default_workspace = data_dir / "harness_workspace"
            self.workspace = self.stitch_path_row(layout, "工作文件夹", str(default_workspace), True,
                                                   "选择供 Agent 使用的工作文件夹")
            hint = QLabel("Harness 的模型与 API Key 在工作台内部设置，与活动方案的 API 设置分别生效。日间／夜间统一使用软件右上角切换。执行活动方案可使用内置 activity-plan 技能。")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            self.log = QTextEdit()
            self.log.setObjectName("stitch_run_log")
            self.log.setReadOnly(True)
            self.log.setPlaceholderText("启动与运行日志显示在这里。")
            self.log.document().setMaximumBlockCount(400)
            layout.addWidget(self.log, 1)
            self.tabs.addTab(service, "运行设置")

            skills_page = QWidget()
            skills_page.setObjectName("harness_tab")
            sl = QVBoxLayout(skills_page)
            note = QLabel("本地技能沿用 Harness 的 SKILL.md 格式。导入文件夹时保留参考资料、脚本和模板；脚本所需依赖需另行安装。")
            note.setWordWrap(True)
            sl.addWidget(note)
            actions = QHBoxLayout()
            self.import_button = ui.AnimatedButton("导入技能文件夹", "secondary")
            self.import_button.clicked.connect(self._import)
            self.toggle_button = ui.AnimatedButton("停用技能", "secondary")
            self.toggle_button.clicked.connect(self._toggle)
            refresh = ui.AnimatedButton("刷新", "ghost")
            refresh.clicked.connect(self._refresh_skills)
            for button in (self.import_button, self.toggle_button, refresh):
                actions.addWidget(button)
            actions.addStretch()
            sl.addLayout(actions)
            split = QSplitter(Qt.Orientation.Horizontal)
            self.skill_list = QListWidget()
            self.skill_list.setObjectName("briefing_file_list")
            self.skill_list.setMinimumWidth(150)
            self.skill_list.setMaximumWidth(260)
            self.skill_list.currentItemChanged.connect(self._show_skill)
            self.skill_text = QTextEdit()
            self.skill_text.setObjectName("stitch_run_log")
            self.skill_text.setReadOnly(True)
            self.skill_text.setPlaceholderText("选择技能查看说明。")
            split.addWidget(self.skill_list)
            split.addWidget(self.skill_text)
            split.setStretchFactor(1, 1)
            sl.addWidget(split, 1)
            self.tabs.addTab(skills_page, "本地技能")

            controls = QHBoxLayout()
            self.install_button = ui.AnimatedButton("安装固定版本", "secondary")
            self.install_button.clicked.connect(self.controller.install)
            self.stop_button = ui.AnimatedButton("停止工作台", "secondary")
            self.stop_button.clicked.connect(self.controller.stop)
            self.open_button = ui.AnimatedButton("启动工作台", "primary")
            self.open_button.clicked.connect(self._open)
            self._stitch_primary_action = self.open_button
            for button in (self.install_button, self.stop_button, self.open_button):
                button.setMinimumHeight(42)
                button.setFont(ui.ui_font("label"))
                controls.addWidget(button)
            layout.addLayout(controls)
            self.controller.log_line.connect(self._append_log)
            self.controller.state_changed.connect(self._state)
            self.controller.ready.connect(self._show_workbench)
            self.controller.finished.connect(self._after_finish)
            self._state("stopped")
            self.set_theme(main.dark)
            self._refresh_skills()

        def _append_log(self, text):
            cursor = self.log.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text + "\n")
            self.log.setTextCursor(cursor)
            self.log.ensureCursorVisible()

        def _open(self):
            if self.controller.state == "running":
                self._show_workbench(self.controller.url)
                return
            default = data_dir / "harness_workspace"
            if self.workspace.text().strip() == str(default):
                try:
                    default.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    self.log.append(str(exc))
                    return
            self.controller.start(self.workspace.text().strip())

        def _show_workbench(self, url):
            try:
                if self._workbench_view is None:
                    from nv_harness_window import HarnessView
                    self._workbench_view = HarnessView(self.controller.home, self.workbench_page)
                    self.workbench_layout.addWidget(self._workbench_view, 1)
                    self._workbench_view.set_theme(main.dark)
                self.tabs.setCurrentWidget(self.workbench_page)
                self.empty_state.hide()
                self._workbench_view.open_workspace(url)
            except (ImportError, OSError, RuntimeError) as exc:
                self._append_log("无法加载内嵌工作台：" + str(exc))
                ui.stitch_msg_warning(self, "工作台未加载", "请检查 PySide6 WebEngine 安装是否完整。\n" + str(exc))

        def _state(self, state):
            labels = {"stopped": "未启动", "starting": "正在启动", "running": "运行中",
                      "stopping": "正在停止", "failed": "运行失败", "installing": "正在安装"}
            version = installed_version(self.controller.runtime) or "未安装"
            self.status.setText(f"{labels[state]}  ·  Harness {version}")
            self.open_button.setText("返回工作台" if state == "running" else "启动工作台")
            self.open_button.setEnabled(state in ("stopped", "failed", "running"))
            self.launch_button.setEnabled(state in ("stopped", "failed", "running"))
            self.launch_button.setText("返回工作台" if state == "running" else labels[state] if state in ("starting", "stopping", "installing") else "启动工作台")
            if state in ("stopped", "failed"):
                self.empty_state.show()
                if self._workbench_view is not None:
                    self._workbench_view.hide()
                self.launch_button.show()
            self.stop_button.setEnabled(state in ("starting", "running", "installing"))
            self.install_button.setEnabled(not self.controller.active)
            self._set_path_entry_busy(self.workspace, self.controller.active)

        def _refresh_skills(self):
            self.skill_list.clear()
            for folder, label in ((self.controller.runtime / "toolkit-skills", "内置"),
                    (self.controller.home / "skills", "已启用"),
                    (self.controller.home / "skills-disabled", "已停用")):
                if not folder.is_dir():
                    continue
                for path in sorted(folder.iterdir()):
                    md = path / "SKILL.md"
                    if not md.is_file():
                        continue
                    item = QListWidgetItem(f"{path.name}  ·  {label}")
                    item.setData(Qt.ItemDataRole.UserRole, (str(path), label))
                    self.skill_list.addItem(item)
            if self.skill_list.count():
                self.skill_list.setCurrentRow(0)
            else:
                self.toggle_button.setEnabled(False)

        def set_theme(self, dark):
            color = "#93c5fd" if dark else "#1d4ed8"
            background = "rgba(96,165,250,0.14)" if dark else "rgba(37,99,235,0.10)"
            border = "rgba(147,197,253,0.22)" if dark else "rgba(37,99,235,0.16)"
            self.harness_badge.setStyleSheet(
                f"QLabel#harness_badge {{color:{color};background:{background};border:1px solid {border};"
                "border-radius:8px;padding:2px 8px;font-size:10pt;font-weight:500;}"
            )
            if self._workbench_view is not None:
                self._workbench_view.set_theme(dark)

        def _show_skill(self, item, previous=None):
            self.skill_text.clear()
            self.toggle_button.setEnabled(False)
            if item is None:
                return
            path, label = item.data(Qt.ItemDataRole.UserRole)
            try:
                md = Path(path) / "SKILL.md"
                if md.stat().st_size > 1_000_000:
                    raise ValueError("说明文件过大，请在编辑器中查看。")
                self.skill_text.setPlainText(md.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                self.skill_text.setPlainText(str(exc))
            self.toggle_button.setEnabled(label != "内置")
            self.toggle_button.setText("启用技能" if label == "已停用" else "停用技能")

        def _import(self):
            source = QFileDialog.getExistingDirectory(self, "选择包含 SKILL.md 的技能文件夹")
            if not source:
                return
            try:
                name = import_skill(Path(source), self.controller.home, self.controller.runtime)
                self._refresh_skills()
                ui.stitch_msg_information(self, "技能已导入", f"{name} 已加入本地技能库。\n原生工作台会在后续模型步骤中刷新技能目录。")
            except Exception as exc:
                ui.stitch_msg_warning(self, "导入失败", str(exc))

        def _toggle(self):
            item = self.skill_list.currentItem()
            if not item:
                return
            path, label = item.data(Qt.ItemDataRole.UserRole)
            if label == "内置":
                return
            try:
                set_enabled(self.controller.home, Path(path).name, label == "已停用")
                self._refresh_skills()
            except (OSError, ValueError) as exc:
                ui.stitch_msg_warning(self, "技能状态未修改", str(exc))

        def stop_for_close(self):
            self._close_requested = True
            self.controller.stop()

        def _after_finish(self):
            if self._workbench_view is not None:
                self._workbench_view.runtime_stopped()
            if self._close_requested:
                main.close()

        def dispose_workbench(self):
            if self._workbench_view is not None:
                self._workbench_view.dispose()
                self._workbench_view.deleteLater()
                self._workbench_view = None

    return HarnessPage()
