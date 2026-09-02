"""检查政府来源并构造基础教育学校地址。"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_readers import normalize_text  # noqa: E402
from query_city_core.io_utils import write_json_payload  # noqa: E402
from query_city_core.directory_links import collect_directory_links  # noqa: E402
from query_city_core.host_gate import (  # noqa: E402
    DEFAULT_HOST_MAX_WORKERS,
    DEFAULT_HOST_MIN_INTERVAL,
    DEFAULT_MAX_WORKERS,
)
from query_city_core.linked_pages import collect_linked_html_pages  # noqa: E402
from query_city_core.source_files import download_source_files  # noqa: E402
from extract_school_records import extract_school_records  # noqa: E402
from inspect_government_source import build_extraction_plan  # noqa: E402


def build_argument_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description='检查并提取基础教育学校地址')
    commands = parser.add_subparsers(dest='command', required=True)

    def add_fetch_arguments(command_parser):
        """为抓取或下载命令添加并发与同域节流参数。"""
        command_parser.add_argument(
            '--max-workers',
            type=int,
            default=DEFAULT_MAX_WORKERS,
            help='进程内最大并发任务数',
        )
        command_parser.add_argument(
            '--host-max-workers',
            type=int,
            default=DEFAULT_HOST_MAX_WORKERS,
            help='同一主机最大并发数，0 表示不限制',
        )
        command_parser.add_argument(
            '--host-min-interval',
            type=float,
            default=DEFAULT_HOST_MIN_INTERVAL,
            help='同一主机两次请求的最小间隔秒数',
        )

    list_links_command = commands.add_parser(
        'list-links', help='抓取栏目页并列出文章链接'
    )
    list_links_command.add_argument('--input', required=True, help='目录页清单')
    list_links_command.add_argument('--output', required=True, help='链接输出路径')
    add_fetch_arguments(list_links_command)
    download_command = commands.add_parser(
        'download', help='保存已选定的政府来源文件'
    )
    download_command.add_argument(
        '--manifest', required=True, help='下载清单 JSON 路径'
    )
    download_command.add_argument(
        '--output-dir', required=True, help='行政单位目录'
    )
    add_fetch_arguments(download_command)
    inspect_command = commands.add_parser('inspect', help='生成提取计划')
    inspect_command.add_argument(
        '--input', required=True, help='government_source.json 路径'
    )
    inspect_command.add_argument('--output', required=True, help='计划输出路径')
    collect_command = commands.add_parser(
        'collect-details', help='保存名录链接的同构 HTML 详情页'
    )
    collect_command.add_argument('--input', required=True, help='本地名录 HTML')
    collect_command.add_argument(
        '--link-selector', required=True, help='详情页链接 CSS 选择器'
    )
    collect_command.add_argument(
        '--output-dir', required=True, help='详情页保存目录'
    )
    collect_command.add_argument(
        '--manifest', required=True, help='详情页文件与网址清单'
    )
    collect_command.add_argument(
        '--allowed-domain', default='', help='允许下载的唯一域名'
    )
    add_fetch_arguments(collect_command)
    extract_command = commands.add_parser('extract', help='执行已复核计划')
    extract_command.add_argument('--plan', required=True, help='提取计划路径')
    extract_command.add_argument('--output', required=True, help='地址记录输出路径')
    return parser


def main() -> int:
    """执行来源检查或学校地址提取。"""
    arguments = build_argument_parser().parse_args()
    try:
        if arguments.command == 'list-links':
            output_payload, exit_code = collect_directory_links(
                Path(arguments.input).resolve(),
                Path(arguments.output).resolve(),
                arguments.max_workers,
                arguments.host_max_workers,
                arguments.host_min_interval,
            )
            print(json.dumps(output_payload['metrics'], ensure_ascii=False))
            if exit_code != 0:
                error_count = len(output_payload.get('errors') or [])
                print(
                    f'抓取错误 {error_count} 条，详见输出 errors 字段',
                    file=sys.stderr,
                )
            return exit_code
        elif arguments.command == 'download':
            output_payload, exit_code = download_source_files(
                Path(arguments.manifest).resolve(),
                Path(arguments.output_dir).resolve(),
                arguments.max_workers,
                arguments.host_max_workers,
                arguments.host_min_interval,
            )
            print(json.dumps(output_payload['metrics'], ensure_ascii=False))
            if exit_code != 0:
                error_count = len(output_payload.get('errors') or [])
                print(
                    f'下载错误 {error_count} 条，详见清单 errors 字段',
                    file=sys.stderr,
                )
            return exit_code
        elif arguments.command == 'collect-details':
            output_payload, exit_code = collect_linked_html_pages(
                Path(arguments.input).resolve(),
                arguments.link_selector,
                Path(arguments.output_dir).resolve(),
                Path(arguments.manifest).resolve(),
                arguments.allowed_domain,
                arguments.max_workers,
                arguments.host_max_workers,
                arguments.host_min_interval,
            )
            print(json.dumps(output_payload['metrics'], ensure_ascii=False))
            if exit_code != 0:
                error_count = len(output_payload.get('errors') or [])
                print(
                    f'下载错误 {error_count} 条，详见清单 errors 字段',
                    file=sys.stderr,
                )
            return exit_code
        output_path = Path(arguments.output).resolve()
        if arguments.command == 'inspect':
            output_payload, exit_code = build_extraction_plan(
                Path(arguments.input).resolve(), output_path
            )
        else:
            output_payload, exit_code = extract_school_records(
                Path(arguments.plan).resolve()
            )
        write_json_payload(output_path, output_payload)
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
