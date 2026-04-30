"""
Step 3 (combined): Classify every Revolut transaction AND assign a receipt
in a single pass.

Seeing the receipt helps decide business vs. private.
Replaces the old separate Step 2 (classify) + Step 4 (match) pages.

Button logic
------------
  Privat                    → classification=private, no receipt, next
  Pruefen                   → classification=review,  no receipt, next
  Geschaeftlich: Kein Beleg → classification=business, match=NO_RECEIPT, next
  Geschaeftlich + Beleg     → classification=business, match=<selected>, next
"""
from datetime import date as _date, datetime as _datetime
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QVBoxLayout, QWidget, QProgressBar,
)

import core.storage as storage
from core.constants import NEEDS_REVIEW, NO_RECEIPT
from core.matcher import suggest_matches
from gui.manual_expense_dialog import ManualExpenseDialog


def _row_widget(label_text: str, layout: QVBoxLayout):
    """Add a label+value row to a QVBoxLayout; return the value QLabel."""
    row = QHBoxLayout()
    lbl = QLabel(label_text)
    lbl.setFixedWidth(110)
    lbl.setStyleSheet("font-weight: bold; color: #555;")
    val = QLabel("")
    val.setWordWrap(True)
    row.addWidget(lbl)
    row.addWidget(val, 1)
    layout.addLayout(row)
    return val


