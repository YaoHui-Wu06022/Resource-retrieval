#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""医疗机构交付质量闸门：数量下界、类别覆盖与来源完整检查。"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from medical_scope import (
    MAJOR_INSTITUTION_CATEGORIES,
    classify_institution_category,
    collect_administrative_unit_payloads,
    is_abnormal_record,
    merge_city_records,
    partition_main_records,
)


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def load_government_manifest(unit_dir):
    """读取行政单位来源清单，不存在时返回空清单。"""
    manifest_path = Path(unit_dir) / 'government_source.json'
    if not manifest_path.is_file():
        return {}
    return json.loads(manifest_path.read_text(encoding='utf-8'))


def read_platform_reference(unit_dir, source_item):
    """从平台来源返回总数、类别计数与汇总记录文件路径。"""
    platform_result = source_item.get('platform_result') or {}
    total_count = int(platform_result.get('count') or 0)
    local_file = str(source_item.get('local_file') or '').strip()
    records_path = Path(unit_dir) / local_file
    category_counts = Counter()
    record_count = 0
    if records_path.is_file():
        records = json.loads(records_path.read_text(encoding='utf-8'))
        if isinstance(records, list):
            record_count = len(records)
            for record in records:
                category = classify_institution_category(
                    record.get('yytype')
                )
                if category:
                    category_counts[category] += 1
    return {
        'count': total_count,
        'record_count': record_count,
        'category_counts': dict(category_counts),
        'records_file': local_file,
        'file_exists': records_path.is_file(),
    }


def collect_no_official_categories(manifest):
    """返回清单中声明无官方全量来源的大类集合。"""
    covered_categories = set()
    for source_item in manifest.get('sources') or []:
        if str(source_item.get('status') or '') != 'no_official_source':
            continue
        for category_value in source_item.get('category_coverage') or []:
            category_text = str(category_value or '').strip()
            if category_text in MAJOR_INSTITUTION_CATEGORIES:
                covered_categories.add(category_text)
                continue
            category = classify_institution_category(category_text)
            if category:
                covered_categories.add(category)
            elif category_text:
                covered_categories.add(
                    category_text
                )
    return covered_categories


def build_district_quality(
    unit_name,
    unit_dir,
    output_count,
    output_categories,
    min_ratio,
    category_min,
):
    """检查一个行政单位的数量下界、类别覆盖与来源完整。"""
    manifest = load_government_manifest(unit_dir)
    sources = manifest.get('sources') or []
    ready_sources = [
        source_item
        for source_item in sources
        if str(source_item.get('status') or '') == 'ready'
    ]
    platform_sources = [
        source_item
        for source_item in sources
        if str(source_item.get('source_type') or '')
        == 'query_platform'
        and str(source_item.get('status') or '') == 'ready'
    ]
    no_official_categories = collect_no_official_categories(manifest)
    platform_count = 0
    platform_record_count = 0
    platform_category_counter = Counter()
    all_files_exist = True
    for platform_source in platform_sources:
        reference = read_platform_reference(unit_dir, platform_source)
        platform_count += reference['count']
        platform_record_count += reference['record_count']
        platform_category_counter.update(reference['category_counts'])
        all_files_exist = all_files_exist and reference['file_exists']
    platform_categories = dict(platform_category_counter)
    checks = {}
    reasons = []
    checks['has_ready_full_source'] = bool(ready_sources)
    if not ready_sources:
        reasons.append('没有任何 ready 全量来源')
    if platform_sources and not all_files_exist:
        reasons.append('平台汇总记录文件缺失')
    if (
        platform_sources
        and platform_count != platform_record_count
    ):
        reasons.append(
            '平台汇总文件记录数 '
            f'{platform_record_count} 与平台总数 {platform_count} 不一致'
        )
    ratio = (
        output_count / platform_count
        if platform_count > 0
        else None
    )
    checks['ratio'] = ratio
    if (
        platform_count > 0
        and ratio is not None
        and ratio < min_ratio
    ):
        reasons.append(
            f'交付行数 {output_count} 低于平台下界 '
            f'{platform_count * min_ratio:.0f}'
        )
    missing_categories = []
    for category, platform_category_count in (
        platform_categories.items()
    ):
        if (
            platform_category_count >= category_min
            and output_categories.get(category, 0) == 0
            and category not in no_official_categories
        ):
            missing_categories.append(category)
    checks['missing_categories'] = missing_categories
    if missing_categories:
        reasons.append(
            '平台存在但交付缺失的大类：' + '、'.join(missing_categories)
        )
    district_passed = not reasons
    return {
        'administrative_unit': unit_name,
        'platform_count': platform_count,
        'output_count': output_count,
        'ratio': round(ratio, 4) if ratio is not None else None,
        'platform_categories': platform_categories,
        'output_categories': dict(output_categories),
        'missing_categories': missing_categories,
        'checks': checks,
        'reasons': reasons,
        'passed': district_passed,
    }


