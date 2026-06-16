"""
extract_gambhirananda.py
=========================
OCR extractor for Gambhirananda PDFs.
Strategy: extract page-by-page, one record per page.
Let the LLM tagging pipeline handle verse/commentary splitting.
This is more reliable than regex on OCR'd scans.

Works for:
  Eight-Upanisads-Vol-1.pdf
  Eight-Upanisads-vol2.pdf
  Brahma_Sutra_Swami_Gambhirananda.pdf

Run:
  python extract_gambhirananda.py --pdf Eight-Upanisads-Vol-1.pdf
  python extract_gambhirananda.py --pdf Eight-Upanisads-Vol-1.pdf --resume
  python extract_gambhirananda.py --pdf Eight-Upanisads-vol2.pdf --out corpus/gambhirananda_upanishads_vol2.json
  python extract_gambhirananda.py --pdf Brahma_Sutra_Swami_Gambhirananda.pdf --out corpus/gambhirananda_brahmasutra.json
"""

import re
import json
import argparse
import subprocess
import logging
from pathlib import Path

OUTPUT_DIR = Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)
TEMP_DIR   = Path("/tmp/gambhirananda_pages")
TEMP_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# Detect which text we're in from page content
UPANISHAD_MARKERS = {
    "isa upanisad":        "isha_upanishad",
    "isavasyam":           "isha_upanishad",
    "kena upanisad":       "kena_upanishad",
    "katha upanisad":      "katha_upanishad",
    "taittiriya upanisad": "taittiriya_upanishad",
    "aitareya upanisad":   "aitareya_upanishad",
    "mundaka upanisad":    "mundaka_upanishad",
    "mandukya upanisad":   "mandukya_upanishad",
    "prasna upanisad":     "prasna_upanishad",
    # Vol 2
    "chandogya upanisad":      "chandogya_upanishad",
    "brihadaranyaka upanisad": "brihadaranyaka_upanishad",
    "svetasvatara upanisad":   "svetasvatara_upanishad",
    # Brahma Sutra
    "brahma-sutra":        "brahma_sutras",
    "brahmasutra":         "brahma_sutras",
    "vedanta-sutra":       "brahma_sutras",
    "adhyaya i":           "brahma_sutras",
}


def get_page_count(pdf_path):
    result = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True)
    m = re.search(r'Pages:\s+(\d+)', result.stdout)
    return int(m.group(1)) if m else 400


def rasterize_page(pdf_path, page_num):
    prefix = str(TEMP_DIR / "page")
    subprocess.run(
        ["pdftoppm", "-jpeg", "-r", "200",
         "-f", str(page_num), "-l", str(page_num),
         pdf_path, prefix],
        capture_output=True
    )
    matches = sorted(TEMP_DIR.glob("page-*.jpg"))
    return matches[-1] if matches else None


