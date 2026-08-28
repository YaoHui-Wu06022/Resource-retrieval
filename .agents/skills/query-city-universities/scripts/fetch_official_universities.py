#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为高校官网地址证据补充校区语义。"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urldefrag, urlparse


from query_city_core.fetch_official_page import (
    fetch_official_page,
    normalize_domain,
    normalize_lines,
    is_url_in_domains,
)


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


CAMPUS_NAME_EXPRESSION = (
    r'(?:[^\s，,。；;：:、/|｜（）()“”‘’《》？！!?]{1,30}'
    r'(?:[（(][^\s（）()“”‘’《》？！!?]{1,12}[）)])?(?:校区|校园)'
    r'(?:[（(][^\s（）()“”‘’《》？！!?]{1,12}[）)])?|校本部)'
)
CAMPUS_PATTERN = re.compile(CAMPUS_NAME_EXPRESSION)
INLINE_CAMPUS_FIELD_PATTERN = re.compile(
    r'(?:^|\s)(?P<campus>校本部|[^\s，,。；;：:]{1,12}(?:校区|校园))\s*[：:]'
)
CHARTER_CAMPUS_LOCATION_PATTERN = re.compile(
    rf'(?P<campus>{CAMPUS_NAME_EXPRESSION})\s*位于\s*'
    r'(?P<address>[^，,。；;\n]+)'
)
CAMPUS_CONTEXT_SPLIT_PATTERN = re.compile(
    r'[，,。；;：:\n、/|｜]|现有|设有|共有|拥有|下设|包括|分为|分别为|分布在|和|及|与|的'
)
GENERIC_CAMPUS_PATTERN = re.compile(
    r'^(?:各|多个|若干|所有|全部)?(?:校区|校园)$|'
    r'^[一二三四五六七八九十百两\d]+个(?:校区|校园)$|'
    r'^(?:学校|本校)(?:校区|校园)$|'
    r'^图说校区$|'
    r'^.+(?:大学|学院)校园$'
)
RELATED_LINK_RULES = (
    ('campus', re.compile(r'校区|校园(?:介绍|分布)|学校导游|办学地点|走进校园|campus', re.IGNORECASE)),
    ('contact', re.compile(r'联系|地址|contact', re.IGNORECASE)),
    ('overview', re.compile(r'概况|简介|章程|about', re.IGNORECASE)),
)
EXCLUDED_LINK_TEXT = re.compile(r'地图|风光|生活|文化|看点|媒体')
EXCLUDED_LINK_PATH = re.compile(
    r'\.(?:jpe?g|png|gif|webp|svg|pdf|docx?|xlsx?)$', re.IGNORECASE
)
MAX_CAMPUS_HINTS = 30


def extract_campus_names(value):
    """从高校上下文中提取明确的校区名称。"""
    names = []
    for fragment in CAMPUS_CONTEXT_SPLIT_PATTERN.split(normalize_lines(value)):
        compact = re.sub(r'\s+', '', fragment.strip())
        compact = re.sub(r'^[A-Za-z0-9]+(?=[\u4e00-\u9fff].*(?:校区|校园)$)', '', compact)
        compact = re.sub(r'^.+?(?:大学(?!城)|学院)(?=.+(?:校区|校园)$)', '', compact)
        match = CAMPUS_PATTERN.fullmatch(compact)
        if not match:
            continue
        name = match.group(0).replace('(', '（').replace(')', '）')
        if (not re.search(r'设立|位于|坐落|座落|开设', name)
                and not GENERIC_CAMPUS_PATTERN.fullmatch(name)):
            names.append(name)
    return list(dict.fromkeys(names))


def extract_campus_link_names(value):
    """从校区相关链接文本中提取校区名称。"""
    text = normalize_lines(value).replace('(', '（').replace(')', '）')
    if len(text) > 40:
        return []
    for suffix in ('联系方式', '主页', '官网', '介绍', '概况', '交通'):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            break
    return extract_campus_names(text.strip(' \t|｜，,；;。-—'))


def extract_title_campus_names(value):
    """从标题各分段中提取校区名，兼容校区名位于站点名前后。"""
    names = []
    for part in re.split(r'\s*[-—_|｜]\s*', normalize_lines(value)):
        names.extend(extract_campus_names(part))
    return list(dict.fromkeys(names))


