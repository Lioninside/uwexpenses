"""
Create the Excel expense report.

Sheets:
  1. "Spesenabrechnung"  – the official expense table (Uwe format)
  2. "Alle Transaktionen" – all Revolut transactions (for reference)
  3. "Privat / Ausgeschlossen" – private transactions
  4. "Beleg-Zuordnung" – receipt matching table
  5. "Probleme" – issues / warnings
"""
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_ALT_FILL = PatternFill("solid", fgColor="D6E4F0")
_SWISS_FILL = PatternFill("solid", fgColor="FFD6D6")   # light red for Swiss rows
_THIN = Side(style="thin", color="AAAAAA")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_EXPENSE_COLS = [
    ("Datum",        12),
    ("Beleg",         8),
    ("Ort",          30),
    ("Begründung",   40),
    ("Wrg",           6),
    ("Betrag in FW", 14),
    ("Betrag in CHF",14),
    ("Schweiz",       10),
]


def _write_header(ws, row: int, cols: List[tuple]) -> None:
    for col_idx, (label, width) in enumerate(cols, 1):
        cell = ws.cell(row=row, column=col_idx, value=label)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width


def _write_data_row(ws, row: int, values: List, alternate: bool = False,
                    swiss: bool = False) -> None:
    fill = _SWISS_FILL if swiss else (_ALT_FILL if alternate else None)
    for col_idx, value in enumerate(values, 1):
        cell = ws.cell(row=row, column=col_idx, value=value)
        cell.border = _BORDER
        if fill:
            cell.fill = fill
        if col_idx == 1 and isinstance(value, date):
            cell.number_format = "DD.MM.YYYY"
        if isinstance(value, float):
            cell.number_format = '#,##0.00'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_excel(
    output_path: Path,
    template_path: Optional[Path],
    business_transactions: List[Dict],
    all_transactions: List[Dict],
    receipts: List[Dict],
    classifications: Dict[str, str],
    matches: Dict[str, str],
    justifications: Dict[str, str],
    receipt_numbers: Dict[str, str],
    swiss_flags: Dict[str, bool],
    issues: List[str],
) -> None:
    """Write the complete Excel file to *output_path*."""

    if template_path and template_path.exists():
        wb = openpyxl.load_workbook(str(template_path))
    else:
        wb = openpyxl.Workbook()
        # Remove default sheet; we'll create named ones
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

    # ---- Sheet 1: Expense report ----
    _write_expense_sheet(wb, business_transactions, receipt_numbers,
                         justifications, matches, swiss_flags)

    # ---- Sheet 2: All transactions ----
    _write_all_transactions_sheet(wb, all_transactions)

    # ---- Sheet 3: Private ----
    private_txs = [t for t in all_transactions
                   if classifications.get(t["id"]) == "private"]
    _write_private_sheet(wb, private_txs)

    # ---- Sheet 4: Receipt matching ----
    receipt_map = {r["working_filename"]: r for r in receipts}
    _write_matching_sheet(wb, business_transactions, receipt_numbers,
                          matches, receipt_map)

    # ---- Sheet 5: Issues ----
    _write_issues_sheet(wb, issues)

    wb.save(str(output_path))


def _write_expense_sheet(
    wb, transactions: List[Dict],
    receipt_numbers: Dict[str, str],
    justifications: Dict[str, str],
    matches: Dict[str, str],
    swiss_flags: Dict[str, bool],
) -> None:
    sheet_name = "Spesenabrechnung"
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        ws = wb.create_sheet(sheet_name, 0)

    ws.row_dimensions[1].height = 20
    _write_header(ws, 1, _EXPENSE_COLS)

    for row_idx, tx in enumerate(transactions, 2):
        try:
            tx_date = date.fromisoformat(tx["date"])
        except ValueError:
            tx_date = tx["date"]

        beleg = receipt_numbers.get(tx["id"], "")
        ort = tx.get("description", "")
        begruendung = justifications.get(tx["id"], "")
        wrg = tx.get("currency", "CHF")
        amount = tx.get("amount", 0.0) or 0.0
        is_swiss = swiss_flags.get(tx["id"], False)

        if wrg == "CHF":
            betrag_fw = ""
            betrag_chf = abs(amount)
        else:
            betrag_fw = abs(amount)
            betrag_chf = ""

        _write_data_row(ws, row_idx, [
            tx_date, beleg, ort, begruendung, wrg, betrag_fw, betrag_chf,
            "Ja" if is_swiss else "Nein",
        ], alternate=(row_idx % 2 == 0), swiss=is_swiss)

    # Auto-filter
    ws.auto_filter.ref = f"A1:{get_column_letter(len(_EXPENSE_COLS))}1"


