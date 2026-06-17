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

# Pali sutta argumentation does not use Sanskrit commentarial idiom
# (the markers above return a flat 0% on every Pali theme/collection
# tested). Reading actual undeclared_questions passages shows real
# argumentative structure instead built from named interlocutors,
# question-and-refusal exchanges, and the recurring tetralemma pattern
# ("neither X nor not-X"). These markers are a first attempt at Pali-
# specific detection, built from a small number of directly-read
# examples rather than a systematic survey, and should be treated as
# exploratory in the same way the Sanskrit markers above are.
PALI_DIALOGUE_MARKERS = [
    r"why didn.t you answer", r"why (did|does) (the|he|she) not answer",
    r"sir, (why|what|how)",  # direct address opening a challenge/question
    r"neither .{0,40} nor (no longer|not)",  # tetralemma "neither X nor not-X"
    r"still exists.{0,20}after death", r"no longer exists.{0,20}after death",
    r"the (jain|wanderer|ascetic|brahmin) of the .{0,30} clan",  # named interlocutor intro
    r"is fueled by",  # recurring metaphor-based answer pattern in this corpus
    r"i (don.t|do not) (say|declare|assert) that",
]
PALI_DIALOGUE_RE = re.compile("|".join(PALI_DIALOGUE_MARKERS), re.IGNORECASE)

SENTENCE_SPLIT_RE = re.compile(r'[.!?]+\s+')


