import unittest
from unittest.mock import patch
from datetime import datetime, UTC, timezone
from scoring.filters import _is_stale

class TestFilters(unittest.TestCase):
    @patch('scoring.filters._utc_now')
    def test_is_stale_future_date(self, mock_utc_now):
        mock_utc_now.return_value = datetime(2023, 10, 20, 12, 0, 0)
        self.assertFalse(_is_stale("2023-10-21T12:00:00Z"))
        self.assertFalse(_is_stale("2023-10-20T12:00:01Z"))

    @patch('scoring.filters._utc_now')
    def test_is_stale_past_date(self, mock_utc_now):
        mock_utc_now.return_value = datetime(2023, 10, 20, 12, 0, 0)
        self.assertTrue(_is_stale("2023-10-19T12:00:00Z"))
        self.assertTrue(_is_stale("2023-10-20T11:59:59Z"))

    def test_is_stale_empty_and_none(self):
        self.assertFalse(_is_stale(None))
        self.assertFalse(_is_stale(""))

    def test_is_stale_invalid_date(self):
        self.assertFalse(_is_stale("not-a-date"))
        self.assertFalse(_is_stale("2023-99-99"))

    @patch('scoring.filters._utc_now')
    def test_is_stale_timezone_formats(self, mock_utc_now):
        mock_utc_now.return_value = datetime(2023, 10, 20, 12, 0, 0)
        # Testing different suffix parsing (Z vs +)
        self.assertFalse(_is_stale("2023-10-21T12:00:00+00:00"))
        self.assertTrue(_is_stale("2023-10-19T12:00:00+00:00"))
        # Also check with timezone offset
        self.assertFalse(_is_stale("2023-10-21T12:00:00+02:00"))

        # Check proper offset conversion to UTC
        # Current time mock is 12:00 UTC.
        # 13:00 +02:00 is 11:00 UTC -> Past -> True
        self.assertTrue(_is_stale("2023-10-20T13:00:00+02:00"))
        # 11:00 -02:00 is 13:00 UTC -> Future -> False
        self.assertFalse(_is_stale("2023-10-20T11:00:00-02:00"))

if __name__ == '__main__':
    unittest.main()
