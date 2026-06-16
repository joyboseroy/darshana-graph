"""
embedding_disagreement_finder.py
===================================
Finds cross-school disagreement using sentence embeddings and clustering,
with NO LLM tagging step required. This is a cheap, fast, independent
complement to the LLM-based graph in corpus/tagged/ -- if both methods
flag the same concepts as contested, that's real corroborating evidence.

How it works:
  1. For a target concept (e.g. "atman"), collect every commentary passage
     across the corpus that explicitly mentions that concept's name (or a
     close synonym), grouped by school.
  2. Embed every passage with a sentence-transformer model.
  3. For each pair of schools, compute the average cosine distance between
     their passages discussing the same concept. A LARGE distance means
     the schools are saying very different things about that concept
     (semantic disagreement); a SMALL distance means they describe it
     similarly even while using different words.
  4. Rank concepts by how much their schools' embeddings disagree.

This needs no API key and no internet after the first model download.

Setup:
  pip install sentence-transformers --break-system-packages

Run:
  python embedding_disagreement_finder.py --concept atman
  python embedding_disagreement_finder.py --rank-concepts atman brahman jiva moksha karma dharma maya
"""

import json
import argparse
import re
from pathlib import Path
from collections import defaultdict
from itertools import combinations

CORPUS_DIR = Path("corpus")
SKIP_FILES = {"corpus.json"}

SCHOOL_TO_COMMENTATOR_HINTS = {
    "advaita": ["shankara", "sridhara", "anandagiri", "nilakantha", "dhanpati"],
    "vishishtadvaita": ["ramanuja", "vedanta_desika", "adidevananda"],
    "dvaita": ["madhva"],
    "dvaitadvaita": ["nimbarka", "srinivasa"],
    "achintya_bhedabheda": ["prabhupada"],
    "kashmir_shaivism": ["abhinavagupta"],
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


def passages_mentioning_concept(records, concept, window_chars=400):
    """
    Find passages (verse text or commentary text) that mention the concept
    by name, grouped by school. Returns {school: [passage_text, ...]}.
    """
    concept_pattern = re.compile(re.escape(concept), re.IGNORECASE)
    by_school = defaultdict(list)

    for r in records:
        verse_text = r.get("text", "") or ""

        for c in r.get("commentaries", []) or []:
            comm_text = c.get("text", "") or ""
            school = c.get("school")
            if not school or school == "general":
                continue

            combined = comm_text  # the commentary itself is what we analyze
            if not concept_pattern.search(combined):
                continue

            # Extract a window around the mention rather than the whole
            # (sometimes very long) commentary, to keep embeddings focused
            m = concept_pattern.search(combined)
            start = max(0, m.start() - window_chars // 2)
            end = min(len(combined), m.end() + window_chars // 2)
            snippet = combined[start:end].strip()

            if len(snippet) > 30:
                by_school[school].append(snippet)

    return by_school


def compute_school_disagreement(model, by_school, max_passages_per_school=40):
    """
    For each school, average its passage embeddings into one centroid
    vector. Then compute pairwise cosine distance between school centroids.
    Returns: list of (school_a, school_b, distance) and the per-school
    passage counts used.
    """
    import numpy as np

    centroids = {}
    counts = {}

    for school, passages in by_school.items():
        sample = passages[:max_passages_per_school]
        if len(sample) < 2:
            continue
        embeddings = model.encode(sample, show_progress_bar=False)
        centroid = np.mean(embeddings, axis=0)
        centroids[school] = centroid
        counts[school] = len(sample)

    pairs = []
    for school_a, school_b in combinations(sorted(centroids.keys()), 2):
        a, b = centroids[school_a], centroids[school_b]
        cos_sim = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
        cos_distance = 1 - cos_sim
        pairs.append((school_a, school_b, float(cos_distance)))

    pairs.sort(key=lambda x: -x[2])
    return pairs, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concept", default=None,
                        help="Single concept to analyze, e.g. atman")
    parser.add_argument("--rank-concepts", nargs="+", default=None,
                        help="Rank multiple concepts by overall school disagreement")
    parser.add_argument("--max-passages", type=int, default=40)
    args = parser.parse_args()

    print("Loading sentence-transformers model (first run downloads ~80MB)...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print("Loading corpus records...")
    records = load_all_corpus_records()
    print(f"Loaded {len(records)} records\n")

    if args.concept:
        by_school = passages_mentioning_concept(records, args.concept)
        print(f"Concept: {args.concept}")
        print(f"Schools with mentions: {list(by_school.keys())}")
        for school, passages in by_school.items():
            print(f"  {school}: {len(passages)} passages")
        print()

        pairs, counts = compute_school_disagreement(model, by_school, args.max_passages)
        print("Pairwise school disagreement (cosine distance, higher = more different):\n")
        for school_a, school_b, dist in pairs:
            print(f"  {school_a} vs {school_b}: {dist:.4f}  "
                  f"({counts[school_a]} vs {counts[school_b]} passages)")

    elif args.rank_concepts:
        results = []
        for concept in args.rank_concepts:
            by_school = passages_mentioning_concept(records, concept)
            if len(by_school) < 2:
                print(f"{concept}: not enough schools with mentions, skipping")
                continue
            pairs, counts = compute_school_disagreement(model, by_school, args.max_passages)
            if not pairs:
                continue
            avg_distance = sum(d for _, _, d in pairs) / len(pairs)
            max_pair = max(pairs, key=lambda x: x[2])
            results.append((concept, avg_distance, max_pair, len(by_school)))

        results.sort(key=lambda x: -x[1])
        print("\nConcepts ranked by average cross-school embedding disagreement:\n")
        for concept, avg_dist, max_pair, n_schools in results:
            school_a, school_b, dist = max_pair
            print(f"  {concept}: avg distance {avg_dist:.4f} across {n_schools} schools "
                  f"(most divergent pair: {school_a} vs {school_b} at {dist:.4f})")

    else:
        parser.error("Specify --concept X or --rank-concepts X Y Z")


if __name__ == "__main__":
    main()
