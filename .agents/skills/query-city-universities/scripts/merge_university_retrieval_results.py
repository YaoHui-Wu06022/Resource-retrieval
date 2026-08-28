#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并子 Agent 生成的逐校高校检索结果。"""

import argparse
import json
import sys
from pathlib import Path

from build_university_address_records import (
    build_page_results_payload,
    validate_base_information,
)
from script_io import read_json_payload, write_json_payload


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def read_school_result_files(input_dir, base_school_index):
    """读取以学校标识码命名的逐校结果文件。"""
    school_results = {}
    for input_path in sorted(Path(input_dir).resolve().glob('*.json')):
        school_result = read_json_payload(input_path)
        if not isinstance(school_result, dict):
            raise ValueError(f'{input_path.name} 顶层必须是对象')
        school_identifier = str(
            school_result.get('school_identifier') or ''
        ).strip()
        if input_path.stem != school_identifier:
            raise ValueError(
                f'{input_path.name} 文件名必须等于学校标识码'
            )
        if school_identifier not in base_school_index:
            raise ValueError(f'出现基础名单外学校标识码：{school_identifier}')
        if school_identifier in school_results:
            raise ValueError(f'学校结果重复：{school_identifier}')
        school_results[school_identifier] = school_result
    return school_results


def merge_school_results(input_dir, base_payload):
    """按基础名单顺序合并并校验全部逐校结果。"""
    _, base_school_index = validate_base_information(base_payload)
    school_results = read_school_result_files(input_dir, base_school_index)
    retrieval_payload = {
        'items': [
            school_results[school_identifier]
            for school_identifier in base_school_index
            if school_identifier in school_results
        ],
    }
    build_page_results_payload(retrieval_payload, base_payload)
    return retrieval_payload


def main():
    """解析参数并写出完整高校检索结果。"""
    parser = argparse.ArgumentParser(
        description='合并以学校标识码命名的逐校高校检索结果'
    )
    parser.add_argument('--input-dir', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        input_dir = Path(args.input_dir).resolve()
        if not input_dir.is_dir():
            raise ValueError(f'逐校结果目录不存在：{input_dir}')
        base_path = input_dir.parent / 'base_information.json'
        output_path = Path(args.output).resolve()
        if output_path.parent == input_dir:
            raise ValueError('汇总文件不得写入逐校结果目录')
        base_payload = read_json_payload(base_path)
        retrieval_payload = merge_school_results(input_dir, base_payload)
        write_json_payload(output_path, retrieval_payload)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        'output': str(output_path),
        'school_count': len(retrieval_payload['items']),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
