import unittest

from query_city_core.amap_client import RequestRateLimiter


class RequestRateLimiterTests(unittest.TestCase):
    def test_sliding_window_allows_only_two_requests(self):
        now = [0.0]
        sleeps = []

        def clock():
            return now[0]

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        limiter = RequestRateLimiter(clock=clock, sleeper=sleep)
        limiter.wait()
        limiter.wait()
        limiter.wait()
        self.assertEqual(limiter.total_requests, 3)
        self.assertGreaterEqual(sleeps[0], 1.0)


if __name__ == '__main__':
    unittest.main()
