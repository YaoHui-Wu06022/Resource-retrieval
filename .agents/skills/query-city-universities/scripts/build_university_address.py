#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚合高校官网页面结果并生成公共地址记录。"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from query_city_core.city import validate_city_context
from query_city_core.address.common import address_detail_key
from query_city_core.io_utils import read_json_payload, write_json_payload


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


MAX_PAGES_PER_SCHOOL = 6
PROCESSING_STATUSES = {'completed', 'skipped', 'no_official_site'}
SKIP_REASONS = {'merged', 'ceased_independent_operation'}
WEBSITE_MODULE_CAMPUS_NAMES = frozenset(('数字校园', '智慧校园'))
RETRIEVAL_PAYLOAD_FIELDS = {'items'}
COMPLETED_RESULT_FIELDS = {
    'school_identifier',
    'processing_status',
    'pages',
}
SKIPPED_RESULT_FIELDS = {
    'school_identifier',
    'processing_status',
    'skip_reason',
    'skip_reference',
}
NO_OFFICIAL_SITE_RESULT_FIELDS = {
    'school_identifier',
    'processing_status',
    'evidence_url',
    'reason',
}
CITY_UNIVERSITY_FIELDS = (
    'source_sequence',
    'school_name',
    'school_identifier',
    'supervising_authority',
    'location_city',
    'education_level',
    'school_tag',
    'school_nature',
)
SCHOOL_ATTRIBUTE_FIELDS = (
    'source_sequence',
    'school_name',
    'school_identifier',
    'supervising_authority',
    'location_city',
    'education_level',
    'school_tag',
    'school_nature',
)


def normalize_compact_text(value):
    """删除名称或地址中的全部空白。"""
    return re.sub(r'\s+', '', str(value or ''))


def campus_match_token(value):
    """取得可与地址原文直接比对的明确校区核心词。"""
    value = normalize_compact_text(value)
    for suffix in ('校本部', '校区', '校园'):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    return value.rsplit('校区', 1)[-1] if len(value.rsplit('校区', 1)[-1]) >= 2 else ''


def address_contains_campus_token(address, campus, allow_district_suffix=False):
    """判断校区核心词是否作为地点词出现在地址中。"""
    token = campus_match_token(campus)
    index = address.find(token) if token else -1
    next_index = index + len(token)
    if index < 0:
        return False
    if next_index == len(address):
        return True
    suffix = address[next_index]
    return suffix not in '省市区县' or (allow_district_suffix and suffix in '区县')


def address_equivalence_key(address):
    """取得用于识别同址变体的详细道路和门牌键。"""
    value = normalize_compact_text(address)
    value = re.sub(r'^中国', '', value)
    value = re.sub(r'^[^省]{1,12}省', '', value)
    return address_detail_key(value)


def validate_page_result(page):
    """校验单页抓取结果并返回来源链接。"""
    if not isinstance(page, dict) or page.get('stage') != 'address_candidates':
        raise ValueError('每个页面必须是 address_candidates JSON')
    candidates = page.get('address_candidates')
    hints = page.get('campus_hints')
    if not isinstance(candidates, list):
        raise ValueError('页面 address_candidates 必须是数组')
    if not isinstance(hints, list):
        raise ValueError('页面 campus_hints 必须是数组')
    source_reference = str(
        page.get('final_url') or page.get('requested_url') or ''
    ).strip()
    if not source_reference:
        raise ValueError('每个页面必须包含 requested_url 或 final_url')
    return source_reference


def validate_city_universities(city_universities_payload):
    """校验城市高校名录并按学校标识码建立完整学校索引。"""
    if (
        not isinstance(city_universities_payload, dict)
        or city_universities_payload.get('stage') != 'city_universities'
    ):
        raise ValueError(
            '同目录 city_universities.json 阶段必须是 city_universities'
        )
    city_context = validate_city_context(city_universities_payload.get('city_context'))
    schools = city_universities_payload.get('schools')
    if not isinstance(schools, list):
        raise ValueError('city_universities.schools 必须是数组')

    school_index = {}
    for school in schools:
        if not isinstance(school, dict) or set(school) != set(CITY_UNIVERSITY_FIELDS):
            raise ValueError('city_universities 中的学校字段不完整或包含未知字段')
        school_identifier = str(school.get('school_identifier') or '').strip()
        school_name = normalize_compact_text(school.get('school_name'))
        if not school_identifier or not school_name:
            raise ValueError('城市高校必须包含学校标识码和学校名称')
        if school_identifier in school_index:
            raise ValueError(f'城市高校标识码重复：{school_identifier}')
        school_index[school_identifier] = school
    return city_context, school_index


