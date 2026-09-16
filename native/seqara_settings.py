"""Section-scoped desktop settings, shared by the native and agent surfaces."""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

RULE_FILES = ('ticket_company_schools.json', 'project_company_schools.json',
              'invoice_classify_defaults.json', 'invoice_keyword_learning_state.json')

def prepare_shared_config(data):
    data = Path(data)
    target = data / 'native'
    target.mkdir(parents=True, exist_ok=True)
    marker = target / 'shared-config-v1.json'
    if marker.exists():
        return json.loads(marker.read_text(encoding='utf8'))
    result = {'version': 1, 'canonical': 'native', 'copied': [], 'preserved': []}
    for name in RULE_FILES:
        old, new = data / 'business' / name, target / name
        if not old.is_file():
            continue
        if not new.exists():
            shutil.copy2(old, new)
            result['copied'].append(name)
        elif old.read_bytes() != new.read_bytes():
            backup = data / 'config-backups' / 'v037-agent-rules'
            backup.mkdir(parents=True, exist_ok=True)
            if not (backup / name).exists():
                shutil.copy2(old, backup / name)
            result['preserved'].append(name)
    atomic_json(marker, result)
    return result

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        with tmp.open('w', encoding='utf8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

class SettingsStore:
    FILES = {'connection': 'api_config.json', 'tickets': RULE_FILES[0],
             'projects': RULE_FILES[1], 'defaults': RULE_FILES[2]}
    def __init__(self, folder):
        self.folder = Path(folder)

    def read(self, section):
        path = self.folder / self.FILES[section]
        raw = path.read_bytes() if path.exists() else b'{}'
        value = json.loads(raw)
        if section == 'connection':
            value = {k: v for k, v in value.items() if k in (
                'deepseek_model', 'max_tokens', 'connect_timeout', 'read_timeout', 'net_retry_times', 'server_retry_times')}
            full = json.loads(raw)
            value['key_configured'] = bool(full.get('deepseek_api_key'))
            value['env_key_configured'] = bool(os.environ.get('DEEPSEEK_API_KEY'))
        return {'value': value, 'revision': hashlib.sha256(raw).hexdigest()}

    def save(self, section, value, revision):
        path = self.folder / self.FILES[section]
        current = self.read(section)
        if revision != current['revision']:
            raise ValueError('设置已被其他窗口更新。请先复制需要保留的内容，再重新读取并保存。')
        if not isinstance(value, dict):
            raise ValueError('设置格式不正确')
        if section in ('tickets', 'projects'):
            cleaned = {}
            if not value or len(value) > 1000:
                raise ValueError('请填写至少一组公司与院校，最多 1000 组。')
            for company, schools in value.items():
                if not isinstance(company, str) or not company.strip() or not isinstance(schools, list):
                    raise ValueError('每组须包含公司名称和院校列表。')
                if any(not isinstance(s, str) or not s.strip() for s in schools) or not schools:
                    raise ValueError('请补全院校名称，或移除空行。')
                if len(company) > 500 or any(len(s) > 500 for s in schools):
                    raise ValueError('公司或院校名称过长。')
                key = company.strip()
                if key in cleaned:
                    raise ValueError('公司名称重复，请合并同一公司的院校。')
                cleaned[key] = list(dict.fromkeys(s.strip() for s in schools))
            value = cleaned
        elif section == 'defaults':
            value = {k: str(value.get(k, '')).strip() for k in ('company_name', 'group_prefix')}
            if any(not s or len(s) > 500 for s in value.values()):
                raise ValueError('请填写公司名称与分组名称前缀，每项不超过 500 字。')
        else:
            original = json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
            model = str(value.get('deepseek_model', 'deepseek-v4-flash')).strip()
            if model not in ('deepseek-v4-flash', 'deepseek-v4-pro'):
                raise ValueError('请选择支持的活动方案模型。')
            original['deepseek_model'] = model
            for key, default, low, high in (
                ('max_tokens', 2000, 1, 32768), ('connect_timeout', 30, 1, 120),
                ('read_timeout', 480, 1, 3600), ('net_retry_times', 3, 1, 10), ('server_retry_times', 3, 1, 10)):
                number = int(value.get(key, default))
                if not low <= number <= high:
                    raise ValueError(f'{key} 超出允许范围 {low}–{high}。')
                original[key] = number
            if value.get('replace_key') is True:
                original['deepseek_api_key'] = str(value.get('deepseek_api_key', '')).strip()
            value = original
        if path.exists():
            backup = self.folder / 'settings-backups' / (str(time.time_ns()) + '-' + path.name)
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(path, backup)
        atomic_json(path, value)
        return self.read(section)
