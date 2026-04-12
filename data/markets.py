"""
data/markets.py
Fetches active markets from Polymarket's public Gamma API.
No auth required.
"""

import requests
import pandas as pd
import json
import logging
import re
from config import GAMMA_URL, MARKET_LIMIT, TARGET_TAGS

logger = logging.getLogger(__name__)
SESSION = requests.Session()
SESSION.trust_env = False
MAX_MATCHED_MARKETS = 300


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _parse_market(m: dict) -> dict | None:
    """Normalize a raw Gamma market object into a flat dict."""
    try:
        outcomes = json.loads(m.get("outcomes", "[]"))
        prices   = json.loads(m.get("outcomePrices", "[]"))

        # Only handle binary YES/NO markets for Phase 1
        if len(outcomes) != 2 or len(prices) != 2:
            return None

        yes_price = float(prices[0])
        no_price  = float(prices[1])

        tags = [t.get("slug", "").lower() for t in (m.get("tags") or [])]

        return {
            "market_id":        m.get("id", ""),
            "question":         m.get("question", ""),
            "slug":             m.get("slug", ""),
            "yes_price":        yes_price,
            "no_price":         no_price,
            "spread":           abs(1.0 - yes_price - no_price),
            "liquidity":        float(m.get("liquidityNum", 0) or 0),
            "volume":           float(m.get("volumeNum", 0) or 0),
            "one_day_change":   float(m.get("oneDayPriceChange", 0) or 0),
            "last_trade_price": float(m.get("lastTradePrice", yes_price) or yes_price),
            "end_date":         m.get("endDate", ""),
            "tags":             ",".join(tags),
            "active":           m.get("active", False),
            "closed":           m.get("closed", False),
        }
    except Exception as e:
        logger.debug(f"Parse error on market {m.get('id')}: {e}")
        return None


def _matches_target(parsed: dict, raw: dict, targets: set[str]) -> tuple[bool, str]:
    if not targets:
        return True, "none"

    market_tags = {tag for tag in parsed["tags"].split(",") if tag}
    if market_tags.intersection(targets):
        return True, "tags"

    search_blob = _normalize_text(
        " ".join(
            [
                parsed.get("question", ""),
                parsed.get("slug", ""),
                raw.get("question", ""),
                raw.get("slug", ""),
            ]
        )
    )
    if any(target in search_blob for target in targets):
        return True, "text"

    return False, "none"


def fetch_single_market(market_id: str) -> dict | None:
    """Fetch a single market by ID from Gamma API."""
    try:
        resp = SESSION.get(f"{GAMMA_URL}/markets/{market_id}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data:
            return _parse_market(data)
    except Exception as e:
        logger.debug(f"Failed to fetch market {market_id}: {e}")
    return None

def fetch_markets(tags: list[str] = None) -> pd.DataFrame:
    """
    Fetch active binary markets from Gamma API.
    Optionally filter to markets matching any tag in `tags`.
    Returns a DataFrame.
    """
    all_markets = []
    raw_binary_count = 0
    offset = 0

    tags_to_match = {_normalize_text(tag) for tag in (tags or TARGET_TAGS)}
    matched_from_tags = 0
    matched_from_text = 0

    while True:
        try:
            resp = SESSION.get(
                f"{GAMMA_URL}/markets",
                params={
                    "active":     "true",
                    "closed":     "false",
                    "limit":      MARKET_LIMIT,
                    "offset":     offset,
                    "order":      "volume",
                    "ascending":  "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"Gamma API fetch failed: {e}")
            return pd.DataFrame()

        if not data:
            break

        for raw in data:
            parsed = _parse_market(raw)
            if parsed is None:
                continue
            raw_binary_count += 1

            # Tag filter — keep market if ANY tag matches
            matched, source = _matches_target(parsed, raw, tags_to_match)
            if not matched:
                continue
            if source == "tags":
                matched_from_tags += 1
            elif source == "text":
                matched_from_text += 1

            all_markets.append(parsed)
            if len(all_markets) >= MAX_MATCHED_MARKETS:
                logger.info("Stopping intake early after %s matched markets", MAX_MATCHED_MARKETS)
                break

        # Gamma returns fewer than MARKET_LIMIT → we've hit the end
        if len(all_markets) >= MAX_MATCHED_MARKETS or len(data) < MARKET_LIMIT:
            break

        offset += MARKET_LIMIT
        logger.info("Fetched %s markets so far...", len(all_markets))

    logger.info(f"Raw binary markets fetched: {raw_binary_count}")
    if not all_markets:
        logger.warning("No markets passed tag filters.")
        return pd.DataFrame()

    df = pd.DataFrame(all_markets)
    logger.info(
        "Target matches kept: %s total | %s via tags | %s via question/slug",
        len(df),
        matched_from_tags,
        matched_from_text,
    )
    logger.info(f"Markets after tag filter: {len(df)}")
    return df