def build_quality_report(
    input_dir,
    output_path,
    min_ratio=0.9,
    category_min=10,
):
    """汇总各区质量检查并写出 quality_report.json。"""
    city_name, unit_payloads = collect_administrative_unit_payloads(
        input_dir
    )
    subdivision_names = [
        str(item.get('name') or '').strip()
        for item in unit_payloads[0][2]['city_context'].get(
            'subdivisions'
        ) or []
    ]
    unit_dir_by_name = {
        unit_name: unit_dir
        for unit_name, unit_dir, _payload in unit_payloads
    }
    missing_units = [
        name for name in subdivision_names
        if name not in unit_dir_by_name
    ]
    main_records = [
        record
        for _unit_name, _unit_dir, payload in unit_payloads
        for record in payload['items']
        if not is_abnormal_record(record)
    ]
    merged_records = merge_city_records(
        main_records, subdivision_names
    )
    main_partitions = partition_main_records(
        merged_records, subdivision_names
    )
    district_reports = []
    overall_reasons = []
    if missing_units:
        overall_reasons.append(
            '缺少处理结果的行政单位：' + '、'.join(missing_units)
        )
    for unit_name in subdivision_names:
        unit_dir = unit_dir_by_name.get(unit_name)
        if unit_dir is None:
            district_reports.append({
                'administrative_unit': unit_name,
                'reasons': ['行政单位目录缺少 processed_address_records'],
                'passed': False,
            })
            continue
        unit_records = main_partitions.get(unit_name) or []
        output_categories = Counter()
        for record in unit_records:
            category = classify_institution_category(
                (record.get('attributes') or {}).get(
                    'institution_type'
                )
            )
            if category:
                output_categories[category] += 1
        district_report = build_district_quality(
            unit_name,
            unit_dir,
            len(unit_records),
            output_categories,
            min_ratio,
            category_min,
        )
        district_reports.append(district_report)
        if not district_report['passed']:
            overall_reasons.extend(
                f'{unit_name}：{reason}'
                for reason in district_report['reasons']
            )
    report = {
        'stage': 'medical_quality_report',
        'city': city_name,
        'generated_at': datetime.now(timezone.utc).isoformat(
            timespec='seconds'
        ),
        'config': {
            'min_ratio': min_ratio,
            'category_min': category_min,
            'major_categories': list(MAJOR_INSTITUTION_CATEGORIES),
        },
        'units': district_reports,
        'reasons': overall_reasons,
        'passed': not overall_reasons,
    }
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1),
        encoding='utf-8',
    )
    return report


def main():
    """执行质量闸门并输出 quality_report.json。"""
    parser = argparse.ArgumentParser(
        description='医疗机构交付质量闸门'
    )
    parser.add_argument('--input-dir', required=True)
    parser.add_argument(
        '--output',
        default='',
        help='质量报告输出路径，缺省为输入目录下 quality_report.json',
    )
    parser.add_argument(
        '--min-ratio',
        type=float,
        default=0.9,
        help='平台数量下界比例，默认 0.9',
    )
    parser.add_argument(
        '--category-min',
        type=int,
        default=10,
        help='平台某大类达到该数量而交付为零时阻断，默认 10',
    )
    arguments = parser.parse_args()
    try:
        output_path = (
            arguments.output
            or str(Path(arguments.input_dir).resolve() / 'quality_report.json')
        )
        report = build_quality_report(
            arguments.input_dir,
            output_path,
            arguments.min_ratio,
            arguments.category_min,
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        'output': output_path,
        'passed': report['passed'],
        'unit_count': len(report['units']),
        'reasons': report['reasons'],
    }, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
