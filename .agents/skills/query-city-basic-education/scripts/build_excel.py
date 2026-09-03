#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成行政单位级基础教育工作簿并合并为城市总表。"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from query_city_core.address.city import validate_city_context
from query_city_core.io_utils import read_json_payload
from query_city_core.excel_output import (
    ResultWorkbookSpec,
    abnormal_headers as common_abnormal_headers,
    create_result_workbook,
    main_headers as common_main_headers,
    write_result_workbook_atomically,
)
from query_city_core.excel_style import format_date_cell
from normalize_school_records import merge_school_types


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


SHEET_NAME = '学校信息'
ABNORMAL_SHEET_NAME = '异常校'
DOMAIN_HEADERS = (
    '行政单位',
    '学校名称',
    '学校类型',
    '办学性质',
    '发布日期',
)
DOMAIN_WIDTHS = (14, 36, 20, 12, 18)


def _spec():
    return ResultWorkbookSpec(
        DOMAIN_HEADERS,
        DOMAIN_WIDTHS,
        official_source_label='政府资料',
        map_source_label='高德地图',
    )


OUTPUT_HEADER = common_main_headers(_spec())
ABNORMAL_HEADERS = common_abnormal_headers(_spec())
SCHOOL_NAME_SEPARATOR_PATTERN = re.compile(r'[\s（）()【】\[\]·•]+')
SCHOOL_CAMPUS_SUFFIX_PATTERN = re.compile(
    r'(?P<base>.+?(?:幼儿园|小学|中学|学校))'
    r'(?:校本部|本部|(?:(?!(?:幼儿园|小学|中学|学校)).){1,20}'
    r'(?:校区|园区))$'
)
SCHOOL_STAGE_SUFFIX_PATTERN = re.compile(
    r'(?:(?<=学校)(?:小学|初中|高中)|(?:小学|初中|高中)部)$'
)


SCHOOL_TYPE_SORT_PRIORITIES = {
    '幼儿园': 0,
    '小学': 1,
    '九年一贯制学校': 2,
    '初中': 3,
    '完全中学': 4,
    '高中': 5,
    '十二年一贯制学校': 6,
    '特殊教育学校': 8,
    '中等职业学校': 9,
    '职业高级中学': 10,
    '技工院校': 11,
    '专门学校': 12,
}
OTHER_CONSISTENT_SCHOOL_PRIORITY = 7
OTHER_SCHOOL_TYPE_PRIORITY = 13


def load_processed_address_records(input_path):
    """读取并校验一个行政单位的公共地址处理结果。"""
    address_payload = read_json_payload(input_path)
    if not isinstance(address_payload, dict):
        raise ValueError(f'{input_path} 顶层必须是对象')
    if address_payload.get('stage') != 'processed_address_records':
        raise ValueError(f'{input_path} 阶段必须是 processed_address_records')
    try:
        validate_city_context(address_payload.get('city_context'))
    except ValueError as exc:
        raise ValueError(f'{input_path} 的城市上下文无效：{exc}') from exc
    if not isinstance(address_payload.get('items'), list):
        raise ValueError(f'{input_path} 的 items 必须是数组')
    return address_payload


def collect_administrative_unit_payloads(input_dir):
    """收集各行政单位目录中的公共地址处理结果。"""
    input_root_dir = Path(input_dir).resolve()
    if not input_root_dir.is_dir():
        raise ValueError(f'输入目录不存在：{input_root_dir}')
    administrative_unit_payloads = []
    city_name = ''
    for administrative_unit_dir in sorted(
        input_root_dir.iterdir(), key=lambda unit_path: unit_path.name
    ):
        processed_records_path = (
            administrative_unit_dir / 'processed_address_records.json'
        )
        if not administrative_unit_dir.is_dir() or not processed_records_path.is_file():
            continue
        address_payload = load_processed_address_records(processed_records_path)
        payload_city = address_payload['city_context']['city_name']
        if city_name and payload_city != city_name:
            raise ValueError('各行政单位处理结果的 city 不一致')
        city_name = payload_city
        administrative_unit_payloads.append((
            administrative_unit_dir.name,
            administrative_unit_dir,
            address_payload,
        ))
    if not administrative_unit_payloads:
        raise ValueError('没有找到任何 processed_address_records.json')
    return city_name, administrative_unit_payloads


