#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校工作簿薄包装：领域列与去重保留在 Skill，布局交给公共生成器。"""

import argparse
import json
import sys
from datetime import date

from query_city_core.address.city import validate_city_context
from query_city_core.excel_output import (
    ResultWorkbookSpec,
    abnormal_headers as common_abnormal_headers,
    create_result_workbook,
    main_headers as common_main_headers,
    verify_result_workbook,
    write_result_workbook_atomically,
)
from query_city_core.io_utils import read_json_payload

from build_university_address import postprocess_university_address_records


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


SHEET_NAME = '高校信息'
ABNORMAL_SHEET_NAME = '异常校'
DOMAIN_HEADERS = (
    '学校名称',
    '主管部门',
    '办学层次',
    '院校标签',
    '办学性质',
)
DOMAIN_WIDTHS = (32, 18, 12, 12, 12)


def _spec():
    return ResultWorkbookSpec(
        DOMAIN_HEADERS,
        DOMAIN_WIDTHS,
        official_source_label='官网提取',
        map_source_label='地图信息',
    )


OUTPUT_HEADER = common_main_headers(_spec())
ABNORMAL_HEADERS = common_abnormal_headers(_spec())


def load_processed_records(input_path):
    """读取并校验公共层处理完成的高校地址记录。"""
    payload = read_json_payload(input_path)
    if payload.get('stage') != 'processed_address_records':
        raise ValueError('输入文件阶段必须是 processed_address_records')
    validate_city_context(payload.get('city_context'))
    if not isinstance(payload.get('items'), list):
        raise ValueError('processed_address_records.items 必须是数组')
    return payload


def _read_source_sequence(address_record):
    """读取用于排序的源表序号。"""
    source_sequence = str(
        (address_record.get('attributes') or {}).get('source_sequence') or ''
    ).strip()
    if not source_sequence.isdigit():
        raise ValueError('有效地址记录必须包含纯数字 source_sequence')
    return int(source_sequence)


def _domain_values(address_record):
    attributes = address_record.get('attributes') or {}
    return [
        str(address_record.get('place_name') or '').strip(),
        str(attributes.get('supervising_authority') or '').strip(),
        str(attributes.get('education_level') or '').strip(),
        str(attributes.get('school_tag') or '').strip(),
        str(attributes.get('school_nature') or '').strip(),
    ]


def build_output_rows(address_records, city_name):
    """过滤无效地址并按源表顺序返回 (领域值, 地址记录)。"""
    effective_records = []
    address_records = postprocess_university_address_records(address_records)
    for input_position, address_record in enumerate(address_records):
        if not isinstance(address_record, dict):
            raise ValueError('processed_address_records.items 元素必须是对象')
        final_address = str(
            address_record.get('final_address') or ''
        ).strip()
        if not final_address or not final_address.startswith(city_name):
            continue
        place_name = str(address_record.get('place_name') or '').strip()
        source_reference = str(
            address_record.get('source_reference') or ''
        ).strip()
        if not place_name or not source_reference:
            raise ValueError('有效地址记录缺少名称或来源')
        effective_records.append((
            _read_source_sequence(address_record),
            input_position,
            address_record,
        ))
    effective_records.sort(key=lambda item: (item[0], item[1]))
    return [
        (_domain_values(record), record)
        for _, _, record in effective_records
    ]


def build_abnormal_reason(address_record):
    """从业务、地图与规范化原因中取最具体的一项。"""
    attributes = address_record.get('attributes') or {}
    return str(
        (attributes.get('abnormal_reason') or '').strip()
        or address_record.get('map_reason')
        or address_record.get('normalization_reason')
        or address_record.get('final_address_reason')
        or ''
    ).strip()


def build_abnormal_rows(address_records):
    """构造最终地址为空的异常校行。"""
    rows = []
    for address_record in postprocess_university_address_records(
        address_records
    ):
        if not isinstance(address_record, dict):
            raise ValueError('address_records 元素必须是对象')
        if str(address_record.get('final_address') or '').strip():
            continue
        place_name = str(address_record.get('place_name') or '').strip()
        source_reference = str(
            address_record.get('source_reference') or ''
        ).strip()
        if not place_name or not source_reference:
            raise ValueError('异常校记录缺少名称或来源')
        rows.append((
            _domain_values(address_record),
            address_record,
            build_abnormal_reason(address_record),
        ))
    return rows


def create_workbook(output_rows, abnormal_rows=()):
    """创建高校信息与异常校两个工作表的最终工作簿。"""
    return create_result_workbook(
        _spec(),
        SHEET_NAME,
        ABNORMAL_SHEET_NAME,
        [(SHEET_NAME, output_rows)],
        list(abnormal_rows),
    )


def verify_workbook(workbook_path, expected_row_count, abnormal_row_count=0):
    """重新读取并校验最终工作簿。"""
    return verify_result_workbook(
        workbook_path,
        _spec(),
        [(SHEET_NAME, expected_row_count)],
        ABNORMAL_SHEET_NAME,
        abnormal_row_count,
    )


def main():
    """解析参数并生成高校最终信息工作簿。"""
    parser = argparse.ArgumentParser(description='生成高校最终信息工作簿')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    payload = load_processed_records(args.input)
    output_rows = build_output_rows(
        payload['items'],
        payload['city_context']['city_name'],
    )
    abnormal_rows = build_abnormal_rows(payload['items'])
    output = write_result_workbook_atomically(
        _spec(),
        SHEET_NAME,
        ABNORMAL_SHEET_NAME,
        [(SHEET_NAME, output_rows)],
        abnormal_rows,
        args.output,
    )
    print(json.dumps({
        'output': str(output),
        'city': payload['city_context']['city_name'],
        'row_count': len(output_rows),
        'abnormal_row_count': len(abnormal_rows),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
