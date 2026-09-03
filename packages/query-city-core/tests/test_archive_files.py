"""公共 zip 附件安全解压测试。"""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from query_city_core.official.collectors.archive_files import (
    MAX_ZIP_ENTRIES,
    extract_zip_archive,
)


def build_zip_bytes(entries):
    """把 (成员名, 字节内容) 列表写入内存 zip。"""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return stream.getvalue()


class ExtractZipArchiveTests(unittest.TestCase):
    """验证安全解压、路径限制与登记结果。"""

    def test_extracts_readable_files_preserving_relative_paths(self):
        """可读来源按 zip 内相对路径解压并登记。"""
        content = build_zip_bytes([
            ('名单/小学名录.xlsx', '甲小学'.encode('utf-8')),
            ('名单/说明.txt', '说明'.encode('utf-8')),
            ('图片/地图.png', b'\x89PNG'),
            ('附件目录/', b''),
            ('__MACOSX/._名单', b'junk'),
            ('.DS_Store', b'junk'),
        ])
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            archive_path = source_dir / '附件.zip'
            archive_path.write_bytes(content)
            output_dir = source_dir / 'out'
            result = extract_zip_archive(archive_path, output_dir)
            self.assertEqual(
                [item['file'] for item in result['extracted_files']],
                ['名单/小学名录.xlsx', '图片/地图.png'],
            )
            self.assertEqual(result['skipped_entries'], ['名单/说明.txt'])
            self.assertTrue(
                (output_dir / '名单/小学名录.xlsx').is_file()
            )
            self.assertTrue((output_dir / '图片/地图.png').is_file())
            self.assertFalse((output_dir / '名单/说明.txt').exists())
            self.assertFalse((output_dir / '__MACOSX').exists())

    def test_extracts_gbk_named_zip_members_with_readable_names(self):
        """GBK 编码的 zip 中文成员名应解出可读文件名。"""
        real_name = (
            '21号附件/附件1：2025年越秀区幼儿园取得办学资格情况一览表.xlsx'
        )

        class FakeZipMember:
            """模拟未标记 UTF-8 的 GBK 中文 zip 成员。"""

            filename = real_name.encode('gbk').decode('cp437')
            flag_bits = 0
            file_size = 3

        member = FakeZipMember()

        class FakeZipArchive:
            """模拟可读取单个 GBK 成员的安全 zip 包。"""

            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def infolist(self):
                return [member]

            def open(self, _member):
                return io.BytesIO(b'abc')

        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            archive_path = source_dir / '附件.zip'
            archive_path.write_bytes(b'fake zip bytes')
            output_dir = source_dir / 'out'
            with mock.patch(
                'query_city_core.official.collectors.archive_files.'
                'zipfile.is_zipfile',
                return_value=True,
            ), mock.patch(
                'query_city_core.official.collectors.archive_files.'
                'zipfile.ZipFile',
                FakeZipArchive,
            ):
                result = extract_zip_archive(archive_path, output_dir)
                self.assertEqual(
                    [item['file'] for item in result['extracted_files']],
                    [real_name],
                )
                self.assertTrue((output_dir / real_name).is_file())

    def test_rejects_traversal_and_absolute_member_paths(self):
        """路径穿越与绝对路径成员必须被拒绝且不写文件。"""
        for name in ('../escape.xlsx', '/abs.xlsx', 'C:/drive.xlsx'):
            with tempfile.TemporaryDirectory() as temporary_dir:
                source_dir = Path(temporary_dir)
                archive_path = source_dir / '附件.zip'
                archive_path.write_bytes(
                    build_zip_bytes([(name, b'x')])
                )
                output_dir = source_dir / 'out'
                with self.assertRaisesRegex(ValueError, '路径非法'):
                    extract_zip_archive(archive_path, output_dir)
                self.assertFalse(any(output_dir.rglob('*')))

    def test_collision_rejects_without_overwrite(self):
        """目标已存在时整包报错且不覆盖已有文件。"""
        content = build_zip_bytes([
            ('名单/小学名录.xlsx', b'new content'),
        ])
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            archive_path = source_dir / '附件.zip'
            archive_path.write_bytes(content)
            output_dir = source_dir / 'out'
            existing = output_dir / '名单' / '小学名录.xlsx'
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b'original content')
            with self.assertRaisesRegex(ValueError, '解压目标已存在'):
                extract_zip_archive(archive_path, output_dir)
            self.assertEqual(existing.read_bytes(), b'original content')

    def test_rejects_encrypted_member(self):
        """加密成员必须被拒绝。"""
        content = build_zip_bytes([('普通.xlsx', b'x')])
        encrypted_member = zipfile.ZipInfo('名单/密文.xlsx')
        encrypted_member.flag_bits = 0x1
        encrypted_member.file_size = 10
        with mock.patch(
            'zipfile.ZipFile.infolist',
            return_value=[encrypted_member],
        ):
            with tempfile.TemporaryDirectory() as temporary_dir:
                source_dir = Path(temporary_dir)
                archive_path = source_dir / '加密.zip'
                archive_path.write_bytes(content)
                output_dir = source_dir / 'out'
                with self.assertRaisesRegex(ValueError, '加密成员'):
                    extract_zip_archive(archive_path, output_dir)

    def test_nested_archive_is_skipped_one_level(self):
        """嵌套压缩包只记录不继续解压。"""
        inner_bytes = build_zip_bytes([
            ('内部/小学名录.xlsx', '内部小学'.encode('utf-8')),
        ])
        content = build_zip_bytes([
            ('外层/小学名录.xlsx', '外层小学'.encode('utf-8')),
            ('外层/嵌套.zip', inner_bytes),
        ])
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            archive_path = source_dir / '嵌套.zip'
            archive_path.write_bytes(content)
            output_dir = source_dir / 'out'
            result = extract_zip_archive(archive_path, output_dir)
            self.assertTrue((output_dir / '外层/小学名录.xlsx').is_file())
            self.assertFalse(
                (output_dir / '内部/小学名录.xlsx').exists()
            )
            self.assertEqual(
                result['skipped_entries'], ['外层/嵌套.zip']
            )

    def test_rejects_entry_count_over_limit(self):
        """条目数超过上限时整包拒绝。"""
        entries = [
            (f'文件/{index}.xlsx', b'x')
            for index in range(MAX_ZIP_ENTRIES + 1)
        ]
        content = build_zip_bytes(entries)
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            archive_path = source_dir / '超量.zip'
            archive_path.write_bytes(content)
            output_dir = source_dir / 'out'
            with self.assertRaisesRegex(ValueError, '条目超过上限'):
                extract_zip_archive(archive_path, output_dir)

    def test_rejects_file_and_total_size_over_limits(self):
        """单文件与总解压大小超限时整包拒绝。"""
        content = build_zip_bytes([('大文件.xlsx', b'x' * 10)])
        with mock.patch(
            'query_city_core.official.collectors.archive_files.MAX_ZIP_FILE_BYTES',
            5,
        ):
            with tempfile.TemporaryDirectory() as temporary_dir:
                source_dir = Path(temporary_dir)
                archive_path = source_dir / '大文件.zip'
                archive_path.write_bytes(content)
                output_dir = source_dir / 'out'
                with self.assertRaisesRegex(ValueError, '单文件上限'):
                    extract_zip_archive(archive_path, output_dir)

        total_content = build_zip_bytes([
            ('一.xlsx', b'1' * 4),
            ('二.xlsx', b'2' * 4),
        ])
        with mock.patch(
            'query_city_core.official.collectors.archive_files.MAX_ZIP_TOTAL_BYTES',
            6,
        ):
            with tempfile.TemporaryDirectory() as temporary_dir:
                source_dir = Path(temporary_dir)
                archive_path = source_dir / '总量.zip'
                archive_path.write_bytes(total_content)
                output_dir = source_dir / 'out'
                with self.assertRaisesRegex(ValueError, '总大小超过上限'):
                    extract_zip_archive(archive_path, output_dir)

    def test_rejects_archive_without_readable_files(self):
        """没有可读来源文件时整包报错。"""
        content = build_zip_bytes([
            ('说明.txt', '说明'.encode('utf-8')),
            ('附件目录/', b''),
        ])
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            archive_path = source_dir / '纯文本.zip'
            archive_path.write_bytes(content)
            output_dir = source_dir / 'out'
            with self.assertRaisesRegex(ValueError, '没有可读取'):
                extract_zip_archive(archive_path, output_dir)

    def test_rejects_invalid_zip_bytes(self):
        """损坏或伪造的 zip 必须报错。"""
        with tempfile.TemporaryDirectory() as temporary_dir:
            source_dir = Path(temporary_dir)
            archive_path = source_dir / '损坏.zip'
            archive_path.write_bytes(b'not a zip')
            output_dir = source_dir / 'out'
            with self.assertRaisesRegex(ValueError, '不是合法 zip'):
                extract_zip_archive(archive_path, output_dir)


if __name__ == '__main__':
    unittest.main()