def normalize_school_identity(place_name, administrative_unit, city_name):
    """规范学校名称以识别同址校区别名和学段写法。"""
    school_identity = SCHOOL_NAME_SEPARATOR_PATTERN.sub('', place_name)
    if city_name and school_identity.startswith(city_name):
        school_identity = school_identity[len(city_name):]
    if administrative_unit and school_identity.startswith(administrative_unit):
        school_identity = school_identity[len(administrative_unit):]
    school_identity = SCHOOL_STAGE_SUFFIX_PATTERN.sub('', school_identity)
    campus_match = SCHOOL_CAMPUS_SUFFIX_PATTERN.fullmatch(school_identity)
    return campus_match.group('base') if campus_match else school_identity


def deduplicate_school_output_records(output_records, city_name):
    """按学校身份和最终地址合并同址别名记录。"""
    unique_records = []
    record_indexes = {}
    for output_record in output_records:
        record_key = (
            output_record['administrative_unit'],
            output_record['final_address'],
            normalize_school_identity(
                output_record['place_name'],
                output_record['administrative_unit'],
                city_name,
            ),
        )
        if record_key not in record_indexes:
            record_indexes[record_key] = len(unique_records)
            unique_records.append(output_record)
            continue
        record_index = record_indexes[record_key]
        current_record = unique_records[record_index]
        school_type = merge_school_types(
            current_record['school_type'], output_record['school_type']
        )
        school_nature = (
            current_record['school_nature'] or output_record['school_nature']
        )
        if output_record['publication_date'] > current_record['publication_date']:
            current_record = output_record.copy()
            unique_records[record_index] = current_record
        current_record['school_type'] = school_type
        current_record['school_nature'] = school_nature
    return unique_records


def resolve_school_type_sort_priority(school_type):
    """确定学校类型在行政单位表中的排序优先级。"""
    priorities = []
    for type_name in str(school_type or '').split('、'):
        if type_name in SCHOOL_TYPE_SORT_PRIORITIES:
            priorities.append(SCHOOL_TYPE_SORT_PRIORITIES[type_name])
        elif re.fullmatch(r'.+年一贯制学校', type_name):
            priorities.append(OTHER_CONSISTENT_SCHOOL_PRIORITY)
        else:
            priorities.append(OTHER_SCHOOL_TYPE_PRIORITY)
    return min(priorities, default=OTHER_SCHOOL_TYPE_PRIORITY)


def sort_school_output_records(output_records):
    """按学校类型稳定排序一个行政单位的展示记录。"""
    return sorted(
        output_records,
        key=lambda record: resolve_school_type_sort_priority(
            record['school_type']
        ),
    )


def build_school_output_records(
    administrative_unit_name, address_records, city_name=''
):
    """过滤空最终地址并整理一个行政单位的展示记录。"""
    output_records = []
    for address_record in address_records:
        if not isinstance(address_record, dict):
            raise ValueError(f'{administrative_unit_name}包含非对象地址记录')
        final_address = str(address_record.get('final_address') or '').strip()
        if not final_address:
            continue
        place_name = str(address_record.get('place_name') or '').strip()
        source_reference = str(
            address_record.get('source_reference') or ''
        ).strip()
        record_attributes = address_record.get('attributes') or {}
        if not place_name or not source_reference or not isinstance(record_attributes, dict):
            raise ValueError(
                f'{administrative_unit_name}存在缺少名称、来源或属性的有效记录'
            )
        administrative_unit = str(
            record_attributes.get('administrative_unit') or ''
        ).strip()
        if administrative_unit != administrative_unit_name:
            raise ValueError(
                f'{place_name}的行政单位“{administrative_unit}”与目录不一致'
            )
        output_records.append({
            'administrative_unit': administrative_unit,
            'place_name': place_name,
            'school_type': str(record_attributes.get('school_type') or '').strip(),
            'school_nature': str(record_attributes.get('school_nature') or '').strip(),
            'publication_date': format_date_cell(
                record_attributes.get('publication_date'),
                date.today().isoformat(),
            ),
            'final_address': final_address,
            'address_acquisition_method': (
                '高德地图'
                if address_record.get('final_address_source') == 'map'
                else '政府资料'
            ),
            'map_match_status': address_record.get('map_match_status') or 'skipped',
            'source_reference': source_reference,
        })
    return sort_school_output_records(
        deduplicate_school_output_records(output_records, city_name)
    )


def _domain_values_from_record(record):
    """从整理后的学校展示记录取公共领域列值。"""
    return [
        str(record.get('administrative_unit') or '').strip(),
        str(record.get('place_name') or '').strip(),
        str(record.get('school_type') or '').strip(),
        str(record.get('school_nature') or '').strip(),
        str(record.get('publication_date') or '').strip(),
    ]


