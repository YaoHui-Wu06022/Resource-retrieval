"""调用 MinerU v4 API 把无文本扫描 PDF 解析为 vision_source_result。"""

import base64
import hashlib
import hmac
import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ...env_utils import read_env_value
from . import normalize_text


OPENXLAB_AUTH_BASE = (
    'https://openapi.openxlab.org.cn/api/v1/sso-be/api/v1/open/'
)
MINERU_API_BASE = 'https://mineru.net/api/v4'
CHINA_TIMEZONE = timezone(timedelta(hours=8))
EXPIRATION_FORMAT = '%Y-%m-%d %H:%M:%S'
DEFAULT_POLL_INTERVAL_SECONDS = 8
DEFAULT_TASK_TIMEOUT_SECONDS = 1800
DEFAULT_HTTP_TIMEOUT_SECONDS = 60
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 300

_PUNCTUATION_MAP = str.maketrans({
    ',': '，',
    ';': '；',
    ':': '：',
    '(': '（',
    ')': '）',
})
_HMAC_DIGEST_NAMES = {
    'HmacSHA1': 'sha1',
    'HmacSHA256': 'sha256',
    'HmacSHA512': 'sha512',
}
_SCHOOL_NAME_MARKER = re.compile(
    r'学校|小学|中学|幼儿园|学院|大学|校区|分校|分园|园区|教学点'
)
_NUMERIC_LEAD = re.compile(r'^\d')


class MineruError(RuntimeError):
    """MinerU API 调用或结果转换失败。"""


class MineruConfigError(MineruError):
    """缺少 MinerU 凭据配置。"""


@dataclass
class _OpenXlabToken:
    jwt: str
    refresh_token: str
    expires_at_millis: int
    refresh_expires_at_millis: int


def _parse_expiration(value: Any) -> int:
    if not value:
        return 0
    try:
        moment = datetime.strptime(str(value), EXPIRATION_FORMAT)
        moment = moment.replace(tzinfo=CHINA_TIMEZONE)
        return int(moment.timestamp() * 1000)
    except ValueError:
        return 0


def sign_openxlab_nonce(
    secret_key: str,
    nonce: str,
    algorithm: str,
) -> str:
    """按 OpenXLab 约定用 HMAC 对 nonce 签名并 Base64 编码。"""
    digest_name = _HMAC_DIGEST_NAMES.get(
        algorithm, algorithm.lower().replace('hmac', '')
    )
    if digest_name not in hashlib.algorithms_available:
        raise MineruError(f'不支持的签名算法：{algorithm}')
    digest = hmac.new(
        secret_key.encode('utf-8'),
        nonce.encode('utf-8'),
        digest_name,
    ).digest()
    return base64.b64encode(digest).decode('ascii')


