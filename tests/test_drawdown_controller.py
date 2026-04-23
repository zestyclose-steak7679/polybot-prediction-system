import unittest
from unittest.mock import patch, MagicMock
from risk.drawdown_controller import get_size_multiplier

class TestDrawdownController(unittest.TestCase):

    @patch('risk.drawdown_controller.Path')
    def test_get_size_multiplier_peak_update(self, mock_path):
        # Mocking Path(PEAK_FILE).read_text().strip()
        mock_file = MagicMock()
        mock_file.read_text.return_value = "1000.0"
        mock_path.return_value = mock_file

        # Bankroll higher than peak
        multiplier, label = get_size_multiplier(1100.0)

        self.assertEqual(multiplier, 1.0)
        self.assertEqual(label, "✅ Normal")
        # Verify peak update was saved
        mock_file.write_text.assert_called_once_with("1100.0")

    @patch('risk.drawdown_controller.Path')
    def test_get_size_multiplier_normal(self, mock_path):
        mock_file = MagicMock()
        mock_file.read_text.return_value = "1000.0"
        mock_path.return_value = mock_file

        # 5% drawdown (1000 -> 950)
        multiplier, label = get_size_multiplier(950.0)

        self.assertEqual(multiplier, 1.0)
        self.assertEqual(label, "✅ Normal")
        # Should NOT save peak if bankroll < peak
        self.assertFalse(mock_file.write_text.called)

    @patch('risk.drawdown_controller.Path')
    def test_get_size_multiplier_reduced(self, mock_path):
        mock_file = MagicMock()
        mock_file.read_text.return_value = "1000.0"
        mock_path.return_value = mock_file

        # 15% drawdown (1000 -> 850)
        multiplier, label = get_size_multiplier(850.0)

        self.assertEqual(multiplier, 0.5)
        self.assertEqual(label, "⚡ Reduced")

    @patch('risk.drawdown_controller.Path')
    def test_get_size_multiplier_halt(self, mock_path):
        mock_file = MagicMock()
        mock_file.read_text.return_value = "1000.0"
        mock_path.return_value = mock_file

        # 25% drawdown (1000 -> 750)
        multiplier, label = get_size_multiplier(750.0)

        self.assertEqual(multiplier, 0.0)
        self.assertEqual(label, "🛑 HALT")

    @patch('risk.drawdown_controller._load_peak')
    @patch('risk.drawdown_controller.logger')
    def test_get_size_multiplier_exception(self, mock_logger, mock_load_peak):
        mock_load_peak.side_effect = Exception("Test Error")

        multiplier, label = get_size_multiplier(1000.0)

        self.assertEqual(multiplier, 1.0)
        self.assertEqual(label, "ok")
        mock_logger.error.assert_called_once()

if __name__ == '__main__':
    unittest.main()
