#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从进程环境或工作区 .env 读取公共组件配置。"""

import os
from pathlib import Path


def read_env_file_value(path, name):
    """从指定 .env 文件读取一个配置值。"""
    with Path(path).resolve().open(encoding='utf-8-sig') as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key.strip() == name:
                return value.strip().strip('"\'')
    return ''


def iter_env_files():
    """按工作目录和组件目录由近到远枚举 .env。"""
    checked = set()
    for root in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for directory in (root, *root.parents):
            candidate = directory / '.env'
            if candidate not in checked:
                checked.add(candidate)
                yield candidate


def read_env_value(name):
    """优先读取进程环境变量，否则向上查找 .env。"""
    environment_value = str(os.environ.get(name) or '').strip()
    if environment_value:
        return environment_value
    for path in iter_env_files():
        if path.is_file():
            value = read_env_file_value(path, name)
            if value:
                return value
    return ''
