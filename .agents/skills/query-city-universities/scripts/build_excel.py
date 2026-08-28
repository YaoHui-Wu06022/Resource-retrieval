#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把高校公共地址处理结果写入最终 Excel。"""

import argparse
from copy import copy
from datetime import date
import json
import re
import sys
from urllib.parse import urlparse

import openpyxl

from query_city_core.city import validate_city_context
from query_city_core.excel_style import build_table_workbook
from build_university_address_post import postprocess_university_address_records
from script_io import read_json_payload, write_workbook_atomically


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


SHEET_NAME = '高校信息'
OUTPUT_HEADER = [
    '序号',
    '学校名称',
    '主管部门',
    '办学层次',
    '院校标签',
    '办学性质',
    '地址',
    '地址获取方式',
    '查询日期',
    '信息来源',
]
COLUMN_WIDTHS = [8, 32, 18, 12, 12, 12, 42, 14, 14, 50]


def load_processed_records(input_path):
    """读取并校验公共层处理完成的高校地址记录。"""
    payload = read_json_payload(input_path)
    if not isinstance(payload, dict):
        raise ValueError('输入文件顶层必须是对象')
    if payload.get('stage') != 'processed_address_records':
        raise ValueError('输入文件阶段必须是 processed_address_records')
    validate_city_context(payload.get('city_context'))
    if not isinstance(payload.get('items'), list):
        raise ValueError('processed_address_records.items 必须是数组')
    return payload


def _read_source_sequence(address_record):
    """读取用于排序的教育部源表序号。"""
    attributes = address_record.get('attributes')
    if not isinstance(attributes, dict):
        raise ValueError('有效地址记录的 attributes 必须是对象')
    source_sequence = str(attributes.get('source_sequence') or '').strip()
    if not source_sequence.isdigit():
        raise ValueError('有效地址记录必须包含纯数字 source_sequence')
    return int(source_sequence)


def build_output_rows(address_records):
    """过滤无效地址并构造按源表顺序排列的最终表格行。"""
    effective_records = []
    address_records = postprocess_university_address_records(address_records)
    for input_position, address_record in enumerate(address_records):
        if not isinstance(address_record, dict):
            raise ValueError('processed_address_records.items 中的元素必须是对象')
        final_address = str(address_record.get('final_address') or '').strip()
        if not final_address:
            continue
        place_name = str(address_record.get('place_name') or '').strip()
        source_reference = str(address_record.get('source_reference') or '').strip()
        if not place_name:
            raise ValueError('有效地址记录必须包含非空 place_name')
        if not source_reference:
            raise ValueError(f'{place_name}缺少信息来源')
        source_sequence = _read_source_sequence(address_record)
        effective_records.append((source_sequence, input_position, address_record))

    effective_records.sort(key=lambda entry: (entry[0], entry[1]))
    query_date = date.today().isoformat()
    output_rows = []
    for display_sequence, (_, _, address_record) in enumerate(
        effective_records, start=1
    ):
        attributes = address_record['attributes']
        output_rows.append([
            display_sequence,
            str(address_record['place_name']).strip(),
            str(attributes.get('supervising_authority') or '').strip(),
            str(attributes.get('education_level') or '').strip(),
            str(attributes.get('school_tag') or '').strip(),
            str(attributes.get('school_nature') or '').strip(),
            str(address_record['final_address']).strip(),
            ('地图信息' if address_record.get('final_address_source') == 'map'
             else '官网提取'),
            query_date,
            str(address_record['source_reference']).strip(),
        ])
    return output_rows


