#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为高校官网地址证据补充校区语义。"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urldefrag, urlparse


from query_city_core.web.fetch_official_page import (
    OfficialPageFetcher,
    fetch_official_page,
    normalize_domain,
    normalize_lines,
    is_url_in_domains,
)
from query_city_core.io_utils import read_json_payload, write_json_payload


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
    r'^(?:数字校园|智慧校园)$|'
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
NAVIGATION_LINK_TEXT_PATTERN = re.compile(
    r'^(?:上一条|下一条|上一篇|下一篇|上一页|下一页|返回(?:列表|上页|上一级)?)\s*[：:]?'
)
MAX_CAMPUS_HINTS = 30
DEFAULT_MAX_PAGES_PER_SCHOOL = 3
EXPANDED_MAX_PAGES_PER_SCHOOL = 6


def _normalized_url_key(url):
    """取得用于去重的规范化 URL。"""
    return urldefrag(str(url or ''))[0].rstrip('/')


def has_usable_address_candidate(page_result):
    """判断页面结果是否包含非空地址候选。"""
    return any(
        str(candidate.get('address_text') or '').strip()
        for candidate in page_result.get('address_candidates') or []
    )


def has_campus_expansion_signal(page_result):
    """判断页面是否出现多校区汇总线索，需要继续补抓校区详情页。

    只要页面展示 ≥2 个校区提示或校区相关链接即触发扩展，
    不要求页面“尚无地址”——首页已命中主校区地址时同样需要
    继续核对其余校区。
    """
    campus_hints = [
        str(hint or '').strip()
        for hint in page_result.get('campus_hints') or []
        if str(hint or '').strip() and not str(hint or '').strip().endswith('校本部')
    ]
    campus_link_count = sum(
        1
        for link in page_result.get('related_links') or []
        if str(link.get('link_type') or '') == 'campus'
    )
    return len(campus_hints) >= 2 or campus_link_count >= 2


IDENTITY_WARNING_PREFIX = '页面身份校验：'


def extract_identity_aliases(school_name):
    """生成用于首页身份校验的校名别名（全名及去掉括号的简称）。"""
    aliases = []
    name = str(school_name or '').strip()
    if name:
        aliases.append(name)
    core = re.sub(r'[（(][^（）()]*[）)]', '', name).strip()
    if core and core != name:
        aliases.append(core)
    return list(dict.fromkeys(
        re.sub(r'\s+', '', alias)
        for alias in aliases
        if re.sub(r'\s+', '', alias)
    ))


def build_home_identity_warning(page_result, school_name):
    """首页标题不含学校名称（或其简称）时返回身份校验警告。"""
    title = re.sub(r'\s+', '', str(page_result.get('title') or ''))
    if not title or not school_name:
        return ''
    if any(alias and alias in title for alias in extract_identity_aliases(school_name)):
        return ''
    return f'{IDENTITY_WARNING_PREFIX}首页标题未包含学校名称「{school_name}」'


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


def expand_address_evidence(address_evidence, title_core=''):
    """按章程条款、行内校区字段和分组地址展开地址证据。"""
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
    return expanded_evidence


def build_address_candidate(evidence, title_campus='', title_core=''):
    """从单条展开后的证据构造地址候选；无有效地址时返回 None。"""
    address = str(evidence.get('address_text') or '').strip()
    if not address:
        return None
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
        return None
    return {
        'campus_hint': campus,
        'address_text': address,
        'source_text': raw_text or address,
        'association_method': ('inline_campus_prefix' if inline_campus else
                               'page_title' if page_campus else
                               'dom_context' if campus else 'unmatched'),
        'extraction_method': evidence.get('extraction_method') or '',
        'source_region': evidence.get('source_region') or 'body',
        'visible': bool(evidence.get('visible')),
    }


def build_address_candidates(address_evidence, page_title=''):
    """把公共地址证据转换为结构化地址候选。"""
    page_campuses = extract_title_campus_names(page_title)
    title_campus = page_campuses[0] if page_campuses else ''
    title_core = re.sub(r'(?:校区|校园)$', '', title_campus).rsplit('校区', 1)[-1]
    candidates = []
    seen = set()
    for evidence in expand_address_evidence(address_evidence, title_core):
        candidate = build_address_candidate(evidence, title_campus, title_core)
        if candidate is None:
            continue
        key = (
            candidate['campus_hint'],
            re.sub(r'\s+', '', candidate['address_text']),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
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
                or NAVIGATION_LINK_TEXT_PATTERN.search(text)
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
        'access_attempts': common_result.get('access_attempts') or [],
    }


