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

from query_city_core.address.city import read_city_catalog, validate_city_context
from query_city_core.address.common import (
    address_detail_key,
    address_equivalence_key,
)
from query_city_core.address.normalize import (
    detect_foreign_city_campus,
    normalize_address_value,
)
from query_city_core.io_utils import read_json_payload, write_json_payload
from university_campus_rules import (
    ASSOCIATION_METHOD_CONFIDENCE,
    canonical_campus_name,
    classify_page_source,
    clean_address_text,
    convert_chinese_number,
    has_house_number,
    is_office_noise_address as is_office_noise_address_rule,
    is_rejected_university_address,
    normalize_compact_text,
    road_name,
)


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


MAX_PAGES_PER_SCHOOL = 6
PROCESSING_STATUSES = {'completed', 'skipped', 'no_official_site'}
SKIP_REASONS = {'merged', 'ceased_independent_operation'}
WEBSITE_MODULE_CAMPUS_NAMES = frozenset((
    '数字校园',
    '智慧校园',
    '关于校区',
    '走进校区',
    '走进校园',
    '校区分布',
    '校园分布',
    '学校导游',
    '办学地点',
))
NAVIGATION_LINK_PREFIX_PATTERN = re.compile(
    r'^(?:上一条|下一条|上一篇|下一篇|上一页|下一页)\s*[：:]?\s*'
)
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
HOMEPAGE_PATHS = (
    '',
    '/',
    '/index.html',
    '/index.htm',
    '/index.shtml',
    '/index.php',
    '/default.aspx',
)
def campus_match_token(value):
    """取得可与地址原文直接比对的明确校区核心词。"""
    value = normalize_compact_text(value)
    for suffix in ('校本部', '校区', '校园'):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    return value.rsplit('校区', 1)[-1] if len(value.rsplit('校区', 1)[-1]) >= 2 else ''


def campus_equivalence_key(value):
    """折叠“广州校区校园”一类冗余后缀为“广州校区”。"""
    return canonical_campus_name(value)


def university_address_equivalence_key(value):
    """同址比较键：先统一中文数字门牌再取道路门牌。"""
    return address_equivalence_key(
        convert_chinese_number(normalize_compact_text(value))
    )


def page_navigation_campus_hints(page):
    """从“下一条/上一条”等翻页链接中识别校区提示。"""
    title = str(page.get('title') or '')
    page_hints = {
        normalize_compact_text(hint)
        for hint in (page.get('campus_hints') or [])
    }
    navigation_hints = set()
    for link in page.get('related_links') or []:
        text = normalize_compact_text(link.get('text') or '')
        match = NAVIGATION_LINK_PREFIX_PATTERN.match(text)
        if not match:
            continue
        campus = normalize_compact_text(text[match.end():])
        if campus and campus in page_hints and campus not in title:
            navigation_hints.add(campus)
    return navigation_hints


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


def is_homepage_source_url(source_reference):
    """判断信息来源网址是否为学校主页或常见首页路径。"""
    path = urlparse(str(source_reference or '')).path.lower().rstrip('/')
    return path in HOMEPAGE_PATHS


def is_outside_target_city(address, city_context):
    """规范化后仍指向目标城市以外时返回真。"""
    normalized = normalize_address_value(address, city_context)
    resolved_city = str(normalized.get('resolved_city') or '').strip()
    return bool(
        resolved_city
        and resolved_city != city_context['city_name']
    )


def record_campus_name(record):
    """读取记录中的校区名并去除空白。"""
    return normalize_compact_text(
        (record.get('attributes') or {}).get('campus_name')
    )


def contains_other_city_campus(place_name, city_context):
    """地点名称含目标城市以外的城市校区词时返回城市全名。"""
    target_city = str(city_context.get('city_name') or '')
    target_short = (
        target_city[:-1] if target_city.endswith('市') else target_city
    )
    value = normalize_compact_text(place_name)
    for full_name in read_city_catalog():
        if full_name == target_city:
            continue
        short_name = full_name[:-1] if full_name.endswith('市') else full_name
        if not short_name or short_name == target_short:
            continue
        match = re.search(
            re.escape(short_name) + r'([^，,。；;\s]{0,8}?)校区',
            value,
        )
        if not match:
            continue
        between = match.group(1)
        if target_short and target_short in between:
            continue
        return full_name
    return ''


