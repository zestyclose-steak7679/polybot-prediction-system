import unittest
from unittest.mock import MagicMock
import sys

# 1. Mock the flask module
mock_flask = MagicMock()
sys.modules['flask'] = mock_flask

# Setup what happens when 'from flask import Flask, request, jsonify' is called
mock_flask.Flask = MagicMock()
# IMPORTANT: Make app.route return a decorator that returns the function itself
def mock_route(path, **kwargs):
    def decorator(f):
        return f
    return decorator

mock_flask.Flask.return_value.route = mock_route
mock_flask.request = MagicMock()
mock_flask.jsonify = lambda x: x

# 2. Import the webhook module.
import webhook

# 4. Now we can test the trigger function directly.
class TestWebhookAuth(unittest.TestCase):
    def setUp(self):
        webhook.SECRET = "test_secret"
        webhook.logger = MagicMock()
        webhook._running = False
        # Inject the mock request into the webhook module
        webhook.request = MagicMock()

    def test_trigger_no_auth(self):
        webhook.request.headers.get.return_value = None
        result = webhook.trigger()
        self.assertEqual(result, ({"status": "unauthorized"}, 401))

    def test_trigger_wrong_auth(self):
        webhook.request.headers.get.return_value = "wrong_secret"
        result = webhook.trigger()
        self.assertEqual(result, ({"status": "unauthorized"}, 401))

    def test_trigger_correct_auth_already_running(self):
        webhook.request.headers.get.return_value = "test_secret"
        webhook._running = True
        result = webhook.trigger()
        self.assertEqual(result, ({"status": "already_running"}, 429))

    def test_trigger_correct_auth_starts_thread(self):
        webhook.request.headers.get.return_value = "test_secret"
        webhook._running = False
        with unittest.mock.patch('threading.Thread') as mock_thread:
            result = webhook.trigger()
            self.assertEqual(result, ({"status": "triggered"}, 200))
            mock_thread.assert_called_once()

if __name__ == "__main__":
    unittest.main()
