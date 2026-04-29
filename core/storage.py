"""Session persistence – saves and loads all workflow state as JSON."""
import dataclasses
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

SESSION_FILE = "uw_session.json"


@dataclass
class SessionData:
    folder: str = ""
    start_date: str = ""        # ISO YYYY-MM-DD
    end_date: str = ""
    revolut_pdf: str = ""
    # Raw + filtered transactions (list of dicts from the parser)
    all_transactions: List[Dict] = field(default_factory=list)
    transactions: List[Dict] = field(default_factory=list)
    # Manually entered expenses (same shape as transactions, id = "manual_NNN")
    manual_expenses: List[Dict] = field(default_factory=list)
    # Receipt index (list of dicts from receipt_indexer)
    receipts: List[Dict] = field(default_factory=list)
    # Per-transaction classification: "business" | "private" | "review"
    classifications: Dict[str, str] = field(default_factory=dict)
    # tx_id -> receipt working_filename, NO_RECEIPT, or NEEDS_REVIEW sentinel
    matches: Dict[str, str] = field(default_factory=dict)
    # tx_id -> free-text justification / business purpose
    justifications: Dict[str, str] = field(default_factory=dict)
    # tx_id -> "R001" etc., assigned at export time
    receipt_numbers: Dict[str, str] = field(default_factory=dict)
    output_dir: str = ""
    # Current workflow step
    step: str = "start"
    include_incoming: bool = False


def session_path(folder: str) -> Path:
    return Path(folder) / SESSION_FILE


def save(data: SessionData) -> None:
    path = session_path(data.folder)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(data), fh, indent=2, ensure_ascii=False)


def load(folder: str) -> Optional[SessionData]:
    """
    Load a saved session. Returns None if no session file exists.

    Unknown keys from older/newer file versions are silently ignored so
    the app never crashes on a format mismatch.
    """
    path = session_path(folder)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw: Dict[str, Any] = json.load(fh)
        known = {f.name for f in dataclasses.fields(SessionData)}
        filtered = {k: v for k, v in raw.items() if k in known}
        return SessionData(**filtered)
    except Exception:
        return None
