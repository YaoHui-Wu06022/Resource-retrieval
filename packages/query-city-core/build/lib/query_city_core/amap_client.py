#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提供受限频率的高德地址服务客户端。"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request


GEOCODE_ENDPOINT = 'https://restapi.amap.com/v3/geocode/geo'
POI_SEARCH_ENDPOINT = 'https://restapi.amap.com/v5/place/text'
DISTRICT_ENDPOINT = 'https://restapi.amap.com/v3/config/district'
REQUEST_INTERVAL_SECONDS = 0.4
REQUEST_TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3


class RequestRateLimiter:
    """限制连续地图请求的最短间隔。"""

    def __init__(self, interval=REQUEST_INTERVAL_SECONDS):
        """记录请求间隔并初始化计时状态。"""
        self.interval = interval
        self.last_request_at = 0.0

    def wait(self):
        """在必要时等待至满足最短请求间隔。"""
        delay = self.interval - (time.monotonic() - self.last_request_at)
        if delay > 0:
            time.sleep(delay)
        self.last_request_at = time.monotonic()


def normalize_amap_value(value):
    """把高德可能返回的字符串或空数组统一为字符串。"""
    if isinstance(value, list):
        return next((str(item).strip() for item in value if str(item).strip()), '')
    return str(value or '').strip()


def fetch_amap_payload(endpoint, parameters, rate_limiter):
    """请求高德接口并统一处理重试和服务错误。"""
    query = urllib.parse.urlencode(parameters)
    request = urllib.request.Request(
        f'{endpoint}?{query}',
        headers={'User-Agent': 'dsh-address-components/1.0'},
    )

    for attempt in range(MAX_ATTEMPTS):
        rate_limiter.wait()
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, urllib.error.URLError) as exc:
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(1.0)
                continue
            return {}, f'高德网络请求失败：{type(exc).__name__}'

        if payload.get('status') == '1':
            return payload, ''
        if payload.get('infocode') == '10021' and attempt + 1 < MAX_ATTEMPTS:
            time.sleep(1.0)
            continue
        reason = payload.get('info') or payload.get('infocode') or '未知错误'
        return {}, f'高德服务错误：{reason}'
    return {}, '高德请求重试失败'


def fetch_amap_geocodes(address, city, api_key, rate_limiter):
    """请求高德地理编码并返回候选记录和错误原因。"""
    payload, error_reason = fetch_amap_payload(
        GEOCODE_ENDPOINT,
        {
            'address': address,
            'city': city,
            'key': api_key,
            'output': 'JSON',
        },
        rate_limiter,
    )
    if error_reason:
        return [], error_reason
    geocodes = payload.get('geocodes') or []
    return (geocodes if isinstance(geocodes, list) else []), ''


def fetch_amap_pois(place_name, city, api_key, rate_limiter):
    """在目标城市内按地点全名请求高德 POI 候选。"""
    payload, error_reason = fetch_amap_payload(
        POI_SEARCH_ENDPOINT,
        {
            'keywords': place_name,
            'region': city,
            'city_limit': 'true',
            'page_size': 25,
            'page_num': 1,
            'key': api_key,
            'output': 'JSON',
        },
        rate_limiter,
    )
    if error_reason:
        return [], error_reason
    pois = payload.get('pois') or []
    return (pois if isinstance(pois, list) else []), ''


def fetch_amap_subdivisions(city, api_key, rate_limiter):
    """查询目标城市的直接下一级行政区。"""
    payload, error_reason = fetch_amap_payload(
        DISTRICT_ENDPOINT,
        {
            'keywords': city,
            'subdistrict': 1,
            'extensions': 'base',
            'key': api_key,
            'output': 'JSON',
        },
        rate_limiter,
    )
    if error_reason:
        return [], error_reason

    districts = payload.get('districts') or []
    city_matches = [
        district for district in districts
        if isinstance(district, dict)
        and normalize_amap_value(district.get('name')) == city
    ]
    if len(city_matches) != 1:
        return [], f'高德未唯一匹配目标城市：{city}'

    children = city_matches[0].get('districts') or []
    subdivisions = []
    seen_subdivisions = set()
    for child in children:
        if not isinstance(child, dict):
            continue
        name = normalize_amap_value(child.get('name'))
        adcode = normalize_amap_value(child.get('adcode'))
        subdivision_key = (name, adcode)
        if not name or not adcode or subdivision_key in seen_subdivisions:
            continue
        seen_subdivisions.add(subdivision_key)
        subdivisions.append({
            'name': name,
            'adcode': adcode,
            'level': normalize_amap_value(child.get('level')),
        })
    if not subdivisions:
        return [], f'高德未返回目标城市的下一级行政区：{city}'
    if (
        len(subdivisions) == 1
        and subdivisions[0]['level'] == 'city'
        and subdivisions[0]['name'] != city
    ):
        return fetch_amap_subdivisions(
            subdivisions[0]['name'], api_key, rate_limiter
        )
    return subdivisions, ''
