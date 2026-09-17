"""场景交付质量闸门公共脚手架测试。"""

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from query_city_core.quality_gate import (
    add_quality_gate_arguments,
    build_quality_report,
    resolve_report_path,
    run_quality_gate,
    summarize_quality_report,
    write_quality_report,
)


class QualityGateTests(unittest.TestCase):
    """验证公共闸门脚手架的参数、报告与退出码。"""

    def test_report_skeleton_and_passed_flag(self):
        """报告骨架统一，passed 由 reasons 决定。"""
        report = build_quality_report(
            'sample_quality_report',
            '示例市',
            units=[{'administrative_unit': '甲区', 'passed': True}],
            reasons=[],
            config={'min_ratio': 0.9},
            checks={'main_row_count': 3},
        )
        self.assertEqual(report['stage'], 'sample_quality_report')
        self.assertEqual(report['city'], '示例市')
        self.assertEqual(report['config'], {'min_ratio': 0.9})
        self.assertEqual(report['checks'], {'main_row_count': 3})
        self.assertEqual(len(report['units']), 1)
        self.assertTrue(report['passed'])
        self.assertIn('generated_at', report)
        blocked = build_quality_report(
            'sample_quality_report', '示例市', reasons=['甲区：缺文件']
        )
        self.assertFalse(blocked['passed'])

    def test_default_output_path_and_write(self):
        """缺省输出路径为输入目录下的 quality_report.json。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = resolve_report_path(root)
            self.assertEqual(path, root.resolve() / 'quality_report.json')
            explicit = resolve_report_path(root, str(root / 'other.json'))
            self.assertEqual(explicit, (root / 'other.json').resolve())
            report = build_quality_report('sample_quality_report', '示例市')
            written = write_quality_report(report, path)
            self.assertEqual(written, path)
            self.assertEqual(
                json.loads(path.read_text(encoding='utf-8'))['stage'],
                'sample_quality_report',
            )

    def test_run_quality_gate_returns_exit_code(self):
        """闸门按 passed 返回 0/1，摘要含 stage 与 unit_count。"""
        parser = add_quality_gate_arguments(
            argparse.ArgumentParser(description='示例闸门')
        )
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp)
            code = run_quality_gate(
                parser,
                lambda _input, output, _args: _write_sample(
                    input_dir, output, []
                ),
                argv=['--input-dir', str(input_dir)],
            )
            self.assertEqual(code, 0)
            blocked_parser = add_quality_gate_arguments(
                argparse.ArgumentParser(description='示例闸门')
            )
            code = run_quality_gate(
                blocked_parser,
                lambda _input, output, _args: _write_sample(
                    input_dir, output, ['甲区：缺文件']
                ),
                argv=['--input-dir', str(input_dir)],
            )
            self.assertEqual(code, 1)

    def test_summary_keeps_scene_counts(self):
        """摘要保留 output/passed/units 与 checks。"""
        report = build_quality_report(
            'sample_quality_report',
            '示例市',
            units=[{'administrative_unit': '甲区'}],
            checks={'main_row_count': 3},
        )
        summary = summarize_quality_report(report, Path('report.json'))
        self.assertEqual(summary['unit_count'], 1)
        self.assertEqual(summary['checks'], {'main_row_count': 3})
        self.assertTrue(summary['passed'])


def _write_sample(input_dir, output, reasons):
    """构造并写出示例报告，供 run_quality_gate 测试使用。"""
    report = build_quality_report(
        'sample_quality_report',
        '示例市',
        units=[{'administrative_unit': '甲区'}],
        reasons=reasons,
    )
    write_quality_report(report, output)
    return report


if __name__ == '__main__':
    unittest.main()
