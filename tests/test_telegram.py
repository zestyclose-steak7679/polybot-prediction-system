import unittest
from unittest.mock import patch, MagicMock
<<<<<< testing-improvement-telegram-send-error-9118264119177855348
import io
import sys
from datetime import datetime, UTC

# Mock external dependencies BEFORE importing the module under test
sys.modules['requests'] = MagicMock()
sys.modules['config'] = MagicMock()

from alerts import telegram
from alerts.telegram import _utc_now

=======
<<<<<< test-telegram-send-11353423296918326904
import io

from alerts import telegram
>>>>>> main

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
<<<<<< testing-improvement-telegram-send-error-9118264119177855348

=======
======
import sys
from datetime import datetime, UTC

# Mock external dependencies BEFORE importing the module under test
sys.modules['requests'] = MagicMock()
sys.modules['config'] = MagicMock()

from alerts.telegram import _utc_now

class TestTelegram(unittest.TestCase):
>>>>>> main
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
<<<<<< testing-improvement-telegram-send-error-9118264119177855348

    @patch("alerts.telegram._send")
    def test_send_error(self, mock_send):
        # Setup mock return value
        mock_send.return_value = True

        # Call the function
        msg = "Something went wrong"
        result = telegram.send_error(msg)

        # Assertions
        mock_send.assert_called_once_with("<b>POLYBOT ERROR</b>\nSomething went wrong")
        self.assertTrue(result)

    @patch("alerts.telegram._send")
    def test_send_error_false_return(self, mock_send):
        # Setup mock return value for failure case
        mock_send.return_value = False

        # Call the function
        msg = "Another issue"
        result = telegram.send_error(msg)

        # Assertions
        mock_send.assert_called_once_with("<b>POLYBOT ERROR</b>\nAnother issue")
        self.assertFalse(result)

if __name__ == "__main__":
=======
>>>>>> main

if __name__ == '__main__':
>>>>>> main
    unittest.main()
