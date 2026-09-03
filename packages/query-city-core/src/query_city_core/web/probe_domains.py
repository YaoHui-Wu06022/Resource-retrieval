"""探测机构官网主页的可达性、跳转终域与页面身份。

输入为通用域名探测记录列表，不感知学校/医院/政府机关语义：
每条记录包含 place_id、place_name、home_url、official_domains。
探测是站点访问，不消耗各场景的检索预算。
"""

import re
from urllib.parse import urlparse

from ..access import fetch_direct_content
from .fetch_official_page import decode_html_content


def host_of(url):
    """取 URL 的裸主机名。"""
    return (urlparse(str(url or '')).hostname or '').lower().rstrip('.')


def normalize_domain_item(value):
    """把官方域名条目规范成裸主机名。"""
    text = str(value or '').strip().lower().rstrip('.')
    if '://' in text:
        return host_of(text)
    return text


def host_in_domains(host, domains):
    """判断主机名是否属于任一官方域名。"""
    host = str(host or '').lower().rstrip('.')
    return any(
        host == domain or host.endswith('.' + domain)
        for domain in domains
        if domain
    )


def extract_title(html):
    """从 HTML 中提取 <title> 文本。"""
    match = re.search(
        r'<title[^>]*>(.*?)</title>',
        html or '',
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ''
    return re.sub(r'\s+', ' ', match.group(1)).strip()


def title_matches_place_name(title, place_name):
    """标题（压缩空白后）是否包含机构全名或去掉括号的简称。"""
    compact_title = re.sub(r'\s+', '', str(title or ''))
    aliases = []
    name = str(place_name or '').strip()
    if name:
        aliases.append(name)
    core = re.sub(r'[（(][^（）()]*[）)]', '', name).strip()
    if core and core != name:
        aliases.append(core)
    return any(
        alias and re.sub(r'\s+', '', alias) in compact_title
        for alias in aliases
    )


def build_probe_item(item, fetch):
    """探测单个官网主页并构造通用报告条目。"""
    place_id = str(item.get('place_id') or '').strip()
    place_name = str(item.get('place_name') or '').strip()
    home_url = str(item.get('home_url') or '').strip()
    domains = sorted({
        normalize_domain_item(domain)
        for domain in (item.get('official_domains') or [])
    })
    if not place_id:
        raise ValueError('域名探测记录缺少 place_id')
    if not place_name:
        raise ValueError(f'{place_id} 域名探测记录缺少 place_name')
    if not home_url:
        raise ValueError(f'{place_id} 域名探测记录缺少 home_url')
    probe_item = {
        'place_id': place_id,
        'place_name': place_name,
        'home_url': home_url,
        'official_domains': domains,
        'reachable': False,
        'http_status': None,
        'final_url': '',
        'final_domain': '',
        'redirected': False,
        'final_domain_in_whitelist': False,
        'title': '',
        'identity_match': False,
        'error': '',
        'suggestion': '',
    }
    try:
        body, final_url, http_status, _attempts, charset = fetch(home_url)
    except Exception as error:
        probe_item['error'] = str(error)[:300]
        probe_item['suggestion'] = (
            '主页访问失败，需人工复核域名或按失败项处理'
        )
        return probe_item
    final_url = str(final_url or home_url)
    final_host = host_of(final_url)
    home_host = host_of(home_url)
    html = decode_html_content(body or b'', charset)
    title = extract_title(html)
    identity_match = title_matches_place_name(title, place_name)
    probe_item.update({
        'reachable': True,
        'http_status': http_status,
        'final_url': final_url,
        'final_domain': final_host,
        'redirected': bool(final_host) and final_host != home_host,
        'final_domain_in_whitelist': host_in_domains(final_host, domains),
        'title': title[:200],
        'identity_match': identity_match,
    })
    if probe_item['redirected'] and not probe_item['final_domain_in_whitelist']:
        if identity_match:
            probe_item['suggestion'] = (
                f'主页跳转至白名单外的 {final_host} 且页面身份匹配：'
                f'建议将 {final_host} 并入 official_domains，'
                f'并把主页改为 {final_url}'
            )
        else:
            probe_item['suggestion'] = (
                f'主页跳转至白名单外的 {final_host}，'
                '但终页标题不含机构名称，需人工复核后决定'
            )
    elif probe_item['redirected'] and probe_item['final_domain_in_whitelist']:
        probe_item['suggestion'] = (
            f'主页跳转至白名单内的 {final_host}，'
            f'可将主页改为 {final_url} 减少跳转'
        )
    return probe_item


def probe_domain_items(items, fetch=None):
    """逐条探测通用域名记录并返回报告条目。"""
    fetch = fetch or fetch_direct_content
    return [build_probe_item(item, fetch) for item in items]