def build_school_page_result(item, city_university):
    """用精简检索结果和城市高校名录组装单校页面结果。"""
    if not isinstance(item, dict):
        raise ValueError('每个学校检索结果必须是对象')
    school_identifier = str(item.get('school_identifier') or '').strip()
    if not school_identifier:
        raise ValueError('每个学校检索结果必须包含 school_identifier')
    school_name = normalize_compact_text(city_university.get('school_name'))
    processing_status = str(item.get('processing_status') or '').strip()
    if processing_status not in PROCESSING_STATUSES:
        raise ValueError(
            f'{school_name}的 processing_status 必须是 completed、skipped '
            '或 no_official_site'
        )

    if processing_status == 'completed':
        if set(item) != COMPLETED_RESULT_FIELDS:
            raise ValueError(
                f'{school_name}已完成时只能包含 school_identifier、'
                'processing_status 和 pages'
            )
        pages = item['pages']
        if not isinstance(pages, list):
            raise ValueError(f'{school_name}的 pages 必须是数组')
        if not pages:
            raise ValueError(f'{school_name}必须包含至少一个页面结果')
        if len(pages) > MAX_PAGES_PER_SCHOOL:
            raise ValueError(
                f'{school_name}页面数量超过{MAX_PAGES_PER_SCHOOL}页预算'
            )
        for page in pages:
            validate_page_result(page)
        return {
            'school': dict(city_university),
            'processing_status': processing_status,
            'pages': pages,
        }

    if processing_status == 'no_official_site':
        if set(item) != NO_OFFICIAL_SITE_RESULT_FIELDS:
            raise ValueError(
                f'{school_name}无官网时只能包含 school_identifier、'
                'processing_status、evidence_url 和 reason'
            )
        evidence_url = str(item.get('evidence_url') or '').strip()
        reason = str(item.get('reason') or '').strip()
        parsed_evidence = urlparse(evidence_url)
        if (
            parsed_evidence.scheme not in {'http', 'https'}
            or not parsed_evidence.netloc
        ):
            raise ValueError(f'{school_name}无官网时必须提供证据页面 URL')
        if not reason:
            raise ValueError(f'{school_name}无官网时必须提供原因')
        return {
            'school': dict(city_university),
            'processing_status': processing_status,
            'pages': [],
            'evidence_url': evidence_url,
            'reason': reason,
        }

    if set(item) != SKIPPED_RESULT_FIELDS:
        raise ValueError(
            f'{school_name}已跳过时只能包含 school_identifier、'
            'processing_status、skip_reason 和 skip_reference'
        )
    skip_reason = str(item.get('skip_reason') or '').strip()
    skip_reference = str(item.get('skip_reference') or '').strip()
    if skip_reason not in SKIP_REASONS:
        raise ValueError(
            f'{school_name}的 skip_reason 必须是 merged 或 '
            'ceased_independent_operation'
        )
    parsed_reference = urlparse(skip_reference)
    if parsed_reference.scheme not in {'http', 'https'} or not parsed_reference.netloc:
        raise ValueError(f'{school_name}已跳过时必须提供证据页面URL')
    return {
        'school': dict(city_university),
        'processing_status': processing_status,
        'pages': [],
        'skip_reason': skip_reason,
        'skip_reference': skip_reference,
    }


def build_page_results_payload(payload, city_universities_payload):
    """补齐学校信息并构造完整高校页面结果批次。"""
    if not isinstance(payload, dict) or set(payload) != RETRIEVAL_PAYLOAD_FIELDS:
        raise ValueError('输入必须是仅包含 items 的高校检索结果 JSON')
    items = payload.get('items')
    if not isinstance(items, list):
        raise ValueError('items 必须是数组')
    city_context, city_university_index = validate_city_universities(
        city_universities_payload
    )

    page_results = []
    checked_school_identifiers = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('每个学校检索结果必须是对象')
        school_identifier = str(item.get('school_identifier') or '').strip()
        if not school_identifier:
            raise ValueError('每个学校检索结果必须包含 school_identifier')
        if school_identifier in checked_school_identifiers:
            school_name = normalize_compact_text(
                city_university_index.get(school_identifier, {}).get('school_name')
            )
            raise ValueError(f'学校结果重复：{school_name or school_identifier}')
        if school_identifier not in city_university_index:
            raise ValueError(f'出现城市高校名录外学校标识码：{school_identifier}')
        checked_school_identifiers.add(school_identifier)
        page_results.append(build_school_page_result(
            item,
            city_university_index[school_identifier],
        ))

    missing_identifiers = set(city_university_index) - checked_school_identifiers
    if missing_identifiers:
        missing_names = [
            normalize_compact_text(city_university_index[identifier]['school_name'])
            for identifier in city_university_index
            if identifier in missing_identifiers
        ]
        raise ValueError('缺少学校处理结果：' + '、'.join(missing_names))

    return {
        'stage': 'university_page_results',
        'city_context': city_context,
        'items': page_results,
    }