def _request_json(
    url: str,
    method: str = 'GET',
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    request_headers = dict(headers or {})
    data = None
    if payload is not None:
        request_headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        body = error.read().decode('utf-8', errors='replace')
        raise MineruError(
            f'MinerU HTTP {error.code}：{normalize_text(body)[:300]}'
        ) from error
    except urllib.error.URLError as error:
        raise MineruError(f'MinerU 网络错误：{error.reason}') from error
    try:
        parsed = json.loads(body)
    except ValueError as error:
        raise MineruError(f'MinerU 返回不是 JSON：{body[:200]}') from error
    if not isinstance(parsed, dict):
        raise MineruError(f'MinerU 返回结构异常：{body[:200]}')
    return parsed


def _extract_openxlab_data(root: dict[str, Any]) -> dict[str, Any]:
    """校验 OpenXLab 返回并取出业务 data。"""
    if root.get('msgCode') != '10000':
        raise MineruError(
            f'OpenXLab 鉴权失败：{normalize_text(root.get("msg"))}'
        )
    wrapper = root.get('data')
    if not isinstance(wrapper, dict):
        raise MineruError('OpenXLab 返回缺少 data')
    if wrapper.get('msgCode') not in (None, '10000'):
        raise MineruError(
            f'OpenXLab 鉴权失败：{normalize_text(wrapper.get("msg"))}'
        )
    inner = wrapper.get('data')
    if not isinstance(inner, dict):
        raise MineruError('OpenXLab 返回缺少业务 data')
    return inner


class MineruClient:
    """OpenXLab AK/SK → JWT + MinerU v4 页面解析客户端。"""

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        *,
        auth_base: str = OPENXLAB_AUTH_BASE,
        api_base: str = MINERU_API_BASE,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        task_timeout_seconds: int = DEFAULT_TASK_TIMEOUT_SECONDS,
    ) -> None:
        if not access_key or not secret_key:
            raise MineruConfigError(
                '缺少 MINERU_ACCESS_KEY 或 MINERU_SECRET_KEY 配置'
            )
        self.access_key = access_key
        self.secret_key = secret_key
        self.auth_base = auth_base.rstrip('/') + '/'
        self.api_base = api_base.rstrip('/')
        self.poll_interval_seconds = poll_interval_seconds
        self.task_timeout_seconds = task_timeout_seconds
        self._token: _OpenXlabToken | None = None

    @classmethod
    def from_env(cls) -> 'MineruClient':
        access_key = read_env_value('MINERU_ACCESS_KEY')
        secret_key = read_env_value('MINERU_SECRET_KEY')
        if not access_key or not secret_key:
            raise MineruConfigError(
                '缺少 MINERU_ACCESS_KEY / MINERU_SECRET_KEY，'
                '请在 .env 或环境变量中配置'
            )
        return cls(access_key, secret_key)

    def _auth_request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        root = _request_json(self.auth_base + path, method='POST', payload=payload)
        return _extract_openxlab_data(root)

    def jwt(self) -> str:
        now_millis = int(time.time() * 1000)
        token = self._token
        if token is not None:
            if (
                token.expires_at_millis - 30_000 > now_millis
            ):
                return token.jwt
            if (
                token.refresh_token
                and token.refresh_expires_at_millis - 30_000 > now_millis
            ):
                try:
                    inner = self._auth_request(
                        'refreshJwt',
                        {
                            'ak': self.access_key,
                            'refresh_token': token.refresh_token,
                        },
                    )
                    self._token = self._token_from_inner(inner)
                    return self._token.jwt
                except MineruError:
                    self._token = None
        auth = self._auth_request('auth', {'ak': self.access_key})
        nonce = normalize_text(auth.get('nonce'))
        algorithm = normalize_text(auth.get('algorithm')) or 'HmacSHA256'
        if not nonce:
            raise MineruError('OpenXLab auth 未返回 nonce')
        signature = sign_openxlab_nonce(self.secret_key, nonce, algorithm)
        inner = self._auth_request(
            'getJwt', {'ak': self.access_key, 'd': signature}
        )
        self._token = self._token_from_inner(inner)
        return self._token.jwt

    @staticmethod
    def _token_from_inner(inner: dict[str, Any]) -> _OpenXlabToken:
        jwt = normalize_text(inner.get('jwt'))
        if not jwt:
            raise MineruError('OpenXLab getJwt 未返回 jwt')
        return _OpenXlabToken(
            jwt=jwt,
            refresh_token=normalize_text(inner.get('refresh_token')),
            expires_at_millis=_parse_expiration(inner.get('expiration')),
            refresh_expires_at_millis=_parse_expiration(
                inner.get('refresh_expiration')
            ),
        )

    def _authorized_headers(self) -> dict[str, str]:
        return {'Authorization': 'Bearer ' + self.jwt()}

    @staticmethod
    def _page_entries(pages: Iterable[int]) -> list[dict[str, Any]]:
        return [
            {
                'data_id': f'p{page:04d}',
                'page_ranges': str(page),
                'is_ocr': True,
            }
            for page in sorted(pages)
        ]

    def submit_url_batch(
        self,
        url: str,
        pages: Iterable[int],
    ) -> str:
        entries = []
        for entry in self._page_entries(pages):
            file_entry = {
                'url': url,
                'data_id': entry['data_id'],
                'page_ranges': entry['page_ranges'],
                'is_ocr': entry['is_ocr'],
            }
            entries.append(file_entry)
        root = _request_json(
            self.api_base + '/extract/task/batch',
            method='POST',
            payload={
                'files': entries,
                'model_version': 'vlm',
                'enable_table': True,
                'enable_formula': False,
                'language': 'ch',
            },
            headers=self._authorized_headers(),
        )
        if root.get('code') != 0:
            raise MineruError(
                f'提交 MinerU URL 任务失败：{normalize_text(root.get("msg"))}'
            )
        batch_id = (root.get('data') or {}).get('batch_id')
        if not batch_id:
            raise MineruError('MinerU 未返回 batch_id')
        return str(batch_id)

    def submit_url_task(
        self,
        url: str,
        *,
        data_id: str = 'inspect',
        page_ranges: str = '',
    ) -> str:
        payload: dict[str, Any] = {
            'url': url,
            'model_version': 'vlm',
            'enable_table': True,
            'enable_formula': False,
            'language': 'ch',
            'is_ocr': True,
            'data_id': data_id,
        }
        if page_ranges:
            payload['page_ranges'] = page_ranges
        root = _request_json(
            self.api_base + '/extract/task',
            method='POST',
            payload=payload,
            headers=self._authorized_headers(),
        )
        if root.get('code') != 0:
            raise MineruError(
                f'提交 MinerU URL 任务失败：{normalize_text(root.get("msg"))}'
            )
        task_id = (root.get('data') or {}).get('task_id')
        if not task_id:
            raise MineruError('MinerU 未返回 task_id')
        return str(task_id)

    def wait_task(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.task_timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MineruError(f'MinerU 任务超时：task {task_id}')
            root = _request_json(
                self.api_base + '/extract/task/' + task_id,
                headers=self._authorized_headers(),
                timeout=min(DEFAULT_HTTP_TIMEOUT_SECONDS, max(30, remaining)),
            )
            data = root.get('data') or {}
            state = data.get('state')
            if state == 'failed':
                raise MineruError(
                    'MinerU 解析失败：'
                    + normalize_text(data.get('err_msg'))
                )
            if state == 'done':
                return data
            time.sleep(self.poll_interval_seconds)

    def submit_upload_batch(
        self,
        pdf_path: Path,
        pages: Iterable[int],
    ) -> tuple[str, list[str]]:
        files = []
        for page in sorted(pages):
            files.append({
                'name': pdf_path.name,
                'data_id': f'p{page:04d}',
                'page_ranges': str(page),
                'is_ocr': True,
            })
        root = _request_json(
            self.api_base + '/file-urls/batch',
            method='POST',
            payload={
                'files': files,
                'model_version': 'vlm',
                'enable_table': True,
                'enable_formula': False,
                'language': 'ch',
            },
            headers=self._authorized_headers(),
        )
        if root.get('code') != 0:
            raise MineruError(
                f'申请 MinerU 上传地址失败：{normalize_text(root.get("msg"))}'
            )
        data = root.get('data') or {}
        batch_id = data.get('batch_id')
        upload_urls = data.get('file_urls')
        if not batch_id or not isinstance(upload_urls, list):
            raise MineruError('MinerU 未返回 batch_id 或上传地址')
        if len(upload_urls) != len(files):
            raise MineruError('MinerU 上传地址数量与文件数不一致')
        payload_bytes = pdf_path.read_bytes()
        for upload_url in upload_urls:
            request = urllib.request.Request(
                str(upload_url),
                data=payload_bytes,
                headers={'Content-Type': 'application/pdf'},
                method='PUT',
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS
                ) as response:
                    if response.status >= 400:
                        raise MineruError(
                            f'上传 PDF 失败：HTTP {response.status}'
                        )
            except urllib.error.HTTPError as error:
                raise MineruError(
                    f'上传 PDF 失败：HTTP {error.code}'
                ) from error
            except urllib.error.URLError as error:
                raise MineruError(
                    f'上传 PDF 网络错误：{error.reason}'
                ) from error
        return str(batch_id), [str(item) for item in upload_urls]

    def wait_batch(
        self,
        batch_id: str,
        pages: Iterable[int],
    ) -> dict[str, dict[str, Any]]:
        wanted = {f'p{page:04d}' for page in pages}
        deadline = time.monotonic() + self.task_timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MineruError(f'MinerU 任务超时：batch {batch_id}')
            root = _request_json(
                self.api_base + '/extract-results/batch/' + batch_id,
                headers=self._authorized_headers(),
                timeout=min(DEFAULT_HTTP_TIMEOUT_SECONDS, max(30, remaining)),
            )
            results = (root.get('data') or {}).get('extract_result') or []
            by_data_id: dict[str, dict[str, Any]] = {}
            for entry in results:
                if entry.get('data_id'):
                    by_data_id[str(entry['data_id'])] = entry
            missing = wanted - set(by_data_id)
            if not missing:
                states = {entry.get('state') for entry in by_data_id.values()}
                if states <= {'done', 'failed'}:
                    failed = [
                        (key, entry.get('err_msg'))
                        for key, entry in by_data_id.items()
                        if entry.get('state') == 'failed'
                    ]
                    if failed:
                        detail = '；'.join(
                            f'{key}: {normalize_text(message)}'
                            for key, message in failed
                        )
                        raise MineruError(f'MinerU 解析失败：{detail}')
                    return by_data_id
            time.sleep(self.poll_interval_seconds)

    @staticmethod
    def download_result_zip(entry: dict[str, Any]) -> bytes:
        zip_url = entry.get('full_zip_url')
        if not zip_url:
            raise MineruError('MinerU 结果缺少 full_zip_url')
        try:
            with urllib.request.urlopen(
                zip_url, timeout=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS
            ) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise MineruError(
                f'下载 MinerU 结果失败：HTTP {error.code}'
            ) from error
        except urllib.error.URLError as error:
            raise MineruError(
                f'下载 MinerU 结果网络错误：{error.reason}'
            ) from error

    @staticmethod
    def rows_from_result_zip(zip_bytes: bytes) -> list[list[str]]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as error:
            raise MineruError('MinerU 结果不是有效 zip') from error
        content_names = [
            name
            for name in archive.namelist()
            if name.endswith('content_list.json')
        ]
        if not content_names:
            raise MineruError('MinerU 结果 zip 缺少 content_list.json')
        content = json.loads(
            archive.read(content_names[0]).decode('utf-8')
        )
        return content_list_table_rows(content)

    @staticmethod
    def _is_url_fetch_failure(message: str) -> bool:
        lowered = message.lower()
        return any(
            token in lowered
            for token in ('-60008', 'timeout', 'url', 'read failed')
        )

    def parse_pdf_pages(
        self,
        pages: Iterable[int],
        *,
        url: str = '',
        pdf_path: Path | None = None,
        fallback_to_upload: bool = True,
    ) -> dict[int, list[list[str]]]:
        page_list = sorted(set(int(page) for page in pages))
        if not page_list:
            return {}
        page_by_data_id = {f'p{page:04d}': page for page in page_list}
        rows_by_page: dict[int, list[list[str]]] = {}
        batch_id = ''
        used_upload = False
        if url:
            try:
                batch_id = self.submit_url_batch(url, page_list)
            except MineruError:
                if not fallback_to_upload or not pdf_path:
                    raise
                used_upload = True
        if not url or used_upload:
            if pdf_path is None:
                raise MineruError('没有可用的 URL 或本地 PDF 路径')
            batch_id, _ = self.submit_upload_batch(pdf_path, page_list)
        try:
            results = self.wait_batch(batch_id, page_list)
        except MineruError as error:
            if (
                url
                and fallback_to_upload
                and pdf_path is not None
                and not used_upload
                and self._is_url_fetch_failure(str(error))
            ):
                batch_id, _ = self.submit_upload_batch(pdf_path, page_list)
                results = self.wait_batch(batch_id, page_list)
            else:
                raise
        for data_id, entry in results.items():
            page = page_by_data_id.get(data_id)
            if page is None:
                continue
            zip_bytes = self.download_result_zip(entry)
            rows = self.rows_from_result_zip(zip_bytes)
            rows_by_page[page] = rows
        return rows_by_page


def _table_body_to_rows(table_body: str) -> list[list[str]]:
    if not table_body:
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError as error:
        raise MineruError('解析 MinerU 表格需要 beautifulsoup4') from error
    soup = BeautifulSoup(table_body, 'lxml')
    rows: list[list[str]] = []
    for table_row in soup.find_all('tr'):
        cells = []
        for cell in table_row.find_all(['td', 'th']):
            raw_text = cell.get_text(' ', strip=True)
            cells.append(normalize_text(raw_text.translate(_PUNCTUATION_MAP)))
        if cells:
            rows.append(cells)
    return rows


def content_list_table_rows(content: list[dict[str, Any]]) -> list[list[str]]:
    """把 content_list.json 中的表块拼成二维数组，跨表只去重复表头。"""
    all_rows: list[list[str]] = []
    header: tuple[str, ...] | None = None
    header_width = 0
    for block in content or []:
        if not isinstance(block, dict) or block.get('type') != 'table':
            continue
        rows = _table_body_to_rows(
            normalize_text(block.get('table_body') or '')
        )
        if not rows:
            continue
        if header is None:
            header = tuple(rows[0])
            all_rows.append(rows[0])
            header_width = len(rows[0])
            rows = rows[1:]
        elif tuple(rows[0]) == header:
            rows = rows[1:]
        all_rows.extend(_align_table_rows(rows, header_width))
    return all_rows


def _align_table_rows(
    rows: list[list[str]],
    header_width: int,
) -> list[list[str]]:
    """把短行补齐到表头宽度，缺序号列时前插空单元格。"""
    aligned: list[list[str]] = []
    for row in rows:
        current = list(row)
        if len(current) < header_width:
            first = normalize_text(current[0]) if current else ''
            if (
                len(current) >= 2
                and
                len(current) <= header_width - 2
                and first
                and not _NUMERIC_LEAD.match(first)
                and (
                    first in ('合计', '总计', '小计')
                    or _SCHOOL_NAME_MARKER.search(first)
                )
                and not re.match(
                    r'^(?:对口|招生地段|划片|范围|备注|说明|咨询|序号)',
                    first,
                )
            ):
                current.insert(0, '')
            current.extend([''] * (header_width - len(current)))
        aligned.append(current[:header_width])
    return aligned


def build_vision_payload(
    source_file_stem: str,
    rows_by_page: dict[int, list[list[str]]],
) -> dict[str, Any]:
    """按现有 vision_source_result 结构组装多页识别结果。"""
    pages = []
    for page in sorted(rows_by_page):
        rows = rows_by_page[page]
        if rows:
            pages.append({'page': page, 'rows': rows})
    return {
        'stage': 'vision_source_result',
        'source_file': source_file_stem,
        'pages': pages,
    }


def inspect_pdf_pages(
    url: str,
    *,
    pages: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """提交一次整档 URL 任务并输出逐页表格摘要。"""
    client = MineruClient.from_env()
    page_ranges = ''
    if pages is not None:
        page_ranges = ','.join(str(page) for page in sorted(pages))
    task_id = client.submit_url_task(url, page_ranges=page_ranges)
    data = client.wait_task(task_id)
    zip_bytes = client.download_result_zip(data)
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as error:
        raise MineruError('MinerU 结果不是有效 zip') from error
    content_name = next(
        (
            name
            for name in archive.namelist()
            if name.endswith('content_list.json')
        ),
        None,
    )
    if content_name is None:
        raise MineruError('MinerU 结果 zip 缺少 content_list.json')
    content = json.loads(archive.read(content_name).decode('utf-8'))
    per_page: dict[int, dict[str, Any]] = {}
    for block in content or []:
        if not isinstance(block, dict):
            continue
        page_index = block.get('page_idx')
        if not isinstance(page_index, int):
            continue
        summary = per_page.setdefault(
            page_index + 1, {'page': page_index + 1, 'has_table': False}
        )
        if block.get('type') == 'table':
            summary['has_table'] = True
            caption = block.get('table_caption') or []
            if isinstance(caption, list):
                caption = [normalize_text(item) for item in caption if item]
            if caption and not summary.get('caption'):
                summary['caption'] = '；'.join(caption)
    return [
        per_page[page]
        for page in sorted(per_page)
    ]
