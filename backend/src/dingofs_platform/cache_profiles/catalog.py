"""Versioned CLI metadata and strict, shell-independent option validation."""
import math
import re
from ._catalog import CATALOG, SOURCE_VERSION
INDEX = {row['name']: row for row in CATALOG}
MEMBER_KEYS = {row['name']: row['member_key'] for row in CATALOG if row['member_key']}

def validate_options(values):
    if not isinstance(values, dict) or len(values) > len(INDEX):
        raise ValueError('cache_options: 参数必须为对象')
    result = {}
    for name, value in values.items():
        row = INDEX.get(name)
        if not row or row['managed']:
            raise ValueError('cache_options: 含未知参数或平台托管参数')
        if not isinstance(value, str) or len(value) > 4096 or any((ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError(f'{name}: 参数须为不含控制字符的文本')
        if name == 'id' and value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
            raise ValueError('id: 使用1–128位字母、数字、下划线、点或短横线，首位为字母或数字')
        typ = row['type']
        if typ in ('uint32', 'uint64', 'int32', 'int64'):
            if not re.fullmatch('-?[0-9]+', value):
                raise ValueError(f'{name}: 必须为整数')
            bits = int(typ[-2:])
            signed = typ.startswith('int')
            low, high = (-2 ** (bits - 1), 2 ** (bits - 1) - 1) if signed else (0, 2 ** bits - 1)
            if not low <= int(value) <= high:
                raise ValueError(f'{name}: 超出 {typ} 范围')
            if name in ('cache_size_mb', 'cache_rdma_port_num') and int(value) < 1:
                raise ValueError(f'{name}: 必须大于 0')
            if name == 'cache_rdma_port_num' and int(value) > 255:
                raise ValueError(f'{name}: 端口必须在 1–255 之间')
            value = str(int(value))
        elif typ == 'double':
            try:
                number = float(value)
            except ValueError:
                raise ValueError(f'{name}: 必须为数值') from None
            if not math.isfinite(number) or (name == 'free_space_ratio' and (not 0 <= number <= 1)):
                raise ValueError(f'{name}: 数值超出范围')
        elif typ == 'bool' and value not in ('true', 'false'):
            raise ValueError(f'{name}: 必须为 true 或 false')
        if row.get('choices') and value not in row['choices']:
            raise ValueError(f'{name}: 不支持的选项')
        if name == 'cache_dir':
            from dingofs_platform.resources.schemas import _string
            _string('cache_dir', value)
        result[name] = value
    return result

def member_defaults(options):
    result = {}
    for name, key in MEMBER_KEYS.items():
        if name not in options:
            continue
        value = options[name]
        typ = INDEX[name]['type']
        result[key] = value == 'true' if typ == 'bool' else int(value) if typ.startswith(('int', 'uint')) else value
    return result