def _main_common_rows(output_records):
    """把学校展示记录转换为公共生成器输入。"""
    rows = []
    for record in output_records:
        address_record = {
            'place_name': record['place_name'],
            'source_reference': record['source_reference'],
            'final_address': record['final_address'],
            'final_address_source': (
                'map'
                if record.get('address_acquisition_method') == '高德地图'
                else 'official'
            ),
            'map_match_status': record.get('map_match_status') or 'skipped',
        }
        rows.append((_domain_values_from_record(record), address_record))
    return rows


def _domain_values_from_address_record(address_record):
    attributes = address_record.get('attributes') or {}
    return [
        str(attributes.get('administrative_unit') or '').strip(),
        str(address_record.get('place_name') or '').strip(),
        str(attributes.get('school_type') or '').strip(),
        str(attributes.get('school_nature') or '').strip(),
        format_date_cell(
            attributes.get('publication_date'),
            date.today().isoformat(),
        ),
    ]


def _abnormal_reason_from_record(address_record):
    return str(
        address_record.get('map_reason')
        or address_record.get('normalization_reason')
        or address_record.get('final_address_reason')
        or ''
    ).strip()


def build_worksheet_rows(output_records):
    """返回公共生成器使用的 (领域值, 地址记录) 行。"""
    return _main_common_rows(output_records)


def build_abnormal_rows(administrative_unit_name, address_records):
    """构造异常校公共行：领域值、原记录与原因。"""
    rows = []
    for address_record in address_records:
        if not isinstance(address_record, dict):
            raise ValueError(
                f'{administrative_unit_name}包含非对象地址记录'
            )
        if str(address_record.get('final_address') or '').strip():
            continue
        place_name = str(address_record.get('place_name') or '').strip()
        source_reference = str(
            address_record.get('source_reference') or ''
        ).strip()
        if not place_name or not source_reference:
            raise ValueError(
                f'{administrative_unit_name}存在缺少名称或来源的异常记录'
            )
        attributes = address_record.get('attributes') or {}
        if str(attributes.get('administrative_unit') or '') != (
            administrative_unit_name
        ):
            raise ValueError(
                f'{place_name}的行政单位与目录不一致'
            )
        rows.append((
            _domain_values_from_address_record(address_record),
            address_record,
            _abnormal_reason_from_record(address_record),
        ))
    return rows


def write_workbook(output_path, sheet_records):
    """用公共生成器创建并原子保存工作簿。"""
    main_sheets = []
    abnormal_rows = []
    for sheet_name, rows in sheet_records:
        if sheet_name == ABNORMAL_SHEET_NAME:
            abnormal_rows = list(rows)
        else:
            main_sheets.append((sheet_name, _main_common_rows(rows)))
    return write_result_workbook_atomically(
        _spec(),
        SHEET_NAME,
        ABNORMAL_SHEET_NAME,
        main_sheets,
        abnormal_rows,
        output_path,
    )


def main():
    """生成所有行政单位工作簿和一个城市总表。"""
    parser = argparse.ArgumentParser(
        description='生成基础教育行政单位表和城市总表'
    )
    parser.add_argument('--input-dir', required=True, help='城市输出目录')
    parser.add_argument('--output', required=True, help='城市总表输出路径')
    arguments = parser.parse_args()
    try:
        city, administrative_unit_payloads = collect_administrative_unit_payloads(
            arguments.input_dir
        )
        merged_records = []
        administrative_unit_outputs = []
        administrative_unit_sheets = []
        for unit_name, unit_dir, address_payload in administrative_unit_payloads:
            unit_records = build_school_output_records(
                unit_name, address_payload['items'], city
            )
            unit_abnormal_rows = build_abnormal_rows(
                unit_name, address_payload['items']
            )
            unit_output_path = write_workbook(
                unit_dir / f'基础教育学校信息_{unit_name}.xlsx',
                [
                    (SHEET_NAME, unit_records),
                    (ABNORMAL_SHEET_NAME, unit_abnormal_rows),
                ],
            )
            administrative_unit_outputs.append({
                'administrative_unit': unit_name,
                'output': str(unit_output_path),
                'row_count': len(unit_records),
                'abnormal_row_count': len(unit_abnormal_rows),
            })
            merged_records.extend(unit_records)
            administrative_unit_sheets.append((unit_name, unit_records))
        city_output = write_workbook(
            arguments.output,
            [(SHEET_NAME, merged_records), *administrative_unit_sheets],
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        'city': city,
        'administrative_unit_count': len(administrative_unit_outputs),
        'row_count': len(merged_records),
        'administrative_unit_outputs': administrative_unit_outputs,
        'output': str(city_output),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