def extract_evidence_campus(evidence):
    """按标签、后缀和邻近 DOM 上下文确定地址所属校区。"""
    label = re.sub(r'(?:校址|地址)$', '', str(evidence.get('label_text') or '').strip())
    label_parts = label.split()
    if len(label_parts) > 1 and any(
            marker in label_parts[-1] for marker in ('校区', '校园', '校本部')):
        label = label_parts[-1]
    sources = [label]
    raw_text = str(evidence.get('raw_text') or '')
    suffixes = re.findall(r'[（(]([^（）()]{1,30}(?:校区|校园|校本部))[^（）()]*[）)]', raw_text)
    sources.extend(suffixes)
    sources.extend(item.get('text') for item in evidence.get('context_before') or [])
    sources.extend(item.get('text') for item in evidence.get('context_after') or [])
    for source in sources:
        names = extract_campus_names(source)
        if names:
            return names[0]
    return ''


def split_inline_campus_fields(value):
    """拆分同一行内连续出现的“校区名：地址”字段。"""
    fields = []
    for line in normalize_lines(value).splitlines():
        matches = list(INLINE_CAMPUS_FIELD_PATTERN.finditer(line))
        if len(matches) < 2:
            continue
        line_fields = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            address = line[match.end():end].strip(' ，,；;')
            if address:
                line_fields.append(f"{match.group('campus')}：{address}")
        if len(line_fields) == len(matches):
            fields.extend(line_fields)
    return fields


def build_address_candidates(address_evidence, page_title=''):
    """把公共地址证据转换为结构化地址候选。"""
    page_campuses = extract_title_campus_names(page_title)
    title_campus = page_campuses[0] if page_campuses else ''
    title_core = re.sub(r'(?:校区|校园)$', '', title_campus).rsplit('校区', 1)[-1]
    expanded_evidence = []
    raw_texts = [str(item.get('raw_text') or '') for item in address_evidence]
    for evidence in address_evidence:
        raw_text = str(evidence.get('raw_text') or '')
        charter_locations = list(CHARTER_CAMPUS_LOCATION_PATTERN.finditer(raw_text))
        if charter_locations:
            for match in charter_locations:
                item = dict(evidence)
                item['address_text'] = (
                    f"{match.group('campus')}：{match.group('address').strip()}"
                )
                item['raw_text'] = item['address_text']
                expanded_evidence.append(item)
            continue
        named_fields = split_inline_campus_fields(
            raw_text or evidence.get('address_text') or ''
        )
        if named_fields and raw_texts.count(raw_text) < len(named_fields):
            for field in named_fields:
                item = dict(evidence)
                item['address_text'] = field
                item['raw_text'] = field
                expanded_evidence.append(item)
            continue
        grouped_address = re.sub(
            r'([）)])\s+(?=\S)', r'\1|', str(evidence.get('address_text') or '')
        )
        parts = [item.strip() for item in re.split(r'[|｜/]', grouped_address)]
        split_group = len(parts) > 1 and all(
            any(marker in item for marker in ('校区', '校园', '校本部'))
            or (any(marker in item for marker in ('省', '市', '区', '县'))
                and any(marker in item for marker in ('路', '街', '道', '号', '城')))
            for item in parts
        )
        if split_group:
            matches = [item for item in parts if title_core and title_core in item]
            parts = matches or parts
            for part in parts:
                item = dict(evidence)
                item['address_text'] = part
                item['raw_text'] = part
                expanded_evidence.append(item)
        else:
            expanded_evidence.append(evidence)
    candidates = []
    seen = set()
    for evidence in expanded_evidence:
        address = str(evidence.get('address_text') or '').strip()
        if not address:
            continue
        wrapped_campus = ''
        left, opening, rest = address.replace('(', '（').replace(')', '）').partition('（')
        inner, closing, tail = rest.partition('）')
        wrapped_names = extract_campus_names(left) if opening and closing else []
        if wrapped_names and re.fullmatch(r'\d{6}', tail.strip()):
            wrapped_campus = wrapped_names[0]
            address = inner.strip()
        raw_text = str(evidence.get('raw_text') or '')
        first_line = normalize_lines(raw_text).splitlines()[0] if raw_text else ''
        evidence_campus = extract_evidence_campus(evidence)
        prefix_names = []
        for line in (address, first_line if not evidence_campus else ''):
            prefix, separator, _ = line.replace(':', '：').partition('：')
            prefix = prefix.strip()
            prefix_names = (
                extract_campus_names(prefix)
                if separator and not re.search(r'\d|号', prefix)
                else []
            )
            if prefix_names:
                break
        inline_campus = wrapped_campus or (prefix_names[0] if prefix_names else '')
        campus = inline_campus or evidence_campus
        page_campus = (title_campus if not campus and title_campus
                       and (evidence.get('source_region') == 'body'
                            or title_core in address) else '')
        campus = campus or page_campus
        if inline_campus:
            address_prefix, address_separator, remainder = address.replace(':', '：').partition('：')
            if address_separator and inline_campus in extract_campus_names(address_prefix):
                address = remainder.lstrip()
            elif address.startswith(inline_campus):
                remainder = address[len(inline_campus):].lstrip()
                if remainder.startswith(('：', ':')):
                    address = remainder[1:].lstrip()
        if campus:
            normalized = address.replace('(', '（').replace(')', '）').lstrip()
            if normalized.startswith('（'):
                note, closing, remainder = normalized[1:].partition('）')
                if closing and campus in note:
                    address = remainder.strip()
            address = re.sub(
                rf'\s*[（(]\s*{re.escape(campus)}\s*[）)]\s*$', '', address
            )
            address = re.sub(r'\s+\d{6}$', '', address).strip()
        if not address:
            continue
        key = (campus, re.sub(r'\s+', '', address))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            'campus_hint': campus,
            'address_text': address,
            'source_text': raw_text or address,
            'association_method': ('inline_campus_prefix' if inline_campus else
                                   'page_title' if page_campus else
                                   'dom_context' if campus else 'unmatched'),
            'extraction_method': evidence.get('extraction_method') or '',
            'source_region': evidence.get('source_region') or 'body',
            'visible': bool(evidence.get('visible')),
        })
    return candidates