def _write_all_transactions_sheet(wb, transactions: List[Dict]) -> None:
    cols = [
        ("ID",          10), ("Datum",      12), ("Beschreibung", 35),
        ("Kategorie",   16), ("Betrag",     12), ("Währung",       8),
        ("Saldo",       12), ("Gebühr",     10),
    ]
    sheet_name = "Alle Transaktionen"
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
    _write_header(ws, 1, cols)
    for row_idx, tx in enumerate(transactions, 2):
        try:
            tx_date = date.fromisoformat(tx["date"])
        except ValueError:
            tx_date = tx["date"]
        _write_data_row(ws, row_idx, [
            tx["id"], tx_date, tx.get("description", ""),
            tx.get("category", ""), tx.get("amount", ""),
            tx.get("currency", ""), tx.get("balance", ""), tx.get("fee", ""),
        ], alternate=(row_idx % 2 == 0))
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"


def _write_private_sheet(wb, transactions: List[Dict]) -> None:
    cols = [
        ("Datum", 12), ("Beschreibung", 35), ("Betrag", 12), ("Waehrung", 8),
    ]
    sheet_name = "Privat Ausgeschlossen"
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
    _write_header(ws, 1, cols)
    for row_idx, tx in enumerate(transactions, 2):
        try:
            tx_date = date.fromisoformat(tx["date"])
        except ValueError:
            tx_date = tx["date"]
        _write_data_row(ws, row_idx, [
            tx_date, tx.get("description", ""),
            tx.get("amount", ""), tx.get("currency", ""),
        ], alternate=(row_idx % 2 == 0))


def _write_matching_sheet(
    wb,
    business_txs: List[Dict],
    receipt_numbers: Dict[str, str],
    matches: Dict[str, str],
    receipt_map: Dict[str, Dict],
) -> None:
    cols = [
        ("Beleg-Nr.",  10), ("Datum",       12), ("Beschreibung", 30),
        ("Betrag",     12), ("Belegnr.",    10), ("Beleg-Datei",  30),
        ("Beleg-Datum",14),
    ]
    sheet_name = "Beleg-Zuordnung"
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
    _write_header(ws, 1, cols)
    for row_idx, tx in enumerate(business_txs, 2):
        try:
            tx_date = date.fromisoformat(tx["date"])
        except ValueError:
            tx_date = tx["date"]
        rec_num = receipt_numbers.get(tx["id"], "")
        matched_file = matches.get(tx["id"], "")
        receipt = receipt_map.get(matched_file, {})
        rec_date = receipt.get("image_datetime", "")[:10] if receipt else ""
        _write_data_row(ws, row_idx, [
            rec_num, tx_date, tx.get("description", ""),
            tx.get("amount", ""), rec_num, matched_file, rec_date,
        ], alternate=(row_idx % 2 == 0))


def _write_issues_sheet(wb, issues: List[str]) -> None:
    sheet_name = "Probleme"
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.create_sheet(sheet_name)
    ws.cell(1, 1, "Probleme / Warnungen").font = Font(bold=True)
    ws.column_dimensions["A"].width = 80
    for row_idx, issue in enumerate(issues, 2):
        ws.cell(row_idx, 1, issue)
    if not issues:
        ws.cell(2, 1, "Keine Probleme gefunden.")
