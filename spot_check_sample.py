"""
spot_check_sample.py
=====================
Pulls a random sample of passages flagged by the citation and refutation
regex markers in stylometric_comparison.py, so you can manually mark each
as a true or false positive. Writes a CSV you fill in by hand (add a
"correct" column with Y/N), then rerun with --score to get precision.

Usage:
  python spot_check_sample.py                  # generate sample CSV
  python spot_check_sample.py --score reviewed.csv   # after you fill it in
"""

import json
import re
import csv
import random
import argparse
from pathlib import Path
from collections import defaultdict

CORPUS_DIR = Path("corpus")
SKIP_FILES = {"progress.json"}

QUOTATION_RE = re.compile(
    r"as it is said|the scripture (declares|says)|scripture states|"
    r"it has been said|as the (sruti|smriti) (says|declares)|"
    r"the text (says|declares)|as stated in",
    re.IGNORECASE,
)
REFUTATION_RE = re.compile(
    r"the opponent (argues|says|holds|maintains)|this view is untenable|"
    r"this (cannot|can not) be (accepted|admitted)|we (deny|reject) this|"
    r"this objection is (refuted|answered)|some maintain that.*but|"
    r"against this it (may|might) be said",
    re.IGNORECASE,
)


def load_all_passages():
    passages = []
    for f in sorted(CORPUS_DIR.glob("*.json")):
        if f.name in SKIP_FILES or "progress" in f.name or f.name.endswith((".bak", ".bak2")):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for r in data:
            for c in r.get("commentaries", []) or []:
                text = c.get("text", "")
                commentator = c.get("commentator", "unknown")
                if text:
                    passages.append((commentator, text))
    return passages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", default=None, help="Path to a filled-in CSV to score")
    parser.add_argument("--n", type=int, default=50, help="Sample size per category")
    args = parser.parse_args()

    if args.score:
        total = 0
        correct = 0
        with open(args.score, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                mark = row.get("correct", "").strip().upper()
                if mark in ("Y", "N"):
                    total += 1
                    if mark == "Y":
                        correct += 1
        if total == 0:
            print("No scored rows found. Fill in the 'correct' column with Y or N.")
            return
        print(f"Precision: {correct}/{total} = {100*correct/total:.1f}%")
        return

    passages = load_all_passages()
    print(f"Loaded {len(passages)} total passages.")

    citation_hits = [(c, t) for c, t in passages if QUOTATION_RE.search(t)]
    refutation_hits = [(c, t) for c, t in passages if REFUTATION_RE.search(t)]

    print(f"Citation-flagged: {len(citation_hits)}, Refutation-flagged: {len(refutation_hits)}")

    random.seed(42)
    citation_sample = random.sample(citation_hits, min(args.n, len(citation_hits)))
    refutation_sample = random.sample(refutation_hits, min(args.n, len(refutation_hits)))

    out_path = Path("spot_check_sample.csv")
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "commentator", "passage", "correct"])
        for c, t in citation_sample:
            snippet = t[:400].replace("\n", " ")
            writer.writerow(["citation", c, snippet, ""])
        for c, t in refutation_sample:
            snippet = t[:400].replace("\n", " ")
            writer.writerow(["refutation", c, snippet, ""])

    print(f"\nWrote {len(citation_sample)} citation + {len(refutation_sample)} refutation rows to {out_path}")
    print("Open it, read each passage, and fill the 'correct' column with Y (the marker correctly")
    print("detected a real citation/refutation) or N (false positive - flagged but isn't really one).")
    print(f"Then run: python spot_check_sample.py --score {out_path}")


if __name__ == "__main__":
    main()
