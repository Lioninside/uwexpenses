"""
Step 4: Receipt matching + manual expenses.

Top half: work through each Revolut business expense, pick a receipt.
Bottom panel: add/edit/delete manual expenses (cash, non-Revolut, etc.)
              with direct receipt file selection – no date dependency.
"""
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter,
    QVBoxLayout, QWidget, QProgressBar,
)

import core.storage as storage
from core.matcher import suggest_matches
from gui.manual_expense_dialog import ManualExpenseDialog

_NO_RECEIPT = "__no_receipt__"
_NEEDS_REVIEW = "__needs_review__"


class ReceiptMatchingPage(QWidget):
    def __init__(self, on_continue: Callable[[storage.SessionData], None]) -> None:
        super().__init__()
        self._on_continue = on_continue
        self._session: storage.SessionData = None
        self._business_txs: List[dict] = []
        self._current_idx: int = 0
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 20, 30, 20)
        root.setSpacing(10)

        title = QLabel("Schritt 4 – Belege zuordnen")
        title.setObjectName("heading")
        root.addWidget(title)

        # ---- Main splitter: Revolut matching (left) + preview (right) ----
        top_splitter = QSplitter(Qt.Orientation.Horizontal)

        # -- Left: transaction + candidates --
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(8)

        # Progress
        self._progress = QProgressBar()
        ll.addWidget(self._progress)
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("status")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self._progress_label)

        # Transaction card
        tx_group = QGroupBox("Revolut-Transaktion")
        tg = QVBoxLayout(tx_group)

        def _row(lbl_text):
            row = QHBoxLayout()
            lbl = QLabel(lbl_text)
            lbl.setFixedWidth(110)
            lbl.setStyleSheet("font-weight: bold; color: #555;")
            val = QLabel("")
            val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(val, 1)
            tg.addLayout(row)
            return val

        self._tx_date = _row("Datum:")
        self._tx_desc = _row("Beschreibung:")
        self._tx_amount = _row("Betrag CHF:")
        self._tx_fee = _row("Gebuehr:")     # non-zero = foreign currency conversion
        ll.addWidget(tx_group)

        # Candidate list – taller so more entries fit
        cand_group = QGroupBox("Beleg-Kandidaten (nach Datum sortiert)")
        cg = QVBoxLayout(cand_group)
        self._candidate_list = QListWidget()
        self._candidate_list.setMinimumHeight(220)
        self._candidate_list.currentItemChanged.connect(self._on_candidate_selected)
        cg.addWidget(self._candidate_list)
        btn_browse = QPushButton("Andere Datei auswaehlen ...")
        btn_browse.clicked.connect(self._pick_manual)
        cg.addWidget(btn_browse)
        ll.addWidget(cand_group)

        # Action buttons
        action_group = QGroupBox("Aktion")
        ag = QVBoxLayout(action_group)
        btn_row1 = QHBoxLayout()
        self._btn_confirm = QPushButton("Beleg bestaetigen")
        self._btn_confirm.setObjectName("btn_business")
        self._btn_confirm.setFixedHeight(38)
        self._btn_confirm.clicked.connect(self._confirm_match)
        btn_row1.addWidget(self._btn_confirm)
        self._btn_no_receipt = QPushButton("Kein Beleg")
        self._btn_no_receipt.setObjectName("btn_private")
        self._btn_no_receipt.setFixedHeight(38)
        self._btn_no_receipt.clicked.connect(self._no_receipt)
        btn_row1.addWidget(self._btn_no_receipt)
        self._btn_needs_review = QPushButton("Pruefen")
        self._btn_needs_review.setObjectName("btn_review")
        self._btn_needs_review.setFixedHeight(38)
        self._btn_needs_review.clicked.connect(self._needs_review)
        btn_row1.addWidget(self._btn_needs_review)
        ag.addLayout(btn_row1)

        # Correction: reclassify back to private if Step 3 was wrong
        btn_row2 = QHBoxLayout()
        self._btn_reclassify_private = QPushButton(
            "Korrektur: Als Privat markieren (entfernt aus Abrechnung)"
        )
        self._btn_reclassify_private.setFixedHeight(30)
        self._btn_reclassify_private.setStyleSheet(
            "font-size: 11px; color: #666; background: #F5F5F5; border: 1px solid #CCC;"
        )
        self._btn_reclassify_private.clicked.connect(self._reclassify_private)
        btn_row2.addStretch()
        btn_row2.addWidget(self._btn_reclassify_private)
        btn_row2.addStretch()
        ag.addLayout(btn_row2)

        ll.addWidget(action_group)

        # Nav row
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("<- Zurueck")
        self._btn_prev.clicked.connect(self._go_prev)
        nav.addWidget(self._btn_prev)
        nav.addStretch()
        self._btn_skip = QPushButton("Ueberspringen ->")
        self._btn_skip.clicked.connect(self._go_next)
        nav.addWidget(self._btn_skip)
        ll.addLayout(nav)

        ll.addStretch()
        top_splitter.addWidget(left)

        # -- Right: image preview --
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        preview_group = QGroupBox("Vorschau")
        pg = QVBoxLayout(preview_group)
        self._preview_label = QLabel("Kein Bild ausgewaehlt")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(420, 520)
        self._preview_label.setSizePolicy(
            self._preview_label.sizePolicy().horizontalPolicy(),
            self._preview_label.sizePolicy().verticalPolicy(),
        )
        self._preview_label.setStyleSheet(
            "background: #F0F0F0; border: 1px solid #CCC;"
        )
        pg.addWidget(self._preview_label, stretch=1)
        self._preview_info = QLabel("")
        self._preview_info.setObjectName("status")
        self._preview_info.setWordWrap(True)
        pg.addWidget(self._preview_info)
        rl.addWidget(preview_group, stretch=1)
        top_splitter.addWidget(right)
        top_splitter.setSizes([400, 600])

        root.addWidget(top_splitter, stretch=3)

        # ---- Manual expenses panel ----
        manual_group = QGroupBox(
            "Manuelle Spesen  (Barzahlung, andere Karte, Ausgaben ausserhalb Revolut)"
        )
        mg = QVBoxLayout(manual_group)

        # List of manual expenses
        self._manual_list = QListWidget()
        self._manual_list.setMaximumHeight(130)
        self._manual_list.setAlternatingRowColors(True)
        self._manual_list.itemDoubleClicked.connect(self._edit_manual)
        mg.addWidget(self._manual_list)

        manual_btns = QHBoxLayout()
        btn_add = QPushButton("+ Spese hinzufuegen")
        btn_add.setObjectName("btn_business")
        btn_add.clicked.connect(self._add_manual)
        manual_btns.addWidget(btn_add)
        self._btn_edit_manual = QPushButton("Bearbeiten")
        self._btn_edit_manual.clicked.connect(self._edit_manual)
        manual_btns.addWidget(self._btn_edit_manual)
        self._btn_del_manual = QPushButton("Loeschen")
        self._btn_del_manual.setObjectName("btn_private")
        self._btn_del_manual.clicked.connect(self._delete_manual)
        manual_btns.addWidget(self._btn_del_manual)
        manual_btns.addStretch()
        mg.addLayout(manual_btns)

        root.addWidget(manual_group, stretch=2)

        # ---- Bottom nav ----
        bottom_nav = QHBoxLayout()
        self._status_label = QLabel("")
        self._status_label.setObjectName("status")
        bottom_nav.addWidget(self._status_label)
        bottom_nav.addStretch()
        self._btn_finish = QPushButton("Export erstellen ->")
        self._btn_finish.setFixedHeight(38)
        self._btn_finish.clicked.connect(self._do_finish)
        bottom_nav.addWidget(self._btn_finish)
        root.addLayout(bottom_nav)

    # ------------------------------------------------------------------
    # Session loading
    # ------------------------------------------------------------------

    def load_session(self, session: storage.SessionData) -> None:
        self._session = session
        self._business_txs = [
            tx for tx in session.transactions
            if session.classifications.get(tx["id"]) in ("business", "review")
        ]
        unmatched = [
            i for i, tx in enumerate(self._business_txs)
            if tx["id"] not in session.matches
        ]
        self._current_idx = unmatched[0] if unmatched else 0
        self._refresh()
        self._refresh_manual_list()

    # ------------------------------------------------------------------
    # Revolut matching
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        txs = self._business_txs
        if not txs:
            self._status_label.setText("Keine Revolut-Geschaeftsspesen vorhanden.")
            self._progress_label.setText("")
            return

        n = len(txs)
        matched = sum(1 for tx in txs if tx["id"] in self._session.matches)
        self._progress.setMaximum(n)
        self._progress.setValue(matched)
        self._progress_label.setText(f"{matched} von {n} Revolut-Spesen zugeordnet")

        if self._current_idx >= n:
            self._current_idx = n - 1

        tx = txs[self._current_idx]
        self._tx_date.setText(tx.get("date", ""))
        self._tx_desc.setText(tx.get("description", ""))
        amt = tx.get("amount", 0)
        self._tx_amount.setText(
            f"{amt:.2f} {tx.get('currency','CHF')}"
            if isinstance(amt, float) else str(amt)
        )

        fee = tx.get("fee")
        if fee and isinstance(fee, float) and fee != 0.0:
            self._tx_fee.setText(f"{fee:.2f} CHF  (Fremdwaehrungskonvertierung)")
            self._tx_fee.setStyleSheet("color: #CC6600; font-weight: bold;")
        else:
            self._tx_fee.setText("—")
            self._tx_fee.setStyleSheet("")

        self._candidate_list.clear()
        candidates = suggest_matches(tx, self._session.receipts, self._session.matches)
        for cand in candidates:
            days_text = ""
            from datetime import date as _date, datetime
            try:
                r_dt = datetime.fromisoformat(cand["image_datetime"])
                delta = abs((r_dt.date() - _date.fromisoformat(tx["date"])).days)
                days_text = "  [Gleicher Tag]" if delta == 0 else f"  [{delta}T Abstand]"
            except Exception:
                pass
            used = "  ! bereits verwendet" if cand.get("already_used") else ""
            pdf = "  [PDF]" if cand.get("is_pdf") else ""
            amt_tag = ""
            if cand.get("amount_matched"):
                amt_tag = "  [Betrag OK]"
            elif cand.get("amount_score", 0) > 0:
                amt_tag = "  [Betrag ~]"
            item = QListWidgetItem(
                f"{cand['image_datetime'][:10]}  {cand['original_filename']}"
                f"{pdf}{days_text}{amt_tag}{used}"
            )
            if cand.get("amount_matched"):
                item.setForeground(QColor(0x00, 0x88, 0x00))
            item.setData(Qt.ItemDataRole.UserRole, cand["working_filename"])
            item.setData(Qt.ItemDataRole.UserRole + 1, cand.get("is_pdf", False))
            self._candidate_list.addItem(item)

        # Pre-select current match
        current_match = self._session.matches.get(tx["id"], "")
        for i in range(self._candidate_list.count()):
            if self._candidate_list.item(i).data(Qt.ItemDataRole.UserRole) == current_match:
                self._candidate_list.setCurrentRow(i)
                break

        self._btn_prev.setEnabled(self._current_idx > 0)
        cls = self._session.classifications.get(tx["id"], "")
        self._status_label.setText(
            f"Revolut {self._current_idx + 1}/{n}  |  "
            f"{_CLS_LABELS.get(cls, cls)}"
        )

    def _on_candidate_selected(self, current: QListWidgetItem, _prev) -> None:
        if not current:
            self._preview_label.setText("Kein Bild ausgewaehlt")
            self._preview_info.setText("")
            return
        self._show_preview(current.data(Qt.ItemDataRole.UserRole))

    def _show_preview(self, working_name: str) -> None:
        if not working_name or not self._session.output_dir:
            self._preview_label.setText("Kein Bild")
            return
        path = Path(self._session.output_dir) / "01_working" / working_name
        if not path.exists():
            self._preview_label.setText(f"Datei nicht gefunden:\n{working_name}")
            return

        if path.suffix.lower() == ".pdf":
            rendered = self._try_render_pdf(path)
            if rendered:
                path = rendered
            else:
                self._preview_label.setPixmap(QPixmap())
                self._preview_label.setText(
                    f"PDF-Beleg\n\n{path.name}\n\n"
                    "Vorschau: poppler installieren\n(pip install pdf2image)"
                )
                return

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._preview_label.setText("Vorschau nicht verfuegbar.")
            return
        scaled = pixmap.scaled(
            self._preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)

        receipt = next(
            (r for r in self._session.receipts if r["working_filename"] == working_name),
            None,
        )
        if receipt:
            self._preview_info.setText(
                f"{receipt['original_filename']}\n"
                f"{receipt['image_datetime']}  ({receipt['source']})"
            )

    def _try_render_pdf(self, path: Path) -> Optional[Path]:
        try:
            from pdf2image import convert_from_path
            import tempfile
            pages = convert_from_path(str(path), dpi=120, first_page=1, last_page=1)
            if pages:
                tmp = Path(tempfile.mktemp(suffix=".png"))
                pages[0].save(str(tmp), "PNG")
                return tmp
        except Exception:
            pass
        return None

    def _pick_manual(self) -> None:
        start = self._session.folder
        if self._session.output_dir:
            w = Path(self._session.output_dir) / "01_working"
            if w.exists():
                start = str(w)
        path, _ = QFileDialog.getOpenFileName(
            self, "Beleg-Datei auswaehlen", start,
            "Belege (*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG *.pdf *.PDF)"
        )
        if not path:
            return
        p = Path(path)
        existing = next(
            (r for r in self._session.receipts if r["original_filename"] == p.name),
            None,
        )
        if not existing:
            import shutil
            working_dir = Path(self._session.output_dir) / "01_working"
            working_dir.mkdir(exist_ok=True)
            dest = working_dir / p.name
            if not dest.exists():
                shutil.copy2(path, str(dest))
            entry = {
                "original_filename": p.name,
                "working_filename": p.name,
                "image_datetime": "",
                "source": "manual",
                "notes": "Manuell hinzugefuegt",
                "is_pdf": p.suffix.lower() == ".pdf",
            }
            self._session.receipts.append(entry)
            working_name = p.name
        else:
            working_name = existing["working_filename"]

        item = QListWidgetItem(f"[Manuell]  {p.name}")
        item.setData(Qt.ItemDataRole.UserRole, working_name)
        item.setData(Qt.ItemDataRole.UserRole + 1, p.suffix.lower() == ".pdf")
        self._candidate_list.insertItem(0, item)
        self._candidate_list.setCurrentRow(0)

    def _selected_working_name(self) -> Optional[str]:
        item = self._candidate_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _confirm_match(self) -> None:
        name = self._selected_working_name()
        if not name:
            QMessageBox.information(self, "Info", "Bitte zuerst einen Beleg auswaehlen.")
            return
        self._save_match(name)
        self._go_next()

    def _no_receipt(self) -> None:
        self._save_match(_NO_RECEIPT)
        self._go_next()

    def _needs_review(self) -> None:
        self._save_match(_NEEDS_REVIEW)
        self._go_next()

    def _reclassify_private(self) -> None:
        if not self._business_txs:
            return
        tx = self._business_txs[self._current_idx]
        reply = QMessageBox.question(
            self,
            "Korrektur bestaetigen",
            f"Transaktion «{tx.get('description', '')}» ({tx.get('date', '')}) "
            f"als Privat markieren?\nSie wird aus der Spesenabrechnung entfernt.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Update classification and remove any match
        self._session.classifications[tx["id"]] = "private"
        self._session.matches.pop(tx["id"], None)
        storage.save(self._session)
        # Rebuild the business list and stay at the same position
        self._business_txs = [
            t for t in self._session.transactions
            if self._session.classifications.get(t["id"]) in ("business", "review")
        ]
        if self._current_idx >= len(self._business_txs):
            self._current_idx = max(0, len(self._business_txs) - 1)
        self._refresh()

    def _save_match(self, value: str) -> None:
        tx = self._business_txs[self._current_idx]
        self._session.matches[tx["id"]] = value
        storage.save(self._session)

    def _go_next(self) -> None:
        if self._current_idx < len(self._business_txs) - 1:
            self._current_idx += 1
            self._refresh()
        else:
            self._status_label.setText(
                "Alle Revolut-Spesen bearbeitet. Manuelle Spesen pruefen, dann Export."
            )
            self._refresh()

    def _go_prev(self) -> None:
        if self._current_idx > 0:
            self._current_idx -= 1
            self._refresh()

    # ------------------------------------------------------------------
    # Manual expenses
    # ------------------------------------------------------------------

    def _refresh_manual_list(self) -> None:
        self._manual_list.clear()
        for exp in self._session.manual_expenses:
            match = self._session.matches.get(exp["id"], "")
            if match == _NO_RECEIPT:
                receipt_text = "Kein Beleg"
            elif match == _NEEDS_REVIEW:
                receipt_text = "Pruefen"
            elif match:
                receipt_text = match
            else:
                receipt_text = "Kein Beleg ausgewaehlt"
            amt = exp.get("amount", 0)
            amt_str = f"{abs(amt):.2f}" if isinstance(amt, float) else str(amt)
            text = (
                f"{exp['date']}   {exp['description']:<28}   "
                f"{amt_str} {exp.get('currency','CHF')}   |   {receipt_text}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, exp["id"])
            self._manual_list.addItem(item)

    def _add_manual(self) -> None:
        dlg = ManualExpenseDialog(self._session, parent=self)
        if dlg.exec() and dlg.result_expense:
            exp = dlg.result_expense
            self._session.manual_expenses.append(exp)
            # Save match and justification from dialog
            if dlg._selected_receipt:
                self._session.matches[exp["id"]] = dlg._selected_receipt
            if dlg._justification_text:
                self._session.justifications[exp["id"]] = dlg._justification_text
            elif not self._session.justifications.get(exp["id"]):
                self._session.justifications[exp["id"]] = exp["description"]
            storage.save(self._session)
            self._refresh_manual_list()

    def _edit_manual(self, _item=None) -> None:
        item = self._manual_list.currentItem()
        if not item:
            return
        exp_id = item.data(Qt.ItemDataRole.UserRole)
        exp = next((e for e in self._session.manual_expenses if e["id"] == exp_id), None)
        if not exp:
            return
        dlg = ManualExpenseDialog(self._session, expense=exp, parent=self)
        if dlg.exec() and dlg.result_expense:
            # Replace in list
            idx = next(
                i for i, e in enumerate(self._session.manual_expenses)
                if e["id"] == exp_id
            )
            self._session.manual_expenses[idx] = dlg.result_expense
            if dlg._selected_receipt:
                self._session.matches[exp_id] = dlg._selected_receipt
            if dlg._justification_text:
                self._session.justifications[exp_id] = dlg._justification_text
            storage.save(self._session)
            self._refresh_manual_list()

    def _delete_manual(self) -> None:
        item = self._manual_list.currentItem()
        if not item:
            return
        exp_id = item.data(Qt.ItemDataRole.UserRole)
        exp = next((e for e in self._session.manual_expenses if e["id"] == exp_id), None)
        if not exp:
            return
        reply = QMessageBox.question(
            self, "Loeschen",
            f"Spese '{exp['description']}' loeschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._session.manual_expenses = [
                e for e in self._session.manual_expenses if e["id"] != exp_id
            ]
            self._session.matches.pop(exp_id, None)
            self._session.justifications.pop(exp_id, None)
            self._session.receipt_numbers.pop(exp_id, None)
            storage.save(self._session)
            self._refresh_manual_list()

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------

    def _do_finish(self) -> None:
        unmatched = [
            tx for tx in self._business_txs
            if tx["id"] not in self._session.matches
        ]
        if unmatched:
            reply = QMessageBox.question(
                self, "Nicht alle zugeordnet",
                f"{len(unmatched)} Revolut-Transaktion(en) haben noch keinen Beleg.\n"
                "Als 'Kein Beleg' markieren und fortfahren?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return
            for tx in unmatched:
                self._session.matches[tx["id"]] = _NO_RECEIPT

        self._session.step = "export"
        storage.save(self._session)
        self._on_continue(self._session)


_CLS_LABELS = {"business": "Geschaeftlich", "private": "Privat", "review": "Pruefen"}
