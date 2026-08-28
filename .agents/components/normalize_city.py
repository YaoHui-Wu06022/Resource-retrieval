#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用固定城市资产把用户输入转换为标准城市名称。"""

import argparse
import json
import sys
from pathlib import Path

from amap_client import RequestRateLimiter, fetch_amap_subdivisions
from env_utils import read_env_value


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


DEFAULT_ASSET_PATH = (
    Path(__file__).resolve().parents[1] / 'assets' / 'china_city_prefixes.json'
)


def read_city_prefix_asset(asset_path=DEFAULT_ASSET_PATH):
    """读取并校验城市前缀固定资产。"""
    path = Path(asset_path).resolve()
    with path.open(encoding='utf-8') as stream:
        payload = json.load(stream)
    no_prefix_cities = payload.get('no_prefix_cities')
    province_cities = payload.get('province_cities')
    if not isinstance(no_prefix_cities, list) or not isinstance(province_cities, dict):
        raise ValueError('城市前缀资产结构无效')

    city_prefixes = {}
    for city in no_prefix_cities:
        normalized_city = str(city or '').strip()
        if not normalized_city:
            raise ValueError('无需前缀城市包含空值')
        city_prefixes[normalized_city] = ''
    for province, cities in province_cities.items():
        normalized_province = str(province or '').strip()
        if not normalized_province or not isinstance(cities, list):
            raise ValueError('省级行政区或城市列表无效')
        for city in cities:
            normalized_city = str(city or '').strip()
            if not normalized_city:
                raise ValueError(f'{normalized_province}的城市列表包含空值')
            if normalized_city in city_prefixes:
                raise ValueError(f'城市在固定资产中重复：{normalized_city}')
            city_prefixes[normalized_city] = normalized_province
    return city_prefixes


def normalize_city_name(raw_city, city_prefixes):
    """精确匹配标准城市名或仅补充一个市字后匹配。"""
    city = str(raw_city or '').strip()
    if not city:
        raise ValueError('城市名称不能为空')
    if city in city_prefixes:
        return city
    candidate = f'{city}市'
    if not city.endswith('市') and candidate in city_prefixes:
        return candidate
    raise ValueError(f'城市不在固定资产中：{city}')


def build_normalized_city_payload(raw_city, city_prefixes, subdivisions=None):
    """构造公共城市标准化结果。"""
    city = normalize_city_name(raw_city, city_prefixes)
    return {
        'schema_version': '1.1',
        'stage': 'normalized_city',
        'input_city': str(raw_city or '').strip(),
        'city': city,
        'subdivisions': list(subdivisions or []),
    }


def main():
    """读取城市参数并输出标准城市名称 JSON。"""
    parser = argparse.ArgumentParser(description='标准化中国城市名称')
    parser.add_argument('--city', required=True)
    args = parser.parse_args()
    try:
        city_prefixes = read_city_prefix_asset()
        city = normalize_city_name(args.city, city_prefixes)
        api_key = read_env_value('AMAP_KEY')
        if not api_key:
            raise ValueError('未配置 AMAP_KEY')
        subdivisions, error_reason = fetch_amap_subdivisions(
            city,
            api_key,
            RequestRateLimiter(),
        )
        if error_reason:
            raise ValueError(error_reason)
        result = build_normalized_city_payload(
            args.city, city_prefixes, subdivisions
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