def build_place_name(school_name, campus_name):
    """拼接可供公共地图检索的地点名称。"""
    school_name = normalize_compact_text(school_name)
    campus_name = normalize_compact_text(campus_name)
    if not campus_name:
        return school_name
    if school_name in campus_name:
        return campus_name
    return school_name + campus_name


def build_school_attributes(school, campus_name):
    """把高校基础字段转换为公共层透传属性。"""
    attributes = {
        field: str(school.get(field) or '').strip()
        for field in SCHOOL_ATTRIBUTE_FIELDS
    }
    attributes['campus_name'] = normalize_compact_text(campus_name)
    return attributes


def collect_school_page_results(pages):
    """合并页面地址候选和校区线索并执行去重。"""
    candidates = []
    hints = []
    candidate_keys = set()
    hint_keys = set()
    for page in pages:
        source_reference = str(
            page.get('final_url') or page.get('requested_url')
        ).strip()
        for candidate in page['address_candidates']:
            if not isinstance(candidate, dict):
                raise ValueError('address_candidates 中的候选必须是对象')
            campus = normalize_compact_text(candidate.get('campus_hint'))
            address = str(candidate.get('address_text') or '').strip()
            address_key = normalize_compact_text(address)
            if not address_key:
                raise ValueError('地址候选的 address_text 不能为空')
            key = (campus, address_key)
            if key in candidate_keys:
                continue
            candidate_keys.add(key)
            candidates.append({
                'campus': campus,
                'address': address,
                'address_key': address_key,
                'source_reference': source_reference,
            })
        for hint in page['campus_hints']:
            campus = normalize_compact_text(hint)
            if (
                not campus
                or campus in WEBSITE_MODULE_CAMPUS_NAMES
                or campus in hint_keys
            ):
                continue
            hint_keys.add(campus)
            hints.append({
                'campus': campus,
                'source_reference': source_reference,
            })

    for candidate in candidates:
        if candidate['campus']:
            continue
        matches = []
        for hint in hints:
            if address_contains_campus_token(
                candidate['address_key'], hint['campus']
            ):
                matches.append(hint['campus'])
        if len(matches) == 1:
            candidate['campus'] = matches[0]

    labeled_address_keys = {
        address_equivalence_key(candidate['address'])
        for candidate in candidates
        if candidate['campus']
    }
    candidates = [
        candidate
        for candidate in candidates
        if candidate['campus']
        or address_equivalence_key(candidate['address']) not in labeled_address_keys
    ]
    addressed_campuses = {
        candidate['campus'] for candidate in candidates if candidate['campus']
    }
    hints = [
        hint for hint in hints
        if hint['campus'] not in addressed_campuses
        and not any(
            address_contains_campus_token(
                candidate['address_key'], hint['campus'], allow_district_suffix=True
            )
            for candidate in candidates
        )
    ]
    return candidates, hints


def build_school_address_records(item):
    """把一所学校的页面结果拆成单地点公共记录。"""
    school = item['school']
    pages = item['pages']
    school_name = normalize_compact_text(school['school_name'])
    candidates, hints = collect_school_page_results(pages)
    records = []
    for candidate in candidates:
        campus = candidate['campus']
        records.append({
            'place_name': build_place_name(school_name, campus),
            'original_address': candidate['address'],
            'source_nature': 'web_search',
            'source_reference': candidate['source_reference'],
            'attributes': build_school_attributes(school, campus),
        })
    for hint in hints:
        campus = hint['campus']
        records.append({
            'place_name': build_place_name(school_name, campus),
            'original_address': '',
            'source_nature': 'web_search',
            'source_reference': hint['source_reference'],
            'attributes': build_school_attributes(school, campus),
        })
    if not records:
        source_reference = validate_page_result(pages[0])
        records.append({
            'place_name': school_name,
            'original_address': '',
            'source_nature': 'web_search',
            'source_reference': source_reference,
            'attributes': build_school_attributes(school, ''),
        })
    return records


