# -*- coding: utf-8 -*-
"""产业学院建设交付报告：从 CTK 合并版抽出的生成与保存逻辑（供 PySide6 调用，不依赖 Tk）。"""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

import nv_deepseek_core as nv_ds
from nv_activity_plan_docx import (
    _add_markdown_table_to_docx,
    _try_extract_md_table,
    _write_body_with_markdown_styles,
    safe_filename,
)
from nv_industry_report_prompts import (
    build_industry_delivery_outline_system_prompt,
    build_industry_delivery_system_prompt,
)


def _config_dir() -> str:
    return str(getattr(nv_ds, "config_base_path", os.path.abspath(os.path.dirname(__file__))))


def extract_text_from_docx(path: str) -> str:
    """抽取段落 + 表格单元格文本，便于历史报告范文中的表格数据进入提示词。"""
    try:
        doc = Document(path)
        parts: List[str] = []
        for p in doc.paragraphs:
            t = (p.text or "").strip()
            if t:
                parts.append(t)
        for table in doc.tables:
            rows_out: List[str] = []
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    c = " ".join((cell.text or "").split())
                    cells.append(c)
                rows_out.append(" | ".join(cells))
            if rows_out:
                parts.append("\n".join(rows_out))
        return "\n".join(parts)
    except Exception:
        return ""


def load_report_library(folder_path: str) -> List[Dict]:
    if not folder_path or not os.path.isdir(folder_path):
        return []
    out: List[Dict] = []
    for name in os.listdir(folder_path):
        if not name.lower().endswith(".docx") or name.startswith("~"):
            continue
        fp = os.path.join(folder_path, name)
        if not os.path.isfile(fp):
            continue
        text = extract_text_from_docx(fp)
        if text:
            out.append({"path": fp, "full_text": text})
    return out


def build_activity_stats_block(df: pd.DataFrame) -> str:
    """活动表结构化统计（短），供模型对齐数字、减少自行编造合计。"""
    if df is None or df.empty:
        return ""
    n = len(df)
    if n == 1:
        row_hint = "（对应下方活动#1）"
    else:
        row_hint = f"（与下方活动#1～活动#{n} 一一对应）"
    lines: List[str] = [f"- 有效活动行数{row_hint}：{n}"]

    if "活动类型" in df.columns:
        s = df["活动类型"].fillna("").astype(str).str.strip().replace("", "（未填）")
        vc = s.value_counts().head(12)
        if not vc.empty:
            seg = "；".join(f"{str(k)} {int(v)}项" for k, v in vc.items())
            lines.append(f"- 按「活动类型」：{seg}")

    if "活动时间" in df.columns:
        years: Dict[str, int] = {}
        for x in df["活动时间"].dropna():
            m = re.search(r"(20\d{2})", str(x))
            if m:
                y = m.group(1)
                years[y] = years.get(y, 0) + 1
        if years:
            ordered = sorted(years.items(), key=lambda kv: kv[0])
            seg = "；".join(f"{y}年{c}条" for y, c in ordered[:8])
            lines.append(f"- 活动时间（年份）分布：{seg}")

    for col, label in (
        ("服务教师（人数）", "服务教师人次（逐行相加，仅可解析为数字的行）"),
        ("服务学生（人数）", "服务学生人次（逐行相加，仅可解析为数字的行）"),
    ):
        if col not in df.columns:
            continue
        total, ok = 0, 0
        for x in df[col].dropna():
            try:
                num = int(float(str(x).split(".")[0]))
                if num >= 0:
                    total += num
                    ok += 1
            except (TypeError, ValueError):
                pass
        if ok:
            lines.append(f"- 「{label}」合计约 {total}（成功解析 {ok}/{n} 行）")

    return "【活动表自动统计（须与下方明细一致；正文勿写与此矛盾的合计或条数）】\n" + "\n".join(lines)


def build_activity_summary_for_prompt(
    df: pd.DataFrame,
    link_contents: Optional[Dict[int, str]] = None,
    include_news_link_column: bool = False,
    enumerate_activities: bool = True,
) -> str:
    base_cols = ["活动名称", "活动时间", "活动类型", "学院名称", "服务教师（人数）", "服务学生（人数）", "费用"]
    if include_news_link_column:
        base_cols.append("新闻链接")
    cols = [c for c in base_cols if c in df.columns]
    if not cols:
        return "（活动表无可用列）"
    detail_lines: List[str] = []
    n = 0
    for idx, row in df.iterrows():
        n += 1
        tag = f"活动#{n} " if enumerate_activities else ""
        parts = [f"【{row.get(c, '')}】" for c in cols]
        line = tag + " | ".join(str(p) for p in parts)
        detail_lines.append(line)
        if link_contents and idx in link_contents and link_contents[idx]:
            detail_lines.append("  链接摘要: " + link_contents[idx][:800])

    header_chunks: List[str] = []
    stats = build_activity_stats_block(df)
    if stats:
        header_chunks.append(stats)
    if enumerate_activities and n:
        header_chunks.append(
            f"（共 {n} 条活动记录；正文引用时请使用相同编号「活动#k」或写出活动全称。）"
        )
    sep = "\n\n"
    return sep.join([*header_chunks, *detail_lines])


