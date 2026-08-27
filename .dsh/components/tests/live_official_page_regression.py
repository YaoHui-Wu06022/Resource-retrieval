"""对固定的真实机构首页执行通用地址提取回归。"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from fetch_official_page import collect_official_page_data  # noqa: E402


LIVE_CASES = (
    ('南方科技大学', 'https://www.sustech.edu.cn/', '广东省深圳市南山区学苑大道1088号'),
    ('深圳技术大学', 'https://www.sztu.edu.cn/', '广东省深圳市坪山区兰田路3002号'),
    ('深圳城市职业学院', 'https://www.szcp.edu.cn/', '深圳市龙岗区龙岗街道五联社区将军帽路1号'),
    ('中国银行', 'https://www.boc.cn/', '北京市西城区复兴门内大街1号'),
    (
        '南方科技大学医院',
        'https://www.sustech-hospital.cn/Default.aspx',
        '深圳市南山区西丽留仙大道6019号',
    ),
    ('深圳市人民政府', 'https://www.sz.gov.cn/', ''),
)


def main():
    """逐页检查预期地址，并输出提取插件。"""
    failures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        for name, url, expected_address in LIVE_CASES:
            page.goto(url, wait_until='domcontentloaded', timeout=40000)
            page.wait_for_selector('body', timeout=5000)
            nodes = collect_official_page_data(page)
            candidates = {
                node['address_text']: node['extraction_method']
                for node in nodes['addressNodes']
            }
            passed = (
                expected_address in candidates
                if expected_address
                else not candidates
            )
            print(
                f'{"PASS" if passed else "FAIL"} {name}: '
                f'{candidates or "无地址"}'
            )
            if not passed:
                failures.append(name)
        browser.close()
    if failures:
        raise SystemExit(f'真实页面回归失败：{", ".join(failures)}')


if __name__ == '__main__':
    main()
