"""公共直连访问兜底能力。"""

import shutil
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36')
BROWSER_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Upgrade-Insecure-Requests': '1',
}
CHARSET_PATTERN = re.compile(
    r'charset\s*=\s*["\']?\s*([\w-]+)', re.IGNORECASE
)


def normalize_domain(value):
    """规范化官方域名文本。"""
    value = str(value or '').strip().lower().rstrip('.')
    return (
        (urlparse(value).hostname or '').lower().rstrip('.')
        if '://' in value
        else value
    )


def is_url_in_domains(url, domains):
    """判断网址是否属于任一允许域名。"""
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {'http', 'https'} or not parsed_url.hostname:
        return False
    host = parsed_url.hostname.lower().rstrip('.')
    return any(
        host == domain or host.endswith('.' + domain)
        for domain in domains
    )


def _charset_from_content_type(value):
    """从 Content-Type 文本中提取字符集名称。"""
    match = CHARSET_PATTERN.search(str(value or ''))
    return match.group(1) if match else ''


def _record_attempt(attempts, method, url, final_url, http_status, success, error, started):
    """记录一次访问尝试的审计信息。"""
    attempts.append({
        'method': method,
        'url': url,
        'final_url': final_url,
        'http_status': http_status,
        'success': success,
        'error': error,
        'elapsed_ms': round((time.monotonic() - started) * 1000),
    })


def fetch_direct_content(url, timeout=30, preferred_method=None):
    """按首选顺序用 urllib/curl 获取内容并返回内容、状态和访问审计。"""
    if preferred_method not in {None, 'urllib', 'curl'}:
        raise ValueError('preferred_method 必须为 urllib、curl 或 None')
    attempts = []

    def fetch_urllib():
        started = time.monotonic()
        try:
            request = Request(
                url, headers={'User-Agent': USER_AGENT, **BROWSER_HEADERS}
            )
            with urlopen(request, timeout=timeout) as response:
                content = response.read()
                final_url = response.geturl()
                charset = response.headers.get_content_charset() or ''
                _record_attempt(
                    attempts, 'urllib', url, final_url, response.status,
                    True, '', started,
                )
                return content, final_url, response.status, attempts, charset
        except HTTPError as error:
            _record_attempt(
                attempts, 'urllib', url, error.geturl() or '', error.code,
                False, str(error), started,
            )
        except Exception as error:
            _record_attempt(
                attempts, 'urllib', url, '', None, False, str(error), started,
            )
        return None

    def fetch_curl():
        started = time.monotonic()
        curl = shutil.which('curl.exe') or shutil.which('curl')
        if not curl:
            _record_attempt(
                attempts, 'curl', url, '', None, False,
                'curl unavailable', started,
            )
            return None
        completed = subprocess.run(
            [curl, '--silent', '--show-error', '--location',
             '--fail-with-body', '--compressed', '--http1.1',
             '--max-time', str(timeout), '--user-agent', USER_AGENT,
             '--header', f"Accept: {BROWSER_HEADERS['Accept']}",
             '--header', f"Accept-Language: {BROWSER_HEADERS['Accept-Language']}",
             '--header', 'Cache-Control: no-cache',
             '--header', 'Pragma: no-cache',
             '--header', 'Upgrade-Insecure-Requests: 1',
             '--write-out', '\n%{http_code}\t%{url_effective}\t%{content_type}',
             url],
            capture_output=True, check=False,
        )
        body, separator, metadata = completed.stdout.rpartition(b'\n')
        status_text, _, rest = metadata.partition(b'\t')
        final_url_bytes, _, content_type_bytes = rest.partition(b'\t')
        try:
            http_status = int(status_text or 0) or None
        except ValueError:
            http_status = None
        final_url = final_url_bytes.decode('utf-8', errors='replace')
        charset = _charset_from_content_type(
            content_type_bytes.decode('ascii', errors='ignore')
        )
        if completed.returncode:
            _record_attempt(
                attempts, 'curl', url, final_url, http_status, False,
                f'curl exit {completed.returncode}', started,
            )
            return None
        _record_attempt(
            attempts, 'curl', url, final_url or url, http_status or 200,
            True, '', started,
        )
        return body, final_url or url, http_status or 200, attempts, charset

    methods = ('curl', 'urllib') if preferred_method == 'curl' else ('urllib', 'curl')
    fetchers = {'urllib': fetch_urllib, 'curl': fetch_curl}
    for method in methods:
        result = fetchers[method]()
        if result is not None:
            return result
    raise RuntimeError('HTTP 直连失败：urllib 和 curl 均失败')
