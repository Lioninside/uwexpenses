"""Session persistence – saves and loads all workflow state as JSON."""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

SESSION_FILE = "uw_session.json"


@dataclass
class SessionData:
    folder: str = ""
    start_date: str = ""   # ISO YYYY-MM-DD
    end_date: str = ""
    revolut_pdf: str = ""
    # Raw + filtered transactions from the PDF (list of dicts)
    all_transactions: List[Dict] = field(default_factory=list)
    transactions: List[Dict] = field(default_factory=list)
    # Manually entered expenses (same dict shape as transactions, id = "manual_NNN")
    manual_expenses: List[Dict] = field(default_factory=list)
    # Receipt index (list of dicts from receipt_indexer)
    receipts: List[Dict] = field(default_factory=list)
    # Per-transaction decisions
    # "business" | "private" | "review"
    classifications: Dict[str, str] = field(default_factory=dict)
    # tx_id -> receipt working_filename, "__no_receipt__", or "__needs_review__"
    matches: Dict[str, str] = field(default_factory=dict)
    # tx_id -> free-text justification
    justifications: Dict[str, str] = field(default_factory=dict)
    # tx_id -> "R001" etc., assigned at export time
    receipt_numbers: Dict[str, str] = field(default_factory=dict)
    output_dir: str = ""
    # Workflow step the user is on
    step: str = "start"
    include_incoming: bool = False


def session_path(folder: str) -> Path:
    return Path(folder) / SESSION_FILE


def save(data: SessionData) -> None:
    path = session_path(data.folder)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(data), fh, indent=2, ensure_ascii=False)


def load(folder: str) -> Optional[SessionData]:
    path = session_path(folder)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        raw: Dict[str, Any] = json.load(fh)
    return SessionData(**raw)
