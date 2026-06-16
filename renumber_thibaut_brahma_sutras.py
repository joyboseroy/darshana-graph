"""
renumber_thibaut_brahma_sutras.py
====================================
brahma_sutras.json (Thibaut's Shankara + Ramanuja translations) has no
usable chapter/section/verse fields -- the original scraper only captured
a meaningless 'block_0' sutra_ref. But the actual TEXT of each block
reliably starts with the real sutra number ("1. Then therefore...",
"2. (Brahman is that)...") once past front matter, alternating with
stray site-navigation chrome blocks ("Sacred Texts / Hinduism / Index...").

This script, per commentator (shankara / ramanuja):
  1. Drops navigation-chrome blocks entirely (pure scraping noise)
  2. Tracks Adhyaya/Pada position via "FIRST ADHYAYA"/"PADA I" style
     headers embedded in the text
  3. Extracts the leading sutra number from each real content block
  4. Assigns chapter/section/verse fields so this file can finally be
     joined against brahma_sutras_madhva.json on (chapter, section, verse)

Output: corpus/brahma_sutras.json is updated in place (backup created)
"""

import json
import re
import shutil
from pathlib import Path
from collections import Counter

SRC = Path("corpus/brahma_sutras.json")
BACKUP = Path("corpus/brahma_sutras.json.bak2")

NAV_CHROME_RE = re.compile(
    r'^(Sacred Texts|Buy this Book|The Vedanta Sutras, commentary)',
    re.IGNORECASE
)

ADHYAYA_WORDS = {
    "FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4,
}
ADHYAYA_RE = re.compile(
    r'(FIRST|SECOND|THIRD|FOURTH)\s+ADHY[ÂA]YA', re.IGNORECASE
)
PADA_WORDS = {"I": 1, "II": 2, "III": 3, "IV": 4}
PADA_RE = re.compile(r'P[ÂA]DA\s+(I{1,3}V?|IV)\b', re.IGNORECASE)

SUTRA_START_RE = re.compile(r'^(\d+)\.\s')


def is_nav_chrome(text):
    return bool(NAV_CHROME_RE.match(text.strip()))


def is_front_matter(text):
    """Skip preface/introduction/contents pages (roman numeral page markers)."""
    if re.search(r'\bp\.\s*[ivxlcdm]+\b', text[:50], re.IGNORECASE):
        return True
    if "CONTENTS" in text[:200] or "INTRODUCTION" in text[:200].upper():
        # Only treat as front matter if it ALSO lacks a leading sutra number
        if not SUTRA_START_RE.match(text.strip()):
            return True
    return False


def process_commentator_blocks(records):
    """
    records: list of dicts for ONE commentator, in original scrape order.
    Returns: new list with chapter/section/verse assigned, nav chrome dropped.
    """
    current_adhyaya = 1
    current_pada = 1
    current_sutra_num = 0
    out = []

    for r in records:
        text = r.get("text", "")

        if is_nav_chrome(text):
            continue
        if is_front_matter(text):
            continue

        # Update Adhyaya/Pada tracking from headers embedded anywhere in this block
        m = ADHYAYA_RE.search(text)
        if m:
            current_adhyaya = ADHYAYA_WORDS.get(m.group(1).upper(), current_adhyaya)
            current_pada = 1  # reset pada on new adhyaya

        m = PADA_RE.search(text)
        if m:
            roman = m.group(1).upper()
            current_pada = PADA_WORDS.get(roman, current_pada)

        # Extract leading sutra number if present
        m = SUTRA_START_RE.match(text.strip())
        if m:
            current_sutra_num = int(m.group(1))
        else:
            # Continuation block with no leading number -- still part of
            # the current sutra's commentary, don't advance the counter
            pass

        if current_sutra_num == 0:
            continue  # haven't reached real sutra content yet

        new_record = dict(r)
        new_record["chapter"] = current_adhyaya
        new_record["section"] = current_pada
        new_record["verse"] = current_sutra_num
        new_record["segment_id"] = f"bs_{current_adhyaya}.{current_pada}.{current_sutra_num}"
        out.append(new_record)

    return out


def main():
    if not BACKUP.exists():
        shutil.copy(SRC, BACKUP)
        print(f"Backed up -> {BACKUP}")

    data = json.loads(SRC.read_text(encoding="utf-8"))
    print(f"Loaded {len(data)} total records")

    shankara_records = [r for r in data if "shankara" in r.get("id", "")]
    ramanuja_records = [r for r in data if "ramanuja" in r.get("id", "")]
    print(f"  Shankara: {len(shankara_records)}")
    print(f"  Ramanuja: {len(ramanuja_records)}")

    shankara_fixed = process_commentator_blocks(shankara_records)
    ramanuja_fixed = process_commentator_blocks(ramanuja_records)

    print(f"\nAfter dropping nav-chrome/front-matter and assigning sutra refs:")
    print(f"  Shankara: {len(shankara_fixed)} usable blocks")
    print(f"  Ramanuja: {len(ramanuja_fixed)} usable blocks")

    combined = shankara_fixed + ramanuja_fixed

    # Re-assign globally unique IDs now that content is cleaned
    seen = Counter()
    for r in combined:
        commentator = "shankara" if "shankara" in r["id"] else "ramanuja"
        seen[commentator] += 1
        r["id"] = f"brahma_sutras_{commentator}_{seen[commentator]:05d}"
        r["commentaries"] = [{
            "commentator": commentator,
            "school": "advaita" if commentator == "shankara" else "vishishtadvaita",
            "lang": "en",
            "text": r.get("text", ""),
        }]

    SRC.write_text(json.dumps(combined, ensure_ascii=False, indent=2))
    print(f"\nSaved cleaned + renumbered file -> {SRC}")
    print(f"Final record count: {len(combined)}")

    # Sample check
    print("\nSample of fixed Shankara records:")
    shankara_out = [r for r in combined if "shankara" in r["id"]]
    for r in shankara_out[:5]:
        print(f"  {r['segment_id']}: {r['text'][:80]}")


if __name__ == "__main__":
    main()
