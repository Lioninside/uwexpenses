"""
Parse Revolut CSV account statement exports.

Real Revolut CSV format (comma-separated, UTF-8):
  Art, Produkt, Datum des Beginns, Datum des Abschlusses,
  Beschreibung, Betrag, Gebühr, Währung, Status, Kontostand

Amounts are plain numbers (-6.68), currency is a separate column.
"""
import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.revolut_parser import filter_transactions  # reuse date filter

_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",  # Revolut: 2026-01-01 11:53:25
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y %H:%M:%S",
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
]


def _parse_date(s: str) -> Optional[date]:
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(s: str) -> Optional[float]:
    if not s or s.strip() == "":
        return None
    s = s.strip().replace(" ", "")
    try:
        return float(s)
    except ValueError:
        pass
    # European comma decimal fallback
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Column name → semantic type
# Handles both correct UTF-8 and garbled latin-1 variants of umlauts
# ---------------------------------------------------------------------------
_COL_MAP: Dict[str, str] = {
    # date
    "datum des beginns": "date",
    "datum des abschlusses": "date_settled",
    "started date": "date",
    "completed date": "date_settled",
    "datum": "date",
    "date": "date",
    # description
    "beschreibung": "desc",
    "description": "desc",
    "merchant": "desc",
    "name": "desc",
    # amount
    "betrag": "amount",
    "amount": "amount",
    # fee
    "gebühr": "fee",
    "gebuehr": "fee",
    "gebã¼hr": "fee",   # garbled UTF-8 read as latin-1
    "fee": "fee",
    # currency
    "währung": "currency",
    "waehrung": "currency",
    "wã¤hrung": "currency",  # garbled
    "currency": "currency",
    "ccy": "currency",
    # balance
    "kontostand": "balance",
    "saldo": "balance",
    "guthaben": "balance",
    "balance": "balance",
    # ignore
    "art": "ignore",
    "produkt": "ignore",
    "status": "ignore",
    "type": "ignore",
    "product": "ignore",
}


def _norm(h: str) -> str:
    h = h.lower().strip().replace("\n", " ")
    return _COL_MAP.get(h, "")


def _detect_delimiter(sample: str) -> str:
    counts = {d: sample.count(d) for d in (";", ",", "\t")}
    return max(counts, key=counts.get)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_revolut_csv(csv_path: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Revolut CSV export.
    Returns (transactions, issues).
    """
    transactions: List[Dict] = []
    issues: List[str] = []

    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    text: Optional[str] = None
    used_enc = ""

    for enc in encodings:
        try:
            text = Path(csv_path).read_text(encoding=enc)
            used_enc = enc
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        issues.append("CSV-Datei konnte nicht gelesen werden (Encoding-Fehler).")
        return [], issues

    # Normalise line endings so csv module doesn't choke
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    delimiter = _detect_delimiter(text[:2000])

    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    except Exception as exc:
        issues.append(f"CSV-Fehler: {exc}")
        return [], issues

    if not reader.fieldnames:
        issues.append("CSV hat keine Spaltenheader.")
        return [], issues

    # Map raw fieldnames to semantic types
    col_map: Dict[str, str] = {}
    for field in reader.fieldnames:
        sem = _norm(field)
        if sem and sem not in col_map.values():
            col_map[field] = sem

    if "date" not in col_map.values() and "date_settled" not in col_map.values():
        issues.append(
            f"Keine Datumsspalte gefunden. Spalten: {list(reader.fieldnames)}"
        )
        return [], issues

    tx_id = 0
    for row in reader:
        if not any(v.strip() for v in row.values() if v):
            continue

        def get(sem: str) -> str:
            for f, s in col_map.items():
                if s == sem:
                    return (row.get(f) or "").strip()
            return ""

        # Date: prefer "Datum des Beginns" (when you spent), fall back to settled
        raw_date = get("date") or get("date_settled")
        tx_date = _parse_date(raw_date)
        if not tx_date:
            continue

        desc = get("desc") or "Unknown"

        # Amount is a plain number in this format
        amount = _parse_amount(get("amount"))
        if amount is None:
            continue

        currency = get("currency") or "CHF"
        fee = _parse_amount(get("fee"))
        balance = _parse_amount(get("balance"))

        transactions.append({
            "id": f"tx_{tx_id:04d}",
            "date": tx_date.isoformat(),
            "description": desc,
            "category": "",
            "amount": amount,
            "currency": currency,
            "balance": balance,
            "fee": fee,
            "raw": str(dict(row)),
        })
        tx_id += 1

    if not transactions:
        issues.append("Keine Transaktionen in der CSV-Datei gefunden.")

    return transactions, issues
