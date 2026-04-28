"""
Index receipt images and PDFs in the expense folder.

Date extraction priority:
  1. Filename pattern:  DD-MM-YYYY-HHhMMmin  (Adobe Scan default)
  2. EXIF DateTimeOriginal / DateTime         (camera JPG)
  3. File modification time                   (fallback)

Supports: JPG, JPEG, PNG, PDF
"""
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PIL import Image, ExifTags

from core.ocr_extractor import extract_amounts, ocr_available

RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}

_EXIF_DATE_FIELDS = ["DateTimeOriginal", "DateTime", "DateTimeDigitized"]
_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"

# Adobe Scan naming: 27-04-2026-18h29min.pdf  (DD-MM-YYYY-HHhMMmin)
_ADOBE_SCAN_PATTERN = re.compile(
    r"(\d{2})-(\d{2})-(\d{4})-(\d{1,2})h(\d{2})min",
    re.IGNORECASE,
)

# Android/Samsung camera: 20260421_180629  (YYYYMMDD_HHMMSS)
_ANDROID_PATTERN = re.compile(
    r"(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})"
)

# ISO with separators: 2026-04-21_180629  or  2026-04-21-18-06-29
_ISO_FILENAME_PATTERN = re.compile(
    r"(\d{4})[_-](\d{2})[_-](\d{2})[_-](\d{2})(\d{2})(\d{2})"
)


def _parse_date_from_filename(name: str) -> Optional[Tuple[datetime, str]]:
    """Try to extract a datetime from the filename stem."""
    stem = Path(name).stem

    # 1. Adobe Scan: DD-MM-YYYY-HHhMMmin
    m = _ADOBE_SCAN_PATTERN.search(stem)
    if m:
        day, month, year, hour, minute = (int(x) for x in m.groups())
        try:
            dt = datetime(year, month, day, hour, minute)
            return dt, "filename (Adobe Scan)"
        except ValueError:
            pass

    # 2. Android/Samsung camera: YYYYMMDD_HHMMSS
    m = _ANDROID_PATTERN.search(stem)
    if m:
        year, month, day, hour, minute, second = (int(x) for x in m.groups())
        try:
            dt = datetime(year, month, day, hour, minute, second)
            return dt, "filename (Android)"
        except ValueError:
            pass

    # 3. ISO-style with separators: YYYY-MM-DD_HHMMSS
    m = _ISO_FILENAME_PATTERN.search(stem)
    if m:
        year, month, day, hour, minute, second = (int(x) for x in m.groups())
        try:
            dt = datetime(year, month, day, hour, minute, second)
            return dt, "filename (ISO)"
        except ValueError:
            pass

    return None


def _read_exif_date(path: Path) -> Optional[Tuple[datetime, str]]:
    """Return (datetime, source) from EXIF, or None. Only for image files."""
    if path.suffix.lower() == ".pdf":
        return None
    try:
        img = Image.open(path)
        exif_data = img._getexif()
        if not exif_data:
            return None
        tag_map = {ExifTags.TAGS.get(k, k): v for k, v in exif_data.items()}
        for field in _EXIF_DATE_FIELDS:
            raw = tag_map.get(field)
            if raw:
                try:
                    return datetime.strptime(str(raw).strip(), _EXIF_DATE_FMT), f"EXIF:{field}"
                except ValueError:
                    continue
    except Exception:
        pass
    return None


def _file_mtime(path: Path) -> Tuple[datetime, str]:
    return datetime.fromtimestamp(path.stat().st_mtime), "file mtime"


def index_receipts(
    folder: Path,
    working_dir: Path,
    run_ocr: bool = False,
) -> Tuple[List[Dict], List[str]]:
    """
    Scan *folder* for receipt files, copy working copies to *working_dir*.

    Date priority: filename > EXIF > file mtime.

    Returns (index_list, issues).

    Each index dict:
        original_filename, working_filename, image_datetime (ISO),
        source, notes, is_pdf
    """
    working_dir.mkdir(parents=True, exist_ok=True)
    issues: List[str] = []

    files = sorted(
        [p for p in folder.iterdir() if p.suffix.lower() in RECEIPT_EXTENSIONS]
    )

    if not files:
        issues.append(
            "Keine Belege (JPG/PNG/PDF) im gewaehlten Ordner gefunden."
        )
        return [], issues

    entries: List[Tuple[datetime, Path, str]] = []
    for p in files:
        # Priority: filename date > EXIF > mtime
        result = _parse_date_from_filename(p.name)
        if result is None:
            result = _read_exif_date(p)
        if result is None:
            dt, source = _file_mtime(p)
            issues.append(
                f"{p.name}: kein Datum im Dateinamen und kein EXIF – "
                "Datei-Aenderungsdatum wird verwendet."
            )
        else:
            dt, source = result
        entries.append((dt, p, source))

    # Sort by datetime
    entries.sort(key=lambda x: x[0])

    index: List[Dict] = []
    for idx, (dt, orig_path, source) in enumerate(entries, 1):
        ext = orig_path.suffix.lower()
        is_pdf = ext == ".pdf"
        safe_name = re.sub(r"[^\w.]", "_", orig_path.name)
        working_name = f"{idx:03d}_{dt.strftime('%Y-%m-%d_%H%M%S')}_{safe_name}"
        working_path = working_dir / working_name

        notes = ""
        if working_path.exists():
            notes = "Bereits in Arbeitsordner vorhanden"
        else:
            try:
                shutil.copy2(str(orig_path), str(working_path))
            except Exception as exc:
                notes = f"Kopieren fehlgeschlagen: {exc}"
                issues.append(f"{orig_path.name}: {notes}")

        ocr_amounts: List[float] = []
        if run_ocr:
            try:
                ocr_amounts = extract_amounts(working_path if working_path.exists() else orig_path)
            except Exception:
                pass

        index.append({
            "original_filename": orig_path.name,
            "working_filename": working_name,
            "image_datetime": dt.isoformat(timespec="seconds"),
            "source": source,
            "notes": notes,
            "is_pdf": is_pdf,
            "ocr_amounts": ocr_amounts,
        })

    return index, issues
