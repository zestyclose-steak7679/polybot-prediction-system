import unittest
from unittest.mock import patch, MagicMock
import sys

# We need to mock external dependencies that main.py tries to import on the global level
# and which are not available in this test environment (like numpy, models, database etc.)
sys.modules['numpy'] = MagicMock()
sys.modules['pandas'] = MagicMock()
sys.modules['data'] = MagicMock()
sys.modules['data.database'] = MagicMock()
sys.modules['data.markets'] = MagicMock()
sys.modules['data.price_history'] = MagicMock()
sys.modules['data.features'] = MagicMock()
sys.modules['data.regime_features'] = MagicMock()
sys.modules['scoring'] = MagicMock()
sys.modules['scoring.filters'] = MagicMock()
sys.modules['scoring.strategies'] = MagicMock()
sys.modules['models'] = MagicMock()
sys.modules['models.edge_model'] = MagicMock()
sys.modules['models.clv_model'] = MagicMock()
sys.modules['models.meta_model'] = MagicMock()
sys.modules['models.regime_model'] = MagicMock()
sys.modules['portfolio'] = MagicMock()
sys.modules['portfolio.allocator'] = MagicMock()
sys.modules['portfolio.risk_manager'] = MagicMock()
sys.modules['portfolio.strategy_weights'] = MagicMock()
sys.modules['tracking'] = MagicMock()
sys.modules['tracking.clv'] = MagicMock()
sys.modules['learning'] = MagicMock()
sys.modules['learning.tracker'] = MagicMock()
sys.modules['learning.online_trainer'] = MagicMock()
sys.modules['learning.drift_monitor'] = MagicMock()
sys.modules['learning.alpha_diagnostics'] = MagicMock()
sys.modules['learning.regime_stability'] = MagicMock()
sys.modules['risk'] = MagicMock()
sys.modules['risk.controls'] = MagicMock()
sys.modules['risk.strategy_killer'] = MagicMock()
sys.modules['risk.drawdown_controller'] = MagicMock()
sys.modules['alerts'] = MagicMock()
sys.modules['alerts.telegram'] = MagicMock()
sys.modules['strategies'] = MagicMock()
sys.modules['strategies.router'] = MagicMock()
sys.modules['backtest'] = MagicMock()
sys.modules['backtest.engine'] = MagicMock()
sys.modules['alpha'] = MagicMock()

import main
from pathlib import Path
import config

class TestLoadBankroll(unittest.TestCase):

    @patch.object(Path, 'read_text')
    def test_load_bankroll_success(self, mock_read_text):
        """Test that load_bankroll correctly parses and returns the bankroll from file."""
        mock_read_text.return_value = " 1234.56 \n"
        result = main.load_bankroll()
        self.assertEqual(result, 1234.56)
        mock_read_text.assert_called_once()

    @patch('main.BANKROLL', 100.0)
    @patch.object(Path, 'read_text')
    def test_load_bankroll_file_exception(self, mock_read_text):
        """Test that load_bankroll returns config.BANKROLL when reading the file raises an exception."""
        mock_read_text.side_effect = Exception("File not found or permission error")

        result = main.load_bankroll()
        self.assertEqual(result, 100.0)
        mock_read_text.assert_called_once()

    @patch('main.BANKROLL', 100.0)
    @patch.object(Path, 'read_text')
    def test_load_bankroll_invalid_format(self, mock_read_text):
        """Test that load_bankroll returns config.BANKROLL when the file contains invalid data (ValueError)."""
        mock_read_text.return_value = "not_a_number"

        result = main.load_bankroll()
        self.assertEqual(result, 100.0)
        mock_read_text.assert_called_once()


if __name__ == '__main__':
    unittest.main()