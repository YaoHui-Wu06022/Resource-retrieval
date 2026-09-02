"""公共层的本地 JSON 文件读写。"""

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
