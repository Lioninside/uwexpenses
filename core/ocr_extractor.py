"""
Optional OCR-based amount extraction from receipt images and PDFs.

For images: requires easyocr  (pip install easyocr)
            falls back to pytesseract if easyocr not available
For PDFs:   uses pdfplumber (already a dependency) – no extra install needed

Gracefully returns [] when nothing is available.

Rotation strategy:
  1. Apply EXIF orientation (fixes most phone photos automatically)
  2. If fewer than 5 text fragments detected, retry at 90 / 180 / 270°

Amount strategy:
  - Find lines containing Swiss-German total keywords
  - Also check the 1-2 lines below each keyword line (layout can split them)
  - Return a deduplicated list of candidate amounts (most likely total first)
"""
import importlib.util
import re
from pathlib import Path
from typing import List, Optional

_TOTAL_KEYWORDS = [
    "rechnungsbetrag", "total", "summe", "gesamtbetrag",
    "kartenzahlung", "aldi preis", "zu zahlen", "bezahlt",
    "total-eft", "endbetrag", "gesamtsumme", "chf",
    "zu bezahlen", "gesamt", "betrag",
]

_AMOUNT_RE = re.compile(r"\b(\d{1,4}[.,]\d{2})\b")

_reader_cache = None


def _easyocr_reader():
    global _reader_cache
    if _reader_cache is None:
        import easyocr
        _reader_cache = easyocr.Reader(["de", "en"], verbose=False)
    return _reader_cache


def _parse_amount(s: str) -> Optional[float]:
    s = s.strip().replace("'", "").replace(" ", "")
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _find_totals(text: str) -> List[float]:
    """Extract candidate total amounts from plain text."""
    candidates: List[tuple] = []  # (priority, amount)
    lines = text.split("\n")

    for i, line in enumerate(lines):
        lower = line.lower()
        is_total = any(kw in lower for kw in _TOTAL_KEYWORDS)

        # Scan this line and next 2 lines for amounts
        window = "\n".join(lines[i : i + 3])
        for m in _AMOUNT_RE.finditer(window):
            amt = _parse_amount(m.group(1))
            if amt and 0.10 <= amt <= 9999.99:
                priority = 2 if is_total else 1
                candidates.append((priority, amt))

    if not candidates:
        return []

    # Higher-priority amounts first, then de-duplicate
    candidates.sort(key=lambda x: -x[0])
    seen: set = set()
    result: List[float] = []
    for _, amt in candidates:
        rounded = round(amt, 2)
        if rounded not in seen:
            seen.add(rounded)
            result.append(rounded)
    return result


def _ocr_image_easyocr(path: Path) -> List[float]:
    try:
        import numpy as np
        from PIL import Image, ImageOps

        reader = _easyocr_reader()
        img = Image.open(path).convert("RGB")
        img = ImageOps.exif_transpose(img)  # fix phone rotation via EXIF

        def _run(image):
            arr = np.array(image)
            results = reader.readtext(arr, detail=0, paragraph=True)
            return results

        results = _run(img)

        # If very little text, try rotations
        if len(results) < 5:
            for angle in [90, 180, 270]:
                rotated = img.rotate(angle, expand=True)
                alt = _run(rotated)
                if len(alt) > len(results):
                    results = alt

        text = "\n".join(results)
        return _find_totals(text)

    except Exception:
        return []


def _ocr_image_tesseract(path: Path) -> List[float]:
    try:
        import pytesseract
        from PIL import Image, ImageOps

        img = Image.open(path).convert("RGB")
        img = ImageOps.exif_transpose(img)

        # Auto-detect orientation via OSD, fall back to direct read
        try:
            osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
            angle = osd.get("rotate", 0)
            if angle:
                img = img.rotate(-angle, expand=True)
        except Exception:
            pass

        text = pytesseract.image_to_string(img, lang="deu+eng")
        return _find_totals(text)

    except Exception:
        return []


def _ocr_pdf(path: Path) -> List[float]:
    try:
        import pdfplumber

        lines = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    lines.append(t)
        return _find_totals("\n".join(lines))
    except Exception:
        return []


def extract_amounts(path: Path) -> List[float]:
    """
    Return a list of candidate total amounts from a receipt file.
    Returns [] if no OCR library is available.
    """
    if path.suffix.lower() == ".pdf":
        return _ocr_pdf(path)

    # Try easyocr, fall back to tesseract
    try:
        import easyocr  # noqa: F401
        return _ocr_image_easyocr(path)
    except ImportError:
        pass

    try:
        import pytesseract  # noqa: F401
        return _ocr_image_tesseract(path)
    except ImportError:
        pass

    return []


def ocr_available() -> str:
    """Return which OCR backend is installed — without importing it (avoids slow startup)."""
    if importlib.util.find_spec("easyocr") is not None:
        return "easyocr"
    if importlib.util.find_spec("pytesseract") is not None:
        return "tesseract"
    return "pdf_only"
