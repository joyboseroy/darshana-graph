"""
convert_madhva.py — parse Madhva's Brahmasutra Bhashya (S. Subba Rau, 1904)
=============================================================================
Source: archive.org "Brahmasutra Sri Madhvacharya English_djvu.txt"
(part of the "Brahma Sutra (Vedanta) by Three Old commentaries" collection)

Structure:
  - ADHYAYA I / ADHYAYA II / ADHYAYA III / ADHYAYA IV  -- chapter headers
  - FIRST PADA / SECOND PADA / THIRD PADA / FOURTH PADA -- section headers
  - Numbered sutras: "1. (text of sutra)" followed by Madhva's commentary
    in prose until the next numbered sutra
  - Noise to strip: "ankurnagpall08@gmail.com" (scan-spam), page headers
    like "32 SUTRA-BHASHYA. [ADHYAYA I,", roman-numeral intro page markers

Run:
  python convert_madhva.py --file "Brahmasutra Sri Madhvacharya English_djvu.txt"
"""

import re
import json
import argparse
from pathlib import Path

OUTPUT_DIR = Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)

NOISE_PATTERNS = [
    re.compile(r'ankurnagpall0?8@gmail\.com', re.IGNORECASE),
    re.compile(r'^\d+\s+SUTRA-BHASHYA\.?\s*\[?ADHYAYA', re.IGNORECASE),
    re.compile(r'^SUTRA-BHASHYA\.?\s*\[?ADHYAYA', re.IGNORECASE),
    re.compile(r'^INTRODUCTION,?\s*$', re.IGNORECASE),
    re.compile(r'^[ivxlcdm]+\.?\s*$', re.IGNORECASE),   # bare roman numeral page nums
]

ADHYAYA_RE = re.compile(
    r'^(FIRST|SECOND|THIRD|FOURTH)\s+ADHYAYA\.?$|^ADHYAYA\s+([IVX]+)\.?$',
    re.IGNORECASE
)
PADA_RE = re.compile(
    r'^(FIRST|SECOND|THIRD|FOURTH)\s+PADA\.?,?$',
    re.IGNORECASE
)
SUTRA_RE = re.compile(r'^(\d+)\.\s*\(?(.+)')

ADHYAYA_NUM = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4,
               "I": 1, "II": 2, "III": 3, "IV": 4}
PADA_NUM = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4}


def is_noise(line):
    return any(p.search(line) for p in NOISE_PATTERNS)


# Page-header noise that can appear mid-line, not just as standalone lines
MIDLINE_NOISE_RE = re.compile(
    r'\d{1,4}\s+SUTRA-BHASHYA,?\s*\[?ADHYAYA\s*[IVX1-4]*,?',
    re.IGNORECASE
)
MIDLINE_NOISE_RE2 = re.compile(
    r'INTRODUCTION,?\s*[ivxlcdm]+\.?',
    re.IGNORECASE
)


def clean_line(line):
    line = re.sub(r'ankurnagpall0?8@gmail\.com', '', line, flags=re.IGNORECASE)
    line = MIDLINE_NOISE_RE.sub('', line)
    line = MIDLINE_NOISE_RE2.sub('', line)
    return line.strip()


def parse_file(filepath):
    raw_lines = Path(filepath).read_text(encoding="utf-8", errors="replace").split("\n")

    records = []
    current_adhyaya = 1
    current_pada = 1
    current_sutra_num = None
    current_sutra_text = []
    current_commentary = []
    in_sutra_text = False  # True while reading the sutra statement itself
    past_introduction = False
    intro_marker_count = 0

    def flush():
        nonlocal current_sutra_text, current_commentary, current_sutra_num
        if current_sutra_num is not None and (current_sutra_text or current_commentary):
            sutra_text = " ".join(current_sutra_text).strip()
            commentary_text = " ".join(current_commentary).strip()
            sutra_text = re.sub(r'\s+', ' ', sutra_text)
            commentary_text = re.sub(r'\s+', ' ', commentary_text)

            if len(sutra_text) > 5 or len(commentary_text) > 20:
                records.append({
                    "id":          f"brahma_sutras_madhva_{current_adhyaya}_{current_pada}_{current_sutra_num:03d}",
                    "source":      "brahma_sutras",
                    "tradition":   "hindu_astika",
                    "darshana":    "vedanta",
                    "chapter":     current_adhyaya,
                    "section":     current_pada,
                    "verse":       current_sutra_num,
                    "segment_id":  f"bs_{current_adhyaya}.{current_pada}.{current_sutra_num}",
                    "text":        sutra_text,
                    "translator":  "subba_rau_1904",
                    "commentaries": [{
                        "commentator": "madhva",
                        "school":      "dvaita",
                        "lang":        "en",
                        "text":        commentary_text,
                    }] if commentary_text else [],
                })
        current_sutra_text = []
        current_commentary = []

    for raw_line in raw_lines:
        if is_noise(raw_line):
            continue
        line = clean_line(raw_line)
        if not line:
            continue

        # Detect entry into main body (skip Preface/Introduction roman-numeral pages)
        if not past_introduction:
            # Heuristic: once we hit "ADHYAYA I." as a standalone heading
            # AFTER having seen it at least once already (intro mentions it too),
            # or once we see the first real numbered sutra pattern, we're in the body.
            if SUTRA_RE.match(line) and len(line) < 200:
                past_introduction = True
            else:
                # Track standalone ADHYAYA headers; the 2nd occurrence = real start
                if re.match(r'^ADHYAYA\s+I\.?$', line, re.IGNORECASE):
                    intro_marker_count += 1
                    if intro_marker_count >= 2:
                        past_introduction = True
                continue

        # Chapter header
        m = ADHYAYA_RE.match(line)
        if m:
            flush()
            word = (m.group(1) or m.group(2) or "").upper()
            current_adhyaya = ADHYAYA_NUM.get(word, current_adhyaya)
            current_pada = 1
            current_sutra_num = None
            continue

        # Section header
        m = PADA_RE.match(line)
        if m:
            flush()
            word = m.group(1).upper()
            current_pada = PADA_NUM.get(word, current_pada)
            current_sutra_num = None
            continue

        # New sutra
        m = SUTRA_RE.match(line)
        if m:
            flush()
            current_sutra_num = int(m.group(1))
            current_sutra_text = [m.group(2)]
            in_sutra_text = True
            continue

        # Continuation lines: heuristically, sutra text is usually short
        # (1-3 lines) and commentary is everything after.
        if current_sutra_num is not None:
            if in_sutra_text and len(current_sutra_text) < 3 and not line[0].islower():
                current_sutra_text.append(line)
            else:
                in_sutra_text = False
                current_commentary.append(line)

    flush()
    return records


def convert(filepath):
    print(f"Parsing {filepath} ...")
    records = parse_file(filepath)
    print(f"  -> {len(records)} sutra records")

    out = OUTPUT_DIR / "brahma_sutras_madhva.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print(f"Saved -> {out}")

    from collections import Counter
    by_adhyaya = Counter(r["chapter"] for r in records)
    print("\nBy Adhyaya:")
    for ch, count in sorted(by_adhyaya.items()):
        print(f"  Adhyaya {ch}: {count} sutras")

    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to the djvu.txt file")
    args = parser.parse_args()
    convert(args.file)
