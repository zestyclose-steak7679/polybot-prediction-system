import unittest
from unittest.mock import MagicMock, patch
import sys

# Mocking flask before importing webhook
mock_flask = MagicMock()
sys.modules["flask"] = mock_flask

import webhook

class TestWebhook(unittest.TestCase):
    def test_imports(self):
        # If we reached here, webhook was imported successfully
        self.assertIn("Flask", dir(webhook))
        self.assertIn("jsonify", dir(webhook))
        # Ensure 'request' is NOT in webhook's namespace from flask
        # Note: it might be in sys.modules if other things imported it,
        # but we want to check if it's used/available in webhook.py
        # Since I removed it from 'from flask import ...', it shouldn't be there
        # unless it's imported elsewhere.
        self.assertNotIn("request", dir(webhook))

if __name__ == "__main__":
    unittest.main()
