#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""医疗机构工作簿薄包装：只提供领域列与行筛选，布局交给公共生成器。"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from query_city_core.address.city import validate_city_context
from query_city_core.excel_output import (
    ResultWorkbookSpec,
    write_result_workbook_atomically,
)
from query_city_core.io_utils import read_json_payload


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


DOMAIN_HEADERS = ('行政单位', '机构名称', '机构类型', '机构级别')
DOMAIN_WIDTHS = (14, 40, 26, 16)


def _read_payload(path):
    payload = read_json_payload(path)
    validate_city_context(payload.get('city_context'))
    if not isinstance(payload.get('items'), list):
        raise ValueError('items 必须是数组')
    return payload


def _domain_values(record):
    attributes = record.get('attributes') or {}
    return [
        str(attributes.get('administrative_unit') or '').strip(),
        str(record.get('place_name') or '').strip(),
        str(attributes.get('institution_type') or '').strip(),
        str(attributes.get('institution_level') or '').strip(),
    ]


def _effective_main_record(record):
    """官方地址可用但地图未确认时，主表仍展示官方地址。"""
    effective = dict(record)
    final_address = str(record.get('final_address') or '').strip()
    original_address = str(record.get('original_address') or '').strip()
    if not final_address and original_address:
        effective['final_address'] = original_address
        effective['final_address_source'] = 'official'
        effective['map_match_status'] = 'skipped'
    return effective


def _abnormal_reason(record):
    attributes = record.get('attributes') or {}
    return str(
        (attributes.get('abnormal_reason') or '').strip()
        or record.get('map_reason')
        or record.get('normalization_reason')
        or '官方来源未提供可用地址'
    ).strip()


def build_main_rows(records):
    """过滤无地址记录并返回公共生成器需要的 (领域值, 地址记录)。"""
    rows = []
    for record in records:
        effective = _effective_main_record(record)
        if not str(effective.get('final_address') or '').strip():
            continue
        rows.append((_domain_values(record), effective))
    return rows


def build_abnormal_rows(records):
    """构造异常机构行。"""
    return [
        (_domain_values(record), record, _abnormal_reason(record))
        for record in records
    ]


def _write_workbook(output_path, spec, main_rows, abnormal_rows):
    return write_result_workbook_atomically(
        spec,
        '机构信息',
        '异常机构',
        [('机构信息', main_rows)],
        abnormal_rows,
        output_path,
    )


def main():
    """解析参数并生成医疗机构工作簿。"""
    parser = argparse.ArgumentParser(description='生成医疗机构信息 Excel')
    parser.add_argument('--input', required=True)
    parser.add_argument('--anomalies', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    processed = _read_payload(args.input)
    anomalies = _read_payload(args.anomalies)
    city_name = processed['city_context']['city_name']
    spec = ResultWorkbookSpec(DOMAIN_HEADERS, DOMAIN_WIDTHS)
    processed_abnormal = [
        record
        for record in processed['items']
        if not str(record.get('final_address') or '').strip()
        and not str(record.get('original_address') or '').strip()
    ]
    main_rows = build_main_rows(processed['items'])
    abnormal_rows = build_abnormal_rows(
        list(anomalies['items']) + processed_abnormal
    )
    output = _write_workbook(
        args.output, spec, main_rows, abnormal_rows
    )
    district_outputs = []
    rows_by_unit = defaultdict(list)
    for domain_values, record in main_rows:
        rows_by_unit[str(domain_values[0])].append((domain_values, record))
    abnormal_by_unit = defaultdict(list)
    for domain_values, record, reason in abnormal_rows:
        abnormal_by_unit[str(domain_values[0])].append(
            (domain_values, record, reason)
        )
    for unit in sorted(set(rows_by_unit) | set(abnormal_by_unit)):
        district_path = (
            Path(args.output).parent / f'医疗机构信息_{unit}.xlsx'
        )
        district_outputs.append(str(_write_workbook(
            district_path,
            spec,
            rows_by_unit.get(unit, []),
            abnormal_by_unit.get(unit, []),
        )))
    print(json.dumps({
        'output': str(output),
        'city': city_name,
        'row_count': len(main_rows),
        'abnormal_row_count': len(abnormal_rows),
        'district_outputs': district_outputs,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
