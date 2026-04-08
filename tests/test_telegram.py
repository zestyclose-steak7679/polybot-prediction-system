import unittest
from unittest.mock import patch, MagicMock
<<<<<< test-telegram-send-11353423296918326904
import io

from alerts import telegram

class TestTelegram(unittest.TestCase):
    @patch('alerts.telegram.TELEGRAM_TOKEN', '')
    @patch('alerts.telegram.TELEGRAM_CHAT_ID', '')
    @patch('sys.stdout', new_callable=io.StringIO)
    def test_send_missing_credentials(self, mock_stdout):
        # When token and chat_id are empty, it should print and return False
        result = telegram._send("Test message")

        self.assertFalse(result)
        self.assertIn("Test message", mock_stdout.getvalue())

    @patch('alerts.telegram.TELEGRAM_TOKEN', 'test_token')
    @patch('alerts.telegram.TELEGRAM_API', 'https://api.telegram.org/bottest_token')
    @patch('alerts.telegram.TELEGRAM_CHAT_ID', 'test_chat_id')
    @patch('alerts.telegram.SESSION.post')
    def test_send_success(self, mock_post):
        # Setup mock response
        mock_response = MagicMock()
        mock_post.return_value = mock_response

        result = telegram._send("Test message")

        self.assertTrue(result)
        mock_post.assert_called_once_with(
            "https://api.telegram.org/bottest_token/sendMessage",
            json={"chat_id": "test_chat_id", "text": "Test message", "parse_mode": "HTML"},
            timeout=10,
        )
        mock_response.raise_for_status.assert_called_once()

    @patch('alerts.telegram.TELEGRAM_TOKEN', 'test_token')
    @patch('alerts.telegram.TELEGRAM_API', 'https://api.telegram.org/bottest_token')
    @patch('alerts.telegram.TELEGRAM_CHAT_ID', 'test_chat_id')
    @patch('alerts.telegram.SESSION.post')
    @patch('alerts.telegram.logger.error')
    def test_send_exception(self, mock_logger_error, mock_post):
        # Setup mock response to raise an exception
        mock_post.side_effect = Exception("Network Error")

        result = telegram._send("Test message")

        self.assertFalse(result)
        mock_logger_error.assert_called_once()
        self.assertIn("Telegram error", mock_logger_error.call_args[0][0])
======
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
>>>>>> main

if __name__ == '__main__':
    unittest.main()
