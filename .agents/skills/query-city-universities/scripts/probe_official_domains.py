#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校域名现用性探测命令层：读取高校批次并适配公共探测能力。"""

import argparse
import json
import sys
from pathlib import Path

from query_city_core.io_utils import read_json_payload, write_json_payload
from query_city_core.web.probe_domains import probe_domain_items

from merge_domain_batches import read_domain_batches


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


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


def main():
    """解析参数并输出高校域名现用性探测报告。"""
    parser = argparse.ArgumentParser(
        description='探测高校域名清单主页的可达性与跳转终域'
    )
    parser.add_argument('--run-dir', required=True)
    args = parser.parse_args()
    try:
        result = probe_domain_batches(args.run_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
