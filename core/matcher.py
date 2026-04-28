"""
Suggest receipt matches for each business expense transaction.

Combined scoring (v2):
  date_score   = max(0, 7 - days_diff)      →  0–7 pts
  amount_score = 10 if exact match (±0.01)  →  0 or 10 pts
               =  3 if close  match (±0.50)

Results are sorted by combined score descending, then by date proximity.
All receipts are returned (no cap) so nothing is ever hidden.
"""
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple


def suggest_matches(
    transaction: Dict,
    receipts: List[Dict],
    already_matched: Dict[str, str],
    top_n: int = 5,  # kept for API compatibility, not used
) -> List[Dict]:
    """
    Return ALL receipts sorted by combined date + amount score.
    Each dict gains: score, date_score, amount_score, amount_matched, already_used.
    """
    tx_date = _tx_date(transaction)
    tx_amount = abs(float(transaction.get("amount") or 0))
    used_receipts = set(already_matched.values()) - {""}

    scored: List[Tuple[int, int, Dict]] = []  # (total_score, days_diff, candidate)

    for receipt in receipts:
        # --- date score ---
        days_diff = 9999
        try:
            r_dt = datetime.fromisoformat(receipt["image_datetime"])
            if tx_date:
                days_diff = abs((r_dt.date() - tx_date).days)
        except (ValueError, KeyError):
            pass
        date_score = max(0, 7 - days_diff) if days_diff < 9999 else 0

        # --- amount score ---
        amount_score = 0
        amount_matched = False
        if tx_amount > 0:
            for ocr_amt in receipt.get("ocr_amounts", []):
                diff = abs(float(ocr_amt) - tx_amount)
                if diff <= 0.01:
                    amount_score = 10
                    amount_matched = True
                    break
                elif diff <= 0.50:
                    amount_score = max(amount_score, 3)

        total_score = date_score + amount_score

        candidate = dict(receipt)
        candidate["score"] = total_score
        candidate["date_score"] = date_score
        candidate["amount_score"] = amount_score
        candidate["amount_matched"] = amount_matched
        candidate["already_used"] = receipt["working_filename"] in used_receipts
        scored.append((total_score, days_diff, candidate))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [r for _, _, r in scored]


def _tx_date(tx: Dict) -> Optional[date]:
    try:
        return date.fromisoformat(tx["date"])
    except (ValueError, KeyError):
        return None