def build_conflict_warnings(school_name, records):
    """记录同一明确校区出现多个不同地址的情况。"""
    campus_addresses = defaultdict(set)
    for record in records:
        campus = record['attributes'].get('campus_name') or ''
        address = normalize_compact_text(record['original_address'])
        if campus and address:
            campus_addresses[campus].add(address)
    return [
        {
            'school_name': school_name,
            'campus': campus,
            'reason': '同一校区出现多个不同官网地址',
        }
        for campus, addresses in campus_addresses.items()
        if len(addresses) > 1
    ]


def build_address_payload(page_results):
    """把已校验的高校页面批次转换为公共地址记录。"""
    records = []
    warnings = []
    completed_school_count = 0
    skipped_school_count = 0
    no_official_site_school_count = 0
    page_count = 0
    for item in page_results['items']:
        school = item['school']
        school_name = normalize_compact_text(school.get('school_name'))
        if item['processing_status'] == 'skipped':
            skipped_school_count += 1
            continue
        if item['processing_status'] == 'no_official_site':
            no_official_site_school_count += 1
            attributes = build_school_attributes(school, '')
            attributes['abnormal_reason'] = item['reason']
            records.append({
                'place_name': school_name,
                'original_address': '',
                'source_nature': 'web_search',
                'source_reference': item['evidence_url'],
                'attributes': attributes,
            })
            continue

        completed_school_count += 1
        page_count += len(item['pages'])
        school_records = build_school_address_records(item)
        records.extend(school_records)
        warnings.extend(build_conflict_warnings(school_name, school_records))

    original_address_count = sum(
        bool(record['original_address']) for record in records
    )
    return {
        'stage': 'address_records',
        'city_context': page_results['city_context'],
        'items': records,
        'metrics': {
            'city_university_count': len(page_results['items']),
            'completed_school_count': completed_school_count,
            'skipped_school_count': skipped_school_count,
            'no_official_site_school_count': no_official_site_school_count,
            'missing_school_count': 0,
            'page_count': page_count,
            'item_count': len(records),
            'original_address_count': original_address_count,
            'missing_original_address_count': len(records) - original_address_count,
            'warning_count': len(warnings),
        },
        'warnings': warnings,
    }


def postprocess_university_address_records(records):
    """地图同址时删除同校重复记录并优先保留校区名。"""
    retained = []
    seen = {}
    for record in records:
        attributes = record.get('attributes') or {}
        school_identifier = str(attributes.get('school_identifier') or '').strip()
        campus_name = str(attributes.get('campus_name') or '').strip()
        map_address = str(record.get('map_address') or '').strip()
        detail_key = address_detail_key(map_address)
        key = (school_identifier, detail_key) if detail_key else None
        if not key or not map_address:
            retained.append(record)
            continue
        existing_index = seen.get(key)
        if existing_index is None:
            seen[key] = len(retained)
            retained.append(record)
            continue
        existing = retained[existing_index]
        existing_campus = str(
            (existing.get('attributes') or {}).get('campus_name') or ''
        ).strip()
        if campus_name and not existing_campus:
            retained[existing_index] = record
    return retained


def build_output_payloads(retrieval_payload, city_universities_payload):
    """一次构造页面批次归档和公共地址记录。"""
    page_results = build_page_results_payload(
        retrieval_payload,
        city_universities_payload,
    )
    return page_results, build_address_payload(page_results)


def main():
    """解析命令行参数并写出公共地址记录。"""
    parser = argparse.ArgumentParser(
        description='聚合高校官网页面结果并生成公共地址记录'
    )
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        input_path = Path(args.input).resolve()
        city_universities_path = input_path.parent / 'city_universities.json'
        page_results_path = input_path.parent / 'university_page_results.json'
        output_path = Path(args.output).resolve()
        if output_path in {input_path, page_results_path}:
            raise ValueError('输出文件不得覆盖检索结果或页面批次归档')
        retrieval_payload = read_json_payload(input_path)
        city_universities_payload = read_json_payload(city_universities_path)
        page_results, result = build_output_payloads(
            retrieval_payload,
            city_universities_payload,
        )
        write_json_payload(page_results_path, page_results)
        write_json_payload(output_path, result)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        'page_results_output': str(page_results_path),
        'output': str(output_path),
        **result['metrics'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
