# -*- coding: utf-8 -*-
"""DeepSeek 官方 Chat Completions 接口。"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, Tuple

try:
    import requests
except ImportError as exc:
    raise RuntimeError("缺少 requests；请在构建或部署阶段安装完整依赖。") from exc

config_base_path = os.path.abspath(os.path.dirname(__file__))

# Product output bound for the existing document forms; not the provider's maximum.
CHAT_COMPLETION_MAX_TOKENS_CEILING = 32768
DEFAULT_MODEL = "deepseek-v4-flash"
MODELS = (DEFAULT_MODEL, "deepseek-v4-pro")
API_URL = "https://api.deepseek.com/chat/completions"


def test_api_connection(api_key: str, model: str) -> Tuple[bool, str]:
    from seqara_network import is_offline, OFFLINE_MESSAGE
    if is_offline():return False, OFFLINE_MESSAGE
    """Read the model catalogue only; never generate content or save credentials.

    Endpoint contract: https://api-docs.deepseek.com/api/list-models/
    """
    key = (api_key or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return False, "请填写 API Key，或配置 DEEPSEEK_API_KEY 环境变量。"
    try:
        response = requests.get("https://api.deepseek.com/models",
            headers={"Authorization": f"Bearer {key}"}, timeout=(5, 10))
        if response.status_code in (401, 403):
            return False, "认证失败，请检查 DeepSeek API Key 是否有效。"
        if response.status_code != 200:
            return False, f"连接未通过（HTTP {response.status_code}），请稍后重试。"
        payload = response.json()
        models = {item.get("id") for item in payload.get("data", []) if isinstance(item, dict)}
        if not models:
            return False, "已连接，但未读取到可用模型列表。"
        if model.strip() not in models:
            return False, "认证成功，但当前模型不在可用列表中，请检查模型名称。"
        return True, "连接成功，当前模型可用。此测试仅查询模型列表，不生成内容。"
    except requests.exceptions.Timeout:
        return False, "连接超时，请检查网络后重试。"
    except (requests.exceptions.RequestException, ValueError, TypeError, AttributeError):
        return False, "未能读取模型列表，请检查网络后重试。"


def set_deepseek_config_dir(path: str) -> None:
    global config_base_path
    config_base_path = os.path.abspath(path)


def _api_config_path() -> str:
    return os.path.join(config_base_path, "api_config.json")


def load_api_config_dict() -> Dict[str, Any]:
    """读取 api_config.json；失败或非法时返回空 dict。"""
    try:
        p = _api_config_path()
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_api_config_dict(cfg: Dict[str, Any]) -> None:
    """整体写回 api_config.json（调用方负责合并保留其它键）。"""
    p = _api_config_path()
    tmp = p + ".tmp"
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _cfg_int(cfg: Dict[str, Any], key: str, default: int) -> int:
    if key not in cfg:
        return default
    try:
        return int(cfg[key])
    except (TypeError, ValueError):
        return default


def get_deepseek_api_settings_for_dialog() -> Dict[str, Any]:
    """供 UI 加载：文件中的 Key/模型及数值参数（Key 不含环境变量回退）。"""
    cfg = load_api_config_dict()
    key = (cfg.get("deepseek_api_key") or "").strip()
    model = (cfg.get("deepseek_model") or "deepseek-v4-flash").strip() or "deepseek-v4-flash"
    return {
        "deepseek_api_key": key,
        "deepseek_model": model,
        "max_tokens": min(_cfg_int(cfg, "max_tokens", 2000), CHAT_COMPLETION_MAX_TOKENS_CEILING),
        "connect_timeout": _cfg_int(cfg, "connect_timeout", 30),
        "read_timeout": _cfg_int(cfg, "read_timeout", 480),
        "net_retry_times": _cfg_int(cfg, "net_retry_times", 3),
        "server_retry_times": _cfg_int(cfg, "server_retry_times", 3),
        "env_key_configured": bool((os.environ.get("DEEPSEEK_API_KEY") or "").strip()),
    }


def save_deepseek_api_settings_from_dialog(
    *,
    deepseek_api_key: str,
    deepseek_model: str,
    max_tokens: int,
    connect_timeout: int,
    read_timeout: int,
    net_retry_times: int,
    server_retry_times: int,
) -> None:
    """合并写入 DeepSeek 相关字段，保留 bailian 等其它配置键。"""
    cfg = load_api_config_dict()
    cfg["deepseek_api_key"] = (deepseek_api_key or "").strip()
    cfg["deepseek_model"] = (deepseek_model or "").strip() or "deepseek-v4-flash"
    cfg["max_tokens"] = max(1, min(int(max_tokens), CHAT_COMPLETION_MAX_TOKENS_CEILING))
    cfg["connect_timeout"] = max(1, int(connect_timeout))
    cfg["read_timeout"] = max(1, int(read_timeout))
    cfg["net_retry_times"] = max(1, int(net_retry_times))
    cfg["server_retry_times"] = max(1, int(server_retry_times))
    save_api_config_dict(cfg)


def get_default_deepseek_model() -> str:
    """与 CTK 一致：默认模型来自 api_config.json / 环境变量侧的配置。"""
    _, m = _load_deepseek_config()
    return (m or "deepseek-v4-flash").strip() or "deepseek-v4-flash"


def _load_deepseek_config() -> Tuple[str, str]:
    cfg = load_api_config_dict()
    key = (cfg.get("deepseek_api_key") or "").strip()
    model = (cfg.get("deepseek_model") or "deepseek-v4-flash").strip() or "deepseek-v4-flash"
    if not key:
        key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    return key, model


def call_deepseek_api(
    user_content: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    connect_timeout: Optional[int] = None,
    read_timeout: Optional[int] = None,
    net_retry_times: Optional[int] = None,
    server_retry_times: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
) -> Tuple[bool, str]:
    from seqara_network import is_offline, OFFLINE_MESSAGE
    if is_offline():return False, OFFLINE_MESSAGE
    cfg = load_api_config_dict()
    api_key = (cfg.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        return False, "未配置 DeepSeek API Key：请在设置 → DeepSeek API 填写，或设置 DEEPSEEK_API_KEY 环境变量。旧千问 Key 不可用于 DeepSeek。"
    use_model = (model or cfg.get("deepseek_model") or DEFAULT_MODEL).strip()
    if not use_model.startswith("deepseek-"):
        return False, "请选择 DeepSeek 模型；原千问模型不可用于此接口。"
    use_max = max(1, min(int(max_tokens if max_tokens is not None else _cfg_int(cfg, "max_tokens", 2000)), CHAT_COMPLETION_MAX_TOKENS_CEILING))
    conn = max(1, int(connect_timeout if connect_timeout is not None else _cfg_int(cfg, "connect_timeout", 30)))
    read = max(1, int(read_timeout if read_timeout is not None else _cfg_int(cfg, "read_timeout", 480)))
    net_limit = max(1, min(10, int(net_retry_times if net_retry_times is not None else _cfg_int(cfg, "net_retry_times", 3))))
    server_limit = max(1, min(10, int(server_retry_times if server_retry_times is not None else _cfg_int(cfg, "server_retry_times", 3))))
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})
    payload = {"model": use_model, "messages": messages, "max_tokens": use_max,
               "thinking": {"type": "disabled"}, "stream": False}
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if top_p is not None:
        payload["top_p"] = float(top_p)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    network_failures = 0
    server_failures = 0
    while True:
        try:
            response = requests.post(API_URL, json=payload, headers=headers, timeout=(conn, read))
        except requests.exceptions.RequestException as exc:
            network_failures += 1
            if network_failures >= net_limit:
                kind = "请求超时" if isinstance(exc, requests.exceptions.Timeout) else "网络连接失败"
                return False, f"DeepSeek {kind}，请检查网络或稍后重试。"
            time.sleep(min(2 * network_failures, 8))
            continue
        try:
            status = response.status_code
            try:
                data = response.json()
            except (ValueError, TypeError):
                data = None
            if status != 200:
                server_failures += 1
                if status in (429, 500, 502, 503, 504) and server_failures < server_limit:
                    try:
                        pause = max(1, min(float(response.headers.get("Retry-After", "")), 30))
                    except (TypeError, ValueError):
                        pause = min(server_failures * 3, 15)
                else:
                    hints = {401: "API Key 无效，请检查 DeepSeek Key。", 402: "余额不足，请检查 DeepSeek 账户。",
                             403: "当前 Key 无权访问此服务。", 429: "请求过于频繁，请稍后重试。"}
                    error = data.get("error") if isinstance(data, dict) else None
                    detail = error.get("message", "") if isinstance(error, dict) else ""
                    detail = str(detail).replace(api_key, "[hidden]")[:500]
                    return False, f"DeepSeek API 错误 {status}：" + hints.get(status, detail or "服务响应异常，请检查模型与参数。")
            else:
                if not isinstance(data, dict):
                    return False, "DeepSeek 返回了无法解析的响应。"
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    return False, "DeepSeek 响应中没有有效结果。"
                choice = choices[0]
                if choice.get("finish_reason") == "length":
                    return False, "DeepSeek 输出达到长度上限，正文不完整。请减少输入或分章生成后重试。"
                message = choice.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, str) or not content.strip():
                    return False, "DeepSeek 未返回正文，请检查模型或稍后重试。"
                return True, content.strip()
        finally:
            response.close()
        time.sleep(pause)
