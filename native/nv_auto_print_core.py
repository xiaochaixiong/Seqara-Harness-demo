# -*- coding: utf-8 -*-
"""
Auto print workflow core (from RapidPrint 1.4.1, no GUI).
Requires: watchdog pywin32 Pillow PyPDF2
"""

from __future__ import annotations

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    FileSystemEvent = object  # type: ignore
    FileSystemEventHandler = object  # type: ignore
    Observer = None  # type: ignore

WATCHDOG_AVAILABLE = Observer is not None



import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# 路径与会话
# ---------------------------------------------------------------------------


def desktop_dir() -> Path:
    base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    for name in ("Desktop", "桌面"):
        p = Path(base) / name
        if p.is_dir():
            return p
    return Path(base)


RAPIDPRINT_FOLDER_PREFIX = "WeComRapidPrint_1.4_"


def is_rapidprint_session_dir(path: Path) -> bool:
    return path.is_dir() and path.name.startswith(RAPIDPRINT_FOLDER_PREFIX)


def list_rapidprint_folders(base: Optional[Path] = None) -> list[Path]:
    root = base if base is not None else desktop_dir()
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.iterdir() if is_rapidprint_session_dir(p)),
        key=lambda p: p.name,
    )


def cleanup_rapidprint_folders(
    base: Optional[Path] = None,
    *,
    keep: Optional[Path] = None,
) -> tuple[int, list[str]]:
    """删除桌面（或指定目录）下所有 WeComRapidPrint_1.4_* 临时文件夹。"""
    keep_resolved = keep.resolve() if keep is not None else None
    removed = 0
    errors: list[str] = []
    for folder in list_rapidprint_folders(base):
        try:
            if keep_resolved is not None and folder.resolve() == keep_resolved:
                continue
        except OSError:
            pass
        try:
            shutil.rmtree(folder)
            removed += 1
        except OSError as e:
            errors.append(f"{folder.name}: {e}")
    return removed, errors


def new_session_folder() -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    root = desktop_dir()
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{RAPIDPRINT_FOLDER_PREFIX}{stamp}_", dir=root))


def find_sumatra_pdf() -> Optional[Path]:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "SumatraPDF"
        / "SumatraPDF.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "SumatraPDF"
        / "SumatraPDF.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "SumatraPDF" / "SumatraPDF.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    try:
        import winreg  # type: ignore

        for root in (
            winreg.HKEY_LOCAL_MACHINE,
            winreg.HKEY_CURRENT_USER,
        ):
            for sub in (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\SumatraPDF.exe",
                r"SOFTWARE\SUMATRAPDF",
            ):
                try:
                    key = winreg.OpenKey(root, sub)
                    path, _ = winreg.QueryValueEx(key, "") if sub.endswith(
                        "SumatraPDF.exe"
                    ) else winreg.QueryValueEx(key, "Path")
                    winreg.CloseKey(key)
                    exe = Path(path)
                    if exe.is_file():
                        return exe
                except OSError:
                    continue
    except Exception:
        pass
    return None


def find_libreoffice_soffice() -> Optional[Path]:
    """LibreOffice 的 soffice.com / soffice.exe，用于无界面 docx→pdf。"""
    for root in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "LibreOffice"
        / "program",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "LibreOffice"
        / "program",
    ):
        com = root / "soffice.com"
        if com.is_file():
            return com
        exe = root / "soffice.exe"
        if exe.is_file():
            return exe
    return None


def docx_to_pdf_libreoffice(src: Path, dest: Path, soffice: Path) -> tuple[bool, str]:
    """用 LibreOffice 独立排版引擎转 PDF（与微软 Word 分页常不一致，可作对照/替代）。"""
    try:
        if dest.is_file():
            dest.unlink()
    except OSError:
        pass
    td = Path(tempfile.mkdtemp(prefix="lox_"))
    try:
        prof = td / "profile"
        prof.mkdir(parents=True, exist_ok=True)
        prof_uri = prof.as_uri()
        inch = td / f"in_{time.time_ns()}.docx"
        shutil.copy2(src, inch)
        cmd = [
            str(soffice),
            f"-env:UserInstallation={prof_uri}",
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--invisible",
            "--convert-to",
            "pdf",
            "--outdir",
            str(td),
            str(inch),
        ]
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        produced = inch.with_suffix(".pdf")
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or "").strip() or f"exit {r.returncode}"
            return False, f"LibreOffice: {msg}"
        if not produced.is_file() or produced.stat().st_size == 0:
            return False, "LibreOffice 未生成有效 PDF"
        shutil.move(str(produced), str(dest))
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def filename_matches_receipt_keywords(path: Path, extra_csv: str) -> bool:
    """根据文件名识别常见单据（签收单等），用于自动走 WPS。"""
    name = path.name
    for k in ("签收单",):
        if k in name:
            return True
    for part in (extra_csv or "").split(","):
        t = part.strip()
        if t and t in name:
            return True
    return False


