"""基础教育交付质量闸门测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from school_quality_check import (  # noqa: E402
    build_quality_report,
)


def build_city_context():
    """构造单区城市上下文测试夹具。"""
    return {
        'stage': 'city_context',
        'input_city': '示例市',
        'city_name': '示例市',
        'province_name': '示例省',
        'subdivisions': [{'name': '甲区', 'adcode': '1', 'level': 'district'}],
    }


def build_source_item():
    """构造一条政府来源登记项。"""
    return {
        'source_title': '2026年甲区基础教育学校名录',
        'publisher': '示例市甲区教育局',
        'publication_date': '2026-05-18',
        'landing_page_url': 'https://example.gov.cn/list',
        'content_url': 'https://example.gov.cn/list',
        'covered_school_types': ['小学'],
        'contains_address': True,
        'local_files': ['list.html'],
    }


def build_manifest(coverage_notes=None):
    """构造来源清单，school_type_coverage 全部为 covered。"""
    return {
        'stage': 'basic_education_government_source',
        'city_context': build_city_context(),
        'administrative_unit': {'name': '甲区', 'adcode': '1', 'level': 'district'},
        'processing_status': 'completed',
        'school_type_coverage': {
            '幼儿园': 'covered',
            '小学': 'covered',
            '初中': 'covered',
            '高中': 'covered',
        },
        'coverage_notes': coverage_notes or {},
        'items': [build_source_item()],
    }


def build_plan():
    """构造已复核的提取计划。"""
    return {
        'stage': 'basic_education_extraction_plan',
        'city_context': build_city_context(),
        'administrative_unit': {'name': '甲区', 'adcode': '1', 'level': 'district'},
        'government_source_file': 'government_source.json',
        'items': [{
            'source_title': '2026年甲区基础教育学校名录',
            'review_status': 'ready',
            'extraction_rules': [{'approved': True}],
        }],
    }


def build_processed_items():
    """构造一条主表记录与一条异常记录。"""
    return [
        {
            'place_name': '示例小学',
            'original_address': '示例市甲区测试路1号',
            'final_address': '示例市甲区测试路1号',
            'source_reference': 'https://example.gov.cn/list | row 1',
        },
        {
            'place_name': '示例中学',
            'original_address': '',
            'final_address': '',
            'source_reference': 'https://example.gov.cn/list | row 2',
        },
    ]


def write_unit_dir(root, manifest=None, plan=None):
    """写入一个行政单位的四个阶段文件并返回运行目录。"""
    run_dir = root / 'Basic_Education' / '120000'
    unit_dir = run_dir / '甲区'
    unit_dir.mkdir(parents=True)
    (unit_dir / 'government_source.json').write_text(
        json.dumps(manifest or build_manifest(), ensure_ascii=False),
        encoding='utf-8',
    )
    (unit_dir / 'extraction_plan.json').write_text(
        json.dumps(plan or build_plan(), ensure_ascii=False),
        encoding='utf-8',
    )
    (unit_dir / 'address_records.json').write_text(
        json.dumps({
            'stage': 'address_records',
            'city_context': build_city_context(),
            'items': build_processed_items(),
            'metrics': {'item_count': 2, 'error_count': 0},
        }, ensure_ascii=False),
        encoding='utf-8',
    )
    (unit_dir / 'processed_address_records.json').write_text(
        json.dumps({
            'stage': 'processed_address_records',
            'city_context': build_city_context(),
            'items': build_processed_items(),
        }, ensure_ascii=False),
        encoding='utf-8',
    )
    return run_dir


class SchoolQualityCheckTests(unittest.TestCase):
    """验证基础教育质量闸门的通过与阻断行为。"""

    def test_clean_run_passes(self):
        """各阶段文件齐全且已复核时闸门通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_unit_dir(root)
            report = build_quality_report(run_dir, root / 'quality_report.json')
        self.assertTrue(report['passed'])
        self.assertEqual(report['stage'], 'basic_education_quality_report')
        self.assertEqual(report['units'][0]['main_row_count'], 1)
        self.assertEqual(report['units'][0]['abnormal_row_count'], 1)

    def test_missing_coverage_note_blocks(self):
        """非 covered 学段缺少 coverage_notes 说明时闸门阻断。"""
        manifest = build_manifest()
        manifest['school_type_coverage']['高中'] = 'no_official_source'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_unit_dir(root, manifest=manifest)
            report = build_quality_report(run_dir, root / 'quality_report.json')
        self.assertFalse(report['passed'])
        self.assertTrue(
            any('coverage_notes' in reason for reason in report['reasons']),
            report['reasons'],
        )

    def test_pending_plan_blocks(self):
        """提取计划仍有未复核来源时闸门阻断。"""
        plan = build_plan()
        plan['items'][0]['review_status'] = 'pending'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_unit_dir(root, plan=plan)
            report = build_quality_report(run_dir, root / 'quality_report.json')
        self.assertFalse(report['passed'])
        self.assertTrue(
            any('未完成复核' in reason for reason in report['reasons']),
            report['reasons'],
        )

    def test_incomplete_address_stage_blocks(self):
        """提取阶段写成 incomplete 时闸门阻断。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = write_unit_dir(root)
            address_path = run_dir / '甲区' / 'address_records.json'
            payload = json.loads(address_path.read_text(encoding='utf-8'))
            payload['stage'] = 'address_records_incomplete'
            address_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding='utf-8'
            )
            report = build_quality_report(run_dir, root / 'quality_report.json')
        self.assertFalse(report['passed'])
        self.assertTrue(
            any('address_records' in reason for reason in report['reasons']),
            report['reasons'],
        )


if __name__ == '__main__':
    unittest.main()
