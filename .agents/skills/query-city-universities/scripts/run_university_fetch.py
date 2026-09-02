#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按域名清单并发抓取高校官网并校验逐校结果覆盖。"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fetch_official_universities import has_usable_address_candidate
from query_city_core.io_utils import read_json_payload, write_json_payload


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


DEFAULT_WORKERS = 3
DEFAULT_MAX_PAGES = 3
SKIP_REASONS = {'merged', 'ceased_independent_operation'}


def validate_manifest(payload, city_universities_payload):
    """校验域名清单与城市高校名录一一对应，并拆成可抓取项与无官网项。"""
    if not isinstance(payload, dict) or payload.get('stage') != 'official_domain_manifest':
        raise ValueError('输入必须是 official_domain_manifest JSON')
    items = payload.get('items')
    if not isinstance(items, list):
        raise ValueError('official_domain_manifest.items 必须是数组')

    city_schools = city_universities_payload.get('schools')
    if not isinstance(city_schools, list):
        raise ValueError('city_universities.json schools 必须是数组')
    city_index = {}
    for school in city_schools:
        identifier = str(school.get('school_identifier') or '').strip()
        city_index[identifier] = school
    city_identifiers = set(city_index)

    manifest_identifiers = set()
    fetch_items = []
    no_site_items = []
    skipped_items = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('清单每一项必须是对象')
        identifier = str(item.get('school_identifier') or '').strip()
        if not identifier or identifier not in city_index:
            raise ValueError(f'清单出现名录外或缺少标识码的学校：{identifier or item}')
        if identifier in manifest_identifiers:
            raise ValueError(f'学校标识码重复：{identifier}')
        manifest_identifiers.add(identifier)
        if item.get('no_official_site'):
            evidence_url = str(item.get('evidence_url') or '').strip()
            reason = str(item.get('reason') or '').strip()
            if not evidence_url or not reason:
                raise ValueError(f'{identifier} 无官网项必须包含 evidence_url 和 reason')
            no_site_items.append({
                'school_identifier': identifier,
                'evidence_url': evidence_url,
                'reason': reason,
            })
            continue
        if str(item.get('processing_status') or '') == 'skipped':
            skip_reason = str(item.get('skip_reason') or '').strip()
            skip_reference = str(item.get('skip_reference') or '').strip()
            if skip_reason not in SKIP_REASONS or not skip_reference:
                raise ValueError(
                    f'{identifier} 跳过项必须包含合法 skip_reason 和 skip_reference'
                )
            skipped_items.append({
                'school_identifier': identifier,
                'skip_reason': skip_reason,
                'skip_reference': skip_reference,
            })
            continue
        home_url = str(item.get('home_url') or '').strip()
        official_domains = item.get('official_domains')
        if not home_url or not isinstance(official_domains, list) or not official_domains:
            raise ValueError(
                f'{identifier} 必须包含 home_url 和非空 official_domains'
            )
        fetch_items.append({
            'school_identifier': identifier,
            'home_url': home_url,
            'official_domains': [
                str(domain).strip() for domain in official_domains if str(domain).strip()
            ],
            'candidate_urls': [
                str(url).strip()
                for url in (item.get('candidate_urls') or [])
                if str(url).strip()
            ],
        })

    missing_identifiers = sorted(city_identifiers - manifest_identifiers)
    if missing_identifiers:
        names = [city_index[identifier]['school_name'] for identifier in missing_identifiers]
        raise ValueError('域名清单缺少学校：' + '、'.join(names))
    return fetch_items, no_site_items, skipped_items, city_index


