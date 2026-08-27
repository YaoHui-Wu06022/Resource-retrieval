#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为高校官网地址证据补充校区语义并保持旧输出兼容。"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urldefrag, urlparse


COMPONENTS_DIR = Path(__file__).resolve().parents[3] / 'components'
if str(COMPONENTS_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENTS_DIR))

from fetch_official_page import (
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
CAMPUS_CONTEXT_SPLIT_PATTERN = re.compile(
    r'[，,。；;：:\n、/|｜]|现有|设有|共有|拥有|下设|包括|分为|分别为|分布在|和|及|与|的'
)
GENERIC_CAMPUS_PATTERN = re.compile(
    r'^(?:各|多个|若干|所有|全部)?(?:校区|校园)$|'
    r'^[一二三四五六七八九十百两\d]+个(?:校区|校园)$|'
    r'^.+(?:大学|学院)校园$'
)
RELATED_LINK_RULES = (
    ('campus', re.compile(r'校区|校园介绍|campus', re.IGNORECASE)),
    ('contact', re.compile(r'联系|地址|contact', re.IGNORECASE)),
    ('overview', re.compile(r'概况|简介|about', re.IGNORECASE)),
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
        compact = re.sub(r'^.+?(?:大学|学院)(?=.+(?:校区|校园)$)', '', compact)
        match = CAMPUS_PATTERN.fullmatch(compact)
        if not match:
            continue
        name = match.group(0).replace('(', '（').replace(')', '）')
        if not GENERIC_CAMPUS_PATTERN.fullmatch(name):
            names.append(name)
    return list(dict.fromkeys(names))


def extract_campus_link_names(value):
    """从校区相关链接文本中提取校区名称。"""
    text = normalize_lines(value).replace('(', '（').replace(')', '）')
    for suffix in ('联系方式', '主页', '官网', '介绍', '概况', '交通'):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            break
    return extract_campus_names(text.strip(' \t|｜，,；;。-—'))


def extract_evidence_campus(evidence):
    """按标签、后缀和邻近 DOM 上下文确定地址所属校区。"""
    label = re.sub(r'(?:校址|地址)$', '', str(evidence.get('label_text') or '').strip())
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


def build_address_candidates(address_evidence):
    """把公共地址证据转换为高校工作流兼容候选。"""
    expanded_evidence = []
    for evidence in address_evidence:
        parts = [item.strip() for item in re.split(r'[|｜]', str(evidence.get('address_text') or ''))]
        if len(parts) > 1 and all(any(marker in item for marker in ('校区', '校园', '校本部'))
                                  for item in parts):
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
        prefix, separator, _ = first_line.replace(':', '：').partition('：')
        prefix_names = extract_campus_names(prefix.strip()) if separator else []
        inline_campus = wrapped_campus or (prefix_names[0] if prefix_names else '')
        campus = inline_campus or extract_evidence_campus(evidence)
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
    related_links = filter_related_links(
        common_result.get('links') or [], domains, common_result.get('final_url') or ''
    )
    candidates = build_address_candidates(common_result.get('address_evidence') or [])
    hints = [item['campus_hint'] for item in candidates if item['campus_hint']]
    for link in related_links:
        if link['link_type'] == 'campus':
            hints.extend(extract_campus_link_names(link['text']))
    warnings = list(common_result.get('warnings') or [])
    return {
        'schema_version': '1.0',
        'stage': 'address_candidates',
        'requested_url': common_result['requested_url'],
        'final_url': common_result.get('final_url') or '',
        'http_status': common_result.get('http_status'),
        'page_status': common_result.get('page_status'),
        'title': common_result.get('title') or '',
        'official_domains': domains,
        'address_candidates': candidates[:30],
        'campus_hints': list(dict.fromkeys(hints))[:MAX_CAMPUS_HINTS],
        'related_links': related_links,
        'warnings': warnings,
    }


def fetch_university_page(url, official_domains):
    """抓取高校官网并补充高校专用地址语义。"""
    common_result = fetch_official_page(
        url, official_domains, extra_address_labels=('校址', '校区', '办学地点')
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