def fetch_university_page(url, official_domains, fetcher=None, context=None, page=None):
    """抓取高校官网并补充高校专用地址语义。"""
    if fetcher is None:
        common_result = fetch_official_page(
            url, official_domains,
            extra_address_labels=('校址', '校区', '校园', '办学地点'),
        )
    else:
        common_result = fetcher.fetch(
            url, official_domains,
            extra_address_labels=('校址', '校区', '校园', '办学地点'),
            context=context,
            page=page,
        )
    return build_university_result(common_result)


def build_school_followup_urls(
    page_result, domains, pending, visited, queued_campuses
):
    """把页面返回的相关链接追加为待抓 URL（同域、未访问、未排队）。"""
    for link in page_result.get('related_links') or []:
        url = str(link.get('url') or '').strip()
        campus_names = (
            extract_campus_link_names(link.get('text'))
            if str(link.get('link_type') or '') == 'campus'
            else []
        )
        if (
            url
            and is_url_in_domains(url, domains)
            and _normalized_url_key(url) not in visited
            and (
                not campus_names
                or campus_names[0] not in queued_campuses
            )
        ):
            if campus_names:
                queued_campuses.add(campus_names[0])
            pending.append(url)


def fetch_school_pages(school_item, fetch_page, max_pages=DEFAULT_MAX_PAGES_PER_SCHOOL):
    """按“校区覆盖优先”固定策略抓取一所学校的官网页面。

    先抓 home_url；存在域名确认阶段给出的 candidate_urls 时，
    即使首页已命中地址也会继续补抓候选页（章程/校区/联系方式等
    汇总页），候选页全部抓完且无多校区线索时才停止。页面出现
    ≥2 个校区提示或校区链接时放宽到 ≤6 页，并按校区去重补抓。
    页面访问失败也保留页面对象并计入页数预算。
    """
    home_url = str(school_item.get('home_url') or '').strip()
    official_domains = [
        normalize_domain(domain)
        for domain in school_item.get('official_domains') or []
    ]
    official_domains = sorted({domain for domain in official_domains if domain})
    if not home_url or not is_url_in_domains(home_url, official_domains):
        raise ValueError('school_item 必须包含属于 official_domains 的 home_url')

    pending = [home_url]
    home_key = _normalized_url_key(home_url)
    explicit_keys = []
    for raw_url in school_item.get('candidate_urls') or []:
        url = str(raw_url).strip()
        key = _normalized_url_key(url)
        if (
            url
            and is_url_in_domains(url, official_domains)
            and key != home_key
            and key not in explicit_keys
        ):
            explicit_keys.append(key)
            pending.append(url)
    visited = set()
    queued_campuses = set()
    pages = []
    effective_max_pages = max(
        max_pages,
        min(1 + len(explicit_keys), EXPANDED_MAX_PAGES_PER_SCHOOL),
    )
    campus_expanded = False
    while pending and len(pages) < effective_max_pages:
        url = pending.pop(0)
        url_key = _normalized_url_key(url)
        if url_key in visited:
            continue
        visited.add(url_key)
        page_result = fetch_page(url, official_domains)
        pages.append(page_result)
        if url_key == home_key:
            warning = build_home_identity_warning(
                page_result, str(school_item.get('school_name') or '')
            )
            if warning:
                page_result.setdefault('warnings', []).append(warning)
        if not campus_expanded and has_campus_expansion_signal(page_result):
            campus_expanded = True
            effective_max_pages = max(
                effective_max_pages, EXPANDED_MAX_PAGES_PER_SCHOOL
            )
        remaining_explicit = any(key not in visited for key in explicit_keys)
        has_address = any(
            has_usable_address_candidate(item) for item in pages
        )
        if has_address and not remaining_explicit and not campus_expanded:
            break
        build_school_followup_urls(
            page_result, official_domains, pending, visited, queued_campuses
        )
    if not pages:
        raise ValueError('school_item 未抓取到任何页面')
    return pages


