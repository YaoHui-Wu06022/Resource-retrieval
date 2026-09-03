#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标准化城市输入并取得其直接下级行政单位（address 子包）。"""

import argparse
import json
import sys
from pathlib import Path

from .common import CITY_SUFFIXES
from .amap_client import RequestRateLimiter, fetch_amap_subdivisions
from ..env_utils import read_env_value


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent
    / 'assets'
    / 'china_city_catalog.json'
)


def read_city_catalog(asset_path=DEFAULT_CATALOG_PATH):
    """读取城市目录并返回规范城市名到上级省级单位的映射。"""
    path = Path(asset_path).resolve()
    with path.open(encoding='utf-8') as stream:
        payload = json.load(stream)

    municipalities = payload.get('municipalities')
    province_cities = payload.get('province_cities')
    if not isinstance(municipalities, list) or not isinstance(province_cities, dict):
        raise ValueError('城市目录结构无效')

    city_catalog = {}
    for city in municipalities:
        city_name = str(city or '').strip()
        if not city_name:
            raise ValueError('直辖市列表包含空值')
        if city_name in city_catalog:
            raise ValueError(f'城市目录存在重复名称：{city_name}')
        city_catalog[city_name] = None

    for province, cities in province_cities.items():
        province_name = str(province or '').strip()
        if not province_name or not isinstance(cities, list):
            raise ValueError('省级单位或地级单位列表无效')
        for city in cities:
            city_name = str(city or '').strip()
            if not city_name:
                raise ValueError(f'{province_name}的地级单位列表包含空值')
            if city_name in city_catalog:
                raise ValueError(f'城市目录存在重复名称：{city_name}')
            city_catalog[city_name] = province_name
    return city_catalog


def normalize_city_name(raw_city, city_catalog):
    """精确匹配城市名，或为无后缀输入补充一个行政后缀。"""
    city = str(raw_city or '').strip()
    if not city:
        raise ValueError('城市名称不能为空')
    if city in city_catalog:
        return city

    candidates = [
        f'{city}{suffix}'
        for suffix in CITY_SUFFIXES
        if not city.endswith(suffix) and f'{city}{suffix}' in city_catalog
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError(f'城市名称存在多个后缀候选：{city}')
    raise ValueError(f'城市不在固定目录中：{city}')


def build_city_context(raw_city, city_catalog, subdivisions):
    """构造供后续地址处理使用的城市上下文。"""
    input_city = str(raw_city or '').strip()
    city_name = normalize_city_name(input_city, city_catalog)
    return {
        'stage': 'city_context',
        'input_city': input_city,
        'city_name': city_name,
        'province_name': city_catalog[city_name],
        'subdivisions': list(subdivisions),
    }


def validate_city_context(city_context):
    """校验并整理跨模块传递的城市上下文。"""
    if not isinstance(city_context, dict):
        raise ValueError('城市上下文必须是对象')
    if city_context.get('stage') != 'city_context':
        raise ValueError('城市上下文阶段必须是 city_context')
    input_city = str(city_context.get('input_city') or '').strip()
    city_name = str(city_context.get('city_name') or '').strip()
    province_value = city_context.get('province_name')
    province_name = (
        None if province_value is None else str(province_value).strip()
    )
    subdivisions = city_context.get('subdivisions')
    if not input_city:
        raise ValueError('城市上下文缺少非空 input_city')
    if not city_name:
        raise ValueError('城市上下文缺少非空 city_name')
    if province_name == '':
        raise ValueError('城市上下文中的 province_name 不能为空字符串')
    if not isinstance(subdivisions, list):
        raise ValueError('城市上下文中的 subdivisions 必须是数组')
    return {
        'stage': 'city_context',
        'input_city': input_city,
        'city_name': city_name,
        'province_name': province_name,
        'subdivisions': subdivisions,
    }


def resolve_city_context(
    raw_city,
    api_key,
    city_catalog=None,
    fetch_subdivisions=fetch_amap_subdivisions,
):
    """离线标准化城市后，通过高德查询其直接下级行政单位。"""
    if not api_key:
        raise ValueError('未配置 AMAP_KEY')
    city_catalog = city_catalog or read_city_catalog()
    city_name = normalize_city_name(raw_city, city_catalog)
    subdivisions, error_reason = fetch_subdivisions(
        city_name,
        api_key,
        RequestRateLimiter(),
    )
    if error_reason:
        raise ValueError(error_reason)
    return build_city_context(raw_city, city_catalog, subdivisions)


def main():
    """读取城市参数并输出城市上下文 JSON。"""
    parser = argparse.ArgumentParser(description='标准化中国城市名称并获取直接下级行政单位')
    parser.add_argument('--city', required=True)
    args = parser.parse_args()
    try:
        result = resolve_city_context(args.city, read_env_value('AMAP_KEY'))
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
