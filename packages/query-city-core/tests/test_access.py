"""公共直连访问顺序和审计测试。"""

import unittest
from unittest.mock import Mock, patch

from query_city_core.access import fetch_direct_content


class DirectAccessTests(unittest.TestCase):
    @patch('query_city_core.access.urlopen')
    @patch('query_city_core.access.shutil.which', return_value='curl')
    @patch('query_city_core.access.subprocess.run')
    def test_preferred_curl_skips_urllib(self, run, which, urlopen):
        run.return_value = Mock(
            returncode=0,
            stdout=(
                b'<html>ok</html>\n'
                b'200\thttps://example.edu.cn/\ttext/html; charset=gbk'
            ),
        )

        body, final_url, status, attempts, charset = fetch_direct_content(
            'https://example.edu.cn/', preferred_method='curl',
        )

        self.assertEqual(body, b'<html>ok</html>')
        self.assertEqual(final_url, 'https://example.edu.cn/')
        self.assertEqual(status, 200)
        self.assertEqual([item['method'] for item in attempts], ['curl'])
        self.assertEqual(charset, 'gbk')
        urlopen.assert_not_called()
        which.assert_called_once()

    @patch('query_city_core.access.urlopen')
    @patch('query_city_core.access.shutil.which', return_value='curl')
    @patch('query_city_core.access.subprocess.run')
    def test_curl_failure_keeps_http_status_in_audit(self, run, which, urlopen):
        run.return_value = Mock(
            returncode=22,
            stdout=b'forbidden body\n403\thttps://example.edu.cn/',
        )
        response = Mock()
        response.read.return_value = b'ok'
        response.geturl.return_value = 'https://example.edu.cn/'
        response.status = 200
        urlopen.return_value.__enter__.return_value = response

        body, final_url, status, attempts, charset = fetch_direct_content(
            'https://example.edu.cn/', preferred_method='curl',
        )

        self.assertEqual(body, b'ok')
        self.assertEqual(status, 200)
        self.assertEqual([item['method'] for item in attempts], ['curl', 'urllib'])
        self.assertEqual(attempts[0]['http_status'], 403)
