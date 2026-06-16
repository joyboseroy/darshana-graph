"""
convert_muller.py — parse Max Müller's SBE01/SBE15 Upanishad text dumps
==========================================================================
Input:  sbe01.txt, sbe15.txt (plain text, downloaded from sacred-texts.com)
Output: corpus/upanishads_muller.json

Structure of the source files:
  - Page markers like "[p. 123]" — stripped
  - Footnote markers like "[*1]" — stripped
  - Section headers: "FIRST KHANDA", "SECOND ADHYAYA" etc — chapter boundary
  - Numbered verses: "1. Text of the verse..."
  - Upanishad titles appear as their own headers e.g. "KHANDOGYA-UPANISHAD"

Run:
  python convert_muller.py
  python convert_muller.py --files sbe01.txt sbe15.txt
"""

import re
import json
import argparse
from pathlib import Path

OUTPUT_DIR = Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)

# Map title fragments (as they appear in ALL CAPS headers) to canonical source ids
UPANISHAD_TITLE_MAP = [
    (r"KHANDOGYA[\s-]?UPANISHAD",      "chandogya_upanishad"),
    (r"CHANDOGYA[\s-]?UPANISHAD",      "chandogya_upanishad"),
    (r"TALAVAKARA[\s-]?UPANISHAD",     "kena_upanishad"),
    (r"KENA[\s-]?UPANISHAD",           "kena_upanishad"),
    (r"AITAREYA[\s-]?UPANISHAD",       "aitareya_upanishad"),
    (r"KAUSHITAKI[\s-]?UPANISHAD",     "kaushitaki_upanishad"),
    (r"KATHA[\s-]?UPANISHAD",          "katha_upanishad"),
    (r"MUNDAKA[\s-]?UPANISHAD",        "mundaka_upanishad"),
    (r"TAITTIRIYAKA[\s-]?UPANISHAD",   "taittiriya_upanishad"),
    (r"TAITTIRIYA[\s-]?UPANISHAD",     "taittiriya_upanishad"),
    (r"BRIHADARANYAKA[\s-]?UPANISHAD", "brihadaranyaka_upanishad"),
    (r"SVETASVATARA[\s-]?UPANISHAD",   "svetasvatara_upanishad"),
    (r"MAITRAYANA[\s-]?BRAHMANA[\s-]?UPANISHAD", "maitri_upanishad"),
    (r"MAITRAYANA[\s-]?UPANISHAD",     "maitri_upanishad"),
    (r"MAITRI[\s-]?UPANISHAD",         "maitri_upanishad"),
    (r"MANDUKYA[\s-]?UPANISHAD",       "mandukya_upanishad"),
]

# Section header patterns that mark chapter/section boundaries (not verses)
SECTION_HEADER_RE = re.compile(
    r'^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|'
    r'ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|SIXTEENTH)\s+'
    r'(KHANDA|ADHYAYA|BRAHMANA|CHAPTER|PRAPATHAKA|VALLI|MUNDAKA|PART|ANUVAKA)',
    re.IGNORECASE
)

# Lines that are pure noise — sacred-texts footer/footnote markers, never verse content
NOISE_LINE_RE = re.compile(
    r'^(Footnotes?|\^?\d+:\d+\s|The Upanishads,\s*Part)',
    re.IGNORECASE
)

# Verse start pattern: "1. " or "23. " at line start
VERSE_RE = re.compile(r'^(\d+)\.\s+(.+)')

PAGE_MARKER_RE = re.compile(r'\[p\.\s*[ivxlcdm\d]+\]', re.IGNORECASE)
FOOTNOTE_REF_RE = re.compile(r'\[\*\d+\]')


def clean_line(line):
    line = PAGE_MARKER_RE.sub('', line)
    line = FOOTNOTE_REF_RE.sub('', line)
    return line.strip()


def detect_upanishad_title(line):
    upper = line.upper()
    for pattern, source_id in UPANISHAD_TITLE_MAP:
        if re.search(pattern, upper):
            return source_id
    return None


def parse_file(filepath):
    """Parse one SBE text file into verse records."""
    lines = Path(filepath).read_text(encoding="utf-8", errors="replace").split("\n")

    records = []
    current_upanishad = "unknown_upanishad"
    current_section = ""
    current_verse_text = []
    current_verse_num = None

    def flush_verse():
        nonlocal current_verse_text, current_verse_num
        if current_verse_text and current_verse_num is not None:
            text = " ".join(current_verse_text).strip()
            text = re.sub(r'\s+', ' ', text)
            if len(text) > 15:
                records.append({
                    "id":          f"{current_upanishad}_muller_{current_verse_num:04d}_{len(records):04d}",
                    "source":      current_upanishad,
                    "tradition":   "hindu_astika",
                    "darshana":    "vedanta",
                    "section":     current_section,
                    "verse":       current_verse_num,
                    "segment_id":  f"{current_upanishad}_{current_section}_{current_verse_num}",
                    "text":        text,
                    "translator":  "muller_1879_1884",
                    "commentaries": [],
                })
        current_verse_text = []

    for raw_line in lines:
        line = clean_line(raw_line)
        if not line:
            continue
        if NOISE_LINE_RE.match(line):
            continue

        # Check for Upanishad title change
        detected = detect_upanishad_title(line)
        if detected and detected != current_upanishad:
            flush_verse()
            current_upanishad = detected
            current_verse_num = None
            continue

        # Check for section header (chapter boundary)
        if SECTION_HEADER_RE.match(line):
            flush_verse()
            current_section = line
            current_verse_num = 0  # allow unnumbered prose right after header to attach
            current_verse_text = []
            continue

        # Check for new verse
        verse_match = VERSE_RE.match(line)
        if verse_match:
            flush_verse()
            current_verse_num = int(verse_match.group(1))
            current_verse_text = [verse_match.group(2)]
            continue

        # Continuation of current verse (if we're inside one)
        if current_verse_num is not None:
            current_verse_text.append(line)

    flush_verse()
    return records


def convert(files):
    all_records = []
    for f in files:
        if not Path(f).exists():
            print(f"  Skipping {f} — not found")
            continue
        print(f"Parsing {f} ...")
        records = parse_file(f)
        print(f"  -> {len(records)} verse records")
        all_records.extend(records)

    out = OUTPUT_DIR / "upanishads_muller.json"
    out.write_text(json.dumps(all_records, ensure_ascii=False, indent=2))
    print(f"\nSaved {len(all_records)} total records -> {out}")

    from collections import Counter
    print("\nBreakdown by Upanishad:")
    for src, count in Counter(r["source"] for r in all_records).most_common():
        print(f"  {src}: {count}")

    return all_records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", nargs="+", default=["sbe01.txt", "sbe15.txt"])
    args = parser.parse_args()
    convert(args.files)