def classify_related_link(text, url):
    """判断高校相关页面链接类型。"""
    value = f'{text} {urlparse(url).path}'
    for priority, (link_type, pattern) in enumerate(RELATED_LINK_RULES):
        if pattern.search(value):
            return priority, link_type
    return None


def filter_related_links(links, domains, current_url):
    """筛选同域名的校区、联系和学校概况链接。"""
    current_url = urldefrag(current_url)[0].rstrip('/')
    results = []
    seen = set()
    for index, link in enumerate(links):
        text = normalize_lines(link.get('text')).replace('\n', ' ')
        url = urldefrag(link.get('url') or '')[0]
        if (not is_url_in_domains(url, domains) or url.rstrip('/') == current_url
                or EXCLUDED_LINK_TEXT.search(text)
                or EXCLUDED_LINK_PATH.search(urlparse(url).path)):
            continue
        classification = classify_related_link(text, url)
        if classification is None or url in seen:
            continue
        seen.add(url)
        priority, link_type = classification
        results.append((priority, index, {'text': text, 'url': url, 'link_type': link_type}))
    results.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in results[:20]]


def build_university_result(common_result):
    """用高校语义扩展公共结果。"""
    domains = common_result['official_domains']
    title = common_result.get('title') or ''
    related_links = filter_related_links(
        common_result.get('links') or [], domains, common_result.get('final_url') or ''
    )
    candidates = build_address_candidates(
        common_result.get('address_evidence') or [], title
    )
    hints = extract_title_campus_names(title)
    hints.extend(item['campus_hint'] for item in candidates if item['campus_hint'])
    for link in related_links:
        if link['link_type'] == 'campus':
            hints.extend(extract_campus_link_names(link['text']))
    warnings = list(common_result.get('warnings') or [])
    return {
        'stage': 'address_candidates',
        'requested_url': common_result['requested_url'],
        'final_url': common_result.get('final_url') or '',
        'http_status': common_result.get('http_status'),
        'page_status': common_result.get('page_status'),
        'title': title,
        'official_domains': domains,
        'address_candidates': candidates[:30],
        'campus_hints': list(dict.fromkeys(hints))[:MAX_CAMPUS_HINTS],
        'related_links': related_links,
        'warnings': warnings,
    }


def fetch_university_page(url, official_domains):
    """抓取高校官网并补充高校专用地址语义。"""
    common_result = fetch_official_page(
        url, official_domains,
        extra_address_labels=('校址', '校区', '校园', '办学地点'),
    )
    return build_university_result(common_result)


def main():
    """解析参数并输出单个高校官网页面结果。"""
    parser = argparse.ArgumentParser(description='抓取高校官网页面并提取地址候选')
    parser.add_argument('url')
    parser.add_argument('--official-domain', action='append', required=True)
    args = parser.parse_args()
    domains = sorted({item for item in map(normalize_domain, args.official_domain) if item})
    print(json.dumps(fetch_university_page(args.url, domains), ensure_ascii=False))


if __name__ == '__main__':
    main()