class CombinedReviewPage(QWidget):
    def __init__(self, on_continue: Callable[[storage.SessionData], None]) -> None:
        super().__init__()
        self._on_continue = on_continue
        self._session: storage.SessionData = None
        self._all_txs: List[dict] = []
        self._current_idx: int = 0
        self._preview_rotation: int = 0   # 0 / 90 / 180 / 270
        self._preview_zoom: float = 1.0   # 1.0 = fit, >1 zoomed in
        self._current_pixmap: Optional[QPixmap] = None
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 16, 30, 16)
        root.setSpacing(8)

        title = QLabel("Schritt 3 – Transaktionen klassifizieren & Belege zuordnen")
        title.setObjectName("heading")
        root.addWidget(title)

        # Progress
        self._progress = QProgressBar()
        root.addWidget(self._progress)
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("status")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._progress_label)

        # ── Main splitter ──────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(8)

        # Transaction card
        tx_group = QGroupBox("Revolut-Transaktion")
        tg = QVBoxLayout(tx_group)
        self._tx_date   = _row_widget("Datum:", tg)
        self._tx_desc   = _row_widget("Beschreibung:", tg)
        self._tx_amount = _row_widget("Betrag CHF:", tg)
        self._tx_fee    = _row_widget("Gebuehr:", tg)
        ll.addWidget(tx_group)

        # Candidate list
        cand_group = QGroupBox("Beleg-Kandidaten (nach Score sortiert)")
        cg = QVBoxLayout(cand_group)
        self._candidate_list = QListWidget()
        self._candidate_list.setMinimumHeight(200)
        self._candidate_list.currentItemChanged.connect(self._on_candidate_selected)
        cg.addWidget(self._candidate_list)
        btn_browse = QPushButton("Andere Datei auswaehlen ...")
        btn_browse.clicked.connect(self._pick_manual)
        cg.addWidget(btn_browse)
        ll.addWidget(cand_group, stretch=1)

        # Justification
        just_group = QGroupBox("Begruendung / Notiz (optional)")
        jg = QVBoxLayout(just_group)
        self._justification = QLineEdit()
        self._justification.setPlaceholderText("z.B. 'Kundenlunch mit Firma XY'")
        jg.addWidget(self._justification)
        ll.addWidget(just_group)

        splitter.addWidget(left)

        # Right panel – preview
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        preview_group = QGroupBox("Vorschau")
        pg = QVBoxLayout(preview_group)

        # Zoom / rotate toolbar
        zoom_row = QHBoxLayout()
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedWidth(32)
        btn_zoom_out.setToolTip("Verkleinern  (Strg+−)")
        btn_zoom_out.clicked.connect(self._zoom_out)
        zoom_row.addWidget(btn_zoom_out)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(44)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setToolTip("Klicken: Zoom zuruecksetzen")
        self._zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_label.mousePressEvent = lambda _: self._reset_zoom()
        zoom_row.addWidget(self._zoom_label)
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedWidth(32)
        btn_zoom_in.setToolTip("Vergroessern  (Strg++)")
        btn_zoom_in.clicked.connect(self._zoom_in)
        zoom_row.addWidget(btn_zoom_in)
        zoom_row.addSpacing(12)
        btn_rotate = QPushButton("↺ 90°")
        btn_rotate.setFixedWidth(60)
        btn_rotate.setToolTip("90° im Uhrzeigersinn drehen")
        btn_rotate.clicked.connect(self._rotate_preview)
        zoom_row.addWidget(btn_rotate)
        zoom_row.addStretch()
        pg.addLayout(zoom_row)

        # Scrollable image area
        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(False)
        self._preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_scroll.setStyleSheet("background: #F0F0F0; border: 1px solid #CCC;")
        self._preview_scroll.setMinimumSize(380, 480)
        self._preview_label = QLabel("Kein Beleg ausgewaehlt")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(380, 480)
        self._preview_label.setStyleSheet("background: #F0F0F0;")
        self._preview_scroll.setWidget(self._preview_label)
        pg.addWidget(self._preview_scroll, stretch=1)

        self._preview_info = QLabel("")
        self._preview_info.setObjectName("status")
        self._preview_info.setWordWrap(True)
        pg.addWidget(self._preview_info)
        rl.addWidget(preview_group, stretch=1)
        splitter.addWidget(right)
        splitter.setSizes([420, 580])

        root.addWidget(splitter, stretch=3)

        # ── Action buttons ─────────────────────────────────────────────
        action_group = QGroupBox("Klassifizierung")
        ag = QVBoxLayout(action_group)

        row1 = QHBoxLayout()
        self._btn_private = QPushButton("Privat")
        self._btn_private.setObjectName("btn_private")
        self._btn_private.setFixedHeight(38)
        self._btn_private.clicked.connect(self._mark_private)
        row1.addWidget(self._btn_private)

        self._btn_review = QPushButton("Pruefen")
        self._btn_review.setObjectName("btn_review")
        self._btn_review.setFixedHeight(38)
        self._btn_review.clicked.connect(self._mark_review)
        row1.addWidget(self._btn_review)

        self._btn_no_receipt = QPushButton("Geschaeftlich – Kein Beleg")
        self._btn_no_receipt.setObjectName("btn_business")
        self._btn_no_receipt.setFixedHeight(38)
        self._btn_no_receipt.clicked.connect(self._mark_business_no_receipt)
        row1.addWidget(self._btn_no_receipt)

        self._btn_confirm = QPushButton("Geschaeftlich + Beleg bestaetigen  ✓")
        self._btn_confirm.setObjectName("btn_business")
        self._btn_confirm.setFixedHeight(38)
        self._btn_confirm.clicked.connect(self._mark_business_with_receipt)
        self._btn_confirm.setShortcut(QKeySequence(Qt.Key.Key_Return))
        row1.addWidget(self._btn_confirm)
        ag.addLayout(row1)

        row2 = QHBoxLayout()
        self._chk_swiss = QCheckBox("Schweiz / Inland  (Quittung inkl. MwSt.)")
        self._chk_swiss.setChecked(False)  # default: non-Swiss
        self._chk_swiss.setToolTip(
            "Aktivieren wenn die Ausgabe in der Schweiz getätigt wurde.\n"
            "Schweizer Belege erhalten im PDF einen roten Balken."
        )
        row2.addWidget(self._chk_swiss)
        row2.addStretch()
        ag.addLayout(row2)

        root.addWidget(action_group)

        # ── Nav row ───────────────────────────────────────────────────
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("<- Zurueck")
        self._btn_prev.clicked.connect(self._go_prev)
        nav.addWidget(self._btn_prev)
        self._status_label = QLabel("")
        self._status_label.setObjectName("status")
        nav.addWidget(self._status_label, 1)
        self._btn_skip = QPushButton("Ueberspringen ->")
        self._btn_skip.clicked.connect(self._go_next)
        nav.addWidget(self._btn_skip)
        root.addLayout(nav)

        # ── Manual expenses ───────────────────────────────────────────
        manual_group = QGroupBox(
            "Manuelle Spesen  (Barzahlung, andere Karte, Ausgaben ausserhalb Revolut)"
        )
        mg = QVBoxLayout(manual_group)
        self._manual_list = QListWidget()
        self._manual_list.setMaximumHeight(110)
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
        self._btn_finish = QPushButton("Export erstellen ->")
        self._btn_finish.setFixedHeight(36)
        self._btn_finish.clicked.connect(self._do_finish)
        manual_btns.addWidget(self._btn_finish)
        mg.addLayout(manual_btns)
        root.addWidget(manual_group)

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def load_session(self, session: storage.SessionData) -> None:
        self._session = session
        self._all_txs = list(session.transactions)

        # Start at first unclassified transaction
        unclassified = [
            i for i, tx in enumerate(self._all_txs)
            if tx["id"] not in session.classifications
        ]
        self._current_idx = unclassified[0] if unclassified else 0
        self._refresh()
        self._refresh_manual_list()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        self._preview_rotation = 0
        self._preview_zoom = 1.0
        self._current_pixmap = None
        self._preview_label.setText("Kein Beleg ausgewaehlt")
        self._preview_info.setText("")
        self._zoom_label.setText("100%")

        txs = self._all_txs
        if not txs:
            self._status_label.setText("Keine Transaktionen vorhanden.")
            return

        n = len(txs)
        done = sum(1 for tx in txs if tx["id"] in self._session.classifications)
        self._progress.setMaximum(n)
        self._progress.setValue(done)
        self._progress_label.setText(f"{done} von {n} Transaktionen klassifiziert")

        if self._current_idx >= n:
            self._current_idx = n - 1

        tx = txs[self._current_idx]

        try:
            d = _datetime.fromisoformat(tx["date"])
            self._tx_date.setText(f"{tx['date']}  {d.strftime('%A')}")
        except Exception:
            self._tx_date.setText(tx.get("date", ""))
        self._tx_desc.setText(tx.get("description", ""))
        amt = tx.get("amount", 0)
        self._tx_amount.setText(
            f"{amt:.2f} {tx.get('currency', 'CHF')}" if isinstance(amt, float) else str(amt)
        )
        fee = tx.get("fee")
        if fee and isinstance(fee, float) and fee != 0.0:
            self._tx_fee.setText(f"{fee:.2f} CHF  (Fremdwaehrungskonvertierung)")
            self._tx_fee.setStyleSheet("color: #CC6600; font-weight: bold;")
        else:
            self._tx_fee.setText("—")
            self._tx_fee.setStyleSheet("")

        # Restore justification and Switzerland flag if already set
        self._justification.setText(
            self._session.justifications.get(tx["id"], "")
        )
        self._chk_swiss.setChecked(self._session.swiss_flags.get(tx["id"], False))

        # Highlight current classification
        cls = self._session.classifications.get(tx["id"], "")
        cls_text = {"business": " [Geschaeftlich]", "private": " [Privat]",
                    "review": " [Pruefen]"}.get(cls, " [offen]")
        self._status_label.setText(
            f"Transaktion {self._current_idx + 1}/{n}{cls_text}"
        )
        self._btn_prev.setEnabled(self._current_idx > 0)

        # Candidates
        self._candidate_list.clear()
        if self._session.receipts:
            candidates = suggest_matches(tx, self._session.receipts, self._session.matches)
            for cand in candidates:
                days_text = ""
                date_str = cand["image_datetime"][:10]
                try:
                    r_dt = _datetime.fromisoformat(cand["image_datetime"])
                    weekday = r_dt.strftime("%a")  # Mon, Tue, …
                    date_str = f"{cand['image_datetime'][:10]} {weekday}"
                    delta = abs((r_dt.date() - _date.fromisoformat(tx["date"])).days)
                    days_text = "  [Gleicher Tag]" if delta == 0 else f"  [{delta}T Abstand]"
                except Exception:
                    pass
                used_prefix = "!USED  " if cand.get("already_used") else ""
                pdf_tag = "  [PDF]" if cand.get("is_pdf") else ""
                amt_tag = ""
                if cand.get("amount_matched"):
                    amt_tag = "  [Betrag OK]"
                elif cand.get("amount_score", 0) > 0:
                    amt_tag = "  [Betrag ~]"
                item = QListWidgetItem(
                    f"{used_prefix}{date_str}  {cand['original_filename']}"
                    f"{pdf_tag}{days_text}{amt_tag}"
                )
                item.setData(Qt.ItemDataRole.UserRole, cand["working_filename"])
                item.setData(Qt.ItemDataRole.UserRole + 1, cand.get("is_pdf", False))
                if cand.get("already_used"):
                    item.setForeground(QColor(0xBB, 0x66, 0x00))
                elif cand.get("amount_matched"):
                    item.setForeground(QColor(0x00, 0x88, 0x00))
                self._candidate_list.addItem(item)

            # Pre-select current match
            current_match = self._session.matches.get(tx["id"], "")
            for i in range(self._candidate_list.count()):
                if self._candidate_list.item(i).data(Qt.ItemDataRole.UserRole) == current_match:
                    self._candidate_list.setCurrentRow(i)
                    break
        else:
            self._candidate_list.addItem(
                QListWidgetItem("Keine Belege indexiert – Schritt 3 zuerst ausfuehren")
            )

    def _on_candidate_selected(self, current, _prev) -> None:
        if not current:
            self._current_pixmap = None
            self._preview_label.setText("Kein Beleg ausgewaehlt")
            self._preview_info.setText("")
            return
        self._show_preview(current.data(Qt.ItemDataRole.UserRole))

    def _show_preview(self, working_name: str) -> None:
        self._current_pixmap = None
        if not working_name or not self._session.output_dir:
            self._preview_label.setText("Kein Bild")
            return
        path = Path(self._session.output_dir) / "01_working" / working_name
        if not path.exists():
            self._preview_label.setText(f"Datei nicht gefunden:\n{working_name}")
            return
        if path.suffix.lower() == ".pdf":
            pixmap = self._render_pdf_to_pixmap(path)
        else:
            pixmap = QPixmap(str(path))
        if pixmap is None or pixmap.isNull():
            self._preview_label.setText("Vorschau nicht verfuegbar.\ninstall.bat erneut ausfuehren.")
            return
        self._current_pixmap = pixmap
        self._apply_preview_transform()
        receipt = next(
            (r for r in self._session.receipts if r["working_filename"] == working_name), None
        )
        if receipt:
            self._preview_info.setText(
                f"{receipt['original_filename']}\n"
                f"{receipt['image_datetime']}  ({receipt['source']})"
            )

    def _render_pdf_to_pixmap(self, path: Path) -> Optional[QPixmap]:
        try:
            import fitz
            doc = fitz.open(str(path))
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("png")
            doc.close()
            pixmap = QPixmap()
            pixmap.loadFromData(img_bytes)
            return pixmap
        except Exception:
            return None

    def _apply_preview_transform(self) -> None:
        if self._current_pixmap is None or self._current_pixmap.isNull():
            return
        pixmap = self._current_pixmap
        if self._preview_rotation != 0:
            transform = QTransform().rotate(self._preview_rotation)
            pixmap = pixmap.transformed(transform, Qt.TransformationMode.SmoothTransformation)
        viewport = self._preview_scroll.viewport()
        vw = max(viewport.width() - 4, 50)
        vh = max(viewport.height() - 4, 50)
        if self._preview_zoom == 1.0:
            scaled = pixmap.scaled(vw, vh, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self._preview_label.setPixmap(scaled)
            self._preview_label.resize(vw, vh)
        else:
            fit = pixmap.scaled(vw, vh, Qt.AspectRatioMode.KeepAspectRatio)
            target_w = int(fit.width() * self._preview_zoom)
            target_h = int(fit.height() * self._preview_zoom)
            scaled = pixmap.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self._preview_label.setPixmap(scaled)
            self._preview_label.resize(scaled.width(), scaled.height())
        self._zoom_label.setText(f"{int(self._preview_zoom * 100)}%")

    def _zoom_in(self) -> None:
        if self._current_pixmap is not None:
            self._preview_zoom = min(self._preview_zoom + 0.25, 4.0)
            self._apply_preview_transform()

    def _zoom_out(self) -> None:
        if self._current_pixmap is not None:
            self._preview_zoom = max(self._preview_zoom - 0.25, 0.25)
            self._apply_preview_transform()

    def _reset_zoom(self) -> None:
        if self._current_pixmap is not None:
            self._preview_zoom = 1.0
            self._apply_preview_transform()

    def _rotate_preview(self) -> None:
        if self._current_pixmap is not None:
            self._preview_rotation = (self._preview_rotation + 90) % 360
            self._apply_preview_transform()

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _selected_working_name(self) -> Optional[str]:
        item = self._candidate_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _save_and_advance(self, classification: str, match: Optional[str]) -> None:
        tx = self._all_txs[self._current_idx]
        self._session.classifications[tx["id"]] = classification
        if match is not None:
            self._session.matches[tx["id"]] = match
        just = self._justification.text().strip()
        if just:
            self._session.justifications[tx["id"]] = just
        elif not self._session.justifications.get(tx["id"]):
            self._session.justifications[tx["id"]] = tx.get("description", "")
        self._session.swiss_flags[tx["id"]] = self._chk_swiss.isChecked()
        storage.save(self._session)
        self._go_next()

    def _mark_private(self) -> None:
        self._save_and_advance("private", None)

    def _mark_review(self) -> None:
        self._save_and_advance("review", NEEDS_REVIEW)

    def _mark_business_no_receipt(self) -> None:
        self._save_and_advance("business", NO_RECEIPT)

    def _mark_business_with_receipt(self) -> None:
        name = self._selected_working_name()
        if not name:
            QMessageBox.information(
                self, "Kein Beleg ausgewaehlt",
                "Bitte zuerst einen Beleg aus der Liste auswaehlen,\n"
                "oder 'Geschaeftlich – Kein Beleg' verwenden."
            )
            return
        self._save_and_advance("business", name)

    def _go_next(self) -> None:
        if self._current_idx < len(self._all_txs) - 1:
            self._current_idx += 1
        self._refresh()

    def _go_prev(self) -> None:
        if self._current_idx > 0:
            self._current_idx -= 1
            self._refresh()

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
            (r for r in self._session.receipts if r["original_filename"] == p.name), None
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
                "ocr_amounts": [],
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

    # ------------------------------------------------------------------
    # Manual expenses
    # ------------------------------------------------------------------

    def _refresh_manual_list(self) -> None:
        self._manual_list.clear()
        for exp in self._session.manual_expenses:
            match = self._session.matches.get(exp["id"], "")
            receipt_text = (
                "Kein Beleg" if match == NO_RECEIPT else
                "Pruefen"   if match == NEEDS_REVIEW else
                match       if match else
                "Kein Beleg ausgewaehlt"
            )
            amt = exp.get("amount", 0)
            amt_str = f"{abs(amt):.2f}" if isinstance(amt, float) else str(amt)
            item = QListWidgetItem(
                f"{exp['date']}   {exp['description']:<28}   "
                f"{amt_str} {exp.get('currency','CHF')}   |   {receipt_text}"
            )
            item.setData(Qt.ItemDataRole.UserRole, exp["id"])
            self._manual_list.addItem(item)

    def _add_manual(self) -> None:
        dlg = ManualExpenseDialog(self._session, parent=self)
        if dlg.exec() and dlg.result_expense:
            exp = dlg.result_expense
            self._session.manual_expenses.append(exp)
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
            idx = next(i for i, e in enumerate(self._session.manual_expenses) if e["id"] == exp_id)
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
            self, "Loeschen bestaetigen",
            f"Manuelle Spese «{exp.get('description','')}» loeschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._session.manual_expenses = [
            e for e in self._session.manual_expenses if e["id"] != exp_id
        ]
        self._session.matches.pop(exp_id, None)
        storage.save(self._session)
        self._refresh_manual_list()

    def _do_finish(self) -> None:
        self._session.step = "export"
        storage.save(self._session)
        self._on_continue(self._session)
