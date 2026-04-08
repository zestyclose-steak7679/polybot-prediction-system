"""risk/drawdown_controller.py — volatility-scaled survival mode"""
import logging
from pathlib import Path
logger = logging.getLogger(__name__)

PEAK_FILE = "peak_bankroll.txt"

def _load_peak(current: float) -> float:
    try:
        return max(float(Path(PEAK_FILE).read_text().strip()), current)
    except Exception:
        return current

def _save_peak(peak: float):
    Path(PEAK_FILE).write_text(str(round(peak, 2)))

def get_size_multiplier(bankroll: float) -> tuple[float, str]:
    """
    Returns (multiplier, status_label).
    multiplier: scale applied to all bet sizes this cycle.

    Drawdown tiers:
      < 10%  → full size (1.0)
      10-15% → 75% size
      15-20% → 50% size (caution)
      > 20%  → 0% (halt — handled by risk/controls.py separately)
    """
    peak = _load_peak(bankroll)
    if bankroll >= peak:
        _save_peak(bankroll)
        return 1.0, "✅ Normal"

    drawdown = (peak - bankroll) / peak

    if drawdown >= 0.20:
        return 0.0, "🛑 HALT"
    elif drawdown >= 0.15:
        return 0.5, "⚠️ Caution"
    elif drawdown >= 0.10:
        return 0.75, "⚡ Reduced"
    else:
        return 1.0, "✅ Normal"
