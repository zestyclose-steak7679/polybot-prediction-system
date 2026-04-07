import unittest
from unittest.mock import patch

from alerts import telegram


class TestTelegramAlerts(unittest.TestCase):
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
    unittest.main()