def run_school_batch(school_items, output_dir, max_pages=DEFAULT_MAX_PAGES_PER_SCHOOL):
    """按固定策略抓取一个批次学校，并把完整页面对象原子写入单校结果。"""
    if not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError('max_pages 必须是大于 0 的整数')
    output_dir = Path(output_dir).resolve()
    school_results_dir = output_dir / 'school_results'
    summaries = []
    with OfficialPageFetcher() as fetcher:
        for school_item in school_items:
            school_identifier = str(
                school_item.get('school_identifier') or ''
            ).strip()
            summary = {
                'school_identifier': school_identifier,
                'processing_status': 'completed',
                'page_count': 0,
                'has_address_candidate': False,
                'error': '',
            }
            try:
                if not school_identifier:
                    raise ValueError('school_item 必须包含 school_identifier')
                context = fetcher.new_context()
                try:
                    page = context.new_page()
                    pages = fetch_school_pages(
                        school_item,
                        lambda url, domains: fetch_university_page(
                            url,
                            domains,
                            fetcher=fetcher,
                            context=context,
                            page=page,
                        ),
                        max_pages=max_pages,
                    )
                finally:
                    context.close()
                write_json_payload(
                    school_results_dir / f'{school_identifier}.json',
                    {
                        'school_identifier': school_identifier,
                        'processing_status': 'completed',
                        'pages': pages,
                    },
                )
                summary.update({
                    'page_count': len(pages),
                    'has_address_candidate': any(
                        has_usable_address_candidate(page) for page in pages
                    ),
                })
            except Exception as error:
                summary.update({
                    'processing_status': 'error',
                    'error': str(error),
                })
            summaries.append(summary)
    return summaries


def run_session(input_stream=sys.stdin, output_stream=sys.stdout):
    """复用一个 Chromium，按学校复用浏览器上下文逐页抓取。"""
    with OfficialPageFetcher() as fetcher:
        school_context = None
        school_page = None
        current_school = None
        try:
            for line in input_stream:
                if not line.strip():
                    continue
                request = json.loads(line)
                school_identifier = str(
                    request.get('school_identifier') or ''
                ).strip()
                context = school_context
                page = school_page
                owns_context = False
                if not school_identifier:
                    # 无学校标识的请求保持每页独立上下文。
                    context = fetcher.new_context()
                    page = context.new_page()
                    owns_context = True
                elif school_identifier != current_school:
                    if school_context is not None:
                        school_context.close()
                    school_context = fetcher.new_context()
                    school_page = school_context.new_page()
                    context = school_context
                    page = school_page
                    current_school = school_identifier
                try:
                    result = fetch_university_page(
                        request['url'],
                        request['official_domains'],
                        fetcher=fetcher,
                        context=context,
                        page=page,
                    )
                finally:
                    if owns_context:
                        context.close()
                print(
                    json.dumps(result, ensure_ascii=False),
                    file=output_stream,
                    flush=True,
                )
        finally:
            if school_context is not None:
                school_context.close()


def main():
    """解析参数并启动官网抓取会话。"""
    parser = argparse.ArgumentParser(
        description='抓取高校官网页面并提取地址候选'
    )
    parser.add_argument('--session', action='store_true')
    parser.add_argument('--school-batch', help='批量学校清单 JSON 文件路径')
    parser.add_argument('--output-dir', help='批量模式下写入 school_results 的运行目录')
    parser.add_argument(
        '--max-pages',
        type=int,
        default=DEFAULT_MAX_PAGES_PER_SCHOOL,
        help='每所学校最多抓取页数（默认 3）',
    )
    args = parser.parse_args()
    try:
        if args.school_batch:
            if not args.output_dir:
                parser.error('--school-batch 必须配合 --output-dir 使用')
            batch_payload = read_json_payload(args.school_batch)
            school_items = batch_payload.get('items')
            if not isinstance(school_items, list):
                raise ValueError('批量学校清单 items 必须是数组')
            summaries = run_school_batch(
                school_items,
                args.output_dir,
                max_pages=args.max_pages,
            )
            print(json.dumps({
                'stage': 'university_fetch_batch',
                'items': summaries,
            }, ensure_ascii=False))
            return
        if not args.session:
            parser.error('必须使用 --session 或 --school-batch 启动抓取')
        run_session()
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
