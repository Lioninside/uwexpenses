"""
Parse Revolut CSV/XLSX account statement exports.

Revolut exports a file named .csv which is actually an Excel xlsx
where every row has a single cell in column A containing a full
comma-separated line of data. Umlauts are double-encoded
(UTF-8 bytes stored as Latin-1 chars).

Real columns (comma-separated inside each cell):
  Art, Produkt, Datum des Beginns, Datum des Abschlusses,
  Beschreibung, Betrag, Gebühr, Währung, Status, Kontostand

Amounts are plain numbers (-6.68). Currency is a separate column.
STORNIERT (cancelled) rows are skipped by default.
"""
import csv
import io
import zipfile
import xml.etree.ElementTree as ET
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

_SKIP_STATUSES = {"storniert", "declined", "abgelehnt", "failed"}


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
        # European comma fallback
        try:
            return float(s.replace(".", "").replace(",", "."))
        except ValueError:
            return None


def _fix_encoding(s: str) -> str:
    """Fix Revolut's double-encoded umlauts: latin-1 chars → UTF-8."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


# ---------------------------------------------------------------------------
# Column name → semantic type
# ---------------------------------------------------------------------------
_COL_MAP: Dict[str, str] = {
    "datum des beginns": "date",
    "datum des abschlusses": "date_settled",
    "started date": "date",
    "completed date": "date_settled",
    "datum": "date",
    "date": "date",
    "beschreibung": "desc",
    "description": "desc",
    "merchant": "desc",
    "name": "desc",
    "betrag": "amount",
    "amount": "amount",
    "gebühr": "fee",
    "gebuehr": "fee",
    "fee": "fee",
    "währung": "currency",
    "waehrung": "currency",
    "currency": "currency",
    "ccy": "currency",
    "kontostand": "balance",
    "saldo": "balance",
    "guthaben": "balance",
    "balance": "balance",
    "status": "status",
    "art": "ignore",
    "produkt": "ignore",
    "type": "ignore",
    "product": "ignore",
}


def _norm(h: str) -> str:
    return _COL_MAP.get(h.lower().strip(), "")


def _detect_delimiter(sample: str) -> str:
    counts = {d: sample.count(d) for d in (";", ",", "\t")}
    return max(counts, key=counts.get)


# ---------------------------------------------------------------------------
# xlsx unwrapper (Revolut's actual export format)
# ---------------------------------------------------------------------------

def _extract_text_from_xlsx(path: str) -> Optional[str]:
    """
    Revolut exports .csv files that are actually xlsx files where every
    row has one cell in column A containing a complete CSV line.
    Extract those lines and return them as plain text.
    """
    try:
        with zipfile.ZipFile(path) as z:
            if "xl/sharedStrings.xml" not in z.namelist():
                return None
            ss_xml = z.read("xl/sharedStrings.xml").decode("utf-8")
            root = ET.fromstring(ss_xml)
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            rows: List[str] = []
            for si in root.findall("x:si", ns):
                t = si.find("x:t", ns)
                if t is not None and t.text:
                    rows.append(_fix_encoding(t.text))
                else:
                    parts = [
                        r.find("x:t", ns).text or ""
                        for r in si.findall("x:r", ns)
                        if r.find("x:t", ns) is not None
                    ]
                    rows.append(_fix_encoding("".join(parts)))
            return "\n".join(rows) if rows else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_revolut_csv(csv_path: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Revolut statement file (.csv or xlsx-disguised-as-csv).
    Returns (transactions, issues).
    """
    transactions: List[Dict] = []
    issues: List[str] = []

    # Try xlsx unwrap first (Revolut's real format)
    text = _extract_text_from_xlsx(csv_path)
    if text:
        issues_from_detect = []
    else:
        # Plain text CSV fallback
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = Path(csv_path).read_text(encoding=enc)
                text = text.replace("\r\n", "\n").replace("\r", "\n")
                break
            except UnicodeDecodeError:
                continue
        else:
            issues.append("Datei konnte nicht gelesen werden.")
            return [], issues

    if not text:
        issues.append("Datei ist leer.")
        return [], issues

    delimiter = _detect_delimiter(text[:2000])

    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    except Exception as exc:
        issues.append(f"CSV-Fehler: {exc}")
        return [], issues

    if not reader.fieldnames:
        issues.append("Keine Spaltenheader gefunden.")
        return [], issues

    col_map: Dict[str, str] = {}
    for field in reader.fieldnames:
        sem = _norm(field)
        if sem and sem not in col_map.values():
            col_map[field] = sem

    if "date" not in col_map.values() and "date_settled" not in col_map.values():
        issues.append(
            f"Keine Datumsspalte. Spalten: {list(reader.fieldnames)}"
        )
        return [], issues

    tx_id = 0
    skipped_cancelled = 0

    for row in reader:
        if not any(v.strip() for v in row.values() if v):
            continue

        def get(sem: str) -> str:
            for f, s in col_map.items():
                if s == sem:
                    return (row.get(f) or "").strip()
            return ""

        # Skip cancelled/declined transactions
        status = get("status").lower()
        if status in _SKIP_STATUSES:
            skipped_cancelled += 1
            continue

        raw_date = get("date") or get("date_settled")
        tx_date = _parse_date(raw_date)
        if not tx_date:
            continue

        desc = _fix_encoding(get("desc") or "Unknown")
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

    if skipped_cancelled:
        issues.append(
            f"{skipped_cancelled} stornierte/abgelehnte Transaktionen wurden uebersprungen."
        )

    if not transactions:
        issues.append("Keine Transaktionen gefunden.")

    return transactions, issues
