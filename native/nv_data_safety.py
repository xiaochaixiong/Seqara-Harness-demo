"""Shared local output protection and numeric validation."""
from pathlib import Path
import math
import os
import re
import hashlib
import tempfile
from contextlib import contextmanager


def safe_file_stem(name, fallback='未命名', max_length=100):
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', str(name)).strip('. ') or fallback
    if cleaned.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        cleaned = '_' + cleaned
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length-9] + '_' + hashlib.sha1(cleaned.encode('utf8')).hexdigest()[:8]
    return cleaned


@contextmanager
def staged_outputs(*targets):
    """Publish complete files together; never leave a half-written deliverable."""
    targets = [Path(p) for p in targets]
    with tempfile.TemporaryDirectory(prefix='.seqara-save-', dir=targets[0].parent) as staging:
        staged = [Path(staging)/f'{index}_{p.name}' for index,p in enumerate(targets)]
        published = []
        try:
            yield staged
            # Check every staged file before publishing any member of the batch.
            for source in staged:
                if not source.is_file():
                    raise FileNotFoundError(f'待保存文件不存在：{source.name}')
            for source, target in zip(staged, targets):
                # Windows rename publishes a complete file and refuses overwrite,
                # including on FAT/exFAT where hard links are unavailable.
                if os.name == 'nt':
                    os.rename(source, target)
                else:
                    os.link(source, target)
                published.append(target)
        except BaseException:
            for target in published:
                target.unlink(missing_ok=True)
            raise


def new_output_path(folder, filename, sources=()):
    original = Path(filename)
    target = Path(folder) / (safe_file_stem(original.stem) + original.suffix)
    resolved = target.resolve()
    if any(resolved == Path(source).resolve() for source in sources):
        raise ValueError('输出文件不能与输入文件相同，请更换输出文件名或保存目录。')
    if target.exists():
        index = 2
        while target.with_name(f'{target.stem}_{index}{target.suffix}').exists():
            index += 1
        target = target.with_name(f'{target.stem}_{index}{target.suffix}')
    return target


def parse_headcount(value):
    if value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == '':
        return 0
    if isinstance(value, bool):
        raise ValueError('人数须为非负整数')
    text = str(value).strip()
    if re.search(r'\s', text):
        raise ValueError(f'人数中不能夹有空格或换行：{value}')
    if (',' in text or '，' in text) and not re.fullmatch(r'\d{1,3}(?:[,，]\d{3})+(?:\.0+)?', text):
        raise ValueError(f'人数的千位分隔符格式不正确：{value}')
    text = re.sub(r'[,，\s]', '', text)
    try:
        number = float(text)
    except (ValueError, TypeError):
        raise ValueError(f'无法识别人数：{value}，请填写非负整数。') from None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f'人数须为非负整数：{value}')
    return int(number)