def split_into_sentences(text):
    """
    Split text into sentences. Falls back to a fixed-width pseudo-sentence
    split (every ~20 words) when the text has no recognizable sentence-
    ending punctuation at all, which happens for some commentators whose
    captured text is short gloss-style annotations rather than full
    prose with standard punctuation. Without this fallback, words-per-
    sentence is undefined (reported as near-zero) for those commentators,
    which looked like a real stylistic finding but was actually a parsing
    gap.
    """
    raw_sentences = [s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(raw_sentences) >= 2:
        return raw_sentences

    words = text.split()
    if len(words) < 5:
        return [text] if text.strip() else []

    PSEUDO_SENTENCE_WORDS = 20
    return [
        " ".join(words[i:i + PSEUDO_SENTENCE_WORDS])
        for i in range(0, len(words), PSEUDO_SENTENCE_WORDS)
    ]


THEME_TAG_FILE = Path("corpus/buddhism_philosophical_subset.json")


def collect_passages_by_theme():
    """
    The curated Buddhist philosophical subset carries a theme_tag field
    spanning doctrinal categories (dependent_origination, four_noble_truths,
    eightfold_path, etc.) independent of which Nikaya/collection a passage
    comes from. This lets us ask a different question than the existing
    collection-level comparison: does writing style vary by WHICH DOCTRINE
    is being discussed, holding collection-level genre effects aside, since
    several themes draw passages from multiple collections?
    """
    if not THEME_TAG_FILE.exists():
        return {}
    data = json.loads(THEME_TAG_FILE.read_text(encoding="utf-8"))
    by_theme = defaultdict(list)
    for r in data:
        theme = r.get("theme_tag")
        text = r.get("text", "")
        if theme and text:
            by_theme[theme].append(text)
    return by_theme


TEXT_FIELD_SOURCE_MAP = {
    "sn_nikaya": "theravada",
    "kn_sutta_nipata_nikaya": "theravada",
    "kn_khuddakapatha_nikaya": "theravada",
    "kn_dhammapada_nikaya": "theravada",
    "kn_itivuttaka_nikaya": "theravada",
    "kn_udana_nikaya": "theravada",
    "sutrakritanga": "jain_common",
    "acaranga_sutra": "jain_common",
    "tattvartha_sutra": "jain_common",
}


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


def collect_passages_by_commentator(records, by="commentator"):
    """
    Group passages by commentator (default) or by source-derived label
    (for Buddhism/Jainism, which store content in top-level "text" rather
    than commentaries[], using TEXT_FIELD_SOURCE_MAP as the label).
    """
    by_key = defaultdict(list)
    for r in records:
        for c in r.get("commentaries", []) or []:
            key = c.get(by)
            text = c.get("text", "")
            if key and text:
                by_key[key].append(text)

        source = r.get("source", "")
        label = TEXT_FIELD_SOURCE_MAP.get(source)
        if label:
            top_text = r.get("text", "") or ""
            if top_text:
                by_key[label if by != "commentator" else source].append(top_text)

    return by_key


def analyze_commentator(passages):
    """Compute stylometric stats for one commentator's full set of passages."""
    total_words = 0
    total_sentences = 0
    all_words = set()
    quotation_hits = 0
    refutation_hits = 0
    pali_dialogue_hits = 0
    total_chars = 0
    used_fallback_split = 0

    for text in passages:
        if not text:
            continue
        total_chars += len(text)

        has_real_punctuation = len(SENTENCE_SPLIT_RE.split(text)) >= 2
        if not has_real_punctuation:
            used_fallback_split += 1

        sentences = split_into_sentences(text)
        total_sentences += len(sentences)

        words = re.findall(r"[a-zA-Z']+", text.lower())
        total_words += len(words)
        all_words.update(words)

        if QUOTATION_RE.search(text):
            quotation_hits += 1
        if REFUTATION_RE.search(text):
            refutation_hits += 1
        if PALI_DIALOGUE_RE.search(text):
            pali_dialogue_hits += 1

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
        "pct_passages_with_pali_dialogue": 100 * pali_dialogue_hits / n_passages,
        "pct_used_fallback_split": 100 * used_fallback_split / n_passages,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commentators", nargs="+", default=None,
                        help="Limit to specific commentators, e.g. shankara ramanuja madhva")
    parser.add_argument("--min-passages", type=int, default=10,
                        help="Skip commentators with fewer than this many passages")
    parser.add_argument("--by-theme", action="store_true",
                        help="Group by theme_tag (Buddhist philosophical subset) instead of by commentator")
    args = parser.parse_args()

    if args.by_theme:
        print("Loading Buddhist philosophical subset by theme...")
        by_commentator = collect_passages_by_theme()
        print(f"Loaded {sum(len(v) for v in by_commentator.values())} passages across {len(by_commentator)} themes\n")
    else:
        print("Loading corpus records...")
        records = load_all_corpus_records()
        print(f"Loaded {len(records)} records\n")
        by_commentator = collect_passages_by_commentator(records, by="commentator")

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
          f"{'VocabDiv':>9} {'%Quote':>8} {'%Refute':>8} {'%PaliDlg':>9} {'%NoPunct':>9}")
    print("-" * 106)
    for commentator, s in sorted(results.items(), key=lambda x: -x[1]["n_passages"]):
        print(f"{commentator:<20} {s['n_passages']:>9} {s['avg_chars_per_passage']:>9.0f} "
              f"{s['avg_words_per_sentence']:>11.1f} {s['vocabulary_diversity']:>9.3f} "
              f"{s['pct_passages_with_quotation']:>7.1f}% {s['pct_passages_with_refutation']:>7.1f}% "
              f"{s['pct_passages_with_pali_dialogue']:>8.1f}% "
              f"{s['pct_used_fallback_split']:>8.1f}%")

    print("\nNotes:")
    print("  AvgChars: average commentary length per passage (longer = more elaboration)")
    print("  Words/Sent: average sentence length (longer = denser, more subordinate-clause argument)")
    print("  VocabDiv: unique words / total words (higher = more varied vocabulary, less repetitive)")
    print("  %Quote: fraction of passages containing an explicit scripture-citation marker")
    print("  %Refute: fraction of passages containing an explicit refutation/opponent marker")
    print("  %PaliDlg: fraction of passages containing Pali-style dialogue/argumentation markers")
    print("            (named interlocutors, question-refusal exchanges, tetralemma phrasing).")
    print("            Built from a small number of directly-read examples, not a systematic")
    print("            survey; exploratory in the same sense as %Quote and %Refute above.")
    print("  %NoPunct: fraction of passages with no sentence-ending punctuation, using a 20-word")
    print("            pseudo-sentence fallback instead. High %NoPunct means Words/Sent is less")
    print("            meaningful for that commentator (likely short gloss-style text, not full prose).")
    print("\nThis is a first-pass heuristic, not a rigorous linguistic study.")
    print("Treat differences as a starting point for closer reading, not a final claim.")


if __name__ == "__main__":
    main()