def build_slices(items, workers):
    """把学校列表切成 workers 份互不重叠的切片。"""
    if not isinstance(workers, int) or workers < 1:
        raise ValueError('workers 必须是大于 0 的整数')
    if not items:
        return []
    slice_size = max(1, -(-len(items) // workers))
    return [
        items[index:index + slice_size]
        for index in range(0, len(items), slice_size)
    ]


def write_static_results(no_site_items, skipped_items, output_dir):
    """直接写出无官网或已合并/停办学校的合法单校结果。"""
    school_results_dir = Path(output_dir) / 'school_results'
    for item in no_site_items:
        write_json_payload(
            school_results_dir / f"{item['school_identifier']}.json",
            {
                'school_identifier': item['school_identifier'],
                'processing_status': 'no_official_site',
                'evidence_url': item['evidence_url'],
                'reason': item['reason'],
            },
        )
    for item in skipped_items:
        write_json_payload(
            school_results_dir / f"{item['school_identifier']}.json",
            {
                'school_identifier': item['school_identifier'],
                'processing_status': 'skipped',
                'skip_reason': item['skip_reason'],
                'skip_reference': item['skip_reference'],
            },
        )


def build_fetch_command(slice_path, output_dir, max_pages):
    """构造独立抓取进程的命令与环境。"""
    script = Path(__file__).resolve().parent / 'fetch_official_universities.py'
    environment = dict(os.environ)
    environment['PYTHONIOENCODING'] = 'utf-8'
    return [
        sys.executable,
        str(script),
        '--school-batch',
        str(slice_path),
        '--output-dir',
        str(output_dir),
        '--max-pages',
        str(max_pages),
    ], environment


def parse_process_summaries(returncode, stdout):
    """解析抓取进程返回的批次摘要。"""
    summaries = []
    if returncode == 0:
        try:
            payload = json.loads(stdout)
            summaries = payload.get('items') or []
        except json.JSONDecodeError:
            summaries = []
    return summaries


def build_fetch_report(run_dir, city_index):
    """按城市名录顺序汇总逐校抓取状态。"""
    school_results_dir = Path(run_dir) / 'school_results'
    report_items = []
    for identifier, school in city_index.items():
        result_path = school_results_dir / f'{identifier}.json'
        if not result_path.is_file():
            report_items.append({
                'school_identifier': identifier,
                'school_name': school['school_name'],
                'processing_status': 'missing',
                'page_count': 0,
                'has_address_candidate': False,
                'error': '未生成合法单校结果',
            })
            continue
        result = read_json_payload(result_path)
        status = str(result.get('processing_status') or '').strip()
        pages = result.get('pages') or []
        report_items.append({
            'school_identifier': identifier,
            'school_name': school['school_name'],
            'processing_status': status,
            'page_count': len(pages),
            'has_address_candidate': any(
                has_usable_address_candidate(page) for page in pages
            ),
            'error': '',
        })
    return report_items


def run_university_fetch(
    manifest_path,
    run_dir,
    workers=DEFAULT_WORKERS,
    max_pages=DEFAULT_MAX_PAGES,
    only_failures=False,
):
    """校验域名清单、并发抓取并写出 fetch_report 与复检清单。"""
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise ValueError(f'运行目录不存在：{run_dir}')
    city_universities_payload = read_json_payload(run_dir / 'city_universities.json')
    if city_universities_payload.get('stage') != 'city_universities':
        raise ValueError('运行目录中 city_universities.json 阶段不正确')
    manifest_payload = read_json_payload(manifest_path)
    fetch_items, no_site_items, skipped_items, city_index = validate_manifest(
        manifest_payload, city_universities_payload
    )

    retry_identifiers = set()
    if only_failures:
        retry_payload = read_json_payload(run_dir / 'retry_failures.json')
        retry_identifiers = {
            str(item.get('school_identifier') or '')
            for item in (retry_payload.get('items') or [])
        }
        fetch_items = [
            item for item in fetch_items
            if item['school_identifier'] in retry_identifiers
        ]
        no_site_items = [
            item for item in no_site_items
            if item['school_identifier'] in retry_identifiers
        ]
        skipped_items = [
            item for item in skipped_items
            if item['school_identifier'] in retry_identifiers
        ]

    (run_dir / 'school_results').mkdir(parents=True, exist_ok=True)
    write_static_results(no_site_items, skipped_items, run_dir)

    slice_failures = []
    if fetch_items:
        with tempfile.TemporaryDirectory(
            prefix='fetch_slices_', dir=run_dir
        ) as temporary_dir:
            launched = []
            for index, slice_items in enumerate(build_slices(fetch_items, workers)):
                slice_path = Path(temporary_dir) / f'slice_{index}.json'
                write_json_payload(
                    slice_path,
                    {'stage': 'university_fetch_slice', 'items': slice_items},
                )
                command, environment = build_fetch_command(
                    slice_path, run_dir, max_pages
                )
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    env=environment,
                )
                launched.append((slice_items, process))
            for slice_items, process in launched:
                stdout, stderr = process.communicate()
                returncode = process.returncode
                summaries = parse_process_summaries(returncode, stdout)
                for summary in summaries:
                    if str(summary.get('processing_status') or '') == 'completed':
                        continue
                    slice_failures.append({
                        'school_identifier': str(
                            summary.get('school_identifier') or ''
                        ),
                        'failure_stage': 'fetch',
                        'failure_reason': (
                            str(summary.get('error') or '')
                            or '抓取未生成合法单校结果'
                        ),
                    })
                if returncode == 0:
                    continue
                message = (stderr or stdout or '').strip()
                summary_by_identifier = {
                    str(summary.get('school_identifier') or '')
                    for summary in summaries
                }
                failed_slice_items = [
                    item for item in slice_items
                    if item['school_identifier'] not in summary_by_identifier
                ]
                for item in failed_slice_items:
                    slice_failures.append({
                        'school_identifier': item['school_identifier'],
                        'failure_stage': 'fetch',
                        'failure_reason': (
                            message[:500] or '抓取进程非零退出'
                        ),
                    })

    report_items = build_fetch_report(run_dir, city_index)
    check_items = report_items
    if only_failures:
        check_items = [
            item for item in report_items
            if item['school_identifier'] in retry_identifiers
        ]
    retry_items = []
    for item in check_items:
        if item['processing_status'] not in {
            'completed',
            'no_official_site',
            'skipped',
        }:
            matched_failure = next(
                (
                    failure
                    for failure in slice_failures
                    if failure.get('school_identifier') == item['school_identifier']
                ),
                None,
            )
            retry_items.append({
                'school_identifier': item['school_identifier'],
                'school_name': item['school_name'],
                'failure_stage': 'fetch',
                'failure_reason': (
                    matched_failure.get('failure_reason')
                    if matched_failure
                    else item.get('error') or '未生成合法单校结果'
                ),
            })

    write_json_payload(
        run_dir / 'fetch_report.json',
        {
            'stage': 'university_fetch_report',
            'run_dir': str(run_dir),
            'items': report_items,
        },
    )
    retry_payload = {
        'stage': 'retry_failures',
        'items': retry_items,
    }
    write_json_payload(run_dir / 'retry_failures.json', retry_payload)
    return {
        'fetch_report': str(run_dir / 'fetch_report.json'),
        'retry_failures': str(run_dir / 'retry_failures.json'),
        'school_count': len(report_items),
        'completed_count': sum(
            item['processing_status'] == 'completed' for item in report_items
        ),
        'no_official_site_count': sum(
            item['processing_status'] == 'no_official_site' for item in report_items
        ),
        'missing_count': len(retry_items),
    }


def main():
    """解析参数并运行并发官网抓取。"""
    parser = argparse.ArgumentParser(
        description='按域名清单并发抓取高校官网并校验覆盖'
    )
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--workers', type=int, default=DEFAULT_WORKERS)
    parser.add_argument('--max-pages', type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument(
        '--only-failures',
        action='store_true',
        help='只复检 retry_failures.json 中的学校（域名清单仍需完整覆盖名录）',
    )
    args = parser.parse_args()
    try:
        result = run_university_fetch(
            args.manifest,
            args.run_dir,
            workers=args.workers,
            max_pages=args.max_pages,
            only_failures=args.only_failures,
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
