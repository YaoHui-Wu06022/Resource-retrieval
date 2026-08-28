#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试高校地址后处理。"""

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_university_address_post import (  # noqa: E402
    postprocess_university_address_records,
)


def build_record(school_identifier, campus_name, map_address):
    return {
        'map_address': map_address,
        'attributes': {
            'school_identifier': school_identifier,
            'campus_name': campus_name,
        },
    }


class UniversityAddressPostTests(unittest.TestCase):
    def test_same_school_and_map_detail_prefers_labeled_campus(self):
        unlabeled = build_record(
            '4144010559',
            '',
            '广州市番禺区大学路1号',
        )
        labeled = build_record(
            '4144010559',
            '校本部',
            '广州市番禺区小谷围街大学路1号',
        )

        result = postprocess_university_address_records([unlabeled, labeled])

        self.assertEqual(result, [labeled])

    def test_same_address_for_different_schools_is_preserved(self):
        first = build_record('4144010001', '', '广州市天河区示例路1号')
        second = build_record('4144010002', '', '广州市天河区示例路1号')

        result = postprocess_university_address_records([first, second])

        self.assertEqual(result, [first, second])


if __name__ == '__main__':
    unittest.main()
