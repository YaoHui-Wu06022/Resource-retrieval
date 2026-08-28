"""检查政府来源并构造基础教育学校地址。"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_readers import normalize_text  # noqa: E402
from extract_school_records import extract_school_records  # noqa: E402
from inspect_government_source import (  # noqa: E402
    build_extraction_plan,
    write_json_object,
)


def build_argument_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description='检查并提取基础教育学校地址')
    commands = parser.add_subparsers(dest='command', required=True)
    inspect_command = commands.add_parser('inspect', help='生成提取计划')
    inspect_command.add_argument(
        '--input', required=True, help='government_source.json 路径'
    )
    inspect_command.add_argument('--output', required=True, help='计划输出路径')
    extract_command = commands.add_parser('extract', help='执行已复核计划')
    extract_command.add_argument('--plan', required=True, help='提取计划路径')
    extract_command.add_argument('--output', required=True, help='地址记录输出路径')
    return parser


def main() -> int:
    """执行来源检查或学校地址提取。"""
    arguments = build_argument_parser().parse_args()
    try:
        output_path = Path(arguments.output).resolve()
        if arguments.command == 'inspect':
            output_payload, exit_code = build_extraction_plan(
                Path(arguments.input).resolve(), output_path
            )
        else:
            output_payload, exit_code = extract_school_records(
                Path(arguments.plan).resolve()
            )
        write_json_object(output_path, output_payload)
        print(json.dumps(
            output_payload.get('inspection_summary')
            or output_payload.get('metrics'),
            ensure_ascii=False,
        ))
        return exit_code
    except Exception as exc:
        print(f'错误：{normalize_text(exc)}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
