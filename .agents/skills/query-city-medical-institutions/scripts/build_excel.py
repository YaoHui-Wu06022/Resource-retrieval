#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成行政单位级医疗工作簿并合并为城市总表。"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook
from query_city_core.address.city import validate_city_context
from query_city_core.excel_output import (
    ResultWorkbookSpec,
    create_result_workbook,
    main_headers,
    write_result_workbook_atomically,
)
from query_city_core.excel_style import (
    validate_common_worksheet,
    write_workbook_atomically,
)
from query_city_core.io_utils import read_json_payload


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


DOMAIN_HEADERS = ('行政单位', '机构名称', '机构类型', '机构级别')
DOMAIN_WIDTHS = (14, 40, 26, 16)
MAIN_SHEET = '机构信息'
ABNORMAL_SHEET = '异常机构'
EMPTY_LEVEL_VALUES = frozenset({'未定级', '无定级', '无级别'})


def _display_institution_level(value):
    """把无实质等级意义的机构级别显示为空。"""
    level_text = str(value or '').strip()
    return '' if level_text in EMPTY_LEVEL_VALUES else level_text


def _domain_values(record):
    """从记录取机构领域列值。"""
    attributes = record.get('attributes') or {}
    return [
        str(attributes.get('administrative_unit') or '').strip(),
        str(record.get('place_name') or '').strip(),
        str(attributes.get('institution_type') or '').strip(),
        _display_institution_level(attributes.get('institution_level')),
    ]


def resolve_effective_administrative_unit(record, subdivision_names):
    """按最终地址、来源行政区、执照区顺序解析区级归属。"""
    final_address = str(record.get('final_address') or '').strip()
    if final_address:
        for unit_name in sorted(
            (name for name in subdivision_names if name),
            key=len,
            reverse=True,
        ):
            if unit_name in final_address:
                return unit_name
    attributes = record.get('attributes') or {}
    return str(
        (attributes.get('administrative_unit') or '').strip()
        or (attributes.get('license_administrative_unit') or '').strip()
    )


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
    """返回异常记录的展示原因。"""
    attributes = record.get('attributes') or {}
    return str(
        (attributes.get('abnormal_reason') or '').strip()
        or record.get('map_reason')
        or record.get('normalization_reason')
        or '官方来源未提供可用地址'
    ).strip()


def _is_abnormal_record(record):
    """判断记录是否进入异常机构表。"""
    return (
        not str(record.get('final_address') or '').strip()
        and (
            not str(record.get('original_address') or '').strip()
            or str(
                (record.get('attributes') or {}).get('abnormal_reason') or ''
            ).strip()
        )
    )


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
        if _is_abnormal_record(record)
    ]


def _write_workbook(output_path, spec, main_rows, abnormal_rows):
    """用公共生成器原子写出一个医疗工作簿。"""
    return write_result_workbook_atomically(
        spec,
        MAIN_SHEET,
        ABNORMAL_SHEET,
        [(MAIN_SHEET, main_rows)],
        abnormal_rows,
        output_path,
    )


def _validate_main_only_workbook(temporary_path, spec, main_sheets):
    """校验不含异常表的多主表城市总表。"""
    loaded = load_workbook(temporary_path, data_only=False)
    try:
        expected_sheet_names = [sheet_name for sheet_name, _ in main_sheets]
        if loaded.sheetnames != expected_sheet_names:
            raise ValueError('工作簿的工作表名称或顺序不正确')
        headers = main_headers(spec)
        for sheet_name, rows in main_sheets:
            validate_common_worksheet(
                loaded[sheet_name], headers, len(rows)
            )
    finally:
        loaded.close()


def _write_main_only_workbook(output_path, spec, main_sheets):
    """生成不含异常表的城市总表并原子保存。"""
    workbook = create_result_workbook(
        spec,
        MAIN_SHEET,
        ABNORMAL_SHEET,
        main_sheets,
        [],
    )
    workbook.remove(workbook[ABNORMAL_SHEET])

    def validate(temporary_path):
        _validate_main_only_workbook(
            temporary_path, spec, main_sheets
        )

    return write_workbook_atomically(
        workbook, Path(output_path), validate
    )


