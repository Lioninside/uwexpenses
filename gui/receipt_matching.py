"""
Step 4: Manual receipt matching.

For each business expense, shows:
  - Transaction details
  - Suggested receipt matches (sorted by date proximity)
  - Image preview of selected candidate
  - Buttons: Confirm match | No receipt | Needs review

Decisions are saved after every confirmation.
"""
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget, QProgressBar, QScrollArea, QSplitter,
)

import core.storage as storage
from core.matcher import suggest_matches

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
        root.setSpacing(12)

        title = QLabel("Schritt 4 – Belege zuordnen")
        title.setObjectName("heading")
        root.addWidget(title)

        self._progress = QProgressBar()
        root.addWidget(self._progress)
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("status")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._progress_label)

        # Splitter: left = tx info + candidate list, right = image preview
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        # Transaction info
        tx_group = QGroupBox("Transaktion")
        tg = QVBoxLayout(tx_group)

        def _lbl_row(label: str):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(110)
            lbl.setStyleSheet("font-weight: bold; color: #555;")
            val = QLabel("")
            val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(val, 1)
            tg.addLayout(row)
            return val

        self._tx_date = _lbl_row("Datum:")
        self._tx_desc = _lbl_row("Beschreibung:")
        self._tx_amount = _lbl_row("Betrag:")
        left_layout.addWidget(tx_group)

        # Candidates
        cand_group = QGroupBox("Beleg-Kandidaten (nach Datum)")
        cg = QVBoxLayout(cand_group)
        self._candidate_list = QListWidget()
        self._candidate_list.setMaximumHeight(200)
        self._candidate_list.currentItemChanged.connect(self._on_candidate_selected)
        cg.addWidget(self._candidate_list)

        btn_manual = QPushButton("Datei manuell wählen …")
        btn_manual.clicked.connect(self._pick_manual)
        cg.addWidget(btn_manual)
        left_layout.addWidget(cand_group)

        # Action buttons
        action_group = QGroupBox("Aktion")
        ag = QHBoxLayout(action_group)

        self._btn_confirm = QPushButton("✓  Beleg bestätigen")
        self._btn_confirm.setObjectName("btn_business")
        self._btn_confirm.setFixedHeight(40)
        self._btn_confirm.clicked.connect(self._confirm_match)
        ag.addWidget(self._btn_confirm)

        self._btn_no_receipt = QPushButton("Kein Beleg")
        self._btn_no_receipt.setObjectName("btn_private")
        self._btn_no_receipt.setFixedHeight(40)
        self._btn_no_receipt.clicked.connect(self._no_receipt)
        ag.addWidget(self._btn_no_receipt)

        self._btn_needs_review = QPushButton("Prüfen")
        self._btn_needs_review.setObjectName("btn_review")
        self._btn_needs_review.setFixedHeight(40)
        self._btn_needs_review.clicked.connect(self._needs_review)
        ag.addWidget(self._btn_needs_review)

        left_layout.addWidget(action_group)

        # Nav
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("← Zurück")
        self._btn_prev.clicked.connect(self._go_prev)
        nav.addWidget(self._btn_prev)
        nav.addStretch()
        self._btn_next_skip = QPushButton("Überspringen →")
        self._btn_next_skip.clicked.connect(self._go_next)
        nav.addWidget(self._btn_next_skip)
        self._btn_finish = QPushButton("Export erstellen →")
        self._btn_finish.clicked.connect(self._do_finish)
        nav.addWidget(self._btn_finish)
        left_layout.addLayout(nav)

        left_layout.addStretch()
        splitter.addWidget(left)

        # Right panel – image preview
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        preview_group = QGroupBox("Vorschau")
        pg = QVBoxLayout(preview_group)
        self._preview_label = QLabel("Kein Bild ausgewählt")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(300, 400)
        self._preview_label.setStyleSheet("background: #F0F0F0; border: 1px solid #CCC;")
        pg.addWidget(self._preview_label)
        self._preview_info = QLabel("")
        self._preview_info.setObjectName("status")
        self._preview_info.setWordWrap(True)
        pg.addWidget(self._preview_info)
        right_layout.addWidget(preview_group)

        splitter.addWidget(right)
        splitter.setSizes([450, 380])
        root.addWidget(splitter)

        self._status_label = QLabel("")
        self._status_label.setObjectName("status")
        root.addWidget(self._status_label)

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

    def _refresh(self) -> None:
        txs = self._business_txs
        if not txs:
            self._status_label.setText("Keine Geschäfts-Transaktionen vorhanden.")
            return

        n = len(txs)
        matched = sum(1 for tx in txs if tx["id"] in self._session.matches)
        self._progress.setMaximum(n)
        self._progress.setValue(matched)
        self._progress_label.setText(f"{matched} von {n} zugeordnet")

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

        # Fill candidate list
        self._candidate_list.clear()
        candidates = suggest_matches(tx, self._session.receipts, self._session.matches)

        for cand in candidates:
            days = ""
            from datetime import date as _date, datetime
            try:
                r_dt = datetime.fromisoformat(cand["image_datetime"])
                tx_dt = _date.fromisoformat(tx["date"])
                delta = abs((r_dt.date() - tx_dt).days)
                days = f"  [{delta}T Abstand]"
                if delta == 0:
                    days = "  [Gleicher Tag]"
            except Exception:
                pass
            used_tag = "  ! bereits verwendet" if cand.get("already_used") else ""
            pdf_tag = "  [PDF]" if cand.get("is_pdf") else ""
            text = (
                f"{cand['image_datetime'][:10]}  "
                f"{cand['original_filename']}{pdf_tag}{days}{used_tag}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, cand["working_filename"])
            item.setData(Qt.ItemDataRole.UserRole + 1, cand.get("is_pdf", False))
            self._candidate_list.addItem(item)

        # Pre-select existing match
        current_match = self._session.matches.get(tx["id"], "")
        for i in range(self._candidate_list.count()):
            item = self._candidate_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == current_match:
                self._candidate_list.setCurrentRow(i)
                break

        self._btn_prev.setEnabled(self._current_idx > 0)
        cls = self._session.classifications.get(tx["id"], "")
        self._status_label.setText(
            f"Transaktion {self._current_idx + 1} von {n}  |  "
            f"Klassifizierung: {_CLS_LABELS.get(cls, cls)}"
        )

    def _on_candidate_selected(self, current: QListWidgetItem, _prev) -> None:
        if not current:
            self._preview_label.setText("Kein Bild ausgewählt")
            self._preview_info.setText("")
            return
        working_name = current.data(Qt.ItemDataRole.UserRole)
        self._show_preview(working_name)

    def _show_preview(self, working_name: str) -> None:
        if not working_name or not self._session.output_dir:
            self._preview_label.setText("Kein Bild")
            return
        path = Path(self._session.output_dir) / "01_working" / working_name
        if not path.exists():
            self._preview_label.setText(f"Datei nicht gefunden:\n{working_name}")
            return

        # PDF receipts: try to render first page, otherwise show info block
        if path.suffix.lower() == ".pdf":
            rendered = self._try_render_pdf(path)
            if rendered:
                path = rendered
            else:
                self._preview_label.setText(
                    f"PDF-Beleg\n\n{path.name}\n\n"
                    "Vorschau: poppler installieren\n"
                    "(pip install pdf2image + poppler)\n\n"
                    "Beleg wird im Output-PDF als\n"
                    "Referenz eingebettet."
                )
                self._preview_label.setPixmap(QPixmap())  # clear any old image
                receipt = next(
                    (r for r in self._session.receipts
                     if r["working_filename"] == working_name), None
                )
                if receipt:
                    self._preview_info.setText(
                        f"{receipt['original_filename']}\n"
                        f"{receipt['image_datetime']}  ({receipt['source']})"
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
        # Find receipt info
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
        """Render first PDF page to a temp PNG. Returns None if unavailable."""
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
        start_dir = ""
        if self._session.output_dir:
            start_dir = str(Path(self._session.output_dir) / "01_working")
        path, _ = QFileDialog.getOpenFileName(
            self, "Beleg-Datei waehlen", start_dir,
            "Belege (*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG *.pdf *.PDF)"
        )
        if not path:
            return
        # Add as ad-hoc entry if not in index
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
                shutil.copy2(path, dest)
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
        self._candidate_list.insertItem(0, item)
        self._candidate_list.setCurrentRow(0)

    def _selected_working_name(self) -> Optional[str]:
        item = self._candidate_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _confirm_match(self) -> None:
        name = self._selected_working_name()
        if not name:
            QMessageBox.information(self, "Info", "Bitte zuerst einen Beleg in der Liste auswählen.")
            return
        self._save_match(name)
        self._go_next()

    def _no_receipt(self) -> None:
        self._save_match(_NO_RECEIPT)
        self._go_next()

    def _needs_review(self) -> None:
        self._save_match(_NEEDS_REVIEW)
        self._go_next()

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
                "Alle Geschäfts-Transaktionen bearbeitet. Jetzt Export starten."
            )
            self._refresh()

    def _go_prev(self) -> None:
        if self._current_idx > 0:
            self._current_idx -= 1
            self._refresh()

    def _do_finish(self) -> None:
        unmatched = [
            tx for tx in self._business_txs
            if tx["id"] not in self._session.matches
        ]
        if unmatched:
            reply = QMessageBox.question(
                self,
                "Nicht alle zugeordnet",
                f"{len(unmatched)} Transaktion(en) haben noch keinen Beleg.\n"
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


_CLS_LABELS = {
    "business": "Geschäftlich",
    "private": "Privat",
    "review": "Prüfen",
}