def wps_print_direct(
    path: Path,
    *,
    flatten_float_pics: bool = True,
) -> tuple[bool, str]:
    """WPS 打开后走打印引擎直接送默认打印机（不经 PDF/Sumatra）。无单独「监听打印」API，等同自动化点打印。"""
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    pythoncom.CoInitialize()
    app = None
    doc = None
    try:
        for pid in (
            "Kwps.Application",
            "KWPS.Application",
            "wps.Application",
            "WPS.Application",
        ):
            try:
                app = win32com.client.Dispatch(pid)
                if app is not None:
                    break
            except Exception:
                app = None
        if app is None:
            return False, "未检测到 WPS 文字或 COM 未注册"
        try:
            app.Visible = False
        except Exception:
            pass
        doc = app.Documents.Open(str(path.resolve()), ReadOnly=False)
        if flatten_float_pics:
            _word_inline_floating_pictures(doc)
            try:
                doc.Repaginate()
            except Exception:
                pass
            time.sleep(0.12)
        doc.PrintOut()
        doc.Close(False)
        doc = None
        try:
            app.Quit()
        except Exception:
            pass
        app = None
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _wps_silence_ui(app: object) -> None:
    """尽量关闭 WPS 文字界面与提示（图片、PDF 打开等共用）。"""
    try:
        app.DisplayAlerts = 0
    except Exception:
        pass
    try:
        app.ScreenUpdating = False
    except Exception:
        pass
    try:
        app.Visible = False
    except Exception:
        pass


def _wps_dispatch_word_app() -> Optional[object]:
    import win32com.client  # type: ignore

    for pid in (
        "Kwps.Application",
        "KWPS.Application",
        "wps.Application",
        "WPS.Application",
    ):
        try:
            app = win32com.client.Dispatch(pid)
            if app is not None:
                return app
        except Exception:
            continue
    return None


def _wps_try_exit_protected_view(app: object) -> None:
    try:
        if int(app.ProtectedViewWindows.Count) > 0:
            app.ProtectedViewWindows(1).Edit()
    except Exception:
        pass


def wps_print_image_embedded(path: Path) -> tuple[bool, str]:
    """常见图片：WPS 文字新建文档、嵌入图后 PrintOut（静默，不经画图）。"""
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    pythoncom.CoInitialize()
    app = None
    doc = None
    try:
        for pid in (
            "Kwps.Application",
            "KWPS.Application",
            "wps.Application",
            "WPS.Application",
        ):
            try:
                app = win32com.client.Dispatch(pid)
                if app is not None:
                    break
            except Exception:
                app = None
        if app is None:
            return False, "未检测到 WPS 文字或 COM 未注册"
        _wps_silence_ui(app)
        doc = app.Documents.Add()
        if doc is None:
            return False, "WPS Documents.Add 返回空"
        rng = doc.Range(0, 0)
        doc.InlineShapes.AddPicture(
            str(path.resolve()),
            False,
            True,
            rng,
        )
        time.sleep(0.18)
        doc.PrintOut()
        doc.Close(False)
        doc = None
        try:
            app.Quit()
        except Exception:
            pass
        app = None
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def wps_print_pdf_open(path: Path) -> tuple[bool, str]:
    """PDF：多种 Open 参数尝试 PrintOut；部分 WPS 对从文字打开 PDF 会返回 None。"""
    import pythoncom  # type: ignore

    pythoncom.CoInitialize()
    app = None
    last_err = "未知错误"
    try:
        app = _wps_dispatch_word_app()
        if app is None:
            return False, "未检测到 WPS 文字或 COM 未注册"
        _wps_silence_ui(app)

        open_variants: list[dict[str, object]] = [
            dict(
                ReadOnly=True,
                ConfirmConversions=False,
                AddToRecentFiles=False,
            ),
            dict(
                ReadOnly=False,
                ConfirmConversions=False,
                AddToRecentFiles=False,
            ),
            dict(
                ReadOnly=True,
                ConfirmConversions=True,
                AddToRecentFiles=False,
            ),
            dict(
                ReadOnly=False,
                ConfirmConversions=True,
                AddToRecentFiles=False,
            ),
        ]

        for kw in open_variants:
            doc = None
            try:
                _wps_silence_ui(app)
                doc = app.Documents.Open(str(path.resolve()), **kw)
                if doc is None:
                    last_err = "Documents.Open 返回 None（WPS 可能不支持从文字打开此 PDF）"
                    continue
                _wps_try_exit_protected_view(app)
                time.sleep(0.2)
                doc.PrintOut()
                doc.Close(False)
                doc = None
                try:
                    app.Quit()
                except Exception:
                    pass
                app = None
                return True, ""
            except Exception as e:
                last_err = str(e)
                if doc is not None:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass
                    doc = None
                continue

        try:
            app.Quit()
        except Exception:
            pass
        app = None
        return False, last_err
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def wps_export_to_pdf(
    src: Path,
    dest: Path,
    *,
    flatten_float_pics: bool = True,
) -> tuple[bool, str]:
    """用本机 WPS 文字 COM 导出 PDF（排版常接近你在 WPS 里看到的）。"""
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    try:
        if dest.is_file():
            dest.unlink()
    except OSError:
        pass
    dest_abs = str(dest.resolve())
    pythoncom.CoInitialize()
    app = None
    doc = None
    try:
        for pid in (
            "Kwps.Application",
            "KWPS.Application",
            "wps.Application",
            "WPS.Application",
        ):
            try:
                app = win32com.client.Dispatch(pid)
                if app is not None:
                    break
            except Exception:
                app = None
        if app is None:
            return False, "未检测到 WPS 文字或 COM 未注册（可安装 WPS 后重试）"
        try:
            app.Visible = False
        except Exception:
            pass
        doc = app.Documents.Open(str(src.resolve()), ReadOnly=False)
        if flatten_float_pics:
            _word_inline_floating_pictures(doc)
        ok_export = False
        try:
            doc.ExportAsFixedFormat(
                OutputFileName=dest_abs,
                ExportFormat=17,
                OpenAfterExport=False,
                OptimizeFor=0,
                BitmapMissingFonts=True,
                IncludeDocProps=False,
                CreateBookmarks=0,
                DocStructureTags=False,
            )
            ok_export = True
        except Exception:
            for fmt in (17, 18, 13):
                try:
                    doc.SaveAs2(
                        FileName=dest_abs, FileFormat=fmt, AddToRecentFiles=False
                    )
                    ok_export = True
                    break
                except Exception:
                    continue
        if not ok_export:
            return False, "WPS 不支持当前环境的 PDF 导出方式"
        doc.Close(False)
        doc = None
        try:
            app.Quit()
        except Exception:
            pass
        app = None
        if not dest.is_file() or dest.stat().st_size == 0:
            return False, "WPS 导出后 PDF 为空"
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def docx_convert_to_pdf(
    src: Path,
    dest: Path,
    engine: str,
    *,
    compact_one_page: bool,
    flatten_float_pics: bool,
) -> tuple[bool, str]:
    """docx → 临时 PDF。engine: word | libreoffice | wps"""
    eng = (engine or "word").strip().lower()
    if eng == "libreoffice":
        lo = find_libreoffice_soffice()
        if not lo:
            return False, "未找到 LibreOffice，请从 https://www.libreoffice.org 安装"
        return docx_to_pdf_libreoffice(src, dest, lo)
    if eng == "wps":
        return wps_export_to_pdf(
            src, dest, flatten_float_pics=flatten_float_pics
        )
    return word_export_to_pdf(
        src,
        dest,
        compact_one_page=compact_one_page,
        flatten_float_pics=flatten_float_pics,
    )


