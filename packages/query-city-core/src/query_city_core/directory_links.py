"""从栏目页收集候选链接：抓取目录页并按模式与域名过滤。"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .access import fetch_direct_content, is_url_in_domains, normalize_domain
from .host_gate import (
    DEFAULT_HOST_MAX_WORKERS,
    DEFAULT_HOST_MIN_INTERVAL,
    DEFAULT_MAX_WORKERS,
    HostRequestGate,
    extract_url_host,
)
from .io_utils import read_json_payload, write_json_payload


DIRECTORY_LINK_MANIFEST_STAGE = 'directory_link_manifest'
DIRECTORY_LINKS_STAGE = 'directory_links'
WHITESPACE_PATTERN = re.compile(r'\s+')


def normalize_page_text(raw_text: Any) -> str:
    """折叠文本空白并去除首尾空格。"""
    return WHITESPACE_PATTERN.sub(
        ' ', str(raw_text or '').replace('\xa0', ' ')
    ).strip()


def validate_directory_manifest(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], re.Pattern | None, str]:
    """校验目录页清单并返回待抓取项、链接模式和允许域名。"""
    if manifest.get('stage') != DIRECTORY_LINK_MANIFEST_STAGE:
        raise ValueError(f'stage 必须是 {DIRECTORY_LINK_MANIFEST_STAGE}')
    manifest_items = manifest.get('items')
    if not isinstance(manifest_items, list) or not manifest_items:
        raise ValueError('items 必须是非空数组')
    for item_index, manifest_item in enumerate(manifest_items, start=1):
        if not isinstance(manifest_item, dict):
            raise ValueError(f'items[{item_index}] 必须是对象')
        page_url = normalize_page_text(manifest_item.get('url'))
        if not page_url:
            raise ValueError(f'items[{item_index}] 必须包含非空 url')
        manifest_item['url'] = page_url
    allowed_domain = normalize_domain(manifest.get('allowed_domain'))
    link_pattern_text = normalize_page_text(manifest.get('link_pattern'))
    link_pattern = (
        re.compile(link_pattern_text) if link_pattern_text else None
    )
    return manifest_items, link_pattern, allowed_domain


def collect_page_links(
    manifest_item: dict[str, Any],
    link_pattern: re.Pattern | None,
    allowed_domain: str,
    host_gate: HostRequestGate | None = None,
) -> dict[str, Any]:
    """抓取一个栏目页并列出符合配置的候选链接。"""
    page_url = manifest_item['url']
    host = extract_url_host(page_url)
    if host_gate is not None:
        host_gate.acquire(host)
    try:
        content, final_url, http_status, access_attempts, _ = (
            fetch_direct_content(page_url)
        )
    finally:
        if host_gate is not None:
            host_gate.release(host)
    soup = BeautifulSoup(content, 'lxml')
    base_element = soup.find('base')
    base_url = (
        normalize_page_text(base_element.get('href'))
        if base_element else ''
    )
    page_links = []
    seen_urls = set()
    for anchor in soup.find_all('a', href=True):
        absolute_url = urljoin(
            base_url or final_url, normalize_page_text(anchor.get('href'))
        )
        if (
            not absolute_url
            or absolute_url in seen_urls
            or (allowed_domain and not is_url_in_domains(
                absolute_url, [allowed_domain]
            ))
            or (
                link_pattern is not None
                and link_pattern.search(absolute_url) is None
            )
        ):
            continue
        seen_urls.add(absolute_url)
        page_links.append({
            'title': normalize_page_text(anchor.get_text(' ', strip=True)),
            'url': absolute_url,
        })
    return {
        'url': page_url,
        'note': normalize_page_text(manifest_item.get('note')),
        'final_url': final_url,
        'http_status': http_status,
        'page_title': normalize_page_text(
            soup.title.get_text(' ', strip=True) if soup.title else ''
        ),
        'links': page_links,
        'access_attempts': access_attempts,
    }


def collect_directory_links(
    input_path: Path,
    output_path: Path,
    max_workers: int = DEFAULT_MAX_WORKERS,
    host_max_workers: int = DEFAULT_HOST_MAX_WORKERS,
    host_min_interval: float = DEFAULT_HOST_MIN_INTERVAL,
) -> tuple[dict[str, Any], int]:
    """抓取目录页链接清单并把结果写入输出文件。"""
    manifest = read_json_payload(input_path)
    manifest_items, link_pattern, allowed_domain = validate_directory_manifest(
        manifest
    )
    host_gate = (
        None
        if host_max_workers <= 0
        else HostRequestGate(host_max_workers, host_min_interval)
    )
    page_items = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
        future_items = {
            executor.submit(
                collect_page_links,
                manifest_item,
                link_pattern,
                allowed_domain,
                host_gate,
            ): manifest_item
            for manifest_item in manifest_items
        }
        for future in as_completed(future_items):
            manifest_item = future_items[future]
            try:
                page_items.append(future.result())
            except Exception as exc:
                error_message = str(exc).strip()
                errors.append({
                    'url': manifest_item['url'],
                    'note': normalize_page_text(manifest_item.get('note')),
                    'error': error_message,
                })
    original_indexes = {
        manifest_item['url']: index
        for index, manifest_item in enumerate(manifest_items)
    }
    page_items.sort(
        key=lambda page_item: original_indexes.get(page_item['url'], 0)
    )
    output_payload = {
        'stage': DIRECTORY_LINKS_STAGE,
        'items': page_items,
        'errors': errors,
        'metrics': {
            'item_count': len(manifest_items),
            'page_count': len(page_items),
            'link_count': sum(
                len(page_item['links']) for page_item in page_items
            ),
            'error_count': len(errors),
        },
    }
    write_json_payload(output_path, output_payload)
    return output_payload, 1 if errors else 0
