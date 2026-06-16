"""
convert_prabhupada_1972.py — parse "Bhagavad-Gita As It Is (Original 1972 Edition)"
======================================================================================
Source: PDF with embedded text (no OCR needed), extracted via pdftotext.

Structure per verse:
  CHAPTER ONE / CHAPTER TWO / ... -- chapter header (word-form numbers)
  TEXT N                          -- verse number marker
  <devanagari lines>
  <transliteration lines>
  <word-meanings paragraph, ends with period>
  TRANSLATION
  <translation paragraph>
  PURPORT
  <purport, possibly very long, multiple paragraphs>
  TEXT N+1 (or CHAPTER TWO etc — next boundary)

Run:
  pdftotext "Bhagavad-Gita As It Is (Original 1972 Edition).pdf" bg1972.txt
  python convert_prabhupada_1972.py --file bg1972.txt
"""

import re
import json
import argparse
from pathlib import Path

OUTPUT_DIR = Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)

CHAPTER_WORDS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6,
    "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10, "ELEVEN": 11,
    "TWELVE": 12, "THIRTEEN": 13, "FOURTEEN": 14, "FIFTEEN": 15,
    "SIXTEEN": 16, "SEVENTEEN": 17, "EIGHTEEN": 18,
}

CHAPTER_RE = re.compile(r'^CHAPTER\s+(' + "|".join(CHAPTER_WORDS.keys()) + r')\b', re.IGNORECASE)
TEXT_RE    = re.compile(r'^TEXT\s+(\d+)(?:[-–](\d+))?\s*$')   # handles "TEXT 5" and "TEXT 5-6"
TRANSLATION_RE = re.compile(r'^TRANSLATION\s*$')
PURPORT_RE     = re.compile(r'^PURPORT\s*$')

DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]')


def is_devanagari_line(line):
    chars = [c for c in line if not c.isspace()]
    if not chars:
        return False
    devanagari_count = sum(1 for c in chars if DEVANAGARI_RE.match(c))
    return devanagari_count / len(chars) > 0.3


def parse_file(filepath):
    lines = Path(filepath).read_text(encoding="utf-8", errors="replace").split("\n")

    records = []
    current_chapter = 1
    current_verse_num = None
    state = None  # None | 'devanagari' | 'transliteration' | 'word_meanings' | 'translation' | 'purport'

    sanskrit_lines = []
    iast_lines = []
    word_meaning_lines = []
    translation_lines = []
    purport_lines = []

    def flush():
        nonlocal sanskrit_lines, iast_lines, word_meaning_lines, translation_lines, purport_lines
        if current_verse_num is not None and (translation_lines or purport_lines):
            records.append({
                "id":            f"bg_{current_chapter}_{current_verse_num}",
                "source":        "bhagavad_gita",
                "tradition":     "hindu_astika",
                "darshana":      "vedanta",
                "chapter":       current_chapter,
                "verse":         current_verse_num,
                "segment_id":    f"bg_{current_chapter}.{current_verse_num}",
                "sanskrit":      " ".join(sanskrit_lines).strip(),
                "iast":          " ".join(iast_lines).strip(),
                "word_meanings": " ".join(word_meaning_lines).strip(),
                "text":          " ".join(translation_lines).strip(),
                "translator":    "prabhupada_1972",
                "commentaries": [{
                    "commentator": "prabhupada",
                    "school":      "achintya_bhedabheda",
                    "lang":        "en",
                    "text":        " ".join(purport_lines).strip(),
                }] if purport_lines else [],
            })
        sanskrit_lines = []
        iast_lines = []
        word_meaning_lines = []
        translation_lines = []
        purport_lines = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Chapter boundary
        m = CHAPTER_RE.match(line)
        if m:
            flush()
            current_chapter = CHAPTER_WORDS[m.group(1).upper()]
            current_verse_num = None
            state = None
            continue

        # New verse boundary
        m = TEXT_RE.match(line)
        if m:
            flush()
            current_verse_num = int(m.group(1))
            state = "devanagari"
            continue

        if current_verse_num is None:
            continue  # front matter / intro before TEXT 1

        if TRANSLATION_RE.match(line):
            state = "translation"
            continue
        if PURPORT_RE.match(line):
            state = "purport"
            continue

        # Devanagari block -> transliteration block transition:
        # once we hit a non-devanagari line while in 'devanagari' state,
        # and it doesn't look like a word-meanings line (no em-dash pattern),
        # treat it as transliteration.
        if state == "devanagari":
            if is_devanagari_line(line):
                sanskrit_lines.append(line)
                continue
            else:
                state = "transliteration"
                # fall through to transliteration handling below

        if state == "transliteration":
            # Word meanings lines contain em-dash style "word—meaning;" pairs
            if "—" in line or re.search(r'\w+-\w+—', line):
                state = "word_meanings"
                word_meaning_lines.append(line)
            else:
                iast_lines.append(line)
            continue

        if state == "word_meanings":
            word_meaning_lines.append(line)
            continue

        if state == "translation":
            translation_lines.append(line)
            continue

        if state == "purport":
            purport_lines.append(line)
            continue

    flush()
    return records


def convert(filepath):
    print(f"Parsing {filepath} ...")
    records = parse_file(filepath)
    print(f"  -> {len(records)} verse records")

    out = OUTPUT_DIR / "bg_prabhupada_1972.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print(f"Saved -> {out}")

    from collections import Counter
    by_chapter = Counter(r["chapter"] for r in records)
    print("\nBy chapter:")
    for ch, count in sorted(by_chapter.items()):
        print(f"  Chapter {ch}: {count} verses")

    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to extracted .txt file")
    args = parser.parse_args()
    convert(args.file)