# ---------------------------------------------------------------------------
# PDF 方向（竖版发票误识别时可勾选强制竖版）
# ---------------------------------------------------------------------------


def pdf_print_orientation(path: Path, force: Optional[str] = None) -> str:
    if force in ("portrait", "landscape"):
        return force
    try:
        from PyPDF2 import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        if not reader.pages:
            return "portrait"
        box = reader.pages[0].mediabox
        w, h = float(box.width), float(box.height)
        return "landscape" if w > h else "portrait"
    except Exception:
        return "portrait"


def print_pdf(
    path: Path,
    sumatra: Path,
    force_orientation: Optional[str] = None,
    *,
    scale: str = "shrink",
) -> tuple[bool, str]:
    """scale 见 Sumatra -print-settings：shrink / fit / noscale（与方向组合）。"""
    ori = pdf_print_orientation(path, force_orientation)
    orient = "landscape" if ori == "landscape" else "portrait"
    sm = scale.lower().strip()
    if sm not in ("noscale", "shrink", "fit"):
        sm = "shrink"
    settings = f"{sm},{orient}"
    cmd = [
        str(sumatra),
        "-silent",
        "-print-to-default",
        "-print-settings",
        settings,
        str(path),
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if r.returncode != 0:
            return False, r.stderr or r.stdout or f"exit {r.returncode}"
        return True, ""
    except Exception as e:
        return False, str(e)


def _word_exit_protected_view(word: object) -> None:
    """从「受保护的视图」进入可编辑，否则签章/图片版式常与 WPS 不一致。"""
    try:
        if word.ProtectedViewWindows.Count > 0:
            word.ProtectedViewWindows(1).Edit()
    except Exception:
        pass


def _word_prepare_layout(doc: object, word: object) -> None:
    """打印版式、100% 缩放、显示背景/图形并重分页，避免签章与正文相对错位。

    Word 在非 100% 缩放或隐藏背景时导出的 PDF，常见「签章与文字一起偏」。
    """
    try:
        word.PrintCommunication = True
    except Exception:
        pass
    try:
        word.Options.PrintDraft = False
    except Exception:
        pass
    try:
        doc.Activate()
    except Exception:
        pass
    try:
        w = doc.Windows(1)
        v = w.View
        v.Type = 3  # wdPrintView 打印版式
        try:
            v.DisplayBackgrounds = True
        except Exception:
            pass
        try:
            v.ShowDrawings = True
        except Exception:
            pass
        try:
            z = v.Zoom
            z.Type = 0  # wdZoomPercentage
            z.Percentage = 100
        except Exception:
            pass
    except Exception:
        pass
    try:
        word.ScreenUpdating = True
        doc.Repaginate()
    except Exception:
        pass
    try:
        word.ScreenUpdating = False
    except Exception:
        pass
    time.sleep(0.35)


def _word_page_count(doc: object) -> int:
    try:
        return max(1, int(doc.ComputeStatistics(2)))  # wdStatisticPages = 2
    except Exception:
        return 1


def _word_inline_floating_pictures(doc: object) -> None:
    """浮动图片/签章改为嵌入型，避免紧密环绕+大偏移导致 Word 预留过高竖区、签章整段掉到第二页。

    对 docx 内 msoPicture / msoLinkedPicture 的 Shapes 从后往前 ConvertToInlineShape。
    """
    try:
        n = int(doc.Shapes.Count)
    except Exception:
        return
    # msoLinkedPicture=11, msoPicture=13
    pic_types = frozenset((11, 13))
    for i in range(n, 0, -1):
        try:
            shp = doc.Shapes(i)
            if int(shp.Type) not in pic_types:
                continue
            shp.ConvertToInlineShape()
        except Exception:
            continue


def _word_try_shrink_one_page_mso(
    doc: object,
    word: object,
    *,
    max_initial_pages: int = 4,
) -> None:
    """执行 Word「减少一页」(ShrinkOnePage)，把多出的末尾页（常见为签章顶下去）压回上一页。

    仅当当前总页数 <= max_initial_pages 时处理，避免误伤长文档。
    """
    try:
        n0 = _word_page_count(doc)
        if n0 <= 1 or n0 > max_initial_pages:
            return
        try:
            word.ActiveWindow.Activate()
        except Exception:
            pass
        mso_ids = ("ShrinkOnePage", "FilePrintShrinkOnePage")
        for _ in range(8):
            n_before = _word_page_count(doc)
            if n_before <= 1:
                break
            executed = False
            for mid in mso_ids:
                try:
                    word.CommandBars.ExecuteMso(mid)
                    executed = True
                    break
                except Exception:
                    continue
            if not executed:
                break
            time.sleep(0.2)
            try:
                doc.Repaginate()
            except Exception:
                pass
            n_after = _word_page_count(doc)
            if n_after <= 1:
                break
            if n_after >= n_before:
                break
    except Exception:
        pass


def word_export_to_pdf(
    src: Path,
    dest: Path,
    *,
    compact_one_page: bool = True,
    flatten_float_pics: bool = True,
) -> tuple[bool, str]:
    """后台用 Word 将文档导出为 PDF（不打开预览窗）。

    含电子签章、透明 PNG 等时：只读打开有时版式不完整，故用可写内存打开但不存盘；
    先 ExportAsFixedFormat，失败或空文件再 SaveAs2。
    compact_one_page：少页时对 Word 执行「减少一页」，减轻签章区被单独挤到第二页。
    flatten_float_pics：将浮动式图片改为嵌入型，减轻签章图「紧密环绕+大偏移」撑出第二页。
    """
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    pythoncom.CoInitialize()
    word = None
    doc = None
    dest_abs = str(dest.resolve())
    try:
        if dest.is_file():
            dest.unlink()
    except OSError:
        pass
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            word.ScreenUpdating = False
            word.WindowState = 2  # wdWindowStateMinimize，减轻闪屏
        except Exception:
            pass
        # ReadOnly=False：签章/嵌入图在只读下偶发分页与 WPS/手工不一致；关闭时不保存原文件
        doc = word.Documents.Open(
            str(src.resolve()),
            ReadOnly=False,
            ConfirmConversions=False,
            AddToRecentFiles=False,
        )
        _word_exit_protected_view(word)
        _word_prepare_layout(doc, word)
        if flatten_float_pics:
            _word_inline_floating_pictures(doc)
            try:
                doc.Repaginate()
            except Exception:
                pass
            time.sleep(0.12)
        if compact_one_page:
            _word_try_shrink_one_page_mso(doc, word)

        errs: list[str] = []

        def _unlink_dest() -> None:
            try:
                if dest.is_file():
                    dest.unlink()
            except OSError:
                pass

        # 路径 A：ExportAsFixedFormat（固定版式几何通常更稳，利于签章与文字对齐）
        _unlink_dest()
        try:
            doc.ExportAsFixedFormat(
                OutputFileName=dest_abs,
                ExportFormat=17,
                OpenAfterExport=False,
                OptimizeFor=0,
                BitmapMissingFonts=True,
                IncludeDocProps=False,
                CreateBookmarks=0,
                DocStructureTags=False,
            )
            if dest.is_file() and dest.stat().st_size > 0:
                doc.Close(False)
                doc = None
                word.Quit()
                word = None
                return True, ""
        except Exception as e:
            errs.append(f"Export:{e}")
        _unlink_dest()

        # 路径 B：SaveAs2（导出失败或空文件时再试）
        try:
            doc.SaveAs2(FileName=dest_abs, FileFormat=17, AddToRecentFiles=False)
            if dest.is_file() and dest.stat().st_size > 0:
                doc.Close(False)
                doc = None
                word.Quit()
                word = None
                return True, ""
        except Exception as e:
            errs.append(f"SaveAs2:{e}")
        doc.Close(False)
        doc = None
        word.Quit()
        word = None
        if dest.is_file() and dest.stat().st_size > 0:
            return True, ""
        tail = "; ".join(errs)
        return False, ("导出 PDF 为空或不存在" + (f"; {tail}" if tail else ""))
    except Exception as e:
        return False, str(e)
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def print_word_direct(
    path: Path,
    *,
    compact_one_page: bool = True,
    flatten_float_pics: bool = True,
) -> tuple[bool, str]:
    """直接用 Word 打印（旧方式，偶有不全或前台感卡顿）。"""
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            word.ScreenUpdating = False
            word.WindowState = 2
        except Exception:
            pass
        doc = word.Documents.Open(
            str(path.resolve()),
            ReadOnly=False,
            ConfirmConversions=False,
            AddToRecentFiles=False,
        )
        _word_exit_protected_view(word)
        _word_prepare_layout(doc, word)
        if flatten_float_pics:
            _word_inline_floating_pictures(doc)
            try:
                doc.Repaginate()
            except Exception:
                pass
            time.sleep(0.12)
        if compact_one_page:
            _word_try_shrink_one_page_mso(doc, word)
        try:
            doc.PrintOut()
        finally:
            doc.Close(False)
        word.Quit()
        word = None
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def print_word(
    path: Path,
    sumatra: Optional[Path],
    pdf_force: Optional[str],
    prefer_pdf_route: bool,
    pdf_scale: str = "shrink",
    compact_one_page: bool = True,
    docx_pdf_engine: str = "word",
    flatten_float_pics: bool = True,
) -> tuple[bool, str]:
    """优先：docx 转临时 PDF → Sumatra 静默打印；否则直接 PrintOut。"""
    if prefer_pdf_route and sumatra is not None:
        pdf_tmp = path.parent / f"_rapidprint_{time.time_ns()}.pdf"
        try:
            ok, err = docx_convert_to_pdf(
                path,
                pdf_tmp,
                docx_pdf_engine,
                compact_one_page=compact_one_page,
                flatten_float_pics=flatten_float_pics,
            )
            if not ok:
                return False, err
            return print_pdf(pdf_tmp, sumatra, pdf_force, scale=pdf_scale)
        finally:
            try:
                if pdf_tmp.is_file():
                    pdf_tmp.unlink()
            except OSError:
                pass
    if (docx_pdf_engine or "").strip().lower() == "wps":
        return wps_print_direct(path, flatten_float_pics=flatten_float_pics)
    return print_word_direct(
        path,
        compact_one_page=compact_one_page,
        flatten_float_pics=flatten_float_pics,
    )


_EXT_WORD = {".doc", ".docx"}
_EXT_IMG = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
_EXT_PDF = {".pdf"}
_EXT_ZIP = frozenset({".zip"})
_PRINTABLE_IN_ZIP = _EXT_WORD | _EXT_PDF | _EXT_IMG
_ZIP_MAX_ENTRIES = 400
_ZIP_MAX_TOTAL_UNCOMPRESSED = 120 * 1024 * 1024


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> tuple[list[Path], str]:
    """将 zip 解压到 dest_dir，返回解压出的文件路径列表（不含目录占位）；失败返回 ([], 原因)。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    root = dest_dir.resolve()
    extracted: list[Path] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if len(infos) > _ZIP_MAX_ENTRIES:
                return [], f"压缩内文件条目超过 {_ZIP_MAX_ENTRIES}，已中止"
            total = sum(max(0, i.file_size) for i in infos)
            if total > _ZIP_MAX_TOTAL_UNCOMPRESSED:
                return [], (
                    f"解压后总大小约 {total // (1024 * 1024)} MB，超过上限 "
                    f"{_ZIP_MAX_TOTAL_UNCOMPRESSED // (1024 * 1024)} MB，已中止"
                )
            destinations = set()
            for info in infos:
                normalized = '/'.join(part.rstrip('. ').casefold() for part in Path(info.filename).parts)
                if normalized in destinations:
                    return [], f'压缩包含同名文件，无法安全区分：{info.filename}；请改名后重试。'
                destinations.add(normalized)
            for info in infos:
                rel = Path(info.filename)
                if rel.is_absolute() or ".." in rel.parts:
                    continue
                target = (dest_dir / rel).resolve()
                try:
                    target.relative_to(root)
                except ValueError:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, open(target, "wb") as outf:
                    shutil.copyfileobj(src, outf, length=1024 * 1024)
                if target.is_file():
                    extracted.append(target)
        return extracted, ""
    except zipfile.BadZipFile as e:
        return [], f"ZIP 损坏或格式无效：{e}"
    except OSError as e:
        return [], str(e)
    except Exception as e:
        return [], str(e)


def is_office_lock_file(path: Path) -> bool:
    """Word/Excel 在文档打开时生成的锁文件，勿打印。"""
    return path.name.startswith("~$")


def is_browser_incomplete_download(path: Path) -> bool:
    """Chrome/Edge/Firefox 等下载未完成时的临时文件，勿打印。"""
    n = path.name.lower()
    if n.endswith(".crdownload") or n.endswith(".partial"):
        return True
    if path.suffix.lower() == ".part":
        return True
    return False


def wait_file_size_stable(
    path: Path,
    *,
    same_reads: int = 6,
    interval: float = 0.35,
    max_wait: float = 120.0,
    post_quiet: float = 0.55,
    cancel_event: Optional[threading.Event] = None,
) -> bool:
    """等到文件大小连续若干次不变且非零；再安静 post_quiet 秒复查，适配浏览器末段刷盘。"""
    deadline = time.time() + max_wait
    last: Optional[int] = None
    same = 0
    while time.time() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            return False
        try:
            sz = path.stat().st_size
        except OSError:
            return False
        if sz == 0:
            last, same = None, 0
            if cancel_event is not None:
                if cancel_event.wait(interval):
                    return False
            else:
                time.sleep(interval)
            continue
        if last == sz:
            same += 1
            if same >= same_reads:
                if cancel_event is not None:
                    if cancel_event.wait(post_quiet):
                        return False
                else:
                    time.sleep(post_quiet)
                try:
                    after = path.stat().st_size
                except OSError:
                    return False
                if after == last:
                    return True
                last, same = after, 1
        else:
            last = sz
            same = 1
        if cancel_event is not None:
            if cancel_event.wait(interval):
                return False
        else:
            time.sleep(interval)
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def dispatch_print_all_wps(
    path: Path,
    sumatra: Optional[Path],
    pdf_force: Optional[str],
    pdf_scale: str,
    log: Callable[[str], None],
    word_flatten_float_pics: bool,
) -> bool:
    """全 WPS 直打：Word 仅 WPS；PDF 先 WPS 多方式打开再直打，失败可 Sumatra；图片同默认 1.4。"""
    suf = path.suffix.lower()
    if suf in _EXT_WORD:
        if is_office_lock_file(path):
            log(f"[跳过] Office 锁文件（勿删）：{path.name}")
            return True
        ok, err = wps_print_direct(
            path, flatten_float_pics=word_flatten_float_pics
        )
        log(f"[WPS-全] Word {'OK' if ok else '失败'} {path.name} {err}")
        return ok
    if suf in _EXT_PDF:
        ok, err = wps_print_pdf_open(path)
        if ok:
            log(f"[WPS-全] PDF OK {path.name}")
            return True
        ok2, err2 = wps_print_direct(path, flatten_float_pics=False)
        if ok2:
            log(f"[WPS-全] PDF OK（文字二次打开）{path.name}")
            return True
        if not sumatra:
            log(
                f"[WPS-全] PDF 失败 {path.name} — WPS:{err!r}；二次:{err2!r}；"
                "无 SumatraPDF 无法备用静默打印"
            )
            return False
        ok3, err3 = print_pdf(path, sumatra, pdf_force, scale=pdf_scale)
        if ok3:
            log(f"[WPS-全] PDF OK（Sumatra 备用）{path.name}")
        else:
            log(
                f"[WPS-全] PDF 失败 {path.name} — WPS:{err!r}；二次:{err2!r}；"
                f"Sumatra:{err3!r}"
            )
        return ok3
    if suf in _EXT_IMG:
        ok, err = wps_print_image_embedded(path)
        log(f"[WPS-全] 图片 {'OK' if ok else '失败'} {path.name} {err}")
        return ok
    log(f"[跳过] 不支持的类型：{path.name}")
    return False


def dispatch_print(
    path: Path,
    sumatra: Optional[Path],
    pdf_force: Optional[str],
    log: Callable[[str], None],
    word_via_pdf: bool,
    pdf_scale: str,
    word_compact_one_page: bool,
    docx_pdf_engine: str,
    word_flatten_float_pics: bool,
    receipt_kw_csv: str,
    word_wps_direct_first: bool,
    wps_all_direct: bool = False,
) -> bool:
    if wps_all_direct:
        return dispatch_print_all_wps(
            path,
            sumatra,
            pdf_force,
            pdf_scale,
            log,
            word_flatten_float_pics,
        )
    suf = path.suffix.lower()
    if suf in _EXT_PDF:
        if not sumatra:
            log(f"[跳过] 未找到 SumatraPDF：{path.name}")
            return False
        ok, err = print_pdf(path, sumatra, pdf_force, scale=pdf_scale)
        log(f"[PDF] {'OK' if ok else '失败'} {path.name} {err}")
        return ok
    if suf in _EXT_WORD:
        if is_office_lock_file(path):
            log(f"[跳过] Office 锁文件（勿删）：{path.name}")
            return True
        receipt = filename_matches_receipt_keywords(path, receipt_kw_csv)
        eff_engine = (docx_pdf_engine or "word").strip().lower()
        if eff_engine not in ("word", "libreoffice", "wps"):
            eff_engine = "word"
        if receipt:
            eff_engine = "wps"
            log(f"[自动] 文件名含关键词，备用转 PDF 使用 WPS：{path.name}")
        if word_wps_direct_first:
            okd, errd = wps_print_direct(
                path, flatten_float_pics=word_flatten_float_pics
            )
            if okd:
                log(f"[WPS直打] OK {path.name}")
                return True
            log(f"[WPS直打] 失败 {path.name} {errd} → 改走转 PDF/备用")
        use_pdf = word_via_pdf and sumatra is not None
        if word_via_pdf and sumatra is None:
            log(f"[Word] 未检测到 SumatraPDF，改为 Word 直接打印：{path.name}")
        ok, err = print_word(
            path,
            sumatra,
            pdf_force,
            use_pdf,
            pdf_scale,
            compact_one_page=word_compact_one_page,
            docx_pdf_engine=eff_engine,
            flatten_float_pics=word_flatten_float_pics,
        )
        if use_pdf:
            sub = {"word": "Word", "libreoffice": "LibreOffice", "wps": "WPS"}.get(
                eff_engine, eff_engine
            )
            tag = f"[{sub}→PDF]"
        else:
            tag = "[Word]"
        log(f"{tag} {'OK' if ok else '失败'} {path.name} {err}")
        return ok
    if suf in _EXT_IMG:
        ok, err = wps_print_image_embedded(path)
        log(f"[WPS·图片] {'OK' if ok else '失败'} {path.name} {err}")
        return ok
    log(f"[跳过] 不支持的类型：{path.name}")
    return False


# ---------------------------------------------------------------------------
# 监听（去重 + 短暂等待文件写完）
# ---------------------------------------------------------------------------


class _PrintHandler(FileSystemEventHandler):
    def __init__(
        self,
        watch_root: Path,
        sumatra: Optional[Path],
        pdf_force: Callable[[], Optional[str]],
        word_via_pdf: Callable[[], bool],
        pdf_scale: Callable[[], str],
        word_compact_one_page: Callable[[], bool],
        docx_pdf_engine: Callable[[], str],
        word_flatten_float_pics: Callable[[], bool],
        receipt_kw_csv: Callable[[], str],
        word_wps_direct_first: Callable[[], bool],
        wps_all_direct: Callable[[], bool],
        log: Callable[[str], None],
        lock: threading.Lock,
        state_cb: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        super().__init__()
        self.watch_root = watch_root
        self.sumatra = sumatra
        self.pdf_force = pdf_force
        self.word_via_pdf = word_via_pdf
        self.pdf_scale = pdf_scale
        self.word_compact_one_page = word_compact_one_page
        self.docx_pdf_engine = docx_pdf_engine
        self.word_flatten_float_pics = word_flatten_float_pics
        self.receipt_kw_csv = receipt_kw_csv
        self.word_wps_direct_first = word_wps_direct_first
        self.wps_all_direct = wps_all_direct
        self.log = log
        self.lock = lock
        self.state_cb = state_cb
        self._printed: dict[str, tuple] = {}
        self._inflight: set[str] = set()
        self._pending: dict[str, threading.Timer] = {}
        self._attempts: dict[str, int] = {}
        self._stop_event = threading.Event()
        self._max_retries = 2
        self._empty_since: dict[str, float] = {}
        self._empty_timeout = 30.0
        self._zip_completed: dict[tuple, set[str]] = {}

    def stop(self) -> None:
        """停止接受新任务并取消尚未开始的延迟任务。"""
        self._stop_event.set()
        with self.lock:
            pending_keys = list(self._pending)
            timers = list(self._pending.values())
            self._pending.clear()
        for timer in timers:
            timer.cancel()
        if self.state_cb is not None:
            for key in pending_keys:
                self.state_cb("cancelled", key)

    def is_idle(self) -> bool:
        with self.lock:
            return not self._pending and not self._inflight

    def _process_zip_and_print(self, zip_path: Path) -> bool:
        dest_dir = self.watch_root / f"_unzipped_{zip_path.stem}_{time.time_ns()}"
        files, err = safe_extract_zip(zip_path, dest_dir)
        if err:
            self.log(f"[ZIP] {zip_path.name} — {err}")
            shutil.rmtree(dest_dir, ignore_errors=True)
            return False
        printable = [p for p in files if p.suffix.lower() in _PRINTABLE_IN_ZIP]
        if not printable:
            self.log(
                f"[ZIP] {zip_path.name} 内无 Word/PDF/图片可打印（共 {len(files)} 个文件）"
            )
            shutil.rmtree(dest_dir, ignore_errors=True)
            return True
        self.log(
            f"[ZIP] {zip_path.name} → 解压 {len(files)} 个文件，可打印 {len(printable)} 个"
        )
        signature = (str(zip_path.resolve()), zip_path.stat().st_size, zip_path.stat().st_mtime_ns)
        completed = self._zip_completed.setdefault(signature, set())
        all_ok = True
        for inner in sorted(printable, key=lambda p: str(p).lower()):
            if self._stop_event.is_set():
                all_ok = False
                self.log("[ZIP] 已停止，剩余文件不再发送打印。")
                break
            entry = str(inner.relative_to(dest_dir))
            if entry in completed:
                self.log(f"[ZIP内跳过] 已成功发送：{entry}")
                continue
            if is_office_lock_file(inner):
                self.log(f"[ZIP内跳过] 锁文件：{inner.name}")
                continue
            suf = inner.suffix.lower()
            if suf in _EXT_WORD | _EXT_PDF | _EXT_IMG:
                if not wait_file_size_stable(inner, cancel_event=self._stop_event):
                    self.log(f"[ZIP内跳过] 未稳定或空：{inner.name}")
                    all_ok = False
                    continue
            ok = dispatch_print(
                inner,
                self.sumatra,
                self.pdf_force(),
                self.log,
                self.word_via_pdf(),
                self.pdf_scale(),
                self.word_compact_one_page(),
                self.docx_pdf_engine(),
                self.word_flatten_float_pics(),
                self.receipt_kw_csv(),
                self.word_wps_direct_first(),
                self.wps_all_direct(),
            )
            if ok:
                completed.add(entry)
            all_ok = all_ok and ok
        shutil.rmtree(dest_dir, ignore_errors=True)
        self.log(f"[ZIP] 完成 {zip_path.name}，已清理临时解压目录")
        return all_ok

    @staticmethod
    def _file_version(path: Path):
        try:
            stat = path.stat()
            return stat.st_ino, stat.st_size, stat.st_mtime_ns
        except OSError:
            return None

    def _already_printed(self, key: str) -> bool:
        version = self._file_version(Path(key))
        return version is not None and self._printed.get(key) == version

    def _schedule(self, path: Path, delay: float = 1.0) -> None:
        if is_office_lock_file(path) or is_browser_incomplete_download(path):
            return
        if path.suffix.lower() not in _EXT_PDF | _EXT_WORD | _EXT_IMG | _EXT_ZIP:
            return
        key = str(path.resolve())
        with self.lock:
            if (
                self._stop_event.is_set()
                or self._already_printed(key)
                or key in self._inflight
                or key in self._pending
            ):
                return
            timer = threading.Timer(delay, self._run_scheduled, args=(key,))
            timer.daemon = True
            self._pending[key] = timer
            if self.state_cb is not None:
                self.state_cb("queued", key)
        timer.start()

    def _run_scheduled(self, key: str) -> None:
        with self.lock:
            self._pending.pop(key, None)
        self._try_print(key)

    def _try_print(self, key: str) -> None:
        retry_empty = False
        with self.lock:
            if self._stop_event.is_set() or self._already_printed(key) or key in self._inflight:
                return
            path = Path(key)
            if not path.is_file():
                if self.state_cb is not None:
                    self.state_cb("missing", key)
                return
            if is_office_lock_file(path) or is_browser_incomplete_download(path):
                return
            try:
                if path.stat().st_size == 0:
                    retry_empty = True
            except OSError:
                return
            if not retry_empty:
                self._inflight.add(key)
        if retry_empty:
            started = self._empty_since.setdefault(key, time.monotonic())
            if time.monotonic() - started >= self._empty_timeout:
                self._empty_since.pop(key, None)
                self.log(f"[失败] {path.name} 持续为空，已停止等待；下载完成后将重新检测。")
                if self.state_cb is not None:
                    self.state_cb("failed", key)
            else:
                self._schedule(path, 0.5)
            return
        self._empty_since.pop(key, None)

        suf = path.suffix.lower()
        success = False
        printed_version = None
        if self.state_cb is not None:
            self.state_cb("processing", key)
        try:
            if suf in _EXT_WORD | _EXT_PDF | _EXT_IMG | _EXT_ZIP:
                if not wait_file_size_stable(path, cancel_event=self._stop_event):
                    if not self._stop_event.is_set():
                        self.log(f"[跳过] 文件不可用或在等待时间内未稳定：{path.name}")
                    return
            if self._stop_event.is_set():
                return
            printed_version = self._file_version(path)
            if suf in _EXT_ZIP:
                success = self._process_zip_and_print(path)
            else:
                success = dispatch_print(
                    path,
                    self.sumatra,
                    self.pdf_force(),
                    self.log,
                    self.word_via_pdf(),
                    self.pdf_scale(),
                    self.word_compact_one_page(),
                    self.docx_pdf_engine(),
                    self.word_flatten_float_pics(),
                    self.receipt_kw_csv(),
                    self.word_wps_direct_first(),
                    self.wps_all_direct(),
                )
        except Exception as e:
            self.log(f"[打印异常] {path.name}: {e}")
        finally:
            retry_no = 0
            with self.lock:
                self._inflight.discard(key)
                if success:
                    self._printed[key] = printed_version
                    self._attempts.pop(key, None)
                elif not self._stop_event.is_set():
                    retry_no = self._attempts.get(key, 0) + 1
                    self._attempts[key] = retry_no
            if not success and not self._stop_event.is_set():
                if retry_no <= self._max_retries:
                    delay = 1.5 + retry_no * 1.5
                    self.log(
                        f"[重试] {path.name} 将在 {delay:.1f} 秒后重试 "
                        f"({retry_no}/{self._max_retries})"
                    )
                    self._schedule(path, delay)
                    if self.state_cb is not None:
                        self.state_cb("retrying", key)
                else:
                    with self.lock:
                        self._attempts.pop(key, None)
                    self.log(f"[失败] {path.name} 已达到重试上限，请检查日志后重新放入目录。")
            if self.state_cb is not None:
                if success:
                    self.state_cb("success", key)
                elif self._stop_event.is_set():
                    self.state_cb("cancelled", key)
                elif retry_no > self._max_retries:
                    self.state_cb("failed", key)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(Path(event.dest_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() in _EXT_PDF | _EXT_WORD | _EXT_IMG | _EXT_ZIP:
            self._schedule(p)

