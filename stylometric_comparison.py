"""
stylometric_comparison.py
============================
Compares HOW different commentators argue, not what they conclude.
Pure text statistics, no embeddings, no LLM calls, no external
dependencies beyond the standard library. Should run instantly and
without any environment issues.

For each commentator, computes:
  - Average sentence length (words per sentence)
  - Vocabulary diversity (unique words / total words, a rough proxy for
    repetitiveness vs varied argument)
  - Quotation density: how often the commentary contains a scripture
    citation marker (quoted Sanskrit terms, "as it is said", "the
    scripture declares", etc) vs original argument
  - Refutation rate: how often the commentary explicitly names and
    refutes another position ("this view is wrong", "the opponent
    argues", "we reply")
  - Average commentary length per verse

This is a first-pass heuristic stylometric fingerprint, not a rigorous
linguistic study, but it surfaces real, checkable differences in
argumentative style across schools.

Run:
  python stylometric_comparison.py
  python stylometric_comparison.py --commentators shankara ramanuja madhva
"""

import json
import re
import argparse
from pathlib import Path
from collections import defaultdict

CORPUS_DIR = Path("corpus")
SKIP_FILES = {"corpus.json"}

QUOTATION_MARKERS = [
    r"as it is said", r"the scripture (declares|says|states)",
    r"thus the (sruti|smriti|veda|upanishad)", r"as the (sruti|smriti) (says|declares)",
    r"it is (stated|written|taught) (in|that)", r"the text (says|declares|states)",
    r"\bsmriti\b", r"\bsruti\b",
]

REFUTATION_MARKERS = [
    r"this view is (wrong|untenable|refuted|mistaken)",
    r"the opponent (argues|maintains|holds|says)",
    r"we reply", r"this (objection|argument) (is|cannot)",
    r"\bprima facie\b", r"\bpurvapaksha\b",
    r"some (say|maintain|hold) that.{0,80}but",
    r"it might be (said|argued|objected)",
    r"this (cannot|does not) (be|hold|stand)",
]

QUOTATION_RE = re.compile("|".join(QUOTATION_MARKERS), re.IGNORECASE)
REFUTATION_RE = re.compile("|".join(REFUTATION_MARKERS), re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r'[.!?]+\s+')


def load_all_corpus_records():
    records = []
    for f in sorted(CORPUS_DIR.glob("*.json")):
        if f.name in SKIP_FILES or "progress" in f.name or f.name.endswith((".bak", ".bak2")):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, list):
            records.extend(data)
    return records


def analyze_commentator(passages):
    """Compute stylometric stats for one commentator's full set of passages."""
    total_words = 0
    total_sentences = 0
    all_words = set()
    quotation_hits = 0
    refutation_hits = 0
    total_chars = 0

    for text in passages:
        if not text:
            continue
        total_chars += len(text)
        sentences = [s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
        total_sentences += len(sentences)

        words = re.findall(r"[a-zA-Z']+", text.lower())
        total_words += len(words)
        all_words.update(words)

        if QUOTATION_RE.search(text):
            quotation_hits += 1
        if REFUTATION_RE.search(text):
            refutation_hits += 1

    n_passages = len(passages)
    if n_passages == 0 or total_sentences == 0:
        return None

    return {
        "n_passages": n_passages,
        "avg_chars_per_passage": total_chars / n_passages,
        "avg_words_per_sentence": total_words / total_sentences,
        "vocabulary_diversity": len(all_words) / max(total_words, 1),
        "pct_passages_with_quotation": 100 * quotation_hits / n_passages,
        "pct_passages_with_refutation": 100 * refutation_hits / n_passages,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commentators", nargs="+", default=None,
                        help="Limit to specific commentators, e.g. shankara ramanuja madhva")
    parser.add_argument("--min-passages", type=int, default=10,
                        help="Skip commentators with fewer than this many passages")
    args = parser.parse_args()

    print("Loading corpus records...")
    records = load_all_corpus_records()
    print(f"Loaded {len(records)} records\n")

    by_commentator = defaultdict(list)
    for r in records:
        for c in r.get("commentaries", []) or []:
            commentator = c.get("commentator")
            text = c.get("text", "")
            if commentator and text:
                by_commentator[commentator].append(text)

    if args.commentators:
        by_commentator = {k: v for k, v in by_commentator.items() if k in args.commentators}

    results = {}
    for commentator, passages in by_commentator.items():
        if len(passages) < args.min_passages:
            continue
        stats = analyze_commentator(passages)
        if stats:
            results[commentator] = stats

    if not results:
        print("No commentators met the minimum passage threshold.")
        return

    print(f"{'Commentator':<20} {'Passages':>9} {'AvgChars':>9} {'Words/Sent':>11} "
          f"{'VocabDiv':>9} {'%Quote':>8} {'%Refute':>8}")
    print("-" * 85)
    for commentator, s in sorted(results.items(), key=lambda x: -x[1]["n_passages"]):
        print(f"{commentator:<20} {s['n_passages']:>9} {s['avg_chars_per_passage']:>9.0f} "
              f"{s['avg_words_per_sentence']:>11.1f} {s['vocabulary_diversity']:>9.3f} "
              f"{s['pct_passages_with_quotation']:>7.1f}% {s['pct_passages_with_refutation']:>7.1f}%")

    print("\nNotes:")
    print("  AvgChars: average commentary length per passage (longer = more elaboration)")
    print("  Words/Sent: average sentence length (longer = denser, more subordinate-clause argument)")
    print("  VocabDiv: unique words / total words (higher = more varied vocabulary, less repetitive)")
    print("  %Quote: fraction of passages containing an explicit scripture-citation marker")
    print("  %Refute: fraction of passages containing an explicit refutation/opponent marker")
    print("\nThis is a first-pass heuristic, not a rigorous linguistic study.")
    print("Treat differences as a starting point for closer reading, not a final claim.")


if __name__ == "__main__":
    main()
