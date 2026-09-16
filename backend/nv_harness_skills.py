"""Manage native SKILL.md bundles without adding a competing skill format."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def import_skill(source: Path, home: Path, runtime: Path) -> str:
    source = source.absolute()
    if source.resolve() == home.resolve() or source.resolve() in home.resolve().parents:
        raise ValueError("技能源文件夹不能包含 Harness 数据目录，请选择独立的技能包。")
    if not source.is_dir() or source.is_symlink() or getattr(source, "is_junction", lambda: False)():
        raise ValueError("请选择包含 SKILL.md 的普通文件夹。")
    paths = list(source.rglob("*"))
    if len(paths) > 2000 or any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in paths):
        raise ValueError("技能包过大或包含链接目录，请整理后再导入。")
    if sum(p.stat().st_size for p in paths if p.is_file()) > 50_000_000:
        raise ValueError("技能包不能超过 50 MB。")
    md = source / "SKILL.md"
    if not md.is_file() or md.stat().st_size > 1_000_000:
        raise ValueError("技能包缺少 SKILL.md，或说明文件超过 1 MB。")
    node = shutil.which("node")
    if not node or not (runtime / "node_modules").is_dir():
        raise ValueError("请先安装 Harness 固定版本，以使用相同的技能格式校验。")
    checked = subprocess.run([node, str(runtime / "inspect-skill.mjs"), str(md)],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if checked.returncode:
        raise ValueError("技能格式校验失败：请检查 name、description 和调用开关。\n" + checked.stderr[:1200])
    name = json.loads(checked.stdout)["name"]
    for root in (home / "skills", home / "skills-disabled", runtime / "toolkit-skills"):
        if (root / name).exists():
            raise ValueError(f"已存在同名技能 {name}，请先更改技能名称。")
    destination = home / "skills" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".skill-import-", dir=home) as temporary:
        staged = Path(temporary) / name
        shutil.copytree(source, staged)
        staged.rename(destination)
    return name


def set_enabled(home: Path, name: str, enabled: bool) -> None:
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("无效技能名称")
    source = home / ("skills-disabled" if enabled else "skills") / name
    target = home / ("skills" if enabled else "skills-disabled") / name
    if not source.is_dir() or source.is_symlink() or getattr(source, "is_junction", lambda: False)():
        raise ValueError("技能目录不可用")
    if target.exists():
        raise ValueError("目标目录存在同名技能")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
