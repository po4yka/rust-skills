#!/usr/bin/env python3
"""Fail-closed tests for recorded SPGO evidence."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import sample_pgo

ROOT = Path(__file__).resolve().parent


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.capture = json.loads((ROOT / 'sample_capture.json').read_text())
        self.profile = (ROOT / 'sample_capture.txt').read_text()
        self.source_hash = hashlib.sha256((ROOT / 'sample_workload.rs').read_bytes()).hexdigest()

    def test_recorded_capture_matches_source_and_profile(self):
        sample_pgo.validate_capture(self.capture, self.source_hash, self.profile)

    def test_changed_source_rejects_old_profile(self):
        with self.assertRaisesRegex(RuntimeError, 'source edit'):
            sample_pgo.validate_capture(self.capture, 'different source hash', self.profile)

    def test_empty_profile_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'profile changed'):
            sample_pgo.validate_capture(self.capture, self.source_hash, '')

    def test_inconsistent_sample_count_is_rejected(self):
        capture = copy.deepcopy(self.capture)
        capture['mapped_leaf_samples'] += 1
        with self.assertRaisesRegex(RuntimeError, 'sample count'):
            sample_pgo.validate_capture(capture, self.source_hash, self.profile)

    def test_zero_samples_are_rejected(self):
        capture = copy.deepcopy(self.capture)
        capture['mapped_leaf_samples'] = 0
        with self.assertRaisesRegex(RuntimeError, 'too few samples'):
            sample_pgo.validate_capture(capture, self.source_hash, self.profile)

    def test_unrelated_binary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly the recorded binary'):
            sample_pgo.leaf_counts({'libs': [{'path': '/other/binary'}]}, Path('/intended/binary'))

    def test_acceptance_checks_are_not_python_asserts(self):
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            sample_pgo.require(False, 'rejected')


if __name__ == '__main__':
    unittest.main()
