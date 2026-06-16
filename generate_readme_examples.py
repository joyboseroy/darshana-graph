"""
generate_readme_examples.py
=============================
Pulls real cross-school disagreement examples directly from the tagged
graph data (corpus/tagged/*.jsonl), so README examples are backed by
actual extracted edges with real evidence quotes, not hand-written
illustrations.

For a chosen concept pair (e.g. atman/brahman), finds every edge in the
graph involving that pair, groups by school, and prints a ready-to-paste
markdown block showing each school's relation type and evidence quote.

Run:
  python generate_readme_examples.py --concept-a atman --concept-b brahman
  python generate_readme_examples.py --top-pairs 5     # auto-pick the most
                                                          # contested pairs
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict, Counter

TAGGED_DIR = Path("corpus/tagged")

SCHOOL_DISPLAY_NAMES = {
    "advaita": "Advaita Vedanta",
    "vishishtadvaita": "Vishishtadvaita",
    "dvaita": "Dvaita",
    "dvaitadvaita": "Dvaitadvaita",
    "achintya_bhedabheda": "Achintya Bhedabheda",
    "neo_vedanta": "Neo-Vedanta",
    "samkhya": "Samkhya",
    "yoga": "Yoga",
    "nyaya": "Nyaya",
    "vaisheshika": "Vaisheshika",
    "mimamsa": "Mimamsa",
    "theravada": "Theravada Buddhism",
    "jain_digambara": "Jain Digambara",
    "jain_shvetambara": "Jain Shvetambara",
    "jain_common": "Jainism",
    "kashmir_shaivism": "Kashmir Shaivism",
    "general": "General/unattributed",
}

RELATION_DISPLAY = {
    "IS_IDENTICAL_TO": "are identical",
    "IS_DISTINCT_FROM": "are distinct",
    "IS_QUALIFIED_ASPECT_OF": "is a qualified aspect of",
    "IS_SIMULTANEOUSLY_ONE_AND_DIFFERENT": "are simultaneously one and different",
    "PRESUPPOSES": "presupposes",
    "SUBLATES": "sublates",
    "LEADS_TO": "leads to",
    "OBSTRUCTS": "obstructs",
    "IS_CAUSE_OF": "is the cause of",
    "IS_MANIFESTATION_OF": "is a manifestation of",
    "RECONCILES": "reconciles",
    "CONTRADICTS_IN_SCHOOL": "contradicts",
    "DEFINED_AS": "is defined as",
}


def load_all_edges():
    """Load every edge from every tagged file, with source file noted."""
    edges = []
    for f in sorted(TAGGED_DIR.glob("*.jsonl")):
        if f.name == "test_verse.jsonl":
            continue
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                for rel in obj.get("relationships", []):
                    edges.append({
                        **rel,
                        "record_id": obj.get("record_id"),
                        "source": obj.get("source"),
                        "tagged_from_file": f.name,
                    })
    return edges


def find_contested_pairs(edges, min_schools=2, exclude_general=True):
    """Find concept pairs where 2+ non-general schools use different relations."""
    pair_school_relations = defaultdict(lambda: defaultdict(set))
    pair_evidence = defaultdict(dict)  # (pair, school, relation) -> example edge
    edges_by_pair_school = defaultdict(list)  # (pair, school) -> [edges]

    for e in edges:
        school = e.get("school")
        if exclude_general and school == "general":
            continue
        a, b = e.get("concept_a"), e.get("concept_b")
        if not a or not b:
            continue
        pair = tuple(sorted([a, b]))
        relation = e.get("relation")
        pair_school_relations[pair][school].add(relation)
        key = (pair, school, relation)
        if key not in pair_evidence:
            pair_evidence[key] = e
        edges_by_pair_school[(pair, school)].append(e)

    contested = []
    for pair, school_rels in pair_school_relations.items():
        if len(school_rels) < min_schools:
            continue
        all_relations = set()
        for rels in school_rels.values():
            all_relations.update(rels)
        if len(all_relations) > 1:
            contested.append((pair, school_rels, len(school_rels)))

    contested.sort(key=lambda x: -x[2])
    return contested, pair_evidence, edges_by_pair_school


def render_pair_markdown(pair, school_rels, pair_evidence, edges_by_pair_school):
    """
    For each school, pick the SINGLE most representative edge rather than
    listing every relation type that school happens to use somewhere in
    the corpus. Aggregating across hundreds of verses per school produces
    misleading noise (the same school appearing to assert contradictory
    things), so we surface one clean, confident example per school instead.

    Preference order: high confidence > longer/more substantive evidence
    quote > first seen. This is a simple heuristic, not a claim that the
    chosen edge is the school's only or definitive position.
    """
    a, b = pair
    lines = [f"### {a} and {b}\n"]

    for school in sorted(school_rels.keys()):
        candidates = edges_by_pair_school.get((pair, school), [])
        if not candidates:
            continue

        def score(e):
            conf_score = {"high": 2, "medium": 1, "low": 0}.get(e.get("confidence"), 0)
            quote_len = len(e.get("evidence_quote", "") or "")
            return (conf_score, quote_len)

        best = max(candidates, key=score)
        display_school = SCHOOL_DISPLAY_NAMES.get(school, school)
        display_relation = RELATION_DISPLAY.get(best.get("relation"), best.get("relation"))
        quote = best.get("evidence_quote", "")
        source = best.get("source", "")

        if quote:
            lines.append(
                f"**{display_school}** ({len(candidates)} relevant passage"
                f"{'s' if len(candidates) != 1 else ''} found): {a} {display_relation} {b}. "
                f"From the text ({source}): \"{quote}\"\n"
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concept-a", default=None)
    parser.add_argument("--concept-b", default=None)
    parser.add_argument("--top-pairs", type=int, default=None,
                        help="Auto-find and print the N most contested pairs")
    args = parser.parse_args()

    print("Loading tagged edges...")
    edges = load_all_edges()
    print(f"Loaded {len(edges)} total edges\n")

    contested, pair_evidence, edges_by_pair_school = find_contested_pairs(edges)
    print(f"Found {len(contested)} contested concept pairs (excluding 'general' school)\n")
    print("=" * 70)

    if args.concept_a and args.concept_b:
        target_pair = tuple(sorted([args.concept_a.lower(), args.concept_b.lower()]))
        match = next((c for c in contested if c[0] == target_pair), None)
        if not match:
            print(f"No contested pair found for {args.concept_a} / {args.concept_b}")
            print("Try --top-pairs 10 to see what's available")
            return
        pair, school_rels, n_schools = match
        print(render_pair_markdown(pair, school_rels, pair_evidence, edges_by_pair_school))

    elif args.top_pairs:
        for pair, school_rels, n_schools in contested[:args.top_pairs]:
            print(render_pair_markdown(pair, school_rels, pair_evidence, edges_by_pair_school))
            print("\n" + "-" * 70 + "\n")

    else:
        print("Top 10 most contested concept pairs (specific schools only):\n")
        for pair, school_rels, n_schools in contested[:10]:
            print(f"  {pair[0]} <-> {pair[1]}  ({n_schools} schools disagree)")
        print("\nRun with --concept-a X --concept-b Y for one pair,")
        print("or --top-pairs N for the top N pairs as markdown.")


if __name__ == "__main__":
    main()
