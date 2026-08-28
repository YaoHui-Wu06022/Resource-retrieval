#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提供高校 Skill 脚本共享的本地文件读写。"""

import json
import os
import tempfile
from pathlib import Path


def read_json_payload(path):
    """读取 UTF-8 JSON 文件。"""
    with Path(path).resolve().open(encoding='utf-8') as stream:
        return json.load(stream)


def write_json_payload(path, payload):
    """原子写入 UTF-8 JSON 文件。"""
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=output.stem + '.',
        suffix='.tmp.json',
        dir=output.parent,
    )
    os.close(handle)
    try:
        with open(temporary, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output


def write_workbook_atomically(workbook, output_path, validate):
    """原子保存工作簿并在替换前执行校验。"""
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=output.stem + '.',
        suffix='.tmp.xlsx',
        dir=output.parent,
    )
    os.close(handle)
    try:
        workbook.save(temporary)
        validate(temporary)
        os.replace(temporary, output)
    finally:
        workbook.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output
