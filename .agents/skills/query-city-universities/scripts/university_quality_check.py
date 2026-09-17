#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校交付质量闸门：地址残留与同校同路重复行检查。"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from query_city_core.quality_gate import (
    add_quality_gate_arguments,
    build_quality_report as build_report,
    run_quality_gate,
    write_quality_report,
)

from build_excel import (
    build_abnormal_rows,
    build_output_rows,
    load_processed_records,
)
from university_campus_rules import (
    has_contact_label_noise,
    has_house_number,
    road_name,
)


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


PROCESSED_FILE_NAME = 'processed_address_records.json'
STAGE = 'university_quality_report'


def find_output_row_issues(output_rows):
    """找出高校信息行中应拦截的地址残留问题。"""
    issues = []
    numbered_roads_by_school = defaultdict(set)
    for _, address_record in output_rows:
        attributes = address_record.get('attributes') or {}
        school_identifier = str(
            attributes.get('school_identifier') or ''
        ).strip()
        address = str(address_record.get('final_address') or '').strip()
        if school_identifier and has_house_number(address):
            road = road_name(address)
            if len(road) >= 2:
                numbered_roads_by_school[school_identifier].add(road)
    for domain_values, address_record in output_rows:
        place_name = str(domain_values[0] or '').strip()
        attributes = address_record.get('attributes') or {}
        school_identifier = str(
            attributes.get('school_identifier') or ''
        ).strip()
        address = str(address_record.get('final_address') or '').strip()
        if not address:
            continue
        if has_contact_label_noise(address):
            issues.append(
                f'{place_name}：地址残留联系词「{address}」'
            )
            continue
        road = road_name(address)
        if (
            school_identifier
            and not has_house_number(address)
            and road
            and any(
                road == numbered
                or road.endswith(numbered)
                or numbered.endswith(road)
                for numbered in numbered_roads_by_school.get(
                    school_identifier, ()
                )
            )
        ):
            issues.append(
                f'{place_name}：同路已有带门牌地址却保留无门牌地址'
                f'「{address}」'
            )
    return issues


def build_quality_report(input_dir, output_path, arguments=None):
    """读取运行目录的处理结果，执行发布门禁并写出 quality_report.json。"""
    run_dir = Path(input_dir).resolve()
    processed_path = run_dir / PROCESSED_FILE_NAME
    if not processed_path.is_file():
        raise FileNotFoundError(f'缺少 {PROCESSED_FILE_NAME}')
    payload = load_processed_records(processed_path)
    city_name = payload['city_context']['city_name']
    output_rows = build_output_rows(payload['items'], city_name)
    abnormal_rows = build_abnormal_rows(payload['items'])
    issues = find_output_row_issues(output_rows)
    report = build_report(
        STAGE,
        city_name,
        reasons=issues,
        checks={
            'main_row_count': len(output_rows),
            'abnormal_row_count': len(abnormal_rows),
            'address_issue_count': len(issues),
        },
    )
    write_quality_report(report, output_path)
    return report


def main():
    """执行质量闸门并输出 quality_report.json。"""
    parser = add_quality_gate_arguments(
        argparse.ArgumentParser(description='高校交付质量闸门')
    )
    return run_quality_gate(parser, build_quality_report)


if __name__ == '__main__':
    raise SystemExit(main())
