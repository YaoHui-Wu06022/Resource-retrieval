#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行地址规范化与统一地图解析。"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .amap_client import RequestRateLimiter
from .city import validate_city_context
from ..env_utils import read_env_value
from ..io_utils import read_json_payload, write_json_payload
from .common import MISSING_ADMIN_REASON
from .normalize import (
    normalize_address_record,
)
from .verify import resolve_map_address


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def resolve_address_record(
    address_record,
    city_context,
    api_key,
    rate_limiter,
    resolve_map=resolve_map_address,
):
    """调用统一地图解析入口处理一条规范地址记录。"""
    before = getattr(rate_limiter, 'total_requests', 0)
    processed_record, request_count = resolve_map(
        address_record, city_context, api_key, rate_limiter
    )
    processed_record['actual_http_attempt_count'] = (
        getattr(rate_limiter, 'total_requests', 0) - before
    )
    return processed_record, request_count


def build_address_resolution_metrics(processed_records, map_request_count, city_name=''):
    """统计公共地址处理结果的状态和地图请求数量。"""
    city_counts = Counter(
        address_record.get('resolved_city') or ''
        for address_record in processed_records
    )
    missing_admin_geocode_count = sum(
        address_record.get('normalization_reason') == MISSING_ADMIN_REASON
        and address_record.get('map_match_status') != 'skipped'
        for address_record in processed_records
    )
    target_city = str(city_name or '')
    out_of_city_address_count = sum(
        bool(address_record.get('resolved_city'))
        and target_city
        and address_record.get('resolved_city') != target_city
        for address_record in processed_records
    )
    return {
        'item_count': len(processed_records),
        'map_request_count': map_request_count,
        'source_counts': dict(sorted(Counter(
            address_record['source_nature']
            for address_record in processed_records
        ).items())),
        'address_mode_counts': dict(sorted(Counter(
            address_record['address_mode']
            for address_record in processed_records
        ).items())),
        'normalization_status_counts': dict(sorted(Counter(
            address_record['normalization_status']
            for address_record in processed_records
        ).items())),
        'map_match_status_counts': dict(sorted(Counter(
            address_record['map_match_status']
            for address_record in processed_records
        ).items())),
        'final_address_count': sum(
            bool(address_record['final_address'])
            for address_record in processed_records
        ),
        'resolved_city_counts': dict(sorted(city_counts.items())),
        'missing_admin_geocode_count': missing_admin_geocode_count,
        'out_of_city_address_count': out_of_city_address_count,
        'rate_limit_window_seconds': 1.0,
        'rate_limit_max_requests': 2,
        'actual_http_attempt_count': sum(
            int(address_record.get('actual_http_attempt_count') or 0)
            for address_record in processed_records
        ),
        'not_found_empty_address_count': sum(
            address_record.get('map_match_status') == 'not_found'
            and not address_record.get('original_address')
            for address_record in processed_records
        ),
    }


def resolve_address_payload(
    input_payload,
    api_key,
    resolve_map=resolve_map_address,
):
    """逐条规范化并立即地图解析，避免地图请求堆积。"""
    if (
        not isinstance(input_payload, dict)
        or input_payload.get('stage') != 'address_records'
    ):
        raise ValueError('输入必须是 address_records JSON')
    city_context = validate_city_context(input_payload.get('city_context'))
    address_records = input_payload.get('items')
    if not isinstance(address_records, list):
        raise ValueError('items 必须是数组')
    rate_limiter = RequestRateLimiter()
    processed_records = []
    map_request_count = 0
    for address_record in address_records:
        normalized_record = normalize_address_record(
            address_record, city_context
        )
        processed_record, item_map_request_count = resolve_address_record(
            normalized_record,
            city_context,
            api_key,
            rate_limiter,
            resolve_map,
        )
        processed_records.append(processed_record)
        map_request_count += item_map_request_count
    return {
        'stage': 'processed_address_records',
        'city_context': city_context,
        'items': processed_records,
        'metrics': build_address_resolution_metrics(
            processed_records, map_request_count, city_context['city_name']
        ),
    }


def main():
    """读取公共地址输入并写出完整处理结果。"""
    parser = argparse.ArgumentParser(description='执行统一地址公共处理链路')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        input_payload = read_json_payload(args.input)
        processed_payload = resolve_address_payload(
            input_payload,
            read_env_value('AMAP_KEY'),
        )
        write_json_payload(args.output, processed_payload)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        'output': str(Path(args.output).resolve()),
        **processed_payload['metrics'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
