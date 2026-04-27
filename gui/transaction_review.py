"""
Step 2: Manual transaction classification.

Shows one transaction at a time. User classifies as:
  Business (green)  |  Private (grey)  |  Needs Review (orange)

Progress is auto-saved after every decision.
"""
from typing import Callable, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget, QProgressBar,
    QScrollArea, QSizePolicy,
)

import core.storage as storage


class TransactionReviewPage(QWidget):
    def __init__(self, on_continue: Callable[[storage.SessionData], None]) -> None:
        super().__init__()
        self._on_continue = on_continue
        self._session: storage.SessionData = None
        self._current_idx: int = 0
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 24, 40, 24)
        root.setSpacing(16)

        title = QLabel("Schritt 2 – Transaktionen klassifizieren")
        title.setObjectName("heading")
        root.addWidget(title)

        # Progress bar
        self._progress = QProgressBar()
        root.addWidget(self._progress)
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("status")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._progress_label)

        # Transaction card
        card_group = QGroupBox("Aktuelle Transaktion")
        card_layout = QVBoxLayout(card_group)
        card_layout.setSpacing(8)

        row_style = "QLabel { font-size: 13px; }"

        def info_row(label_text: str) -> tuple:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(130)
            lbl.setStyleSheet("font-weight: bold; color: #555;")
            val = QLabel("")
            val.setWordWrap(True)
            val.setStyleSheet("color: #111; font-size: 14px;")
            row.addWidget(lbl)
            row.addWidget(val, 1)
            return row, val

        row1, self._lbl_date = info_row("Datum:")
        card_layout.addLayout(row1)
        row2, self._lbl_desc = info_row("Beschreibung:")
        card_layout.addLayout(row2)
        row3, self._lbl_amount = info_row("Betrag:")
        card_layout.addLayout(row3)
        row4, self._lbl_category = info_row("Kategorie:")
        card_layout.addLayout(row4)
        row5, self._lbl_currency = info_row("Währung:")
        card_layout.addLayout(row5)

        # Justification
        just_row = QHBoxLayout()
        just_lbl = QLabel("Begründung:")
        just_lbl.setFixedWidth(130)
        just_lbl.setStyleSheet("font-weight: bold; color: #555;")
        self._justification = QLineEdit()
        self._justification.setPlaceholderText(
            "Kurze Beschreibung des Geschäftszwecks (optional, aber empfohlen)"
        )
        just_row.addWidget(just_lbl)
        just_row.addWidget(self._justification, 1)
        card_layout.addLayout(just_row)

        root.addWidget(card_group)

        # Classification buttons
        btn_group = QGroupBox("Klassifizierung")
        btn_layout = QHBoxLayout(btn_group)
        btn_layout.setSpacing(16)

        self._btn_business = QPushButton("✓  Geschäftlich")
        self._btn_business.setObjectName("btn_business")
        self._btn_business.setFixedHeight(44)
        self._btn_business.clicked.connect(lambda: self._classify("business"))
        btn_layout.addWidget(self._btn_business)

        self._btn_private = QPushButton("✗  Privat")
        self._btn_private.setObjectName("btn_private")
        self._btn_private.setFixedHeight(44)
        self._btn_private.clicked.connect(lambda: self._classify("private"))
        btn_layout.addWidget(self._btn_private)

        self._btn_review = QPushButton("?  Prüfen")
        self._btn_review.setObjectName("btn_review")
        self._btn_review.setFixedHeight(44)
        self._btn_review.clicked.connect(lambda: self._classify("review"))
        btn_layout.addWidget(self._btn_review)

        root.addWidget(btn_group)

        # Navigation
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("← Zurück")
        self._btn_prev.clicked.connect(self._go_prev)
        nav.addWidget(self._btn_prev)
        nav.addStretch()
        self._btn_skip = QPushButton("Überspringen →")
        self._btn_skip.clicked.connect(self._go_next)
        nav.addWidget(self._btn_skip)
        self._btn_finish = QPushButton("Weiter zur Beleg-Zuordnung →")
        self._btn_finish.clicked.connect(self._do_finish)
        nav.addWidget(self._btn_finish)
        root.addLayout(nav)

        # Status info at bottom
        self._status_label = QLabel("")
        self._status_label.setObjectName("status")
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

    # ------------------------------------------------------------------
    def load_session(self, session: storage.SessionData) -> None:
        self._session = session
        # Resume at first unclassified transaction
        unclassified = [
            i for i, tx in enumerate(session.transactions)
            if tx["id"] not in session.classifications
        ]
        self._current_idx = unclassified[0] if unclassified else 0
        self._refresh()

    def _refresh(self) -> None:
        txs = self._session.transactions
        if not txs:
            self._status_label.setText("Keine Transaktionen gefunden.")
            return

        n = len(txs)
        classified = len(self._session.classifications)
        self._progress.setMaximum(n)
        self._progress.setValue(classified)
        self._progress_label.setText(
            f"{classified} von {n} klassifiziert"
        )

        if self._current_idx >= n:
            self._current_idx = n - 1
        if self._current_idx < 0:
            self._current_idx = 0

        tx = txs[self._current_idx]
        self._lbl_date.setText(tx.get("date", ""))
        self._lbl_desc.setText(tx.get("description", ""))
        amt = tx.get("amount", 0)
        self._lbl_amount.setText(
            f"{amt:.2f}" if isinstance(amt, float) else str(amt)
        )
        self._lbl_category.setText(tx.get("category", "") or "–")
        self._lbl_currency.setText(tx.get("currency", "CHF"))

        # Show existing justification if any
        self._justification.setText(
            self._session.justifications.get(tx["id"], "")
        )

        # Highlight existing classification
        cls = self._session.classifications.get(tx["id"], "")
        self._btn_business.setChecked(cls == "business")
        self._btn_private.setChecked(cls == "private")
        self._btn_review.setChecked(cls == "review")

        self._btn_prev.setEnabled(self._current_idx > 0)
        self._status_label.setText(
            f"Transaktion {self._current_idx + 1} von {n}  |  "
            f"Aktuell: {_CLS_LABELS.get(cls, 'Noch nicht klassifiziert')}"
        )

    def _classify(self, cls: str) -> None:
        if not self._session or not self._session.transactions:
            return
        tx = self._session.transactions[self._current_idx]
        self._session.classifications[tx["id"]] = cls
        just = self._justification.text().strip()
        if just:
            self._session.justifications[tx["id"]] = just
        elif cls == "review":
            self._session.justifications[tx["id"]] = "Needs review"
        storage.save(self._session)
        self._go_next()

    def _go_next(self) -> None:
        txs = self._session.transactions
        if self._current_idx < len(txs) - 1:
            self._current_idx += 1
            self._refresh()
        else:
            self._status_label.setText(
                "Alle Transaktionen gesehen. Jetzt 'Weiter zur Beleg-Zuordnung' klicken."
            )

    def _go_prev(self) -> None:
        if self._current_idx > 0:
            self._current_idx -= 1
            self._refresh()

    def _do_finish(self) -> None:
        unclassified = [
            tx for tx in self._session.transactions
            if tx["id"] not in self._session.classifications
        ]
        if unclassified:
            reply = QMessageBox.question(
                self,
                "Nicht alle klassifiziert",
                f"{len(unclassified)} Transaktion(en) sind noch nicht klassifiziert.\n"
                "Trotzdem fortfahren? (Unkategorisierte werden als 'Prüfen' behandelt.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return
            for tx in unclassified:
                self._session.classifications[tx["id"]] = "review"
                self._session.justifications[tx["id"]] = "Needs review"

        self._session.step = "receipts"
        storage.save(self._session)
        self._on_continue(self._session)


_CLS_LABELS = {
    "business": "Geschäftlich",
    "private": "Privat",
    "review": "Prüfen",
}
