──────────────────────────────────────────
SECTION 1 — Execution Regression Fix
──────────────────────────────────────────
Confirm by checking next Telegram POLYBOT SUMMARY:

[ ] "executed" count is > 0 (target: 5, matching pre-regression)
[ ] Log shows: "SHADOW execute attempt | market: X | strategy: Y"
[ ] No new exceptions in execution/engine.py logs
[ ] "0 risk blocked" still present (risk engine untouched)

FAIL condition: executed = 0 again → revert last commit immediately

──────────────────────────────────────────
SECTION 2 — Momentum Kill Guard
──────────────────────────────────────────
Confirm by checking next Telegram POLYBOT SUMMARY:

[ ] STRATEGIES line shows: "✅ momentum | ✅ reversal | ✅ volume_spike"
[ ] momentum no longer shows "(disabled)"
[ ] learning/tracker.py logs show: "skipping kill eval — insufficient bets"
    (or equivalent log from the guard you added)
[ ] killed_strategies.json still empty (momentum not re-killed)

FAIL condition: momentum still shows (disabled) → guard not reached,
check if strategy_bet_count variable name matches what tracker.py uses

──────────────────────────────────────────
SECTION 3 — Regime + META Wiring
──────────────────────────────────────────
Confirm by checking next Telegram POLYBOT SUMMARY:

[ ] MODEL line shows: "H/CLV- | META: 0.XX | Regime: volatile"
    (Regime must NOT be N/A)
[ ] META shows a float between 0.0 and 1.0 (not "-" or "None")
[ ] Regime value matches weekly report "Regime distribution: volatile"
[ ] Weekly report regime still populates correctly (not broken by change)

FAIL condition A: Regime still N/A → dom_regime not in scope at
  clv["regime"] = dom_regime line, check variable name in main.py

FAIL condition B: META still "-" → avg_confidence is None,
  check if sig.confidence is being set before send_summary is called

──────────────────────────────────────────
MASTER PASS CRITERIA (all 3 fixes confirmed)
──────────────────────────────────────────
Next POLYBOT SUMMARY must show ALL of:

[ ] executed: > 0
[ ] ✅ momentum | ✅ reversal | ✅ volume_spike
[ ] Regime: volatile (or trending/ranging — NOT N/A)
[ ] META: 0.XX (float — NOT "-")

Only when all 4 boxes are checked → system is stable for Phase 2.
