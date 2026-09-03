#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校域名阶段命令：探测主页现用性并汇总批次输出官方域名清单。"""

import argparse
import json
import re
import sys
from pathlib import Path

from query_city_core.io_utils import read_json_payload, write_json_payload
from query_city_core.web.probe_domains import probe_domain_items


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


SKIP_REASONS = {'merged', 'ceased_independent_operation'}
BATCH_FILE_PATTERN = re.compile(r'^domain_batch_\d+\.json$')
HTTP_URL_PATTERN = re.compile(r'^https?://\S+$')


def read_domain_batches(run_dir):
    """读取 domain_batches 目录下的全部批次文件。"""
    batch_dir = Path(run_dir) / 'domain_batches'
    if not batch_dir.is_dir():
        raise ValueError(f'缺少域名批次目录：{batch_dir}')
    batches = []
    for batch_path in sorted(batch_dir.glob('domain_batch_*.json')):
        batches.append(read_json_payload(batch_path))
    if not batches:
        raise ValueError(f'域名批次目录为空：{batch_dir}')
    return batches


def normalize_school_batch_item(item):
    """校验并规整单个域名确认项，失败原因不为空时返回 failure。"""
    if not isinstance(item, dict):
        raise ValueError('批次每一项必须是对象')
    identifier = str(item.get('school_identifier') or '').strip()
    if not identifier:
        raise ValueError('批次项缺少 school_identifier')
    failure_reason = str(item.get('failure_reason') or '').strip()
    if failure_reason:
        return None, identifier, {
            'school_identifier': identifier,
            'failure_reason': failure_reason,
        }
    if item.get('no_official_site'):
        evidence_url = str(item.get('evidence_url') or '').strip()
        reason = str(item.get('reason') or '').strip()
        if not HTTP_URL_PATTERN.fullmatch(evidence_url) or not reason:
            raise ValueError(f'{identifier} 无官网项必须包含合法 evidence_url 和 reason')
        return 'no_official_site', identifier, {
            'school_identifier': identifier,
            'no_official_site': True,
            'evidence_url': evidence_url,
            'reason': reason,
        }
    if str(item.get('processing_status') or '') == 'skipped':
        skip_reason = str(item.get('skip_reason') or '').strip()
        skip_reference = str(item.get('skip_reference') or '').strip()
        if skip_reason not in SKIP_REASONS or not HTTP_URL_PATTERN.fullmatch(
            skip_reference
        ):
            raise ValueError(
                f'{identifier} 跳过项必须包含合法 skip_reason 和 skip_reference'
            )
        return 'skipped', identifier, {
            'school_identifier': identifier,
            'processing_status': 'skipped',
            'skip_reason': skip_reason,
            'skip_reference': skip_reference,
        }
    home_url = str(item.get('home_url') or '').strip()
    official_domains = [
        str(domain).strip()
        for domain in (item.get('official_domains') or [])
        if str(domain).strip()
    ]
    if not HTTP_URL_PATTERN.fullmatch(home_url) or not official_domains:
        raise ValueError(
            f'{identifier} 普通项必须包含合法 home_url 和非空 official_domains'
        )
    result = {
        'school_identifier': identifier,
        'home_url': home_url,
        'official_domains': official_domains,
    }
    candidate_urls = [
        str(url).strip()
        for url in (item.get('candidate_urls') or [])
        if str(url).strip()
    ]
    if candidate_urls:
        result['candidate_urls'] = candidate_urls
    return 'fetch', identifier, result


