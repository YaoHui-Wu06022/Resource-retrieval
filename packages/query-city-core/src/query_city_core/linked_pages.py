"""批量保存名录页链接指向的同构详情页。"""

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .access import fetch_direct_content, normalize_domain
from .host_gate import (
    DEFAULT_HOST_MAX_WORKERS,
    DEFAULT_HOST_MIN_INTERVAL,
    DEFAULT_MAX_WORKERS,
    HostRequestGate,
    extract_url_host,
)
from .io_utils import write_json_payload


LINKED_HTML_PAGES_STAGE = 'linked_html_pages'
WHITESPACE_PATTERN = re.compile(r'\s+')


def normalize_link_text(raw_text: Any) -> str:
    """折叠链接文本或网址中的空白。"""
    return WHITESPACE_PATTERN.sub(
        ' ', str(raw_text or '').replace('\xa0', ' ')
    ).strip()


def collect_linked_html_pages(
    input_path: Path,
    link_selector: str,
    output_dir: Path,
    manifest_path: Path,
    allowed_domain: str = '',
    max_workers: int = DEFAULT_MAX_WORKERS,
    host_max_workers: int = DEFAULT_HOST_MAX_WORKERS,
    host_min_interval: float = DEFAULT_HOST_MIN_INTERVAL,
) -> tuple[dict[str, Any], int]:
    """下载名录中链接指向的同构 HTML 详情页。"""
    soup = BeautifulSoup(input_path.read_bytes(), 'lxml')
    base_element = soup.find('base')
    base_url = (
        normalize_link_text(base_element.get('href'))
        if base_element else ''
    )
    allowed_domain = normalize_domain(allowed_domain)
    page_links = []
    seen_urls = set()
    for link in soup.select(link_selector):
        page_url = urljoin(
            base_url, normalize_link_text(link.get('href'))
        )
        parsed_url = urlparse(page_url)
        if (
            parsed_url.scheme not in {'http', 'https'}
            or not parsed_url.netloc
            or (allowed_domain and parsed_url.hostname != allowed_domain)
            or page_url in seen_urls
        ):
            continue
        seen_urls.add(page_url)
        page_links.append({
            'url': page_url,
            'title': normalize_link_text(
                link.get('title') or link.get_text(' ', strip=True)
            ),
        })
    if not page_links:
        raise ValueError('链接选择器没有找到合格的详情页')

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir = manifest_path.parent.resolve()
    host_gate = (
        None
        if host_max_workers <= 0
        else HostRequestGate(host_max_workers, host_min_interval)
    )

    def download_page(
        page_index: int,
        page_link: dict[str, str],
        page_host_gate: HostRequestGate | None,
    ) -> dict[str, Any]:
        page_url = page_link['url']
        host = extract_url_host(page_url)
        path_name = (
            Path(urlparse(page_url).path).name or f'page_{page_index}.html'
        )
        if not path_name.lower().endswith(('.htm', '.html')):
            path_name += '.html'
        output_path = output_dir / path_name
        if page_host_gate is not None:
            page_host_gate.acquire(host)
        started = time.monotonic()
        try:
            content, final_url, http_status, access_attempts, _ = (
                fetch_direct_content(page_url)
            )
            output_path.write_bytes(content)
        finally:
            if page_host_gate is not None:
                page_host_gate.release(host)
        for attempt in access_attempts:
            attempt['elapsed_ms'] = round(
                (time.monotonic() - started) * 1000
            )
        fetch_method = access_attempts[-1]['method']
        return {
            'title': page_link['title'],
            'url': page_url,
            'final_url': final_url,
            'http_status': http_status,
            'fetch_method': fetch_method,
            'local_file': Path(
                os.path.relpath(output_path, manifest_dir)
            ).as_posix(),
            'size_bytes': output_path.stat().st_size,
            'access_attempts': access_attempts,
        }

    downloaded_pages = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
        future_pages = {
            executor.submit(
                download_page, index, page_link, host_gate
            ): page_link
            for index, page_link in enumerate(page_links, start=1)
        }
        for future in as_completed(future_pages):
            page_link = future_pages[future]
            try:
                downloaded_pages.append(future.result())
            except Exception as exc:
                errors.append({
                    'title': page_link['title'],
                    'url': page_link['url'],
                    'error': str(exc).strip(),
                })
    downloaded_pages.sort(key=lambda page: page['url'])
    payload = {
        'stage': LINKED_HTML_PAGES_STAGE,
        'index_file': input_path.name,
        'link_selector': link_selector,
        'items': downloaded_pages,
        'errors': errors,
        'metrics': {
            'link_count': len(page_links),
            'downloaded_count': len(downloaded_pages),
            'error_count': len(errors),
        },
    }
    write_json_payload(manifest_path, payload)
    return payload, 1 if errors else 0
