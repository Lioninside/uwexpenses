"""
Suggest receipt matches for each business expense transaction.

Matching strategy (v1, no OCR):
  - Score receipts by proximity of their image_datetime to the transaction date.
  - Closer = higher score.
  - Return top-N candidates sorted by score.
"""
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple


def suggest_matches(
    transaction: Dict,
    receipts: List[Dict],
    already_matched: Dict[str, str],
    top_n: int = 5,
) -> List[Dict]:
    """
    Return up to *top_n* receipt dicts sorted by date proximity to *transaction*.

    Each returned dict is a copy of the receipt dict with an added "score" key
    (higher = better match) and a "already_used" flag.
    """
    tx_date = _tx_date(transaction)
    if tx_date is None:
        return []

    used_receipts = set(already_matched.values()) - {""}

    scored: List[Tuple[float, Dict]] = []
    for receipt in receipts:
        try:
            r_dt = datetime.fromisoformat(receipt["image_datetime"])
            r_date = r_dt.date()
        except (ValueError, KeyError):
            continue

        days_diff = abs((r_date - tx_date).days)
        score = max(0, 7 - days_diff)  # Perfect if same day, 0 if 7+ days apart

        candidate = dict(receipt)
        candidate["score"] = score
        candidate["already_used"] = receipt["working_filename"] in used_receipts
        scored.append((score, candidate))

    scored.sort(key=lambda x: (-x[0], x[1]["image_datetime"]))
    return [r for _, r in scored[:top_n]]


def _tx_date(tx: Dict) -> Optional[date]:
    try:
        return date.fromisoformat(tx["date"])
    except (ValueError, KeyError):
        return None