def is_office_noise_address(record, labeled_address_keys):
    """判断无校区标签记录是否为办公点或报名点噪音地址。"""
    address = str(record.get('original_address') or '').strip()
    if not address:
        return False
    if university_address_equivalence_key(address) in labeled_address_keys:
        return False
    if is_homepage_source_url(record.get('source_reference')):
        return False
    return is_office_noise_address_rule(address)


def preferred_university_record(current, incoming, current_order, incoming_order):
    """比较两条同址记录，按校区名、主页来源与顺序选出代表。"""
    def score(record, order):
        campus = record_campus_name(record)
        return (
            1 if campus else 0,
            1 if is_homepage_source_url(record.get('source_reference')) else 0,
            len(campus),
            -order,
        )
    return (
        current
        if score(current, current_order) >= score(incoming, incoming_order)
        else incoming
    )


def clean_school_address_records(records, city_context):
    """按外市过滤、办公点过滤和落点约化整理单校地址记录。"""
    filtered = []
    has_labeled_campus = any(
        record_campus_name(record) for record in records
    )
    for record in records:
        place_name = str(record.get('place_name') or '')
        if detect_foreign_city_campus(
            str(record.get('place_name') or ''),
            city_context,
        ) or contains_other_city_campus(place_name, city_context):
            continue
        address = str(record.get('original_address') or '').strip()
        if address and is_outside_target_city(address, city_context):
            continue
        filtered.append(record)
    labeled_address_keys = {
        university_address_equivalence_key(
            str(record.get('original_address') or '')
        )
        for record in filtered
        if record_campus_name(record)
        and str(record.get('original_address') or '').strip()
    }
    retained = []
    empty_records = []
    addressed_index = {}
    empty_index = {}
    for order, record in enumerate(filtered):
        if is_office_noise_address(record, labeled_address_keys):
            continue
        if (
            not record_campus_name(record)
            and has_labeled_campus
            and not is_homepage_source_url(record.get('source_reference'))
            and university_address_equivalence_key(
                str(record.get('original_address') or '')
            )
            not in labeled_address_keys
        ):
            continue
        address = str(record.get('original_address') or '').strip()
        if not address:
            empty_records.append((order, record))
            continue
        address_key = university_address_equivalence_key(address)
        existing_index = addressed_index.get(address_key)
        if existing_index is not None:
            existing = retained[existing_index]
            chosen = preferred_university_record(
                existing, record, addressed_index[address_key], order
            )
            if chosen is not existing:
                retained[existing_index] = record
            continue
        retained.append(record)
        addressed_index[address_key] = len(retained) - 1
    addressed_campuses = {
        record_campus_name(record)
        for record in retained
        if record_campus_name(record)
    }
    for order, record in empty_records:
        campus = record_campus_name(record)
        if campus and campus in addressed_campuses:
            continue
        existing_index = empty_index.get(campus)
        if existing_index is not None:
            existing = retained[existing_index]
            chosen = preferred_university_record(
                existing, record, empty_index[campus], order
            )
            if chosen is not existing:
                retained[existing_index] = record
                empty_index[campus] = order
            continue
        empty_index[campus] = len(retained)
        retained.append(record)
    return retained


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
        navigation_hints = page_navigation_campus_hints(page)
        for candidate in page['address_candidates']:
            if not isinstance(candidate, dict):
                raise ValueError('address_candidates 中的候选必须是对象')
            campus = normalize_compact_text(candidate.get('campus_hint'))
            address = str(candidate.get('address_text') or '').strip()
            if is_rejected_university_address(address):
                continue
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
                'association_method': str(
                    candidate.get('association_method') or ''
                ).strip(),
                'source_region': str(
                    candidate.get('source_region') or ''
                ).strip(),
                'page_type': classify_page_source(
                    source_reference,
                    page.get('title') or '',
                ),
            })
        for hint in page['campus_hints']:
            campus = normalize_compact_text(hint)
            if (
                not campus
                or campus in WEBSITE_MODULE_CAMPUS_NAMES
                or campus in navigation_hints
                or campus in hint_keys
            ):
                continue
            hint_keys.add(campus)
            hints.append({
                'campus': campus,
                'source_reference': source_reference,
                'page_type': classify_page_source(
                    source_reference,
                    page.get('title') or '',
                ),
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
            if candidate.get('association_method') == 'unmatched':
                candidate['association_method'] = 'cross_page_hint'

    labeled_address_keys = {
        university_address_equivalence_key(candidate['address'])
        for candidate in candidates
        if candidate['campus']
    }
    candidates = [
        candidate
        for candidate in candidates
        if candidate['campus']
        or university_address_equivalence_key(
            candidate['address']
        ) not in labeled_address_keys
    ]
    addressed_campuses = {
        candidate['campus'] for candidate in candidates if candidate['campus']
    }
    addressed_campus_keys = {
        campus_equivalence_key(campus) for campus in addressed_campuses
    }
    hints = [
        hint for hint in hints
        if campus_equivalence_key(hint['campus']) not in addressed_campus_keys
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
        raw_campus = candidate['campus']
        campus = canonical_campus_name(raw_campus)
        attributes = build_school_attributes(school, campus)
        if raw_campus and raw_campus != campus:
            attributes['campus_name_raw'] = raw_campus
        attributes['source_page_type'] = str(
            candidate.get('page_type') or ''
        ).strip()
        attributes['association_method'] = str(
            candidate.get('association_method') or ''
        ).strip()
        attributes['association_confidence'] = int(
            ASSOCIATION_METHOD_CONFIDENCE.get(
                attributes['association_method'],
                0,
            )
        )
        attributes['source_region'] = str(
            candidate.get('source_region') or ''
        ).strip()
        cleaned_address = clean_address_text(
            candidate['address'],
            school_name,
        ) or candidate['address']
        records.append({
            'place_name': build_place_name(school_name, campus),
            'original_address': cleaned_address,
            'address_mode': 'web_search',
            'source_nature': 'web_search',
            'source_reference': candidate['source_reference'],
            'attributes': attributes,
        })
    for hint in hints:
        raw_campus = hint['campus']
        campus = canonical_campus_name(raw_campus)
        attributes = build_school_attributes(school, campus)
        if raw_campus and raw_campus != campus:
            attributes['campus_name_raw'] = raw_campus
        attributes['source_page_type'] = str(
            hint.get('page_type') or ''
        ).strip()
        records.append({
            'place_name': build_place_name(school_name, campus),
            'original_address': '',
            'address_mode': 'web_search',
            'source_nature': 'web_search',
            'source_reference': hint['source_reference'],
            'attributes': attributes,
        })
    if not records:
        source_reference = validate_page_result(pages[0])
        records.append({
            'place_name': school_name,
            'original_address': '',
            'address_mode': 'web_search',
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
                'address_mode': 'web_search',
                'source_nature': 'web_search',
                'source_reference': item['evidence_url'],
                'attributes': attributes,
            })
            continue

        completed_school_count += 1
        page_count += len(item['pages'])
        school_records = build_school_address_records(item)
        school_records = clean_school_address_records(
            school_records, page_results['city_context']
        )
        if not school_records:
            school = item['school']
            attributes = build_school_attributes(school, '')
            school_records = [{
                'place_name': school_name,
                'original_address': '',
                'address_mode': 'web_search',
                'source_nature': 'web_search',
                'source_reference': str(
                    item['pages'][0].get('final_url')
                    or item['pages'][0].get('requested_url')
                    or ''
                ),
                'attributes': attributes,
            }]
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
    """按校区分组择优，再按同址合并校区写法重复行。"""
    campus_records = []
    campus_seen = {}
    school_campus_values = defaultdict(set)
    labeled_schools = set()
    for record in records:
        attributes = record.get('attributes') or {}
        campus_name = str(attributes.get('campus_name') or '').strip()
        if campus_name:
            school_identifier = str(
                attributes.get('school_identifier') or ''
            ).strip()
            school_campus_values[school_identifier].add(campus_name)
            labeled_schools.add(school_identifier)

    def group_campus_name(school_identifier, campus_name):
        """单校区学校把校本部与无名校区视为同一组。"""
        if (
            campus_name == '校本部'
            and school_campus_values[school_identifier] <= {'校本部'}
        ):
            return ''
        return campus_name

    for order, record in enumerate(records):
        attributes = record.get('attributes') or {}
        school_identifier = str(attributes.get('school_identifier') or '').strip()
        campus_name = str(attributes.get('campus_name') or '').strip()
        group_key = (
            school_identifier,
            group_campus_name(school_identifier, campus_name),
        )
        if not group_key[1] and school_identifier not in labeled_schools:
            campus_records.append(record)
            continue
        existing_index = campus_seen.get(group_key)
        if existing_index is None:
            campus_seen[group_key] = len(campus_records)
            campus_records.append(record)
            continue
        existing = campus_records[existing_index]
        if record_quality(record, order) > record_quality(
            existing, campus_seen[group_key]
        ):
            campus_records[existing_index] = record
    campus_records = drop_unlabeled_incomplete_addresses(campus_records)
    retained = []
    location_seen = {}
    for order, record in enumerate(campus_records):
        attributes = record.get('attributes') or {}
        school_identifier = str(attributes.get('school_identifier') or '').strip()
        location_address = str(
            record.get('map_address') or record.get('final_address') or ''
        ).strip()
        detail_key = address_detail_key(location_address)
        location_key = (
            (school_identifier, detail_key)
            if detail_key and location_address
            else None
        )
        if location_key is None:
            retained.append(record)
            continue
        existing_index = location_seen.get(location_key)
        if existing_index is None:
            location_seen[location_key] = len(retained)
            retained.append(record)
            continue
        existing = retained[existing_index]
        if physical_record_quality(
            record, order
        ) > physical_record_quality(existing, location_seen[location_key]):
            retained[existing_index] = record
    return retained


def drop_unlabeled_incomplete_addresses(records):
    """丢弃同校同路已有门牌时并存的无门牌地址变体（含带校区名残缺行）。"""
    numbered_roads = defaultdict(set)
    for record in records:
        attributes = record.get('attributes') or {}
        school_identifier = str(
            attributes.get('school_identifier') or ''
        ).strip()
        location_address = str(
            record.get('map_address') or record.get('final_address') or ''
        ).strip()
        if has_house_number(location_address):
            numbered_road = road_name(location_address)
            if len(numbered_road) >= 2:
                numbered_roads[school_identifier].add(numbered_road)
    retained = []
    for record in records:
        attributes = record.get('attributes') or {}
        school_identifier = str(
            attributes.get('school_identifier') or ''
        ).strip()
        location_address = str(
            record.get('map_address') or record.get('final_address') or ''
        ).strip()
        road = road_name(location_address)
        if (
            location_address
            and not has_house_number(location_address)
            and road
            and any(
                road == numbered
                or road.endswith(numbered)
                or numbered.endswith(road)
                for numbered in numbered_roads.get(school_identifier, ())
            )
        ):
            continue
        retained.append(record)
    return retained


def record_quality(record, order):
    """给一条高校地址记录计算最终证据质量分。"""
    final_address = str(record.get('final_address') or '').strip()
    address_text = final_address or str(
        record.get('map_address') or ''
    ).strip()
    map_match_status = str(record.get('map_match_status') or '').strip()
    final_address_source = str(
        record.get('final_address_source') or ''
    ).strip()
    return (
        1 if final_address else 0,
        0 if map_match_status in {'conflict', 'error'} else 1,
        1 if map_match_status in {'consistent', 'partial', 'poi_match'} else 0,
        1 if final_address_source == 'official' else 0,
        1 if re.search(r'\d+号', address_text) else 0,
        len(address_text),
        -order,
    )


def physical_record_quality(record, order):
    """同址记录比较时优先保留带校区名的代表。"""
    return (
        1 if record_campus_name(record) else 0,
        *record_quality(record, order),
    )


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
