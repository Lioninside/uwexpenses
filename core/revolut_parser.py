"""
Parse Revolut PDF bank statements.

Specifically tuned for the German Revolut export format:
  Datum | Beschreibung | Kategorie | Geld ein-/ausgezahlt | Guthaben |
  Einbehaltene Steuern | Andere Steuern | Gebuehren

Strategy:
  1. Extract tables with pdfplumber (best result for Revolut PDFs).
  2. Fall back to line-by-line text pattern matching.
  3. Normalise every row into a common transaction dict.
"""
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
_DATE_FORMATS = [
    "%d.%m.%Y",   # 02.01.2026  <-- German Revolut
    "%d %b %Y",   # 12 Jan 2024
    "%d %B %Y",   # 12 January 2024
    "%b %d, %Y",  # Jan 12, 2024
    "%Y-%m-%d",   # 2024-01-12
    "%d/%m/%Y",   # 12/01/2024
    "%d-%m-%Y",   # 12-01-2024
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
    """
    Parse amounts from German Revolut format:
      '-6,68 CHF'   (European decimal comma, no thousands sep)
      '907,18 CHF'
      '-1.234,56'   (European with thousands dot)
      '-1,234.56'   (Anglo format)
    """
    if not s:
        return None
    # Normalise: replace unicode minus U+2212, en-dash, non-breaking space
    s = s.replace("−", "-").replace("–", "-").replace(" ", " ").strip()
    # Strip currency codes (CHF, EUR, USD, GBP ...)
    s = re.sub(r"[A-Z]{3}", "", s).strip()

    m = re.search(r"(-?\s*[\d.,]+)", s)
    if not m:
        return None
    num = m.group(1).replace(" ", "")

    # Determine format by position of last comma vs last dot
    last_comma = num.rfind(",")
    last_dot = num.rfind(".")

    if last_comma > last_dot:
        # European decimal comma: '6,68' or '1.234,56'
        num = num.replace(".", "").replace(",", ".")
    else:
        # Anglo decimal dot: '6.68' or '1,234.56'
        num = num.replace(",", "")

    try:
        return float(num)
    except ValueError:
        return None


def _extract_currency(s: str) -> str:
    m = re.search(r"\b([A-Z]{3})\b", s or "")
    return m.group(1) if m else "CHF"


# ---------------------------------------------------------------------------
# Column-header recognition
# ---------------------------------------------------------------------------
_DATE_HEADERS = {"date", "datum", "completed date", "started date"}
_DESC_HEADERS = {"description", "merchant", "name", "details", "reference",
                 "transaction", "product", "type", "beschreibung"}
# German Revolut: "Geld ein-/ausgezahlt" is the combined in/out amount column
_AMOUNT_HEADERS = {"amount", "betrag", "total", "value",
                   "geld ein-/ausgezahlt", "geld ein/ausgezahlt",
                   "geld ein- /ausgezahlt", "betrag in chf",
                   "geld ein-\n/ausgezahlt"}
_OUT_HEADERS = {"money out", "paid out", "debit", "withdrawal"}
_IN_HEADERS = {"money in", "paid in", "credit", "deposit"}
_BALANCE_HEADERS = {"balance", "saldo", "running balance",
                    "guthaben", "kontostand"}
_FEE_HEADERS = {"fee", "charge", "gebuehren", "gebuhren",
                "gebühren", "gebühren"}
_CURRENCY_HEADERS = {"currency", "währung", "ccy"}
_CATEGORY_HEADERS = {"category", "kategorie"}
# Columns to silently skip
_IGNORE_HEADERS = {"einbehaltene steuern", "andere steuern",
                   "withholding tax", "other tax", "taxes"}


def _header_type(raw: str) -> str:
    h = raw.lower().strip().replace("\n", " ")
    if h in _IGNORE_HEADERS or "steuer" in h or "einbehalt" in h:
        return "ignore"
    if h in _DATE_HEADERS:
        return "date"
    if h in _DESC_HEADERS:
        return "desc"
    if h in _AMOUNT_HEADERS:
        return "amount"
    # Partial match for "Geld ein-/ausgezahlt" which may wrap across lines
    if "geld" in h and ("ein" in h or "aus" in h):
        return "amount"
    if h in _OUT_HEADERS:
        return "out"
    if h in _IN_HEADERS:
        return "in"
    if h in _BALANCE_HEADERS:
        return "balance"
    if h in _FEE_HEADERS:
        return "fee"
    if h in _CURRENCY_HEADERS:
        return "currency"
    if h in _CATEGORY_HEADERS:
        return "category"
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_revolut_pdf(pdf_path: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Revolut PDF and return (transactions, issues).

    Each transaction dict:
        id, date, description, category, amount, currency,
        balance, fee, raw
    """
    transactions: List[Dict] = []
    issues: List[str] = []
    tx_id = 0

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Try strict line-based tables first
                tables = page.extract_tables(
                    table_settings={
                        "vertical_strategy": "lines_strict",
                        "horizontal_strategy": "lines_strict",
                    }
                )
                if not tables:
                    tables = page.extract_tables()

                found_on_page = False
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    parsed, errs = _parse_table(table, tx_id)
                    if parsed:
                        transactions.extend(parsed)
                        tx_id += len(parsed)
                        found_on_page = True
                    issues.extend(errs)

                if not found_on_page:
                    text = page.extract_text() or ""
                    parsed, errs = _parse_text(text, tx_id, page_num)
                    transactions.extend(parsed)
                    tx_id += len(parsed)
                    issues.extend(errs)

    except Exception as exc:
        issues.append(f"Fehler beim Lesen des PDFs: {exc}")

    if not transactions:
        issues.append(
            "Keine Transaktionen gefunden. Das PDF verwendet moeglicherweise "
            "ein unbekanntes Layout. Bitte Revolut-Export als PDF sicherstellen."
        )

    return transactions, issues


def filter_transactions(
    transactions: List[Dict],
    start: date,
    end: date,
    include_incoming: bool = False,
) -> List[Dict]:
    result = []
    for tx in transactions:
        try:
            tx_date = date.fromisoformat(tx["date"])
        except (ValueError, KeyError):
            continue
        if tx_date < start or tx_date > end:
            continue
        if not include_incoming and tx["amount"] > 0:
            continue
        result.append(tx)
    return result


# ---------------------------------------------------------------------------
# Table parser
# ---------------------------------------------------------------------------

def _parse_table(table: List[List], start_id: int) -> Tuple[List[Dict], List[str]]:
    transactions: List[Dict] = []
    issues: List[str] = []

    # First row: detect headers
    raw_headers = [str(c or "").strip() for c in table[0]]
    col_map: Dict[str, int] = {}
    for i, h in enumerate(raw_headers):
        t = _header_type(h)
        if t and t not in col_map and t != "ignore":
            col_map[t] = i

    has_headers = bool(col_map)
    data_rows = table[1:] if has_headers else table

    for row in data_rows:
        if not row:
            continue
        cells = [str(c or "").strip() for c in row]
        if all(c == "" for c in cells):
            continue
        tx = _row_to_tx(cells, col_map, start_id + len(transactions))
        if tx:
            transactions.append(tx)

    return transactions, issues


def _row_to_tx(cells: List[str], col_map: Dict[str, int], tx_id: int) -> Optional[Dict]:
    def get(key: str) -> str:
        idx = col_map.get(key)
        if idx is not None and idx < len(cells):
            return cells[idx]
        return ""

    # --- date ---
    raw_date = get("date")
    if not raw_date:
        for c in cells:
            if _parse_date(c):
                raw_date = c
                break
    tx_date = _parse_date(raw_date)
    if not tx_date:
        return None

    # --- description ---
    desc = get("desc")
    if not desc:
        candidates = [
            c for c in cells
            if c and not _parse_date(c) and not re.fullmatch(r"[-\d.,\s%]+", c)
        ]
        desc = max(candidates, key=len, default="Unknown")

    # --- category ---
    category = get("category")

    # --- amount ---
    amount: Optional[float] = None
    currency = "CHF"

    if "amount" in col_map:
        raw_amt = get("amount")
        currency = _extract_currency(raw_amt) or get("currency") or "CHF"
        amount = _parse_amount(raw_amt)
    elif "out" in col_map or "in" in col_map:
        raw_out = get("out")
        raw_in = get("in")
        currency = _extract_currency(raw_out or raw_in or "") or get("currency") or "CHF"
        out_val = _parse_amount(raw_out)
        in_val = _parse_amount(raw_in)
        if out_val is not None:
            amount = -abs(out_val)
        elif in_val is not None:
            amount = abs(in_val)

    if amount is None:
        # Scan cells right-to-left for any numeric value
        for c in reversed(cells):
            v = _parse_amount(c)
            if v is not None:
                currency = _extract_currency(c) or "CHF"
                amount = v
                break

    if amount is None:
        return None

    return {
        "id": f"tx_{tx_id:04d}",
        "date": tx_date.isoformat(),
        "description": desc,
        "category": category,
        "amount": amount,
        "currency": currency,
        "balance": _parse_amount(get("balance")),
        "fee": _parse_amount(get("fee")),
        "raw": " | ".join(cells),
    }


# ---------------------------------------------------------------------------
# Text fallback parser (German Revolut date format: DD.MM.YYYY)
# ---------------------------------------------------------------------------
_TX_PATTERN = re.compile(
    r"(\d{2}\.\d{2}\.\d{4})"              # date  02.01.2026
    r"(.+?)"                               # description
    r"(-[\d.,]+)\s*(CHF|EUR|USD|GBP)?"    # negative amount
    r"(?:\s+([\d.,]+)\s*(CHF|EUR|USD|GBP))?",  # optional balance
    re.MULTILINE,
)


def _parse_text(text: str, start_id: int, page_num: int) -> Tuple[List[Dict], List[str]]:
    transactions: List[Dict] = []
    issues: List[str] = []

    for m in _TX_PATTERN.finditer(text):
        tx_date = _parse_date(m.group(1))
        if not tx_date:
            continue
        desc = m.group(2).strip()
        amount = _parse_amount(m.group(3))
        if amount is None:
            continue
        currency = m.group(4) or "CHF"
        balance = _parse_amount(m.group(5)) if m.group(5) else None

        transactions.append({
            "id": f"tx_{start_id + len(transactions):04d}",
            "date": tx_date.isoformat(),
            "description": desc,
            "category": "",
            "amount": amount,
            "currency": currency,
            "balance": balance,
            "fee": None,
            "raw": m.group(0),
        })

    return transactions, issues
