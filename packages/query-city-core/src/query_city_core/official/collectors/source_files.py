"""来源文件批量下载：按清单保存网页或附件并写回审计结果。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ...access import (
    fetch_direct_content,
    is_url_in_domains,
    normalize_domain,
)
from ...host_gate import (
    DEFAULT_HOST_MAX_WORKERS,
    DEFAULT_HOST_MIN_INTERVAL,
    DEFAULT_MAX_WORKERS,
    HostRequestGate,
    extract_url_host,
)
from ...io_utils import read_json_payload, write_json_payload
from .archive_files import extract_zip_archive


SOURCE_DOWNLOAD_STAGE = 'source_download_manifest'


def validate_download_manifest(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """校验来源下载清单并返回待下载项与允许域名。"""
    if manifest.get('stage') != SOURCE_DOWNLOAD_STAGE:
        raise ValueError(f'stage 必须是 {SOURCE_DOWNLOAD_STAGE}')
    manifest_items = manifest.get('items')
    if not isinstance(manifest_items, list) or not manifest_items:
        raise ValueError('items 必须是非空数组')
    for item_index, manifest_item in enumerate(manifest_items, start=1):
        if not isinstance(manifest_item, dict):
            raise ValueError(f'items[{item_index}] 必须是对象')
        file_name = str(manifest_item.get('file') or '').strip()
        source_url = str(manifest_item.get('url') or '').strip()
        if not file_name or not source_url:
            raise ValueError(
                f'items[{item_index}] 必须同时包含非空 file 和 url'
            )
        manifest_item['file'] = file_name
        manifest_item['url'] = source_url
    allowed_domain = normalize_domain(manifest.get('allowed_domain'))
    return manifest_items, allowed_domain


def resolve_output_path(output_dir: Path, file_name: str) -> Path:
    """解析并限制输出文件位于目标目录内。"""
    output_path = (output_dir / file_name).resolve()
    try:
        output_path.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise ValueError(f'输出文件越出目标目录：{file_name}') from exc
    return output_path


def download_source_file(
    output_path: Path,
    manifest_item: dict[str, Any],
    allowed_domain: str = '',
    host_gate: HostRequestGate | None = None,
) -> dict[str, Any]:
    """下载单个来源文件并返回保存结果。"""
    source_url = manifest_item['url']
    host = extract_url_host(source_url)
    if host_gate is not None:
        host_gate.acquire(host)
    try:
        content, final_url, http_status, access_attempts, _ = (
            fetch_direct_content(source_url)
        )
        if allowed_domain and not is_url_in_domains(
            final_url, [allowed_domain]
        ):
            raise ValueError(f'下载结果域名不在允许范围内：{final_url}')
        output_path.write_bytes(content)
    finally:
        if host_gate is not None:
            host_gate.release(host)
    download_result = {
        'file': manifest_item['file'],
        'url': source_url,
        'final_url': final_url,
        'http_status': http_status,
        'size_bytes': output_path.stat().st_size,
        'access_attempts': access_attempts,
    }
    if output_path.suffix.lower() == '.zip':
        extraction = extract_zip_archive(output_path, output_path.parent)
        download_result['extracted_files'] = extraction['extracted_files']
        if extraction['skipped_entries']:
            download_result['skipped_entries'] = extraction['skipped_entries']
    return download_result


def download_source_files(
    manifest_path: Path,
    output_dir: Path,
    max_workers: int = DEFAULT_MAX_WORKERS,
    host_max_workers: int = DEFAULT_HOST_MAX_WORKERS,
    host_min_interval: float = DEFAULT_HOST_MIN_INTERVAL,
) -> tuple[dict[str, Any], int]:
    """按清单下载来源文件并把结果写回清单。"""
    manifest = read_json_payload(manifest_path)
    manifest_items, allowed_domain = validate_download_manifest(manifest)
    host_gate = (
        None
        if host_max_workers <= 0
        else HostRequestGate(host_max_workers, host_min_interval)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_items = [
        (manifest_item, resolve_output_path(output_dir, manifest_item['file']))
        for manifest_item in manifest_items
    ]
    downloaded_items = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
        future_items = {
            executor.submit(
                download_source_file,
                output_path,
                manifest_item,
                allowed_domain,
                host_gate,
            ):
            manifest_item
            for manifest_item, output_path in resolved_items
        }
        for future in as_completed(future_items):
            manifest_item = future_items[future]
            try:
                download_result = future.result()
                manifest_item.update(download_result)
                downloaded_items.append(download_result)
            except Exception as exc:
                error_message = str(exc).strip()
                manifest_item['error'] = error_message
                errors.append({
                    'file': manifest_item['file'],
                    'url': manifest_item['url'],
                    'error': error_message,
                })
    downloaded_items.sort(key=lambda result: result['file'])
    manifest['errors'] = errors
    zip_output_paths = [
        output_path
        for _manifest_item, output_path in resolved_items
        if output_path.suffix.lower() == '.zip'
    ]
    manifest['metrics'] = {
        'item_count': len(manifest_items),
        'downloaded_count': len(downloaded_items),
        'archive_count': sum(
            1 for output_path in zip_output_paths if output_path.is_file()
        ),
        'extracted_file_count': sum(
            len(manifest_item.get('extracted_files') or [])
            for manifest_item in manifest_items
        ),
        'error_count': len(errors),
    }
    write_json_payload(manifest_path, manifest)
    return manifest, 1 if errors else 0
