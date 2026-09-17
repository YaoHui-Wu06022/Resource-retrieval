#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基础教育交付质量闸门：来源清单、提取计划与记录文件检查。"""

import argparse
import sys
from pathlib import Path

from query_city_core.io_utils import read_json_payload
from query_city_core.quality_gate import (
    add_quality_gate_arguments,
    build_quality_report as build_report,
    run_quality_gate,
    write_quality_report,
)

from build_excel import (
    collect_administrative_unit_payloads,
    load_processed_address_records,
)
from school_government_flow import validate_source_manifest


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


PLAN_STAGE = 'basic_education_extraction_plan'
ALLOWED_REVIEW_STATUSES = {'ready', 'skipped'}
STAGE = 'basic_education_quality_report'


def check_administrative_unit(unit_name, unit_dir):
    """检查一个行政单位的来源清单、提取计划与记录文件。"""
    reasons = []
    manifest_path = unit_dir / 'government_source.json'
    if not manifest_path.is_file():
        return {
            'administrative_unit': unit_name,
            'main_row_count': 0,
            'abnormal_row_count': 0,
            'reasons': ['缺少 government_source.json'],
            'passed': False,
        }
    try:
        validate_source_manifest(read_json_payload(manifest_path))
    except (TypeError, ValueError) as exc:
        reasons.append(f'来源清单不合规：{exc}')

    plan_path = unit_dir / 'extraction_plan.json'
    if not plan_path.is_file():
        reasons.append('缺少 extraction_plan.json')
    else:
        plan = read_json_payload(plan_path)
        if plan.get('stage') != PLAN_STAGE:
            reasons.append(f'extraction_plan.json 阶段必须是 {PLAN_STAGE}')
        for index, source_plan in enumerate(plan.get('items') or [], start=1):
            if not isinstance(source_plan, dict):
                reasons.append(f'提取计划第 {index} 项不是对象')
                continue
            review_status = str(source_plan.get('review_status') or '')
            if review_status not in ALLOWED_REVIEW_STATUSES:
                reasons.append(
                    f'提取计划第 {index} 项未完成复核'
                    f'（review_status={review_status or "空"}）'
                )
                continue
            if review_status == 'skipped':
                continue
            approved_rules = [
                rule
                for rule in source_plan.get('extraction_rules') or []
                if isinstance(rule, dict) and rule.get('approved') is True
            ]
            if not approved_rules:
                reasons.append(
                    f'提取计划第 {index} 项没有已批准的提取规则'
                )

    address_path = unit_dir / 'address_records.json'
    if not address_path.is_file():
        reasons.append('缺少 address_records.json')
    elif read_json_payload(address_path).get('stage') != 'address_records':
        reasons.append(
            'address_records.json 阶段必须是 address_records'
            '（提取出错时会写成 address_records_incomplete）'
        )

    main_row_count = 0
    abnormal_row_count = 0
    processed_path = unit_dir / 'processed_address_records.json'
    if not processed_path.is_file():
        reasons.append('缺少 processed_address_records.json')
    else:
        try:
            processed = load_processed_address_records(processed_path)
        except ValueError as exc:
            reasons.append(f'地址处理结果不合规：{exc}')
        else:
            items = [
                item for item in processed['items'] if isinstance(item, dict)
            ]
            main_row_count = len([
                item
                for item in items
                if str(item.get('final_address') or '').strip()
            ])
            abnormal_row_count = len(items) - main_row_count

    return {
        'administrative_unit': unit_name,
        'main_row_count': main_row_count,
        'abnormal_row_count': abnormal_row_count,
        'reasons': reasons,
        'passed': not reasons,
    }


def build_quality_report(input_dir, output_path, arguments=None):
    """汇总各行政单位检查并写出 quality_report.json。"""
    city_name, unit_payloads = collect_administrative_unit_payloads(input_dir)
    subdivisions = [
        str(item.get('name') or '').strip()
        for item in unit_payloads[0][2]['city_context'].get('subdivisions')
        or []
    ]
    unit_dir_by_name = {
        unit_name: unit_dir for unit_name, unit_dir, _payload in unit_payloads
    }
    missing_units = [
        name for name in subdivisions if name not in unit_dir_by_name
    ]
    unit_reports = []
    overall_reasons = []
    if missing_units:
        overall_reasons.append(
            '缺少处理结果的行政单位：' + '、'.join(missing_units)
        )
    for unit_name in subdivisions:
        unit_dir = unit_dir_by_name.get(unit_name)
        if unit_dir is None:
            unit_reports.append({
                'administrative_unit': unit_name,
                'main_row_count': 0,
                'abnormal_row_count': 0,
                'reasons': ['缺少 processed_address_records.json'],
                'passed': False,
            })
            continue
        unit_report = check_administrative_unit(unit_name, unit_dir)
        unit_reports.append(unit_report)
        if not unit_report['passed']:
            overall_reasons.extend(
                f'{unit_name}：{reason}'
                for reason in unit_report['reasons']
            )
    report = build_report(
        STAGE,
        city_name,
        units=unit_reports,
        reasons=overall_reasons,
    )
    write_quality_report(report, output_path)
    return report


def main():
    """执行质量闸门并输出 quality_report.json。"""
    parser = add_quality_gate_arguments(
        argparse.ArgumentParser(description='基础教育交付质量闸门')
    )
    return run_quality_gate(parser, build_quality_report)


if __name__ == '__main__':
    raise SystemExit(main())
