import unittest
from unittest.mock import patch, MagicMock
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

if __name__ == '__main__':
    unittest.main()