def validate_delivery_report_body(body: str, df: Optional[pd.DataFrame]) -> List[str]:
    """保存前轻量核对：仅返回提示文案，不阻断保存。"""
    warns: List[str] = []
    text = (body or "").strip()
    if not text:
        return warns
    if re.search(r"https?://[^\s\u4e00-\u9fff）】」]+", text):
        warns.append("正文中检测到 URL/超链接样式内容；按写作规范通常不写链接，请确认是否删除。")

    if df is None or df.empty:
        return warns

    nrow = len(df)

    m_stat = re.search(
        r"(?:根据活动表|活动表(?:中|统计)?)?(?:共|计)?\s*(?:列示|收录)?\s*活动\s*(\d+)\s*[项条个]",
        text,
    )
    if m_stat:
        try:
            claimed = int(m_stat.group(1))
            if claimed != nrow:
                warns.append(
                    "正文写到的活动条数（%d）与当前活动表行数（%d）不一致，请核对表述或更新活动表后重生成。"
                    % (claimed, nrow)
                )
        except ValueError:
            pass

    tags = {int(x) for x in re.findall(r"活动[#＃]\s*(\d+)", text)}
    if nrow >= 5 and tags:
        covered = sum(1 for k in range(1, nrow + 1) if k in tags)
        if covered < max(2, nrow // 4):
            warns.append(
                "正文中「活动#编号」引用较少（约 %d/%d 条有编号痕迹），若需便于核对，可适当点活动#或写活动全称。"
                % (covered, nrow)
            )

    col = "活动名称" if "活动名称" in df.columns else None
    if col:
        names = [
            str(x).strip()
            for x in df[col].dropna()
            if str(x).strip() and str(x).strip().lower() not in ("nan", "none")
        ]
        if len(names) >= 3:
            hits = sum(1 for n in names if n and n in text)
            if hits < max(1, len(names) // 3):
                warns.append(
                    "正文中仅约 %d/%d 条活动名称与活动表完全字面匹配，其余可能以概括表述带过；请核对是否需补充具体活动名称或编号引用。"
                    % (hits, len(names))
                )
    fluff = len(
        re.findall(
            r"高度重视|积极推进|不断完善|切实加强|充分发挥|扎实推动|深入推进",
            text,
        )
    )
    if fluff >= 8:
        warns.append(
            "检测到较多概括性用语（约 %d 处），建议结合活动表改为具体活动、数据或「待补充」。"
            % fluff
        )
    return warns


def _delivery_cover_template_path() -> str:
    return os.path.join(_config_dir(), "industry_delivery_cover_template.docx")


def ensure_delivery_cover_template(template_path: Optional[str] = None) -> str:
    """确保存在可供 docxtpl 渲染的封面模板（含 {{ subject_name }}、{{ report_subtitle }}）。

    仅当目标为默认路径 ``industry_delivery_cover_template.docx`` 且文件不存在时自动创建；
    自定义路径若不存在则返回该路径（由上层渲染失败后再回退内置封面）。
    """
    path = (template_path or "").strip() or _delivery_cover_template_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.isfile(path):
        return path
    default_abs = os.path.abspath(_delivery_cover_template_path())
    if os.path.abspath(path) != default_abs:
        return path
    doc = Document()
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    p1 = doc.add_paragraph(style="Title" if "Title" in doc.styles else None)
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p1.add_run("{{ subject_name }}")
    r1.font.name = "仿宋"
    r1._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋")
    r1.font.size = Pt(24)
    r1.bold = True
    p2 = doc.add_paragraph(style="Title" if "Title" in doc.styles else None)
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run("{{ report_subtitle }}")
    r2.font.name = "仿宋"
    r2._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋")
    r2.font.size = Pt(24)
    r2.bold = True
    doc.add_paragraph()
    doc.save(path)
    return path


def _append_body_to_document(
    doc: Document,
    raw_body: str,
    use_raw_markdown: bool,
) -> None:
    raw_body = (raw_body or "").strip() or "（正文为空）"
    if use_raw_markdown:
        _lines = raw_body.split("\n")
        _i = 0
        while _i < len(_lines):
            _tbl, _next = _try_extract_md_table(_lines, _i)
            if _tbl is not None:
                _add_markdown_table_to_docx(doc, _tbl, "微软雅黑", 12, qn)
                _i = _next
                continue
            p = doc.add_paragraph(_lines[_i])
            for r in p.runs:
                r.font.name = "微软雅黑"
                try:
                    r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
                except Exception:
                    pass
                r.font.size = Pt(12)
            _i += 1
    else:
        _write_body_with_markdown_styles(
            doc,
            raw_body,
            font_name="微软雅黑",
            body_pt=12,
            heading1_pt=14,
            heading2_pt=12,
        )
        if len(doc.paragraphs) <= 2:
            p = doc.add_paragraph(raw_body)
            for r in p.runs:
                r.font.name = "微软雅黑"
                try:
                    r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
                except Exception:
                    pass
                r.font.size = Pt(12)


def _normalize_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """去除列名 BOM、首尾空格，避免 Excel 导出后 `活动名称` 匹配失败。"""
    out = df.copy()
    names = []
    for c in out.columns:
        if c is None or (isinstance(c, float) and pd.isna(c)):
            names.append("")
        else:
            names.append(str(c).replace("\ufeff", "").strip())
    out.columns = names
    return out


def _prepare_activity_dataframe_for_prompt(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名并补齐「活动时间」（部分台账只有「开始时间」）。"""
    out = _normalize_dataframe_columns(df)
    if "活动时间" not in out.columns and "开始时间" in out.columns:
        out = out.copy()
        out["活动时间"] = out["开始时间"]
    return out


def load_activity_table_for_delivery_report(path: str, log_cb: Callable[[str], None]) -> pd.DataFrame:
    """读取活动总结表：支持 CSV / .xlsx / .xls，多工作表与多行表头自动探测。

    产业学院交付报告此前仅 ``openpyxl`` + 固定 ``header=1/0``，在以下情况会读空表或无法匹配列名，
    导致无法生成报告：旧版 .xls、首行为说明/封面导致表头不在第 2 行、数据在非第一个工作表、列名带 BOM 等。
    """
    p = (path or "").strip()
    if not p or not os.path.isfile(p):
        raise FileNotFoundError("活动表文件不存在或路径无效")

    lower = p.lower()
    if lower.endswith(".csv"):
        df = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
        df = _prepare_activity_dataframe_for_prompt(df)
        return df.dropna(how="all").reset_index(drop=True)

    def _engines():
        if lower.endswith(".xls") and not lower.endswith(".xlsx"):
            try:
                import xlrd  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "读取 .xls 需要 xlrd，请使用完整发布包或先将文件另存为 .xlsx。"
                ) from exc
            yield "xlrd"
        yield "openpyxl"

    def _row_looks_like_data(d: pd.DataFrame) -> bool:
        if d.empty or len(d.columns) < 2:
            return False
        cols = set(d.columns)
        if "活动名称" in cols or "新闻链接" in cols:
            return True
        if "活动类型" in cols and ("学院名称" in cols or "学校名称" in cols):
            return True
        return False

    last_err: Optional[Exception] = None
    for eng in _engines():
        try:
            xf = pd.ExcelFile(p, engine=eng)
        except Exception as e:
            last_err = e
            log_cb("尝试打开 Excel（引擎 %s）失败: %s" % (eng, str(e)[:120]))
            continue
        try:
            for sn in xf.sheet_names:
                for header in (1, 0, 2):
                    try:
                        df = xf.parse(sheet_name=sn, header=header, dtype=str)
                        df = _prepare_activity_dataframe_for_prompt(df)
                        df = df.dropna(how="all").reset_index(drop=True)
                        if not _row_looks_like_data(df):
                            continue
                        log_cb(
                            "活动表解析成功：引擎=%s，工作表「%s」，表头参数 header=%s"
                            % (eng, sn, header)
                        )
                        return df
                    except Exception as e:
                        last_err = e
                        continue
        finally:
            try:
                xf.close()
            except Exception:
                pass

    hint = str(last_err) if last_err else "未知原因"
    raise ValueError(
        "无法解析活动表（请确认文件未加密、格式为 .xlsx/.xls/.csv，且包含「活动名称」等列）。详情: " + hint[:200]
    )


def _load_bailian_kb_config() -> Tuple[str, str, str, str]:
    """从 api_config.json 读取百炼知识库配置，返回 (workspace_id, index_id, access_key_id, access_key_secret)。任一为空则不可用。
    配置项：bailian_workspace_id, bailian_index_id, bailian_access_key_id, bailian_access_key_secret（或 aliyun_access_key_id/secret）。
    打包成 exe 时，配置文件从 exe 同目录读取。"""
    ws, idx, ak_id, ak_sec = "", "", "", ""
    try:
        config_path = os.path.join(_config_dir(), "api_config.json")
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ws = (cfg.get("bailian_workspace_id") or cfg.get("workspace_id") or "").strip()
            idx = (cfg.get("bailian_index_id") or cfg.get("bailian_knowledge_base_id") or "").strip()
            ak_id = (cfg.get("bailian_access_key_id") or cfg.get("aliyun_access_key_id") or "").strip()
            ak_sec = (cfg.get("bailian_access_key_secret") or cfg.get("aliyun_access_key_secret") or "").strip()
    except Exception:
        pass
    if not ak_id:
        ak_id = (os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID") or "").strip()
    if not ak_sec:
        ak_sec = (os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET") or "").strip()
    if not ws:
        ws = (os.environ.get("WORKSPACE_ID") or "").strip()
    return ws, idx, ak_id, ak_sec


def retrieve_from_bailian_kb(
    query: str,
    workspace_id: str,
    index_id: str,
    access_key_id: str,
    access_key_secret: str,
    top_n: int = 5,
    log_cb: Optional[Callable[[str], None]] = None,
) -> str:
    """调用百炼知识库 Retrieve 接口，返回拼接后的参考文本；失败或未配置时返回空字符串。"""
    if not query or not workspace_id or not index_id or not access_key_id or not access_key_secret:
        return ""
    try:
        try:
            from alibabacloud_bailian20231229.client import Client as BailianClient
            from alibabacloud_bailian20231229 import models as bailian_models
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_tea_util import models as util_models
        except ImportError as exc:
            raise RuntimeError("当前发布包未包含百炼知识库组件。") from exc
        config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            endpoint="bailian.cn-beijing.aliyuncs.com",
        )
        client = BailianClient(config)
        headers = {}
        runtime = util_models.RuntimeOptions()

        # 与控制台「命中测试」一致：向量/关键词 TopK=50，相似度阈值 0.20，最终召回 5
        def _do_retrieve(enable_rerank: bool = True):
            kwargs = dict(
                query=query,
                index_id=index_id,
                dense_similarity_top_k=50,
                sparse_similarity_top_k=50,
                rerank_top_n=min(top_n, 5),
                enable_reranking=enable_rerank,
            )
            if enable_rerank:
                kwargs["rerank_min_score"] = 0.20
            r = bailian_models.RetrieveRequest(**kwargs)
            resp = client.retrieve_with_options(workspace_id=workspace_id, tmp_req=r, headers=headers, runtime=runtime)
            body = resp.body
            data = None
            nodes = None
            # 优先用 to_map() 取原始 JSON（SDK 可能把 Data/Nodes 放在别处，getattr 取到 None）
            if hasattr(body, "to_map"):
                try:
                    raw = body.to_map()
                    if isinstance(raw, dict):
                        data = raw.get("Data") or raw.get("data")
                        if isinstance(data, list):
                            nodes = data
                        elif isinstance(data, dict):
                            nodes = data.get("Nodes") or data.get("nodes") or []
                except Exception:
                    pass
            if data is None:
                data = getattr(body, "data", None) or getattr(body, "Data", None)
                if data is None and hasattr(body, "get"):
                    data = body.get("data") or body.get("Data")
            if nodes is None and data is not None:
                if isinstance(data, list):
                    nodes = data
                else:
                    nodes = getattr(data, "nodes", None) or getattr(data, "Nodes", None)
                    if nodes is None and hasattr(data, "get"):
                        nodes = data.get("nodes") or data.get("Nodes")
                    if nodes is None and hasattr(data, "to_map"):
                        try:
                            d = data.to_map()
                            if isinstance(d, dict):
                                nodes = d.get("Nodes") or d.get("nodes") or []
                        except Exception:
                            pass
            if nodes is None:
                nodes = []
            elif not isinstance(nodes, list):
                nodes = list(nodes) if nodes else []
            return nodes, body, data

        nodes, resp_body, resp_data = _do_retrieve(enable_rerank=True)
        if not nodes and log_cb:
            log_cb("百炼知识库首次检索无结果，尝试关闭重排序再检索…")
            nodes, resp_body, resp_data = _do_retrieve(enable_rerank=False)
        if not nodes:
            if log_cb:
                try:
                    config_path = os.path.join(_config_dir(), "api_config.json")
                    log_cb("百炼知识库检索无结果")
                    log_cb("使用的配置文件: %s" % config_path)
                    log_cb("当前 WorkspaceId: %s（请与业务空间详情中的「业务空间id」逐字一致）" % (workspace_id or "未填"))
                    log_cb("当前 IndexId: %s" % (index_id or "未填"))
                    # 诊断：打印接口完整返回，便于区分「服务端报错」与「成功但无数据」
                    if hasattr(resp_body, "to_map"):
                        try:
                            raw = resp_body.to_map()
                            if isinstance(raw, dict):
                                code = raw.get("code") or raw.get("Code")
                                msg = raw.get("message") or raw.get("Message") or ""
                                req_id = raw.get("request_id") or raw.get("RequestId") or ""
                                ok = raw.get("success") if "success" in raw else None
                                log_cb("接口返回: code=%s, success=%s, message=%s" % (code, ok, msg[:80] if msg else ""))
                                if req_id:
                                    log_cb("request_id: %s" % req_id[:50])
                                rdata = raw.get("Data") or raw.get("data")
                                if rdata is not None:
                                    log_cb("接口 data 类型: %s, 长度: %s" % (type(rdata).__name__, len(rdata) if isinstance(rdata, (list, dict)) else "-"))
                                    if isinstance(rdata, dict):
                                        log_cb("data 键: %s" % list(rdata.keys())[:15])
                                else:
                                    log_cb("接口返回的 data 为 None/空。请用同一参数在阿里云 OpenAPI 调试页试一次以确认是否为账号/权限问题。")
                        except Exception as e:
                            log_cb("诊断解析异常: %s" % str(e)[:60])
                except Exception:
                    log_cb("百炼知识库检索无结果（请确认 WorkspaceId 与命中测试所在工作空间一致）")
            return ""
        texts = []
        for node in nodes[:top_n]:
            t = getattr(node, "text", None) or getattr(node, "Text", None) or getattr(node, "content", None) or getattr(node, "Content", None)
            if not t and hasattr(node, "get"):
                t = (node.get("text") or node.get("Text") or node.get("content") or node.get("Content") or
                     (node.get("metadata") or {}).get("content") or (node.get("metadata") or {}).get("text"))
            if not t and getattr(node, "metadata", None):
                meta = node.metadata
                t = getattr(meta, "content", None) or getattr(meta, "Content", None) or getattr(meta, "text", None) or getattr(meta, "Text", None)
            if not t and hasattr(node, "__dict__"):
                for k in ("text", "Text", "content", "Content"):
                    if k in node.__dict__ and isinstance(node.__dict__[k], str):
                        t = node.__dict__[k]
                        break
            if t and isinstance(t, str) and t.strip():
                texts.append(t.strip())
        if log_cb and texts:
            log_cb(f"百炼知识库检索到 {len(texts)} 条参考片段")
        elif log_cb and nodes:
            # 便于排查：若控制台/日志可见，可看到首条节点字段
            try:
                n0 = nodes[0]
                info = getattr(n0, "__dict__", None) or str(type(n0))
                if isinstance(info, dict):
                    info = list(info.keys())
                log_cb("百炼知识库检索无结果（接口返回 %d 条但无法解析正文，首条节点字段: %s）" % (len(nodes), info))
            except Exception:
                log_cb("百炼知识库检索无结果（接口返回 %d 条但无法解析正文）" % len(nodes))
        return "\n\n".join(texts) if texts else ""
    except Exception as e:
        err_str = str(e)
        if log_cb:
            if "403" in err_str and ("NoPermission" in err_str or "not authorized" in err_str.lower()):
                log_cb("百炼知识库检索跳过: 403 无权限。请用主账号 AccessKey，或由主账号为当前子账号授予 AliyunBailianDataFullAccess 策略。")
            else:
                log_cb("百炼知识库检索跳过: " + err_str[:200])
        return ""

# 分章生成：各章正文合计目标上限（汉字，不含文末活动表）。可在界面「分章全文上限」修改，或改此默认值。
MULTI_TURN_BODY_CHAR_MAX_DEFAULT = 11000
MULTI_TURN_BODY_CHAR_MIN = 8000
MULTI_TURN_BODY_CHAR_HARD_MAX = 18000
DELIVERY_BODY_TARGET_CHAR = 11000
DELIVERY_BODY_MIN_CHAR = 10800
DELIVERY_BODY_MAX_CHAR = 11200

# 分章生成时的默认章节结构（当「先出提纲」解析失败时回退使用）
# 以用户指定的“重庆样稿”结构为基准：序言开篇，结语收束。
REPORT_CHAPTERS = [
    ("序言", "序言"),
    ("创新人才培养模式", "创新人才培养模式"),
    ("提升专业建设质量", "提升专业建设质量"),
    ("产教融合机制建设", "产教融合机制建设"),
    ("阶段性成果与数据总览", "阶段性成果与数据总览"),
    ("存在问题与改进方向", "存在问题与改进方向"),
    ("结语", "结语"),
]

DELIVERY_STYLE_TEMPLATE_CANDIDATES = [
    os.path.join(
        os.path.expanduser("~"),
        "Desktop",
        "2025示例院校12示例设计产业学院阶段性交付报告.docx",
    ),
    os.path.join(_config_dir(), "industry_delivery_report_template.docx"),
]


def _resolve_delivery_style_template_path(explicit_path: Optional[str] = None) -> str:
    custom = (explicit_path or "").strip()
    if custom and os.path.isfile(custom):
        return custom
    for p in DELIVERY_STYLE_TEMPLATE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return ""


def _ensure_preface_and_conclusion(chapters: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    out = [(str(t).strip(), str(s).strip()) for t, s in chapters if str(t).strip()]
    if not out:
        return list(REPORT_CHAPTERS)
    if not re.search(r"序言|前言", out[0][0]):
        out.insert(0, ("序言", "序言"))
    if not re.search(r"结语|总结|展望", out[-1][0]):
        out.append(("结语", "结语"))
    return out


def _capture_template_paragraph_refs(doc: Document) -> Dict[str, Any]:
    refs: Dict[str, Any] = {}
    non_empty = [p for p in doc.paragraphs if (p.text or "").strip()]
    if not non_empty:
        return refs
    refs["cover_school"] = non_empty[0]
    refs["cover_year"] = non_empty[1] if len(non_empty) > 1 else non_empty[0]
    refs["cover_title"] = non_empty[2] if len(non_empty) > 2 else non_empty[0]
    refs["meta"] = non_empty[3] if len(non_empty) > 3 else non_empty[0]
    refs["heading"] = next((p for p in non_empty if (p.text or "").strip() in ("序言", "结语")), non_empty[0])
    refs["body"] = non_empty[7] if len(non_empty) > 7 else non_empty[min(1, len(non_empty) - 1)]
    return refs


def _copy_para_format(dst_para, src_para) -> None:
    try:
        if src_para.style is not None:
            dst_para.style = src_para.style
    except Exception:
        pass
    try:
        src_ppr = src_para._p.pPr
        if src_ppr is not None:
            dst_ppr = dst_para._p.pPr
            if dst_ppr is not None:
                dst_para._p.remove(dst_ppr)
            dst_para._p.insert(0, deepcopy(src_ppr))
    except Exception:
        pass
    try:
        dst_para.alignment = src_para.alignment
    except Exception:
        pass


def _copy_run_format(dst_run, src_para) -> None:
    try:
        src_run = src_para.runs[0] if src_para.runs else None
        if src_run is None or src_run._element.rPr is None:
            return
        dst_run._element.get_or_add_rPr()
        dst_run._element.rPr.clear()
        dst_run._element.rPr.extend(deepcopy(src_run._element.rPr))
    except Exception:
        pass


def _clear_document_content_keep_sections(doc: Document) -> None:
    body = doc._element.body
    sect_pr = body.sectPr
    for child in list(body):
        body.remove(child)
    if sect_pr is not None:
        body.append(sect_pr)


def _append_template_paragraph(doc: Document, text: str, src_para) -> None:
    p = doc.add_paragraph()
    if src_para is not None:
        _copy_para_format(p, src_para)
    r = p.add_run(text)
    if src_para is not None:
        _copy_run_format(r, src_para)


def _request_report_outline(
    subject_name: str,
    report_title: str,
    year: str,
    period: str,
    activity_text: str,
    reference_block: str,
    model: Optional[str],
    log_cb: Callable[[str], None],
) -> List[Tuple[str, str]]:
    """请模型根据活动表与参考范文仅输出章节提纲，解析为 [(章节标题, 短名), ...]。失败或解析不足时返回空列表，由调用方回退到 REPORT_CHAPTERS。"""
    outline_user = f"""请根据以下信息，**仅输出**本报告的章节提纲，每行一章，不要输出任何正文或解释。

【报告主体】{subject_name}
【报告标题】{report_title}
【年份与时间段】{year}年{period}

【活动表数据摘要】
{activity_text[:4000]}
"""
    if reference_block:
        outline_user += "\n【参考范文摘要】\n" + (reference_block[:2000] if len(reference_block) > 2000 else reference_block)
    outline_user += """
要求：
1. 每行**只写一章标题**，共输出 5～8 行（5～8 章），不要 9 章。格式任选其一：「第一章 xxx」「一、xxx」「1. xxx」「1、xxx」。
2. 不要写前言、不要写「以下是提纲」、不要用 Markdown 标题符号 #、不要空行分段说明，**从第一行开始就是第一章**。
3. 覆盖建设背景、产教融合、人才培养、师资、实践、成效、问题与改进等要素即可合并表述。
4. 章节设计须能覆盖活动表中的「活动#1…」等内容维度；勿假设活动表中不存在的合作方或数据。"""
    outline_system = build_industry_delivery_outline_system_prompt()
    ok, text = nv_ds.call_deepseek_api(
        outline_user, system_prompt=outline_system, model=model, max_tokens=1200
    )
    if not ok or not text or not text.strip():
        log_cb("章节提纲：DeepSeek未返回有效内容，将使用内置默认 9 章（可在日志中查看是否 API 报错）。")
        return []
    # 解析：去掉 #、-、* 行首标记后再识别序号
    chapters = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if re.match(r"^[`]{3}", line) or line.startswith("```"):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^[-*]\s+", "", line).strip()
        if not line or len(line) < 2:
            continue
        # 跳过明显非标题行
        if re.match(r"^要求[:：]", line) or re.match(r"^第.+[条条]", line):
            continue
        title = re.sub(r"^\s*第?[一二三四五六七八九十百零\d]+[章节、．.]\s*", "", line)
        title = re.sub(r"^\s*[（(][一二三四五六七八九十\d]+[）)]\s*", "", title)
        title = re.sub(r"^\s*\d+[\.、．]\s*", "", title).strip()
        if not title or len(title) < 2:
            continue
        if title in ("标题", "章节", "章"):
            continue
        short = title[:20] if len(title) > 20 else title
        chapters.append((title, short))
    # 至多保留前 9 章
    if len(chapters) > 9:
        chapters = chapters[:9]
    if len(chapters) >= 2:
        chapters = _ensure_preface_and_conclusion(chapters)
        log_cb("章节提纲：已解析 %d 章（按活动表动态生成）。" % len(chapters))
        return chapters
    log_cb(
        "章节提纲：解析仅得到 %d 条，不足 2 条有效标题。DeepSeek原文片段：%s … 将使用内置默认 9 章。"
        % (len(chapters), (text[:180].replace("\n", " ") + ("…" if len(text) > 180 else "")))
    )
    return []


def _build_chapter_prompt(
    chapter_title: str,
    chapter_index: int,
    total_chapters: int,
    subject_name: str,
    report_title: str,
    year: str,
    period: str,
    activity_text: str,
    reference_block: str,
    prev_chapter_tail: Optional[str] = None,
    body_char_max: int = MULTI_TURN_BODY_CHAR_MAX_DEFAULT,
) -> str:
    """构建单章的用户提示词，供多轮分章调用DeepSeek时使用。body_char_max：各章合计正文上限，按章数均分本章目标字数。"""
    n = max(1, int(total_chapters))
    cap = max(MULTI_TURN_BODY_CHAR_MIN, min(MULTI_TURN_BODY_CHAR_HARD_MAX, int(body_char_max)))
    base = cap // n
    rem = cap % n
    chapter_budget = base + (1 if chapter_index < rem else 0)
    ch_lo = max(300, int(chapter_budget * 0.90))
    ch_hi = chapter_budget + max(60, int(chapter_budget * 0.06))
    user = f"""【本章事实】本章可写入报告的具体事实仅来自下方「活动总结表」；与参考范文或知识片段冲突时以活动表为准。

请仅撰写产业学院建设交付报告中的【第 {chapter_index + 1}/{total_chapters} 章】：{chapter_title}。

【报告主体名称】{subject_name}
【报告标题】{report_title}
【年份与时间段】{year}年{period}

【字数要求】全报告共 {n} 章，合计目标约 {cap} 字。本章请控制在约 {ch_lo}～{ch_hi} 字，精炼务实，避免与其它章节重复套话；表格宜小不宜多。

【活动总结表数据与链接摘要】
{activity_text}
"""
    if reference_block:
        user += "\n【参考范文与知识片段（仅结构与文风，禁止照搬其中校名/企业名/数据）】\n" + reference_block
    user += """

【事实约束】本章具体事实须来自上文活动表；材料不足处请写「待补充」，禁止编造活动名、数字与合作方。引用活动时可使用「活动#k」或活动全称。
【格式】只输出本章内容（可含本章标题）。Markdown：一级 `# 本章标题`，二级 `## （一）……`，关键处 `**加粗**`。不要链接或 URL。不要输出其他章节。"""
    if prev_chapter_tail and prev_chapter_tail.strip():
        user += f"\n【上一章结尾（供衔接参考）】\n{prev_chapter_tail.strip()[-300:]}"
    return user


def _multi_turn_chapter_max_tokens(chapter_budget: int) -> int:
    """按本章目标字数估算输出 token 上限。"""
    return min(2400, max(900, int(chapter_budget * 1.5) + 200))


def _body_has_complete_tail(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if not re.search(r"(^|\n)#\s*结语", t):
        return False
    return bool(re.search(r"[。！？；]$|[。！？；][\s\n]*$", t))


def _build_auto_md_tables(df: pd.DataFrame) -> str:
    """生成可直接嵌入正文的辅助图表（Markdown 表格）。"""
    if df is None or df.empty:
        return ""
    blocks: List[str] = []
    if "活动类型" in df.columns:
        s = df["活动类型"].fillna("").astype(str).str.strip().replace("", "（未填）")
        vc = s.value_counts().head(6)
        if not vc.empty:
            lines = ["| 活动类型 | 场次 | 占比 |", "|---|---:|---:|"]
            total = max(1, int(vc.sum()))
            for k, v in vc.items():
                lines.append(f"| {str(k)} | {int(v)} | {int(round(v * 100 / total))}% |")
            blocks.append("### 图表1：活动类型结构（Top6）\n" + "\n".join(lines))
    if "活动时间" in df.columns:
        q_map = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
        for x in df["活动时间"].dropna():
            m = re.search(r"(20\d{2})\D?(\d{1,2})\D?", str(x))
            if not m:
                continue
            month = int(m.group(2))
            q = "Q1" if month <= 3 else "Q2" if month <= 6 else "Q3" if month <= 9 else "Q4"
            q_map[q] += 1
        if any(q_map.values()):
            lines = ["| 季度 | 活动场次 |", "|---|---:|"]
            for q in ("Q1", "Q2", "Q3", "Q4"):
                lines.append(f"| {q} | {q_map[q]} |")
            blocks.append("### 图表2：季度活动分布\n" + "\n".join(lines))
    return "\n\n".join(blocks)


def _inject_auto_tables_into_body(body: str, df: pd.DataFrame) -> str:
    text = (body or "").strip()
    if not text:
        return text
    tables = _build_auto_md_tables(df)
    if not tables:
        return text
    if "图表1：活动类型结构（Top6）" in text:
        return text
    m = re.search(r"(^|\n)#\s*阶段性成果与数据总览[^\n]*\n", text)
    if m:
        idx = m.end()
        return text[:idx] + "\n" + tables + "\n\n" + text[idx:]
    m2 = re.search(r"(^|\n)#\s*结语", text)
    if m2:
        return text[:m2.start()] + "\n\n" + tables + "\n\n" + text[m2.start():]
    return text + "\n\n" + tables


def _fit_report_body_length(
    body: str,
    model: Optional[str],
    log_cb: Callable[[str], None],
) -> str:
    """硬控正文长度至 10800~11200，并校验结尾完整性。"""
    text = (body or "").strip()
    if not text:
        return text
    if DELIVERY_BODY_MIN_CHAR <= len(text) <= DELIVERY_BODY_MAX_CHAR and _body_has_complete_tail(text):
        return text
    cur = text
    for _ in range(2):
        if len(cur) > DELIVERY_BODY_MAX_CHAR:
            action = "压缩"
        elif len(cur) < DELIVERY_BODY_MIN_CHAR:
            action = "扩写"
        else:
            action = "润色收尾"
        prompt = f"""请对以下交付报告正文做{action}修订。

【长度硬约束】
- 输出总长度必须在 {DELIVERY_BODY_MIN_CHAR}~{DELIVERY_BODY_MAX_CHAR} 字之间。

【完整性硬约束】
1. 保留原有章节顺序与层级（序言 ... 结语），不得新增/删减章节标题。
2. 结尾必须完整，不得截断；最后一章为 `# 结语`，且最后一句以句号结尾。
3. 不得引入新事实、新数据、新合作方；无依据内容写「待补充」。
4. 保留图表小节（若已存在“图表1/图表2”不得删除）。

【待修订正文】
{cur}
"""
        ok, out = nv_ds.call_deepseek_api(
            prompt,
            system_prompt="你是公文编辑专家，严格按长度与完整性约束改写。",
            model=model,
            max_tokens=7800,
        )
        if not ok or not (out or "").strip():
            log_cb("正文长度硬控修订未成功，保留当前正文。")
            break
        cur = out.strip()
    if DELIVERY_BODY_MIN_CHAR <= len(cur) <= DELIVERY_BODY_MAX_CHAR and _body_has_complete_tail(cur):
        log_cb(f"正文硬控完成：{len(text)} -> {len(cur)} 字（目标 10800~11200）。")
        return cur
    log_cb("正文未完全命中硬控区间或结尾完整性校验，保留最近可用版本。")
    return cur if _body_has_complete_tail(cur) else text



def _add_dataframe_to_docx(doc: "Document", df: pd.DataFrame, title: str = "活动数据一览", max_cols: int = 10):
    """将 DataFrame 以表格形式追加到 Word 文档。"""
    from docx.oxml.ns import qn
    if df.empty:
        p = doc.add_paragraph()
        r = p.add_run(title)
        r.font.name = "微软雅黑"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
        r.font.bold = True
        r.font.size = Pt(12)
        doc.add_paragraph("（无数据）")
        return
    doc.add_paragraph()
    heading = doc.add_heading(title, level=1)
    for r in heading.runs:
        r.font.name = "微软雅黑"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    cols = list(df.columns)[:max_cols]
    nrows = len(df) + 1
    table = doc.add_table(rows=nrows, cols=len(cols))
    table.style = "Table Grid"
    for j, col_name in enumerate(cols):
        cell = table.rows[0].cells[j]
        cell.text = str(col_name)
        for p in cell.paragraphs:
            for r in p.runs:
                r.font.name = "微软雅黑"
                r.font.bold = True
                r.font.size = Pt(10)
                r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    for i, row in df.iterrows():
        for j, col_name in enumerate(cols):
            val = row.get(col_name, "")
            if pd.isna(val):
                val = ""
            cell = table.rows[i + 1].cells[j]
            cell.text = str(val)[:200]
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.name = "微软雅黑"
                    r.font.size = Pt(9)
                    r._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    doc.add_paragraph()


def apply_unified_format(
    doc: "Document",
    font_name: str = "仿宋",
    body_pt: int = 14,      # 四号≈14pt
    heading1_pt: int = 16,  # 三号≈16pt
    heading2_pt: int = 15,  # 小三≈15pt
    heading3_pt: int = 16,  # 三号≈16pt
    table_pt: int = 12,     # 小四≈12pt
    title_pt: int = 24,     # 小一≈24pt（封面大标题）
) -> None:
    """对整份 Word 文档统一字体与字号（正文、标题、表格、页眉页脚）。

    设计目标：在尽量不破坏简报原有版式（对齐/缩进/间距）的前提下，统一字体字号。
    """

    def _set_run_font(run, pt: int):
        run.font.name = font_name
        try:
            run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
        except Exception:
            pass
        run.font.size = Pt(pt)

    def _detect_md_heading_level(text: str) -> Optional[int]:
        # 支持正文中残留的 Markdown 标题行：# / ## / ###
        if not text:
            return None
        m = re.match(r"^\s*(#{1,3})\s+\S", text)
        if not m:
            return None
        return len(m.group(1))

    def _para_target_pt(para, is_title: bool = False) -> int:
        if is_title:
            return title_pt
        style_name = ((para.style and para.style.name) or "").lower()
        if "heading" in style_name and "1" in style_name:
            return heading1_pt
        if "heading" in style_name and "2" in style_name:
            return heading2_pt
        if "heading" in style_name and "3" in style_name:
            return heading3_pt
        if "title" in style_name:
            return title_pt
        md_lv = _detect_md_heading_level((para.text or "").strip())
        if md_lv == 1:
            return heading1_pt
        if md_lv == 2:
            return heading2_pt
        if md_lv == 3:
            return heading3_pt
        return body_pt

    def _iter_paragraphs_and_tables(document: "Document"):
        # 主体段落
        for p in document.paragraphs:
            yield ("paragraph", p)
        # 主体表格
        for t in document.tables:
            yield ("table", t)
        # 页眉页脚
        try:
            for sec in document.sections:
                for hf in (sec.header, sec.footer):
                    for p in hf.paragraphs:
                        yield ("paragraph", p)
                    for t in hf.tables:
                        yield ("table", t)
        except Exception:
            pass

    # 先更新样式（对没有显式 run.font.size 的段落更稳）
    try:
        normal = doc.styles["Normal"]
        normal.font.name = font_name
        normal._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
        normal.font.size = Pt(body_pt)
        for nm, pt in (("Heading 1", heading1_pt), ("Heading 2", heading2_pt), ("Heading 3", heading3_pt), ("Title", title_pt)):
            if nm in doc.styles:
                st = doc.styles[nm]
                st.font.name = font_name
                st._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
                st.font.size = Pt(pt)
    except Exception:
        pass

    # 识别“文档最上方的大标题”：第一个非空段落，通常是居中且加粗
    first_non_empty = None
    for p in doc.paragraphs:
        if (p.text or "").strip():
            first_non_empty = p
            break

    from docx.enum.text import WD_ALIGN_PARAGRAPH

    for kind, obj in _iter_paragraphs_and_tables(doc):
        if kind == "paragraph":
            para = obj
            is_title = (para is first_non_empty) and (getattr(para, "alignment", None) is not None)
            md_lv = _detect_md_heading_level((para.text or "").strip())
            target_pt = _para_target_pt(para, is_title=is_title)
            style_name_l = (((para.style and para.style.name) or "").lower())

            # 对齐规则：标题左对齐；正文两端对齐（尽量不影响空段/表格内段落）
            try:
                if is_title:
                    # 封面大标题：居中
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif "title" in style_name_l:
                    # Title 样式：居中（用于封面两行标题）
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    # 封面标题行距 1.5 倍
                    try:
                        para.paragraph_format.line_spacing = 1.5
                    except Exception:
                        pass
                elif md_lv in (1, 2, 3) or "heading" in (((para.style and para.style.name) or "").lower()):
                    para.alignment = WD_ALIGN_PARAGRAPH.LEFT
                elif (para.text or "").strip():
                    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            except Exception:
                pass

            # 正文首行缩进 2 个字符（按正文字号估算 2*字号 pt）
            try:
                if (
                    (not is_title)
                    and (md_lv is None)
                    and ("heading" not in style_name_l)
                    and ("title" not in style_name_l)
                ):
                    if (para.text or "").strip():
                        para.paragraph_format.first_line_indent = Pt(body_pt * 2)
            except Exception:
                pass

            for r in para.runs:
                _set_run_font(r, target_pt)
                # 标题加粗：一级/二级/三级
                try:
                    if is_title or ("title" in style_name_l) or md_lv in (1, 2, 3) or ("heading" in style_name_l):
                        r.bold = True
                except Exception:
                    pass
        else:
            table = obj
            # 表格：表头（第一行）加粗；内容不强制加粗
            for r_i, row in enumerate(table.rows):
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            _set_run_font(run, table_pt)
                            try:
                                if r_i == 0:
                                    run.bold = True
                            except Exception:
                                pass

def save_delivery_report_docx(
    out_path: str,
    subject_name: str,
    year: str,
    period: str,
    body_markdown: str,
    df: pd.DataFrame,
    briefing_docx_paths: Optional[List[str]],
    use_raw_markdown: bool,
    include_activity_table_in_doc: bool,
    log_cb: Callable[[str], None],
    dialog_cb: Callable[[str, str, str], None],
    cover_template_path: Optional[str] = None,
) -> bool:
    """将交付报告正文（Markdown）与活动表、简报合并写入 Word。成功返回 True。

    封面优先使用 docxtpl 模板（默认同目录 ``industry_delivery_cover_template.docx``，首次保存时自动创建）；
    可在 Word 中打开该文件修改字体与版式，占位符须保留：{{ subject_name }}、{{ report_subtitle }}。
    """
    try:
        doc: Document
        subtitle = f"{year} 年{period}建设交付报告"
        style_tpl_path = _resolve_delivery_style_template_path(cover_template_path)
        used_style_template = False
        template_refs: Dict[str, Any] = {}

        if style_tpl_path:
            try:
                doc = Document(style_tpl_path)
                template_refs = _capture_template_paragraph_refs(doc)
                _clear_document_content_keep_sections(doc)
                _append_template_paragraph(doc, (subject_name or "").strip(), template_refs.get("cover_school"))
                _append_template_paragraph(doc, f"{year}年{period}示例设计产业学院", template_refs.get("cover_year"))
                _append_template_paragraph(doc, "交付报告", template_refs.get("cover_title"))
                _append_template_paragraph(doc, "交付单位：示例企业B有限公司", template_refs.get("meta"))
                _append_template_paragraph(doc, f"服务单位：{(subject_name or '').strip()}", template_refs.get("meta"))
                _append_template_paragraph(doc, f"报告周期：{year}年{period}", template_refs.get("meta"))
                used_style_template = True
                log_cb("已按重庆样稿模板对齐版式: " + os.path.basename(style_tpl_path))
            except Exception as e:
                log_cb("重庆样稿模板加载失败，回退默认封面导出: " + str(e)[:120])
                style_tpl_path = ""

        if not style_tpl_path:
            tpl_file = ensure_delivery_cover_template(None)
            used_tpl = False
            try:
                try:
                    from docxtpl import DocxTemplate
                except ImportError as exc:
                    raise RuntimeError("当前发布包未包含 docxtpl，将使用内置封面。") from exc
                tpl = DocxTemplate(tpl_file)
                tpl.render(
                    {
                        "subject_name": (subject_name or "").strip(),
                        "report_subtitle": subtitle,
                    }
                )
                tpl.save(out_path)
                doc = Document(out_path)
                used_tpl = True
                log_cb("已使用封面模板渲染: " + os.path.basename(tpl_file))
            except Exception as e:
                log_cb("封面模板未使用（将用内置封面）: " + str(e)[:120])
                doc = Document()
                doc.styles["Normal"].font.name = "微软雅黑"
                doc.styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
                doc.styles["Normal"].font.size = Pt(12)
                from docx.enum.text import WD_ALIGN_PARAGRAPH

                line1 = (subject_name or "").strip()
                title_para1 = doc.add_paragraph(style="Title" if "Title" in doc.styles else None)
                title_para1.alignment = WD_ALIGN_PARAGRAPH.CENTER
                try:
                    title_para1.paragraph_format.line_spacing = 1.5
                except Exception:
                    pass
                r1 = title_para1.add_run(line1)
                r1.font.name = "仿宋"
                r1._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋")
                r1.font.size = Pt(24)
                r1.bold = True
                title_para2 = doc.add_paragraph(style="Title" if "Title" in doc.styles else None)
                title_para2.alignment = WD_ALIGN_PARAGRAPH.CENTER
                try:
                    title_para2.paragraph_format.line_spacing = 1.5
                except Exception:
                    pass
                r2 = title_para2.add_run(subtitle)
                r2.font.name = "仿宋"
                r2._element.rPr.rFonts.set(qn("w:eastAsia"), "仿宋")
                r2.font.size = Pt(24)
                r2.bold = True
                doc.add_paragraph()

            if used_tpl:
                doc.styles["Normal"].font.name = "微软雅黑"
                try:
                    doc.styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
                    doc.styles["Normal"].font.size = Pt(12)
                except Exception:
                    pass

        if used_style_template:
            _append_template_paragraph(doc, "序言", template_refs.get("heading"))

        raw_body = (body_markdown or "").strip() or "（正文为空）"
        _append_body_to_document(doc, raw_body, use_raw_markdown)

        if used_style_template:
            _append_template_paragraph(doc, "结语", template_refs.get("heading"))
            _append_template_paragraph(
                doc,
                "本报告依据活动表与相关材料形成，后续将按整改计划持续推进并滚动更新。",
                template_refs.get("body"),
            )

        if include_activity_table_in_doc and df is not None and not df.empty:
            log_cb("正在将活动数据表写入交付报告…")
            _add_dataframe_to_docx(doc, df, title="活动数据一览", max_cols=12)
        briefing_paths = [p for p in (briefing_docx_paths or []) if p and os.path.isfile(p) and p.lower().endswith(".docx")]
        doc.save(out_path)
        if briefing_paths:
            log_cb("正在合并活动简报文档（保留图片和版式）…")
            try:
                try:
                    from docxcompose.composer import Composer
                except ImportError as exc:
                    raise RuntimeError("当前发布包未包含 docxcompose，无法合并简报附件。") from exc
                base_doc = Document(out_path)
                composer = Composer(base_doc)
                for bp in briefing_paths:
                    log_cb("追加简报文档: " + os.path.basename(bp))
                    composer.append(Document(bp))
                composer.save(out_path)
            except Exception as merge_err:
                log_cb("简报合并失败（将仅保留文字部分）: " + str(merge_err))
        try:
            if used_style_template:
                log_cb("已按样稿模板输出，跳过二次统一格式，避免覆盖模板字号/行距。")
            else:
                log_cb("正在统一字体与格式…")
                final_doc = Document(out_path)
                apply_unified_format(final_doc)
                final_doc.save(out_path)
        except Exception as fmt_err:
            log_cb("统一格式时出错（已保留原样）: " + str(fmt_err))
        log_cb(f"报告已保存: {out_path}")
        return True
    except Exception as e:
        log_cb("保存报告异常: " + str(e))
        dialog_cb("保存失败", str(e), "error")
        return False

def generate_delivery_report_ai_content(
    activity_excel_path: str,
    school_name: str,
    college_name: str,
    industry_college_name: str,
    year: str,
    period: str,
    library_reports: List[Dict],
    log_cb: Callable[[str], None],
    dialog_cb: Callable[[str, str, str], None],
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    use_multi_turn: bool = True,
    use_raw_markdown: bool = True,
    multi_turn_body_char_max: Optional[int] = None,
    use_bailian_kb: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    仅调用DeepSeek生成交付报告正文（Markdown）并返回活动表 DataFrame 等，不写盘。
    返回 dict：body, df, subject_name, year, period；失败返回 None。
    """
    try:
        cn = (college_name or "").strip()
        subject_name = f"{school_name}{industry_college_name}"
        report_title = f"{subject_name}{year}年{period}产业学院建设交付报告"
        college_line = f"- 学院名称：{cn}\n" if cn else ""
        log_cb(f"读取活动表: {activity_excel_path}")
        try:
            df = load_activity_table_for_delivery_report(activity_excel_path, log_cb)
        except Exception as e:
            dialog_cb("生成失败", str(e), "error")
            return None
        df = df.dropna(how="all").reset_index(drop=True)
        if df.empty:
            dialog_cb("生成失败", "活动表为空或无法解析。", "error")
            return None
        activity_text = build_activity_summary_for_prompt(df, None, enumerate_activities=True)
        reference_block = ""
        use_model = (model or nv_ds.get_default_deepseek_model()).strip() or nv_ds.get_default_deepseek_model()
        log_cb("当前DeepSeek模型: %s" % use_model)
        ws_id, idx_id, ak_id, ak_sec = _load_bailian_kb_config()
        if use_bailian_kb and ws_id and idx_id and ak_id and ak_sec:
            log_cb("正在检索百炼知识库…")
            kb_query = f"产业学院 建设交付报告 产教融合 课程 师资 实践 人才培养"
            kb_text = retrieve_from_bailian_kb(kb_query, ws_id, idx_id, ak_id, ak_sec, top_n=5, log_cb=log_cb)
            if kb_text:
                reference_block = (
                    "【知识库片段】仅用于章节结构与公文表述风格；其中校名、企业名、数据不得写入正文，事实以活动表为准。\n\n"
                    + kb_text[:15000]
                )
        elif use_bailian_kb:
            log_cb("百炼知识库未配置或不可用（见 api_config），将仅使用本地资料库（若已加载）。")
        else:
            log_cb("已关闭百炼知识库检索（界面选项）；将仅使用本地资料库（若已加载）。")
        if library_reports:
            total_ref = 0
            for ref in library_reports[:2]:
                t = (ref.get("full_text") or "")[:12000]
                if t:
                    total_ref += 1
                    reference_block += f"\n\n--- 参考范文 {total_ref} ---\n{t}"
            if reference_block and "【知识库片段】" not in reference_block:
                reference_block = (
                    "【本地历史范文】仅模仿结构与文风；禁止照搬其中校名、企业名与具体数据，事实以活动表为准。\n"
                    + reference_block
                )
            elif reference_block and "--- 参考范文" in reference_block and "【知识库片段】" in reference_block:
                reference_block = reference_block.replace(
                    "【知识库片段】仅用于章节结构与公文表述风格",
                    "【知识库片段】仅用于章节结构与公文表述风格；【本地范文】同上",
                    1,
                )
        user_content = f"""请根据以下输入内容，撰写一份完整的产业学院建设交付报告（年度总结 + 建设方案交付）。

【主体信息】
- 学校名称 / 报告主体：{subject_name}
{college_line}- 报告标题：{report_title}
- 报告年度与时间段：{year}年{period}

【活动表数据与链接摘要（唯一事实来源；引用请用「活动#k」或活动全称）】
{activity_text}
"""
        if reference_block:
            user_content += "\n【参考材料（非事实来源）】\n" + reference_block
        user_content += """

【写作要求】
1. 阅读对象为学校/学院领导、委托方；表述须可核对，少用空话套话。
2. 必须使用「序言」开篇、「结语」收尾；中间章节覆盖建设背景、目标、产教融合、人才培养、师资、实践条件、合作与成效、问题与改进等；信息不足可合并弱化，**不足处写「待补充」，禁止编造**。
3. 不要重复报告大标题；一级 `#`、二级 `##`，小节（一）（二）连续；关键处 `**加粗**`。
4. 总结与展望仅在**最后一章**；中间章不要章末小结。
5. 正文中的统计与小表须来自活动表；全文硬控在 10800～11200 字（不含文末追加活动明细表），不可虚构凑字。
6. 正文至少包含 2 处图表辅助说明（Markdown 表格形式，建议“活动类型结构表”“季度活动分布表”）。
7. 不要输出链接或 URL，少用无意义换行与竖线 `|`（图表表格除外）。
8. 只输出 Markdown 正文，不要解释写作过程。

请开始撰写。"""
        custom_long = (system_prompt or "").strip() or None
        use_system_prompt = build_industry_delivery_system_prompt(custom_long)

        if use_multi_turn:
            log_cb("正在生成报告章节提纲…")
            chapter_list = _request_report_outline(
                subject_name, report_title, year, period, activity_text, reference_block,
                model, log_cb,
            )
            if not chapter_list:
                chapter_list = REPORT_CHAPTERS
                log_cb("使用分章生成（多轮），共 7 章（序言→结语内置结构）。")
            else:
                if len(chapter_list) > 9:
                    chapter_list = chapter_list[:9]
                chapter_list = _ensure_preface_and_conclusion(chapter_list)
                log_cb("使用分章生成（多轮），共 %d 章（按活动表与提纲生成）…" % len(chapter_list))
            mt_cap = multi_turn_body_char_max
            if mt_cap is None:
                mt_cap = MULTI_TURN_BODY_CHAR_MAX_DEFAULT
            try:
                mt_cap = int(mt_cap)
            except (TypeError, ValueError):
                mt_cap = MULTI_TURN_BODY_CHAR_MAX_DEFAULT
            mt_cap = max(MULTI_TURN_BODY_CHAR_MIN, min(MULTI_TURN_BODY_CHAR_HARD_MAX, mt_cap))
            log_cb(f"分章正文合计目标约 {mt_cap} 字（各章均分，供模型参考）")
            chapter_parts = []
            prev_tail = ""
            total_ch = len(chapter_list)
            base_t = mt_cap // max(1, total_ch)
            rem_t = mt_cap % max(1, total_ch)
            for idx, (ch_title, _) in enumerate(chapter_list):
                ch_budget = base_t + (1 if idx < rem_t else 0)
                max_tok = _multi_turn_chapter_max_tokens(ch_budget)
                log_cb(f"正在生成第 {idx + 1}/{total_ch} 章：{ch_title}…（本章目标约 {ch_budget} 字，max_tokens={max_tok}）")
                ch_ref = reference_block
                if (
                    use_bailian_kb
                    and ws_id
                    and idx_id
                    and ak_id
                    and ak_sec
                ):
                    ch_kb = retrieve_from_bailian_kb(
                        f"产业学院 {ch_title}", ws_id, idx_id, ak_id, ak_sec, top_n=3, log_cb=log_cb
                    )
                    if ch_kb:
                        ch_kb = "【本章知识库片段·仅结构与文风】\n" + ch_kb
                        ch_ref = (ch_ref + "\n\n" + ch_kb) if ch_ref else ch_kb
                ch_user = _build_chapter_prompt(
                    ch_title, idx, total_ch, subject_name, report_title, year, period,
                    activity_text, ch_ref, prev_chapter_tail=prev_tail, body_char_max=mt_cap,
                )
                ok, ch_text = nv_ds.call_deepseek_api(ch_user, system_prompt=use_system_prompt, model=model, max_tokens=max_tok)
                if not ok:
                    log_cb(f"第 {idx + 1} 章失败，重试一次…")
                    ok, ch_text = nv_ds.call_deepseek_api(ch_user, system_prompt=use_system_prompt, model=model, max_tokens=max_tok)
                if ok and ch_text and ch_text.strip():
                    chapter_parts.append(ch_text.strip())
                    prev_tail = ch_text.strip()[-400:] if len(ch_text.strip()) > 400 else ch_text.strip()
                else:
                    chapter_parts.append(f"{ch_title}\n（本章待补充）")
                    prev_tail = ""
            body = "\n\n".join(chapter_parts)
            body = _inject_auto_tables_into_body(body, df)
            body = _fit_report_body_length(body, model, log_cb)
            log_cb("分章生成完成。请在预览窗口中确认正文后保存为 Word。")
        else:
            log_cb("正在调用DeepSeek生成报告（单次全文）…")
            ok, body = nv_ds.call_deepseek_api(user_content, system_prompt=use_system_prompt, model=model, max_tokens=8000)
            if not ok:
                log_cb("DeepSeek调用失败: " + body)
                dialog_cb("生成失败", body, "error")
                return None
            if not (body or "").strip():
                log_cb("DeepSeek返回空正文，尝试截断活动表摘要后重试一次…")
                short_user = user_content[:14000] + (
                    "\n\n（上文活动表摘要已截断；请仍按完整结构撰写。）" if len(user_content) > 14000 else ""
                )
                ok2, body2 = nv_ds.call_deepseek_api(
                    short_user, system_prompt=use_system_prompt, model=model, max_tokens=8000
                )
                if ok2 and (body2 or "").strip():
                    body = body2
                else:
                    msg = "DeepSeek返回空正文。请检查模型与 API，或勾选「分章生成（多轮）」后重试。"
                    log_cb(msg)
                    dialog_cb("生成失败", msg, "error")
                    return None
            body = _inject_auto_tables_into_body(body, df)
            body = _fit_report_body_length(body, model, log_cb)
        return {
            "body": (body or "").strip(),
            "df": df,
            "subject_name": subject_name,
            "year": year,
            "period": period,
        }
    except Exception as e:
        log_cb("生成异常: " + str(e))
        dialog_cb("生成失败", str(e), "error")
        return None



def generate_delivery_report_ai(
    activity_excel_path: str,
    school_name: str,
    college_name: str,
    industry_college_name: str,
    year: str,
    period: str,
    output_dir: str,
    library_reports: List[Dict],
    log_cb: Callable[[str], None],
    dialog_cb: Callable[[str, str, str], None],
    briefing_docx_paths: Optional[List[str]] = None,
    include_activity_table_in_doc: bool = True,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    use_multi_turn: bool = True,
    use_raw_markdown: bool = True,
    multi_turn_body_char_max: Optional[int] = None,
    use_bailian_kb: bool = True,
) -> Optional[str]:
    draft = generate_delivery_report_ai_content(
        activity_excel_path,
        school_name,
        college_name,
        industry_college_name,
        year,
        period,
        library_reports,
        log_cb,
        dialog_cb,
        system_prompt=system_prompt,
        model=model,
        use_multi_turn=use_multi_turn,
        use_raw_markdown=use_raw_markdown,
        multi_turn_body_char_max=multi_turn_body_char_max,
        use_bailian_kb=use_bailian_kb,
    )
    if not draft:
        return None
    os.makedirs(output_dir, exist_ok=True)
    _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = safe_filename(
        f"{draft['subject_name']}_{draft['year']}年{draft['period']}_产业学院建设交付报告_{_ts}"
    )
    out_path = os.path.join(output_dir, f"{safe_name}.docx")
    ok = save_delivery_report_docx(
        out_path,
        draft["subject_name"],
        draft["year"],
        draft["period"],
        draft["body"],
        draft["df"],
        briefing_docx_paths,
        use_raw_markdown,
        include_activity_table_in_doc,
        log_cb,
        dialog_cb,
    )
    return out_path if ok else None
