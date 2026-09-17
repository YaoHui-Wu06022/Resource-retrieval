"""场景交付质量闸门的公共脚手架：参数、报告骨架、摘要与退出码。"""

import json
from datetime import datetime, timezone
from pathlib import Path

from query_city_core.io_utils import write_json_payload


REPORT_FILE_NAME = 'quality_report.json'


def build_quality_report(
    stage,
    city,
    units=None,
    reasons=None,
    config=None,
    checks=None,
):
    """按统一结构组装质量报告，passed 由 reasons 是否为空决定。"""
    report = {
        'stage': stage,
        'city': city,
        'generated_at': datetime.now(timezone.utc).isoformat(
            timespec='seconds'
        ),
        'config': dict(config or {}),
    }
    if checks is not None:
        report['checks'] = dict(checks)
    report['units'] = list(units or [])
    report['reasons'] = list(reasons or [])
    report['passed'] = not report['reasons']
    return report


def add_quality_gate_arguments(parser):
    """为场景闸门脚本登记统一的命令行参数。"""
    parser.add_argument('--input-dir', required=True)
    parser.add_argument(
        '--output',
        default='',
        help=f'质量报告输出路径，缺省为输入目录下 {REPORT_FILE_NAME}',
    )
    return parser


def resolve_report_path(input_dir, output=''):
    """返回质量报告输出路径。"""
    if output:
        return Path(output).resolve()
    return Path(input_dir).resolve() / REPORT_FILE_NAME


def write_quality_report(report, output_path):
    """原子写出质量报告。"""
    return write_json_payload(output_path, report)


def summarize_quality_report(report, output_path):
    """生成 CLI 单行摘要。"""
    summary = {
        'output': str(output_path),
        'stage': report.get('stage'),
        'passed': report['passed'],
    }
    if 'units' in report:
        summary['unit_count'] = len(report['units'])
    if report.get('checks'):
        summary['checks'] = report['checks']
    summary['reasons'] = list(report.get('reasons') or [])
    return summary


def run_quality_gate(parser, report_builder, argv=None):
    """解析参数、生成报告、打印摘要并按检查结果返回退出码。

    report_builder 签名为 (input_dir, output_path, arguments) -> report，
    并负责用 write_quality_report 写出报告文件。
    """
    arguments = parser.parse_args(argv)
    try:
        output_path = resolve_report_path(
            arguments.input_dir, arguments.output
        )
        report = report_builder(
            arguments.input_dir, str(output_path), arguments
        )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(
        summarize_quality_report(report, output_path),
        ensure_ascii=False,
    ))
    return 0 if report['passed'] else 1
