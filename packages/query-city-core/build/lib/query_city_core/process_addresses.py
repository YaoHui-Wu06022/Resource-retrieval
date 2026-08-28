#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按来源性质执行统一地址规范化、地图验证和地图兜底。"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .amap_client import RequestRateLimiter
from .city import read_city_catalog
from .env_utils import read_env_value
from .fallback_address import resolve_fallback_map_address
from .normalize_address import (
    normalize_address_payload,
    write_json_payload,
)
from .verify_address import verify_map_address


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def build_map_address_record(address_record):
    """为未调用地图的记录补齐固定地图字段。"""
    return {
        **address_record,
        'map_address': '',
        'map_status': '',
        'map_reason': '',
        'map_poi_type': '',
        'map_poi_typecode': '',
        'final_address': '',
    }


def resolve_address_record(
    address_record,
    city,
    api_key,
    city_prefixes,
    rate_limiter,
    verify_address=verify_map_address,
    resolve_fallback_address=resolve_fallback_map_address,
):
    """按来源性质和规范化状态处理一条地址记录。"""
    processed_record = build_map_address_record(address_record)
    source_nature = address_record['source_nature']
    normalization_status = address_record['normalization_status']

    if (
        source_nature == 'government_information'
        and normalization_status == 'complete'
    ):
        processed_record.update(
            map_status='skipped',
            map_reason='政府信息地址完整，按规则跳过地图服务',
            final_address=address_record['normalized_address'],
        )
        return processed_record, 0

    if source_nature == 'web_search' and normalization_status == 'complete':
        processed_record, map_request_count = verify_address(
            processed_record, city, api_key, rate_limiter
        )
        processed_record['final_address'] = address_record['normalized_address']
        return processed_record, map_request_count

    fallback_allowed = (
        source_nature == 'web_search' and normalization_status == 'empty'
    ) or (
        source_nature == 'government_information'
        and normalization_status in {'empty', 'partial'}
    )
    if fallback_allowed:
        processed_record, map_request_count = resolve_fallback_address(
            processed_record,
            city,
            api_key,
            city_prefixes,
            rate_limiter,
        )
        if processed_record['map_status'] == 'fallback':
            processed_record['final_address'] = processed_record['map_address']
        return processed_record, map_request_count

    processed_record.update(
        map_status='skipped',
        map_reason=(
            f'{source_nature} 的 {normalization_status} 地址不允许调用地图服务'
        ),
    )
    return processed_record, 0


def build_address_resolution_metrics(processed_records, map_request_count):
    """统计公共地址处理结果的状态和地图请求数量。"""
    return {
        'item_count': len(processed_records),
        'map_request_count': map_request_count,
        'source_counts': dict(sorted(Counter(
            address_record['source_nature']
            for address_record in processed_records
        ).items())),
        'normalization_status_counts': dict(sorted(Counter(
            address_record['normalization_status']
            for address_record in processed_records
        ).items())),
        'map_status_counts': dict(sorted(Counter(
            address_record['map_status']
            for address_record in processed_records
        ).items())),
        'final_address_count': sum(
            bool(address_record['final_address'])
            for address_record in processed_records
        ),
    }


def resolve_address_payload(
    input_payload,
    api_key,
    city_prefixes,
    verify_address=verify_map_address,
    resolve_fallback_address=resolve_fallback_map_address,
):
    """规范化并按原顺序处理一批公共地址记录。"""
    normalized_payload = normalize_address_payload(input_payload, city_prefixes)
    city = normalized_payload['city']
    rate_limiter = RequestRateLimiter()
    processed_records = []
    map_request_count = 0
    for address_record in normalized_payload['items']:
        processed_record, item_map_request_count = resolve_address_record(
            address_record,
            city,
            api_key,
            city_prefixes,
            rate_limiter,
            verify_address,
            resolve_fallback_address,
        )
        processed_records.append(processed_record)
        map_request_count += item_map_request_count
    return {
        'schema_version': '1.0',
        'stage': 'processed_address_records',
        'city': city,
        'items': processed_records,
        'metrics': build_address_resolution_metrics(processed_records, map_request_count),
    }


def main():
    """读取公共地址输入并写出完整处理结果。"""
    parser = argparse.ArgumentParser(description='执行统一地址公共处理链路')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        with Path(args.input).resolve().open(encoding='utf-8') as stream:
            input_payload = json.load(stream)
        processed_payload = resolve_address_payload(
            input_payload,
            read_env_value('AMAP_KEY'),
            read_city_catalog(),
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