def ocr_page(img_path):
    result = subprocess.run(
        ["tesseract", str(img_path), "stdout", "-l", "eng",
         "--oem", "3", "--psm", "6"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def detect_source(text, current, fixed_source=None):
    """
    If fixed_source is given (e.g. for a single continuous text like
    the Brahma Sutras), always return it -- don't let stray references
    to other texts (which the Brahma Sutra quotes constantly) override it.
    """
    if fixed_source:
        return fixed_source

    text_lower = text.lower()
    for marker, source_id in UPANISHAD_MARKERS.items():
        if marker in text_lower:
            return source_id
    return current


def is_mostly_sanskrit(text):
    """True if page is >50% Devanagari — skip these."""
    devanagari = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    return devanagari / max(len(text), 1) > 0.3


def is_front_matter(text, page_num):
    """Skip preface, TOC, and other front matter."""
    if page_num < 8:
        return True
    lower = text.lower()
    skip_phrases = [
        "table of contents", "preface", "foreword",
        "publisher", "printed in", "copyright",
        "all rights reserved", "first edition",
    ]
    return any(p in lower for p in skip_phrases)


def extract_verse_numbers(text):
    """Find all verse numbers mentioned on this page."""
    # Patterns: "1. Om", "Mantra 3", "Text 2", standalone bold numbers
    patterns = [
        r'^\s*(\d+)\.\s+[A-Z"\u2018\u2019]',   # "1. Om..." at line start
        r'Mantra\s+(\d+)',
        r'Text\s+(\d+)',
        r'^(\d+)\s*$',                            # standalone number
    ]
    found = []
    for line in text.split('\n'):
        for p in patterns:
            m = re.search(p, line, re.MULTILINE)
            if m:
                found.append(int(m.group(1)))
    return sorted(set(found))


def process_pdf(pdf_path, out_file, start_page=1, end_page=None, resume=False, fixed_source=None):
    progress_file = Path(str(out_file).replace('.json', '_progress.json'))

    total_pages = get_page_count(pdf_path)
    end_page    = end_page or total_pages
    log.info(f"PDF: {pdf_path}  Pages: {total_pages}  Processing: {start_page}-{end_page}")

    # Resume support
    done_pages = set()
    records    = []
    if resume and progress_file.exists():
        prog = json.loads(progress_file.read_text())
        done_pages = set(prog.get("done_pages", []))
        if out_file.exists():
            records = json.loads(out_file.read_text())
        log.info(f"Resuming: {len(done_pages)} done, {len(records)} records")

    current_source = fixed_source or "unknown"

    for page_num in range(start_page, end_page + 1):
        if page_num in done_pages:
            continue

        img_path = rasterize_page(pdf_path, page_num)
        if not img_path:
            continue

        text = ocr_page(img_path)
        img_path.unlink(missing_ok=True)

        if not text or len(text) < 100:
            done_pages.add(page_num)
            continue

        if is_front_matter(text, page_num):
            done_pages.add(page_num)
            continue

        if is_mostly_sanskrit(text):
            done_pages.add(page_num)
            continue

        # Update current source text
        current_source = detect_source(text, current_source, fixed_source=fixed_source)
        verse_nums     = extract_verse_numbers(text)

        record = {
            "id":          f"gambhirananda_{Path(pdf_path).stem}_p{page_num:04d}",
            "source":      current_source,
            "tradition":   "hindu_astika",
            "darshana":    "vedanta",
            "page":        page_num,
            "verse_nums":  verse_nums,     # verse numbers found on this page
            "text":        text,           # full page OCR — verse + commentary mixed
            "translator":  "gambhirananda",
            "commentaries": [{
                "commentator": "shankara",
                "school":      "advaita",
                "lang":        "en",
                "text":        text,       # LLM tagging will separate verse from commentary
            }],
        }
        records.append(record)
        done_pages.add(page_num)

        if page_num % 10 == 0:
            _save(records, done_pages, out_file, progress_file)
            log.info(f"  Page {page_num}/{end_page} — {len(records)} pages, source: {current_source}")

    _save(records, done_pages, out_file, progress_file)

    log.info(f"Done: {len(records)} page records from {pdf_path}")
    from collections import Counter
    for src, count in Counter(r["source"] for r in records).most_common():
        log.info(f"  {src}: {count} pages")

    return records


def _save(records, done_pages, out_file, progress_file):
    out_file.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    progress_file.write_text(json.dumps({"done_pages": list(done_pages)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf",    required=True)
    parser.add_argument("--start",  type=int, default=1)
    parser.add_argument("--end",    type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--out",    default=None,
                        help="Output JSON path (default: corpus/<pdf_stem>.json)")
    parser.add_argument("--fixed-source", default=None,
                        help="Force a single source id for the whole PDF "
                             "(use for continuous texts like Brahma Sutras, "
                             "where stray quotes of other texts would otherwise "
                             "mislabel pages)")
    args = parser.parse_args()

    out = Path(args.out) if args.out else \
          OUTPUT_DIR / f"gambhirananda_{Path(args.pdf).stem.lower().replace(' ','_')}.json"

    process_pdf(args.pdf, out, args.start, args.end, args.resume, fixed_source=args.fixed_source)
