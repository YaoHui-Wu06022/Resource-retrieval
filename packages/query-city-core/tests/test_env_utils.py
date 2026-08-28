#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试公共 .env 配置读取。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


COMPONENT_DIR = Path(__file__).resolve().parents[1]
if str(COMPONENT_DIR) not in sys.path:
    sys.path.insert(0, str(COMPONENT_DIR))

from query_city_core.env_utils import (  # noqa: E402
    read_env_file_value,
    read_env_value,
)


class EnvUtilsTests(unittest.TestCase):
    """覆盖环境变量优先级和 .env 文本解析。"""

    def test_reads_quoted_env_file_value(self):
        """读取 .env 时移除配置值两侧引号。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('TEST_VALUE="example-value"\n', encoding='utf-8')
            value = read_env_file_value(path, 'TEST_VALUE')
        self.assertEqual(value, 'example-value')

    def test_environment_variable_has_priority(self):
        """进程环境变量存在时不再依赖 .env。"""
        with patch.dict(os.environ, {'TEST_VALUE': 'environment-value'}):
            self.assertEqual(read_env_value('TEST_VALUE'), 'environment-value')


if __name__ == '__main__':
    unittest.main()
