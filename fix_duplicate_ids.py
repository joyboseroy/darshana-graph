"""
fix_duplicate_ids.py — check and fix duplicate IDs across ALL corpus files
=============================================================================
Several scraper functions (parse_sacred_texts_page, parse_single_page_darshana,
parse_archive_txt_darshana, scrape_sacred_texts_jain) reset their per-page
block counter to 0 on every HTML page scraped, producing colliding IDs
across hundreds of pages. This silently breaks the tagging pipeline's
--resume logic, which dedupes by ID and will skip almost everything once
even a few colliding IDs are marked "done".

This script checks every corpus/*.json file for ID uniqueness, and for
any file with duplicates, regenerates a globally unique id by appending
a running counter, preserving a backup and the original id under
_original_id for traceability.

Run:
  python fix_duplicate_ids.py              # check + fix everything
  python fix_duplicate_ids.py --check-only # report only, don't modify
"""

import json
import shutil
import argparse
from pathlib import Path
from collections import Counter

CORPUS_DIR = Path("corpus")
SKIP_NAMES = {"corpus.json"}


def check_file(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"ERROR reading: {e}"
    if not isinstance(data, list) or not data:
        return None, "not a non-empty list, skipping"
    ids = [r.get("id") for r in data if isinstance(r, dict)]
    total = len(ids)
    unique = len(set(ids))
    return data, (total, unique)


def fix_file(path, data):
    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy(path, backup)

    seen_prefix_counts = Counter()
    for r in data:
        old_id = r.get("id", "record")
        parts = old_id.rsplit("_", 1)
        prefix = parts[0] if len(parts) == 2 and parts[1].isdigit() else old_id
        seen_prefix_counts[prefix] += 1
        r["id"] = f"{prefix}_{seen_prefix_counts[prefix]:05d}"
        r["_original_id"] = old_id

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    new_unique = len(set(r["id"] for r in data))
    return new_unique == len(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    files = sorted(
        f for f in CORPUS_DIR.glob("*.json")
        if f.name not in SKIP_NAMES and "progress" not in f.name and not f.name.endswith(".bak")
    )

    print(f"Checking {len(files)} corpus files...\n")

    problem_files = []

    for f in files:
        data, result = check_file(f)
        if data is None:
            print(f"  {f.name}: {result}")
            continue

        total, unique = result
        status = "OK" if unique == total else "DUPLICATE IDs"
        print(f"  {f.name}: {total} records, {unique} unique IDs  [{status}]")

        if unique != total:
            problem_files.append((f, data, total, unique))

    if not problem_files:
        print("\nAll files have fully unique IDs. Nothing to fix.")
        return

    print(f"\n{len(problem_files)} file(s) need fixing: {[f.name for f,_,_,_ in problem_files]}")

    if args.check_only:
        print("--check-only set, not modifying anything.")
        return

    for f, data, total, unique in problem_files:
        print(f"\nFixing {f.name} ({unique} unique -> should be {total}) ...")
        ok = fix_file(f, data)
        print(f"  {'Fixed successfully' if ok else 'STILL HAS DUPLICATES -- investigate manually'}")
        print(f"  Backup saved at {f.with_suffix(f.suffix + '.bak')}")


if __name__ == "__main__":
    main()

