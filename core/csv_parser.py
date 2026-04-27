"""
Parse Revolut CSV account statement exports.

The German Revolut CSV has these columns (semicolon-separated):
  Datum; Beschreibung; Geldeingang; Geldausgang; Betrag; Waehrung;
  Saldo; Kategorie; Anmerkungen

Or the English CSV variant:
  Date; Description; Money In; Money Out; Amount; Currency; Balance; Category; Notes

The app auto-detects delimiter and column names.
"""
import csv
import io
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_DATE_FORMATS = [
    "%d.%m.%Y",          # German: 02.01.2026
    "%Y-%m-%d",          # ISO
    "%d %b %Y",          # 02 Jan 2026
    "%d/%m/%Y",          # 02/01/2026
    "%b %d, %Y",         # Jan 02, 2026
    "%d %B %Y",          # 02 January 2026
    "%d.%m.%Y %H:%M:%S", # with time
    "%Y-%m-%d %H:%M:%S",
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
    s = s.strip().replace(" ", "").replace(" ", "")
    # Strip currency
    import re
    s = re.sub(r"[A-Z]{3}", "", s).strip()
    s = s.replace("−", "-").replace("–", "-")

    last_comma = s.rfind(",")
    last_dot = s.rfind(".")
    if last_comma > last_dot:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_currency(s: str) -> str:
    import re
    m = re.search(r"\b([A-Z]{3})\b", s or "")
    return m.group(1) if m else "CHF"


# Column name normalization
_COL_MAP = {
    # date
    "datum": "date", "date": "date", "started date": "date", "completed date": "date",
    # description
    "beschreibung": "desc", "description": "desc", "name": "desc", "merchant": "desc",
    # combined amount (German Revolut CSV has "Betrag" as signed)
    "betrag": "amount", "amount": "amount",
    # money in
    "geldeingang": "in", "money in": "in", "paid in": "in", "credit": "in",
    "geld ein": "in",
    # money out
    "geldausgang": "out", "money out": "out", "paid out": "out", "debit": "out",
    "geld aus": "out",
    # currency
    "währung": "currency", "wahrung": "currency", "currency": "currency", "ccy": "currency",
    # balance
    "saldo": "balance", "balance": "balance", "guthaben": "balance",
    # category
    "kategorie": "category", "category": "category",
    # fee
    "gebühren": "fee", "gebuehren": "fee", "fee": "fee",
    # notes (ignore)
    "anmerkungen": "notes", "notes": "notes", "note": "notes",
}


def _norm_header(h: str) -> str:
    h = h.lower().strip().replace("\n", " ")
    result = _COL_MAP.get(h, "")
    if result:
        return result
    # Partial match for "Geld ein-/ausgezahlt" variants
    if "geld" in h and ("ein" in h or "aus" in h):
        return "amount"
    # Ignore tax columns
    if "steuer" in h or "einbehalt" in h:
        return "ignore"
    return ""


def parse_revolut_csv(csv_path: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Revolut CSV export.

    Returns (transactions, issues).
    """
    transactions: List[Dict] = []
    issues: List[str] = []

    try:
        raw = Path(csv_path).read_bytes()
        # Try UTF-8 BOM first, then UTF-8, then latin-1
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            issues.append("CSV-Datei konnte nicht dekodiert werden.")
            return [], issues

        # Detect delimiter
        sample = text[:2000]
        delimiters = [";", ",", "\t"]
        delimiter = max(delimiters, key=lambda d: sample.count(d))

        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

        if not reader.fieldnames:
            issues.append("CSV hat keine Spaltenheader.")
            return [], issues

        # Map fieldnames to semantic types
        col_map: Dict[str, str] = {}
        for field in reader.fieldnames:
            mapped = _norm_header(field)
            if mapped and mapped not in col_map.values():
                col_map[field] = mapped

        if "date" not in col_map.values():
            issues.append(
                f"Keine Datums-Spalte gefunden. Gefundene Spalten: "
                f"{list(reader.fieldnames)}"
            )
            return [], issues

        tx_id = 0
        for row_num, row in enumerate(reader, 2):
            if not any(row.values()):
                continue

            def get(semantic: str) -> str:
                for field, sem in col_map.items():
                    if sem == semantic:
                        return (row.get(field) or "").strip()
                return ""

            # Date
            tx_date = _parse_date(get("date"))
            if not tx_date:
                continue

            # Description
            desc = get("desc") or "Unknown"

            # Amount
            amount: Optional[float] = None
            currency = get("currency") or "CHF"

            raw_amount = get("amount")
            if raw_amount:
                amount = _parse_amount(raw_amount)

            if amount is None:
                raw_out = get("out")
                raw_in = get("in")
                out_val = _parse_amount(raw_out)
                in_val = _parse_amount(raw_in)
                if out_val is not None:
                    amount = -abs(out_val)
                elif in_val is not None:
                    amount = abs(in_val)

            if amount is None:
                continue

            # Currency from amount cell if not in dedicated column
            if not currency:
                for field, sem in col_map.items():
                    if sem == "amount":
                        currency = _extract_currency(row.get(field, "")) or "CHF"
                        break

            transactions.append({
                "id": f"tx_{tx_id:04d}",
                "date": tx_date.isoformat(),
                "description": desc,
                "category": get("category"),
                "amount": amount,
                "currency": currency,
                "balance": _parse_amount(get("balance")),
                "fee": _parse_amount(get("fee")),
                "raw": str(dict(row)),
            })
            tx_id += 1

    except Exception as exc:
        issues.append(f"Fehler beim Lesen der CSV: {exc}")

    if not transactions:
        issues.append("Keine Transaktionen in der CSV-Datei gefunden.")

    return transactions, issues


def filter_transactions(
    transactions: List[Dict],
    start: date,
    end: date,
    include_incoming: bool = False,
) -> List[Dict]:
    from core.revolut_parser import filter_transactions as _ft
    return _ft(transactions, start, end, include_incoming)
