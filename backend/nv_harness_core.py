"""Desktop ownership of an unmodified, pinned DeepSeek Harness CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

PINNED_VERSION = "0.1.2-rc.1"


def runtime_paths(resource_dir: Path, data_dir: Path) -> tuple[Path, Path]:
    # Release installs use a sidecar, never unpack thousands of npm files per launch.
    sidecar = data_dir / "harness_runtime"
    runtime = sidecar if (sidecar / "package.json").is_file() else resource_dir / "harness_runtime"
    return runtime.resolve(), (data_dir / ".harness-data").resolve()


def installed_version(runtime: Path) -> str | None:
    try:
        return json.loads((runtime / "node_modules/@deepseek-ai/dsh/package.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None


def redact_log(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = re.sub(r"([?&]token=)[^\s&#]+", r"\1[hidden]", text)
    return re.sub(r"(Bearer\s+)\S+", r"\1[hidden]", text, flags=re.I)


def prepare_environment(runtime: Path, home: Path, data_dir: Path, resource_dir: Path) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--harness-tool-worker"]
    else:
        command = [sys.executable, str(resource_dir / "nv_harness_tools.py")]
    env = dict(os.environ)
    env.update(DSH_HOME=str(home), DSH_AGENTS_HOME=str(home / "agents"),
               NV_HARNESS_MANAGED="1", NV_TOOLKIT_COMMAND=json.dumps(command),
               NV_TOOLKIT_DATA_DIR=str(data_dir), PYTHONIOENCODING="utf-8")
    # The overlay only inserts our tools and a bundled skill source. No upstream rows are removed.
    patch = [{"insert": [
        {"id": "nv-toolkit-tools", "name": (runtime / "toolkit-plugin/index.mjs").as_uri()},
        {"id": "nv-toolkit-skills", "name": "@deepseek-ai/dsh-skill-filesystem", "config": {
            "providerName": "nv-toolkit", "includeDefaultRoots": False,
            "customSkillDirs": [str(runtime / "toolkit-skills")], "watch": True}},
    ]}]
    # JSON is a YAML subset; all paths are serialized, not interpolated into executable YAML.
    (home / "toolkit.patch.yml").write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")
    web_patch = [
        {"id": "ui-brand-official", "disabled": True},
        {"insert": [{"id": "nv-toolkit-brand", "name": (runtime / "toolkit-brand" / "index.mjs").resolve().as_uri()}]},
    ]
    (home / "toolkit-web.patch.yml").write_text(json.dumps(web_patch, indent=2), encoding="utf-8")
    return env


class HarnessController(QObject):
    state_changed = Signal(str)
    log_line = Signal(str)
    ready = Signal(str)
    finished = Signal()

    def __init__(self, resource_dir: Path, data_dir: Path, parent=None):
        super().__init__(parent)
        self.resource_dir, self.data_dir = resource_dir, data_dir
        self.runtime, self.home = runtime_paths(resource_dir, data_dir)
        self.state = "stopped"
        self.url = ""
        self._buffer = ""
        self._job = None
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.started.connect(self._started)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._force_stop)
        self.start_deadline = QTimer(self)
        self.start_deadline.setSingleShot(True)
        self.start_deadline.timeout.connect(self._start_timeout)

    @property
    def active(self):
        return self.state in ("starting", "running", "stopping", "installing")

    def _state(self, state):
        self.state = state
        self.state_changed.emit(state)

    def start(self, workspace: str):
        if self.active:
            return
        try:
            node = shutil.which("node")
            if not node:
                raise ValueError("未找到 Node.js，请安装 Node.js 24 LTS 后重新打开软件。")
            if installed_version(self.runtime) != PINNED_VERSION:
                raise ValueError("Harness 尚未安装或版本不符，请点击“安装固定版本”。")
            root = Path(workspace).expanduser().resolve()
            if not root.is_dir():
                raise ValueError("请选择存在的工作文件夹。")
            env = prepare_environment(self.runtime, self.home, self.data_dir, self.resource_dir)
            self._launch(node, ["--import", (self.runtime / "lifecycle.mjs").as_uri(),
                str(self.runtime / "node_modules/@deepseek-ai/dsh/lib/bin.js"),
                "web", "--patch", str(self.home / "toolkit.patch.yml"),
                "--patch", str(self.home / "toolkit-web.patch.yml"),
                "--host", "127.0.0.1", "--port", "0", "--no-open"], env, root, "starting")
            self.start_deadline.start(90_000)
        except (OSError, ValueError) as exc:
            self.log_line.emit(str(exc))
            self._state("failed")

    def install(self):
        if self.active:
            return
        # Invoke npm's JS entry directly: no cmd quoting and no global npm modifications.
        node = shutil.which("node")
        npm = Path(node).parent / "node_modules/npm/bin/npm-cli.js" if node else Path("")
        if not npm.is_file():
            self.log_line.emit("未找到 Node 附带的 npm。请安装 Node.js 24 LTS，或在 harness_runtime 中执行 npm ci。")
            self._state("failed")
            return
        if not (self.runtime / "package-lock.json").is_file():
            self.log_line.emit("运行时目录缺少锁定文件，请重新复制完整 harness_runtime 目录。")
            self._state("failed")
            return
        self._launch(node, [str(npm), "ci", "--no-audit", "--no-fund"], dict(os.environ), self.runtime, "installing")

    def _launch(self, executable, arguments, env, cwd, state):
        self.url, self._buffer = "", ""
        qenv = QProcessEnvironment()
        for key, value in env.items():
            qenv.insert(key, value)
        self.process.setProcessEnvironment(qenv)
        self.process.setWorkingDirectory(str(cwd))
        self._state(state)
        self.process.start(executable, arguments)

    def _started(self):
        if sys.platform == "win32":
            # Kill only our owned process tree if the desktop crashes or shutdown times out.
            try:
                import win32api, win32con, win32job
                job = win32job.CreateJobObject(None, "")
                info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
                info["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
                handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, int(self.process.processId()))
                try:
                    win32job.AssignProcessToJobObject(job, handle)
                finally:
                    handle.Close()
                self._job = job
            except Exception:
                if 'job' in locals():
                    job.Close()
                self.log_line.emit("无法建立 Windows 子进程回收组，停止启动。请检查 pywin32 与运行环境。")
                self.process.kill()

    def _read(self):
        self._buffer += bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            match = re.search(r"dsh web: (http://127\.0\.0\.1:\d+/\?token=[^\s]+)", line)
            if match and self.state == "starting":
                self.url = match.group(1)
                self.start_deadline.stop()
                self._state("running")
                self.ready.emit(self.url)
            self.log_line.emit(redact_log(line.rstrip()))
        if len(self._buffer) > 20000:
            self.log_line.emit(redact_log(self._buffer[:20000]))
            self._buffer = ""

    def stop(self):
        if not self.active or self.state == "stopping":
            return
        installing = self.state == "installing"
        self._state("stopping")
        self.start_deadline.stop()
        if installing:
            self._force_stop()
        else:
            self.process.write(b"shutdown\n")
            self.deadline.start(15000)

    def _force_stop(self):
        if self._job is not None:
            self._job.Close()
            self._job = None
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _start_timeout(self):
        self.log_line.emit("启动超过 90 秒，正在回收进程。请检查日志后重试。")
        self.stop()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.start_deadline.stop()
            self.log_line.emit("无法启动运行时：" + self.process.errorString())
            self._state("failed")
            self.finished.emit()

    def _finished(self, code, status):
        previous = self.state
        self._read()
        self.deadline.stop()
        self.start_deadline.stop()
        self.url = ""
        if self._buffer:
            self.log_line.emit(redact_log(self._buffer))
            self._buffer = ""
        if self._job is not None:
            self._job.Close()
            self._job = None
        failed = code != 0 and previous != "stopping"
        self._state("failed" if failed else "stopped")
        self.log_line.emit(f"进程已结束（退出码 {code}）。")
        if previous == "installing" and not failed:
            self.log_line.emit("固定版本安装完成，可以启动工作台。")
        self.finished.emit()