def _is_web_url(value):
    """判断信息来源是否为可点击的网页链接。"""
    parsed = urlparse(str(value or '').strip())
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def create_workbook(output_rows):
    """创建只有高校信息表的最终工作簿。"""
    workbook = build_table_workbook(
        SHEET_NAME,
        OUTPUT_HEADER,
        output_rows,
        COLUMN_WIDTHS,
    )
    worksheet = workbook[SHEET_NAME]

    for source_cell in worksheet['J'][1:]:
        if _is_web_url(source_cell.value):
            source_cell.hyperlink = source_cell.value
            hyperlink_font = copy(source_cell.font)
            hyperlink_font.color = '0563C1'
            hyperlink_font.underline = 'single'
            source_cell.font = hyperlink_font
    return workbook


def verify_workbook(workbook_path, expected_row_count):
    """重新读取工作簿并验证字段、数据和基础显示格式。"""
    workbook = openpyxl.load_workbook(workbook_path, data_only=False)
    try:
        if workbook.sheetnames != [SHEET_NAME]:
            raise ValueError('最终工作簿只能包含“高校信息”表')
        worksheet = workbook[SHEET_NAME]
        if [cell.value for cell in worksheet[1]] != OUTPUT_HEADER:
            raise ValueError('最终工作簿字段不正确')
        if worksheet.max_row - 1 != expected_row_count:
            raise ValueError('最终工作簿记录数不正确')

        address_column = OUTPUT_HEADER.index('地址') + 1
        for row in worksheet.iter_rows(
            min_row=1,
            max_row=worksheet.max_row,
            min_col=1,
            max_col=len(OUTPUT_HEADER),
        ):
            for cell in row:
                alignment = cell.alignment
                if alignment.horizontal != 'center' or alignment.vertical != 'center':
                    raise ValueError('最终工作簿存在未居中的单元格')
                expected_wrap = cell.row == 1 or (
                    cell.row >= 2 and cell.column == address_column
                )
                if bool(alignment.wrap_text) != expected_wrap:
                    raise ValueError('最终工作簿自动换行设置不正确')
                if alignment.indent not in {None, 0, 0.0}:
                    raise ValueError('最终工作簿不得设置缩进')

        for display_sequence, row_index in enumerate(
            range(2, worksheet.max_row + 1), start=1
        ):
            if worksheet.cell(row_index, 1).value != display_sequence:
                raise ValueError('最终工作簿序号不连续')
            if not str(worksheet.cell(row_index, 2).value or '').strip():
                raise ValueError('最终工作簿存在空学校名称')
            if not str(worksheet.cell(row_index, 7).value or '').strip():
                raise ValueError('最终工作簿存在空地址')
            acquisition_method = worksheet.cell(row_index, 8).value
            if acquisition_method not in {'官网提取', '地图信息'}:
                raise ValueError('最终工作簿存在无效地址获取方式')
            query_date = worksheet.cell(row_index, 9).value
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(query_date or '')):
                raise ValueError('最终工作簿存在无效查询日期')
            source_cell = worksheet.cell(row_index, 10)
            if not str(source_cell.value or '').strip():
                raise ValueError('最终工作簿存在空信息来源')
            if _is_web_url(source_cell.value) and not source_cell.hyperlink:
                raise ValueError('网页信息来源没有写成可点击链接')
    finally:
        workbook.close()


def write_workbook(workbook, output_path, expected_row_count):
    """原子保存并复核最终工作簿。"""
    return write_workbook_atomically(
        workbook,
        output_path,
        lambda path: verify_workbook(path, expected_row_count),
    )


def main():
    """解析命令行参数并生成最终高校信息工作簿。"""
    parser = argparse.ArgumentParser(description='生成高校最终信息工作簿')
    parser.add_argument('--input', required=True, help='公共层处理完成的JSON')
    parser.add_argument('--output', required=True, help='最终Excel输出路径')
    arguments = parser.parse_args()

    payload = load_processed_records(arguments.input)
    output_rows = build_output_rows(payload['items'])
    workbook = create_workbook(output_rows)
    output = write_workbook(workbook, arguments.output, len(output_rows))
    print(json.dumps({
        'output': str(output),
        'city': payload['city_context']['city_name'],
        'row_count': len(output_rows),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