def probe_domain_batches(run_dir, fetch=None):
    """把高校域名批次映射为通用记录并输出探测报告。"""
    run_dir = Path(run_dir).resolve()
    city_payload = read_json_payload(run_dir / 'city_universities.json')
    if city_payload.get('stage') != 'city_universities':
        raise ValueError('运行目录中 city_universities.json 阶段不正确')
    city_index = {}
    for school in city_payload.get('schools') or []:
        identifier = str(school.get('school_identifier') or '').strip()
        if identifier:
            city_index[identifier] = school
    domain_items = []
    for batch_payload in read_domain_batches(run_dir):
        if batch_payload.get('stage') != 'domain_batch':
            raise ValueError('domain_batches 文件 stage 必须是 domain_batch')
        for entry in batch_payload.get('items') or []:
            identifier = str(entry.get('school_identifier') or '').strip()
            if not identifier or identifier not in city_index:
                raise ValueError(f'批次出现名录外学校：{identifier}')
            if (
                entry.get('no_official_site')
                or str(entry.get('processing_status') or '') == 'skipped'
                or str(entry.get('failure_reason') or '').strip()
                or not str(entry.get('home_url') or '').strip()
            ):
                continue
            domain_items.append({
                'place_id': identifier,
                'place_name': str(
                    city_index[identifier].get('school_name') or ''
                ),
                'home_url': str(entry.get('home_url') or '').strip(),
                'official_domains': entry.get('official_domains') or [],
            })
    items = probe_domain_items(domain_items, fetch=fetch)
    output_path = run_dir / 'domain_probe_report.json'
    write_json_payload(output_path, {
        'stage': 'domain_probe_report',
        'run_dir': str(run_dir),
        'items': items,
    })
    return {
        'output': str(output_path),
        'probed_count': len(items),
        'issue_count': sum(1 for item in items if item.get('suggestion')),
    }


def merge_domain_batches(run_dir):
    """汇总域名批次并按城市名录顺序输出清单；有 failure 时拒绝。"""
    run_dir = Path(run_dir).resolve()
    city_payload = read_json_payload(run_dir / 'city_universities.json')
    if city_payload.get('stage') != 'city_universities':
        raise ValueError('运行目录中 city_universities.json 阶段不正确')
    schools = city_payload.get('schools')
    if not isinstance(schools, list):
        raise ValueError('city_universities.json schools 必须是数组')

    city_index = {}
    for school in schools:
        identifier = str(school.get('school_identifier') or '').strip()
        if not identifier or identifier in city_index:
            raise ValueError('城市高校标识码缺失或重复')
        city_index[identifier] = school

    manifest_by_identifier = {}
    failures = []
    for batch_payload in read_domain_batches(run_dir):
        if batch_payload.get('stage') != 'domain_batch':
            raise ValueError('domain_batches 文件 stage 必须是 domain_batch')
        batch_items = batch_payload.get('items')
        if not isinstance(batch_items, list):
            raise ValueError('domain_batch items 必须是数组')
        for item in batch_items:
            status, identifier, normalized = normalize_school_batch_item(item)
            if identifier not in city_index:
                raise ValueError(f'批次出现名录外学校：{identifier}')
            if identifier in manifest_by_identifier:
                raise ValueError(f'学校标识码重复：{identifier}')
            manifest_by_identifier[identifier] = normalized
            if status is None:
                failures.append(normalized)

    missing_identifiers = set(city_index) - set(manifest_by_identifier)
    if missing_identifiers:
        missing_names = [
            city_index[identifier]['school_name']
            for identifier in sorted(missing_identifiers)
        ]
        raise ValueError('域名批次缺少学校：' + '、'.join(missing_names))
    if failures:
        failure_names = [
            city_index[item['school_identifier']]['school_name']
            for item in failures
        ]
        raise ValueError(
            '存在待复检学校，拒绝输出域名清单：' + '、'.join(failure_names)
        )

    manifest_items = [
        manifest_by_identifier[str(school['school_identifier'])]
        for school in schools
    ]
    output_path = run_dir / 'official_domain_manifest.json'
    write_json_payload(output_path, {
        'stage': 'official_domain_manifest',
        'items': manifest_items,
    })
    return {
        'output': str(output_path),
        'school_count': len(manifest_items),
    }


def main():
    """解析子命令并执行域名探测或批次汇总。"""
    parser = argparse.ArgumentParser(
        description='高校域名阶段：探测主页现用性并汇总官方域名清单'
    )
    subparsers = parser.add_subparsers(dest='command', required=True)
    probe_parser = subparsers.add_parser(
        'probe',
        description='探测高校域名清单主页的可达性与跳转终域',
    )
    probe_parser.add_argument('--run-dir', required=True)
    merge_parser = subparsers.add_parser(
        'merge',
        description='汇总并行域名确认批次并输出官方域名清单',
    )
    merge_parser.add_argument('--run-dir', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'probe':
            result = probe_domain_batches(args.run_dir)
        else:
            result = merge_domain_batches(args.run_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
