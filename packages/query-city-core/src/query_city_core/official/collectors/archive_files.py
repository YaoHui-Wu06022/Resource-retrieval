"""zip 附件安全解压：仅提取可读来源并按相对路径登记。"""

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path


MAX_ZIP_ENTRIES = 500
MAX_ZIP_FILE_BYTES = 256 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 1024 * 1024 * 1024


def _decode_zip_member_name(member):
    """修复非 UTF-8 中文 zip 条目名（GBK）产生的乱码。"""
    if member.flag_bits & 0x800:
        return member.filename
    try:
        raw_bytes = member.filename.encode('cp437')
    except UnicodeEncodeError:
        return member.filename
    try:
        return raw_bytes.decode('gbk')
    except UnicodeDecodeError:
        return member.filename


def _normalize_archive_path(raw_name):
    """规整 zip 成员名为安全的相对路径，非法时抛错。"""
    name = str(raw_name).replace('\\', '/')
    if (
        not name
        or name.startswith('/')
        or re.match(r'^[A-Za-z]:', name)
        or any(part == '..' for part in name.split('/'))
    ):
        raise ValueError(f'zip 成员路径非法：{raw_name}')
    parts = [part for part in name.split('/') if part not in ('', '.')]
    return '/'.join(parts)


def _is_macos_junk(clean_name):
    """判断是否属于 macOS 元数据或系统垃圾文件。"""
    parts = clean_name.split('/')
    return parts[0] == '__MACOSX' or parts[-1] == '.DS_Store'


def extract_zip_archive(archive_path, output_dir):
    """安全解压 zip 并返回输出目录内的可读来源文件。"""
    archive_path = Path(archive_path).resolve()
    output_dir = Path(output_dir).resolve()
    if archive_path.suffix.lower() != '.zip':
        raise ValueError(f'不是 zip 压缩包：{archive_path.name}')
    if not archive_path.is_file():
        raise FileNotFoundError(f'zip 压缩包不存在：{archive_path.name}')
    if not zipfile.is_zipfile(archive_path):
        raise ValueError(f'不是合法 zip 压缩包：{archive_path.name}')
    from ..readers import FORMAT_BY_SUFFIX

    readable_suffixes = frozenset(FORMAT_BY_SUFFIX)
    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix='.zip-extract-', dir=output_dir))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ZIP_ENTRIES:
                raise ValueError(f'zip 条目超过上限：{len(members)}')
            candidates = []
            skipped_entries = []
            seen_targets = set()
            declared_total_size = 0
            for member in members:
                entry_name = _decode_zip_member_name(member) or ''
                if entry_name.endswith(('/', '\\')):
                    continue
                clean_name = _normalize_archive_path(entry_name)
                if not clean_name or _is_macos_junk(clean_name):
                    continue
                if Path(clean_name).suffix.lower() not in readable_suffixes:
                    skipped_entries.append(clean_name)
                    continue
                if member.flag_bits & 0x1:
                    raise ValueError(f'zip 含加密成员：{clean_name}')
                if member.file_size > MAX_ZIP_FILE_BYTES:
                    raise ValueError(
                        f'zip 成员超过单文件上限：{clean_name}'
                    )
                declared_total_size += member.file_size
                if declared_total_size > MAX_ZIP_TOTAL_BYTES:
                    raise ValueError('zip 解压总大小超过上限')
                target_path = (output_dir / clean_name).resolve()
                try:
                    target_path.relative_to(output_dir)
                except ValueError as exc:
                    raise ValueError(
                        f'zip 成员越出目标目录：{clean_name}'
                    ) from exc
                if clean_name in seen_targets:
                    raise ValueError(f'zip 内存在重复目标：{clean_name}')
                seen_targets.add(clean_name)
                if target_path.exists():
                    raise ValueError(f'解压目标已存在：{clean_name}')
                candidates.append((clean_name, member))
            if not candidates:
                raise ValueError('压缩包内没有可读取的来源文件')
            staged_total_size = 0
            for clean_name, member in candidates:
                stage_path = staging_dir / clean_name
                stage_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source:
                    with stage_path.open('wb') as target:
                        shutil.copyfileobj(source, target)
                actual_size = stage_path.stat().st_size
                if actual_size > MAX_ZIP_FILE_BYTES:
                    raise ValueError(
                        f'zip 成员超过单文件上限：{clean_name}'
                    )
                staged_total_size += actual_size
                if staged_total_size > MAX_ZIP_TOTAL_BYTES:
                    raise ValueError('zip 解压总大小超过上限')
            extracted_files = []
            for clean_name, _member in candidates:
                final_path = output_dir / clean_name
                final_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging_dir / clean_name, final_path)
                extracted_files.append({
                    'file': clean_name,
                    'size_bytes': final_path.stat().st_size,
                })
    except Exception as exc:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f'zip 解压失败：{exc}') from exc
    else:
        shutil.rmtree(staging_dir, ignore_errors=True)
    extracted_files.sort(key=lambda result: result['file'])
    return {
        'extracted_files': extracted_files,
        'skipped_entries': skipped_entries,
    }
