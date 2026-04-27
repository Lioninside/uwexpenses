"""
Index receipt images in the expense folder.

For each image:
  - read EXIF DateTimeOriginal / DateTime
  - fall back to file mtime
  - copy a working version into output/01_working/ with a sortable name
  - build an index dict
"""
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PIL import Image, ExifTags

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

_EXIF_DATE_FIELDS = ["DateTimeOriginal", "DateTime", "DateTimeDigitized"]
_EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"


def _read_exif_date(path: Path) -> Optional[Tuple[datetime, str]]:
    """Return (datetime, source_description) from EXIF, or None."""
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
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts), "file mtime"


def index_receipts(folder: Path, working_dir: Path) -> Tuple[List[Dict], List[str]]:
    """
    Scan *folder* for receipt images, copy sorted working copies to *working_dir*.

    Returns (index_list, issues).

    Each index dict:
        original_filename, working_filename, image_datetime (ISO), source, notes
    """
    working_dir.mkdir(parents=True, exist_ok=True)
    issues: List[str] = []

    images = sorted(
        [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS]
    )

    if not images:
        issues.append("No receipt images (JPG/PNG) found in the selected folder.")
        return [], issues

    entries: List[Tuple[datetime, Path]] = []
    for img_path in images:
        result = _read_exif_date(img_path)
        if result:
            dt, source = result
        else:
            dt, source = _file_mtime(img_path)
            issues.append(
                f"{img_path.name}: no EXIF date found, using file modification time."
            )
        entries.append((dt, img_path, source))

    # Sort by datetime
    entries.sort(key=lambda x: x[0])

    index: List[Dict] = []
    for idx, (dt, orig_path, source) in enumerate(entries, 1):
        # Working filename: NNN_YYYY-MM-DD_HHMMSS_originalname.ext
        safe_name = re.sub(r"[^\w.]", "_", orig_path.name)
        working_name = f"{idx:03d}_{dt.strftime('%Y-%m-%d_%H%M%S')}_{safe_name}"
        working_path = working_dir / working_name

        if working_path.exists():
            notes = "already exists in working folder"
        else:
            try:
                shutil.copy2(str(orig_path), str(working_path))
                notes = ""
            except Exception as exc:
                notes = f"copy failed: {exc}"
                issues.append(f"{orig_path.name}: {notes}")

        index.append({
            "original_filename": orig_path.name,
            "working_filename": working_name,
            "image_datetime": dt.isoformat(timespec="seconds"),
            "source": source,
            "notes": notes,
        })

    return index, issues
