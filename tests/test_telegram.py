import unittest
from unittest.mock import patch, MagicMock
import sys
from datetime import datetime, UTC

# Mock external dependencies BEFORE importing the module under test
sys.modules['requests'] = MagicMock()
sys.modules['config'] = MagicMock()

from alerts.telegram import _utc_now

class TestTelegram(unittest.TestCase):
    @patch('alerts.telegram.datetime')
    def test_utc_now(self, mock_datetime):
        # Create a fixed datetime for testing
        fixed_now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Configure the mock
        mock_datetime.now.return_value = fixed_now

        # Call the function
        result = _utc_now()

        # Assert that datetime.now was called with UTC
        mock_datetime.now.assert_called_once_with(UTC)

        # Assert the result is as expected
        self.assertEqual(result, fixed_now)

if __name__ == '__main__':
    unittest.main()