def load_unit_payload(input_path):
    """读取并校验一个行政单位目录的地址处理结果。"""
    payload = read_json_payload(input_path)
    if payload.get('stage') != 'processed_address_records':
        raise ValueError(
            f'{input_path} 阶段必须是 processed_address_records'
        )
    validate_city_context(payload.get('city_context'))
    if not isinstance(payload.get('items'), list):
        raise ValueError(f'{input_path} items 必须是数组')
    return payload


def collect_administrative_unit_payloads(input_dir):
    """收集各行政单位目录中的地址处理结果。"""
    root = Path(input_dir).resolve()
    if not root.is_dir():
        raise ValueError(f'输入目录不存在：{root}')
    unit_payloads = []
    city_name = ''
    for unit_dir in sorted(root.iterdir(), key=lambda path: path.name):
        processed_path = unit_dir / 'processed_address_records.json'
        if not unit_dir.is_dir() or not processed_path.is_file():
            continue
        payload = load_unit_payload(processed_path)
        payload_city = payload['city_context']['city_name']
        if city_name and payload_city != city_name:
            raise ValueError('各行政单位处理结果的 city 不一致')
        city_name = payload_city
        unit_payloads.append((unit_dir.name, unit_dir, payload))
    if not unit_payloads:
        raise ValueError('没有找到任何 processed_address_records.json')
    return city_name, unit_payloads


def scope_records_to_unit(records, unit_name, subdivision_names):
    """把记录归属到目录行政单位并校验，防止跨区记录混入。"""
    scoped_records = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f'{unit_name}包含非对象地址记录')
        effective_record = dict(record)
        effective_attributes = dict(record.get('attributes') or {})
        effective_unit = resolve_effective_administrative_unit(
            record, subdivision_names
        )
        if not effective_unit:
            raise ValueError(
                f'{record.get("place_name")} 无法确定行政单位'
            )
        if effective_unit != unit_name:
            raise ValueError(
                f'{record.get("place_name")} 的行政单位'
                f'“{effective_unit}”与目录不一致'
            )
        effective_attributes['administrative_unit'] = effective_unit
        effective_record['attributes'] = effective_attributes
        scoped_records.append(effective_record)
    return scoped_records


def main():
    """生成所有行政单位工作簿和一个城市总表。"""
    parser = argparse.ArgumentParser(
        description='生成医疗机构行政单位表和城市总表'
    )
    parser.add_argument(
        '--input-dir',
        required=True,
        help='包含各行政单位目录的 Medical_Institutions 运行目录',
    )
    parser.add_argument(
        '--output',
        required=True,
        help='城市总表输出路径',
    )
    arguments = parser.parse_args()
    try:
        city_name, unit_payloads = collect_administrative_unit_payloads(
            arguments.input_dir
        )
        subdivision_names = [
            str(item.get('name') or '').strip()
            for item in unit_payloads[0][2]['city_context'].get(
                'subdivisions'
            ) or []
        ]
        spec = ResultWorkbookSpec(DOMAIN_HEADERS, DOMAIN_WIDTHS)
        merged_main_rows = []
        unit_outputs = []
        unit_main_sheets = []
        for unit_name, unit_dir, payload in unit_payloads:
            records = scope_records_to_unit(
                payload['items'], unit_name, subdivision_names
            )
            main_rows = build_main_rows(records)
            abnormal_rows = build_abnormal_rows(records)
            unit_output_path = _write_workbook(
                unit_dir / f'医疗机构信息_{unit_name}.xlsx',
                spec,
                main_rows,
                abnormal_rows,
            )
            unit_outputs.append({
                'administrative_unit': unit_name,
                'output': str(unit_output_path),
                'row_count': len(main_rows),
                'abnormal_row_count': len(abnormal_rows),
            })
            merged_main_rows.extend(main_rows)
            unit_main_sheets.append((unit_name, main_rows))
        city_main_sheets = [
            (MAIN_SHEET, merged_main_rows),
            *unit_main_sheets,
        ]
        city_output_path = _write_main_only_workbook(
            Path(arguments.output).resolve(),
            spec,
            city_main_sheets,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        'output': str(city_output_path),
        'city': city_name,
        'administrative_unit_count': len(unit_outputs),
        'row_count': len(merged_main_rows),
        'administrative_unit_outputs': unit_outputs,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
