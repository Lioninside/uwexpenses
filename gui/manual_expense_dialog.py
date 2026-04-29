"""
Dialog to add or edit a manual expense.

Manual expenses cover cash payments, non-Revolut cards, or anything
not in the bank statement. Receipt date is not used for matching –
the user picks the receipt file directly.
"""
import shutil
import uuid
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import core.storage as storage
from core.constants import NEEDS_REVIEW, NO_RECEIPT

_CURRENCIES = ["CHF", "EUR", "USD", "GBP", "SEK", "DKK", "NOK"]


class ManualExpenseDialog(QDialog):
    """
    Add or edit a manual expense.
    Returns the expense dict via .result_expense after exec().
    """

    def __init__(
        self,
        session: storage.SessionData,
        expense: Optional[Dict] = None,
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._editing = expense  # None = new, dict = edit existing
        self._selected_receipt: str = ""  # working_filename or sentinel
        self.result_expense: Optional[Dict] = None
        self.setWindowTitle("Manuelle Spese" if expense is None else "Spese bearbeiten")
        self.setMinimumWidth(520)
        self._setup_ui()
        if expense:
            self._load_expense(expense)

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(14)

        form_group = QGroupBox("Angaben zur Spese")
        form = QFormLayout(form_group)
        form.setSpacing(10)

        # Date
        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        form.addRow("Datum:", self._date_edit)

        # Description
        self._desc = QLineEdit()
        self._desc.setPlaceholderText("z.B. Taxi, Restaurantbesuch, Parkhaus ...")
        form.addRow("Beschreibung:", self._desc)

        # Amount
        self._amount = QLineEdit()
        self._amount.setPlaceholderText("z.B. 45.00")
        form.addRow("Betrag:", self._amount)

        # Currency
        self._currency = QComboBox()
        self._currency.addItems(_CURRENCIES)
        form.addRow("Waehrung:", self._currency)

        # Justification
        self._justification = QLineEdit()
        self._justification.setPlaceholderText(
            "Geschaeftszweck (z.B. Kundentermin Bern)"
        )
        form.addRow("Begruendung:", self._justification)

        root.addWidget(form_group)

        # Receipt selection
        receipt_group = QGroupBox("Beleg")
        rg = QVBoxLayout(receipt_group)

        self._receipt_label = QLabel("Kein Beleg ausgewaehlt")
        self._receipt_label.setWordWrap(True)
        self._receipt_label.setStyleSheet("color: #555; font-style: italic;")
        rg.addWidget(self._receipt_label)

        btn_row = QHBoxLayout()
        btn_browse = QPushButton("Datei auswaehlen ...")
        btn_browse.clicked.connect(self._pick_receipt)
        btn_row.addWidget(btn_browse)

        btn_no = QPushButton("Kein Beleg vorhanden")
        btn_no.setObjectName("btn_private")
        btn_no.clicked.connect(self._set_no_receipt)
        btn_row.addWidget(btn_no)

        btn_review = QPushButton("Noch unklar")
        btn_review.setObjectName("btn_review")
        btn_review.clicked.connect(self._set_needs_review)
        btn_row.addWidget(btn_review)

        btn_row.addStretch()
        rg.addLayout(btn_row)
        root.addWidget(receipt_group)

        # Standard OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    def _load_expense(self, expense: Dict) -> None:

        try:
            d = date.fromisoformat(expense["date"])
            self._date_edit.setDate(QDate(d.year, d.month, d.day))
        except (ValueError, KeyError):
            pass
        self._desc.setText(expense.get("description", ""))
        amt = expense.get("amount", "")
        self._amount.setText(str(abs(amt)) if isinstance(amt, float) else str(amt))
        cur = expense.get("currency", "CHF")
        idx = self._currency.findText(cur)
        if idx >= 0:
            self._currency.setCurrentIndex(idx)
        self._justification.setText(
            self._session.justifications.get(expense.get("id", ""), "")
        )
        matched = self._session.matches.get(expense.get("id", ""), "")
        self._selected_receipt = matched
        self._update_receipt_label(matched)

    def _update_receipt_label(self, value: str) -> None:
        if value == NO_RECEIPT:
            self._receipt_label.setText("Kein Beleg vorhanden")
            self._receipt_label.setStyleSheet("color: #888;")
        elif value == NEEDS_REVIEW:
            self._receipt_label.setText("Noch unklar / pruefen")
            self._receipt_label.setStyleSheet("color: #E07B00;")
        elif value:
            self._receipt_label.setText(f"Beleg: {value}")
            self._receipt_label.setStyleSheet("color: #1A7340; font-weight: bold;")
        else:
            self._receipt_label.setText("Kein Beleg ausgewaehlt")
            self._receipt_label.setStyleSheet("color: #555; font-style: italic;")

    def _pick_receipt(self) -> None:
        """Browse for any file in the folder – no date restriction."""
        start = self._session.folder
        if self._session.output_dir:
            working = Path(self._session.output_dir) / "01_working"
            if working.exists():
                start = str(working)

        path, _ = QFileDialog.getOpenFileName(
            self, "Beleg auswaehlen", start,
            "Belege (*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG *.pdf *.PDF)"
        )
        if not path:
            return

        p = Path(path)
        # Copy to working dir if not already there
        working_name = self._ensure_in_working(p)
        self._selected_receipt = working_name
        self._update_receipt_label(working_name)

        # Add to receipts index if missing
        existing = next(
            (r for r in self._session.receipts
             if r["working_filename"] == working_name), None
        )
        if not existing:
            self._session.receipts.append({
                "original_filename": p.name,
                "working_filename": working_name,
                "image_datetime": "",
                "source": "manual",
                "notes": "Manuell hinzugefuegt",
                "is_pdf": p.suffix.lower() == ".pdf",
            })

    def _ensure_in_working(self, src: Path) -> str:
        """Copy src to 01_working/ if needed. Returns the working filename."""
        if not self._session.output_dir:
            return src.name
        working_dir = Path(self._session.output_dir) / "01_working"
        working_dir.mkdir(parents=True, exist_ok=True)
        dest = working_dir / src.name
        if not dest.exists():
            shutil.copy2(str(src), str(dest))
        return src.name

    def _set_no_receipt(self) -> None:
        self._selected_receipt = NO_RECEIPT
        self._update_receipt_label(NO_RECEIPT)

    def _set_needs_review(self) -> None:
        self._selected_receipt = NEEDS_REVIEW
        self._update_receipt_label(NEEDS_REVIEW)

    def _on_ok(self) -> None:
        # Validate
        desc = self._desc.text().strip()
        if not desc:
            QMessageBox.warning(self, "Fehler", "Bitte eine Beschreibung eingeben.")
            return
        amt_text = self._amount.text().strip().replace(",", ".")
        try:
            amount = float(amt_text)
        except ValueError:
            QMessageBox.warning(self, "Fehler", "Betrag ungueltig (z.B. 45.00).")
            return

        qd = self._date_edit.date()

        tx_date = date(qd.year(), qd.month(), qd.day())

        # Preserve existing ID when editing
        if self._editing:
            tx_id = self._editing["id"]
        else:
            tx_id = f"manual_{uuid.uuid4().hex[:8]}"

        self.result_expense = {
            "id": tx_id,
            "date": tx_date.isoformat(),
            "description": desc,
            "category": "Manuell",
            "amount": -abs(amount),   # expenses are always negative
            "currency": self._currency.currentText(),
            "balance": None,
            "fee": None,
            "raw": "manual",
        }
        self._justification_text = self._justification.text().strip()
        self.accept()
