"""进程内按主机节流的并发调度测试。"""

import unittest

from query_city_core.host_gate import (
    HostRequestGate,
    extract_url_host,
)


class HostRequestGateTests(unittest.TestCase):
    """验证同一主机的请求间隔与不同主机的并发隔离。"""

    class FakeClock:
        """固定时刻的测试时钟。"""

        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    def test_same_host_requests_keep_minimum_interval(self):
        """同一主机连续请求应等待最小间隔。"""
        clock = self.FakeClock()
        sleep_calls = []
        gate = HostRequestGate(
            host_max_workers=1,
            min_interval=0.3,
            clock=clock,
            sleeper=sleep_calls.append,
        )
        gate.acquire('www.example.gov.cn')
        gate.release('www.example.gov.cn')
        gate.acquire('www.example.gov.cn')
        gate.release('www.example.gov.cn')
        self.assertGreaterEqual(sleep_calls[-1], 0.3)

    def test_different_hosts_do_not_wait(self):
        """不同主机之间不共享最小间隔。"""
        clock = self.FakeClock()
        sleep_calls = []
        gate = HostRequestGate(
            host_max_workers=1,
            min_interval=0.3,
            clock=clock,
            sleeper=sleep_calls.append,
        )
        gate.acquire('a.example.gov.cn')
        gate.acquire('b.example.gov.cn')
        gate.release('a.example.gov.cn')
        gate.release('b.example.gov.cn')
        self.assertEqual(sleep_calls, [])

    def test_extract_url_host_returns_lowercase_host(self):
        """网址应解析为小写主机名，非 http 链接返回空。"""
        self.assertEqual(
            extract_url_host('https://www.Example.gov.cn/a/b.html'),
            'www.example.gov.cn',
        )
        self.assertEqual(extract_url_host('mailto:test@example.gov.cn'), '')


if __name__ == '__main__':
    unittest.main()
