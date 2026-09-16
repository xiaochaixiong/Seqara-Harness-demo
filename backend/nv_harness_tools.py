"""Local business tools exposed through the Harness plugin; no Qt or model calls."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import uuid


def run_tool(name: str, args: dict, data_dir: Path) -> dict:
    if name == "classify_invoice_text":
        import nv_classify_core as core
        text = args.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 100_000:
            raise ValueError("发票文本不能为空，且不能超过十万字符。")
        core.set_classify_config_dir(str(data_dir))
        core.load_keyword_learning_state()
        category, evidence = core.classify_keywords_first(text)
        return {"category": category or "未分类", "evidence": evidence or "未命中可靠关键词",
                "method": "现有关键词分类规则；单条预检查，不替代整表票种识别与分组。"}
    if name == "activity_plan_brief":
        from nv_activity_plan_prompts import ACTIVITY_PLAN_BODY_SYSTEM_STRICT
        fields = ("activity_type", "major_name", "activity_time", "service_college")
        for field in fields:
            if not isinstance(args.get(field), str) or not args[field].strip():
                raise ValueError("请提供活动类型、专业名称、活动周期和服务院校。")
        return {"system_instructions": ACTIVITY_PLAN_BODY_SYSTEM_STRICT,
                "inputs": {key: args[key].strip() for key in fields},
                "output": "完整 Markdown 正文，调用 toolkit_save_activity_plan 保存 Word。"}
    if name == "save_activity_plan":
        from nv_activity_plan_docx import save_activity_plan_to_docx
        for key in ("body_markdown", "project_title", "service_college", "activity_type", "activity_time"):
            if not isinstance(args.get(key), str) or not args[key].strip():
                raise ValueError(f"缺少参数：{key}")
        if len(args["body_markdown"]) > 500_000:
            raise ValueError("方案内容超过长度限制")
        # Always publish a new artifact; no caller-controlled write path or overwrite.
        out = data_dir / "harness_outputs"
        out.mkdir(parents=True, exist_ok=True)
        stem = "活动方案_" + uuid.uuid4().hex[:12]
        target = out / (stem + ".docx")
        pending = out / (stem + ".pending.docx")
        try:
            save_activity_plan_to_docx(str(pending), args["project_title"], args["service_college"],
                args["activity_type"], args["activity_time"], "", args["body_markdown"])
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
        return {"path": str(target.resolve()), "format": "docx"}
    raise ValueError("未知的本地业务工具")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-file", required=True)
    parser.add_argument("--result-file", required=True)
    args = parser.parse_args(argv)
    target = Path(args.result_file)
    try:
        request = Path(args.request_file)
        if request.stat().st_size > 2_000_000:
            raise ValueError("请求过大")
        payload = json.loads(request.read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(io.StringIO()):
            value = run_tool(payload["name"], payload["args"],
                             Path(os.environ.get("NV_TOOLKIT_DATA_DIR", Path(__file__).parent)))
        result = {"ok": True, "value": value}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
