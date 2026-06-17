"""
audit_tagged.py — quality and coverage audit across all tagged output
=========================================================================
Run this after a tagging pass to get an honest picture of:
  - How many records got real concepts/relationships vs empty/error
  - Relation type distribution (sanity check against fixed vocabulary)
  - School distribution
  - Sample of highest-confidence multi-school disagreements (a preview
    of the tension-scoring analysis)

Run:
  python audit_tagged.py
"""

import json
import argparse
from pathlib import Path
from collections import Counter, defaultdict

TAGGED_DIR = Path("corpus/tagged")


def load_jsonl(path):
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def relation_profile_by_school(files, min_school_edges=20):
    """
    For each school with a specific (non-general) attribution, compute
    what fraction of its edges use each relation type. This answers a
    different question than the existing tension-preview: not "where do
    schools disagree on a specific concept pair" but "does each school
    have a distinctive overall argumentative signature in how it uses
    the relation vocabulary at all".

    Schools with fewer than min_school_edges specific-attribution edges
    are excluded from the printed table, since a percentage computed on
    a handful of edges is not meaningful; the excluded count is reported
    so this exclusion is visible rather than silent.
    """
    school_relation_counts = defaultdict(Counter)
    school_totals = Counter()

    for f in files:
        records = load_jsonl(f)
        for r in records:
            for rel in r.get("relationships", []):
                school = rel.get("school")
                relation = rel.get("relation")
                if not school or school == "general" or not relation:
                    continue
                school_relation_counts[school][relation] += 1
                school_totals[school] += 1

    included = {s: n for s, n in school_totals.items() if n >= min_school_edges}
    excluded = {s: n for s, n in school_totals.items() if n < min_school_edges}

    all_relations = sorted({rel for counts in school_relation_counts.values() for rel in counts})

    print("\n" + "=" * 70)
    print("RELATION-TYPE PROFILE BY SCHOOL")
    print(f"(schools with fewer than {min_school_edges} specific-attribution edges excluded)")
    print("=" * 70)

    if excluded:
        print(f"\nExcluded for insufficient data: {', '.join(f'{s} ({n})' for s, n in excluded.items())}")

    if not included:
        print("\nNo school has enough specific-attribution edges for this analysis.")
        return

    print(f"\n{'School':<22}{'Total edges':>13}  " + "  ".join(f"{rel[:18]:>18}" for rel in all_relations))
    for school, total in sorted(included.items(), key=lambda x: -x[1]):
        counts = school_relation_counts[school]
        row = f"{school:<22}{total:>13}  "
        row += "  ".join(f"{100*counts.get(rel,0)/total:>17.1f}%" for rel in all_relations)
        print(row)

    print("\nEach cell is the percentage of that school's specific-attribution edges using that relation type.")
    print("Compare row shapes, not just individual cells, to see whether a school's relation-vocabulary")
    print("usage forms a distinctive overall signature rather than a single standout percentage.")


def relation_profile_by_text(files, min_text_edges=20):
    """
    Same idea as relation_profile_by_school, but grouped by source_text
    (e.g. brahma_sutras, bhagavad_gita, upanishads) instead of school.
    This tests a different hypothesis: is the IS_QUALIFIED_ASPECT_OF
    over-triggering driven by which SCHOOL wrote a commentary, or by
    which ROOT TEXT is being commented on (e.g. terse sutra-style text
    forcing the model to infer relationships from minimal context,
    regardless of which school's commentator is speaking)? Unlike the
    school-level cut, this one is NOT restricted to specific-attribution
    edges, since source_text is independent of the school field and
    available on every edge regardless of attribution quality.
    """
    text_relation_counts = defaultdict(Counter)
    text_totals = Counter()

    for f in files:
        records = load_jsonl(f)
        for r in records:
            source_text = r.get("source")
            for rel in r.get("relationships", []):
                relation = rel.get("relation")
                if not source_text or not relation:
                    continue
                text_relation_counts[source_text][relation] += 1
                text_totals[source_text] += 1

    included = {t: n for t, n in text_totals.items() if n >= min_text_edges}
    excluded = {t: n for t, n in text_totals.items() if n < min_text_edges}

    all_relations = sorted({rel for counts in text_relation_counts.values() for rel in counts})

    print("\n" + "=" * 70)
    print("RELATION-TYPE PROFILE BY SOURCE TEXT")
    print(f"(source texts with fewer than {min_text_edges} edges excluded; ALL edges")
    print(" included regardless of school attribution, unlike --relation-profile)")
    print("=" * 70)

    if excluded:
        print(f"\nExcluded for insufficient data: {', '.join(f'{t} ({n})' for t, n in excluded.items())}")

    if not included:
        print("\nNo source text has enough edges for this analysis.")
        return

    print(f"\n{'Source text':<22}{'Total edges':>13}  " + "  ".join(f"{rel[:18]:>18}" for rel in all_relations))
    for text, total in sorted(included.items(), key=lambda x: -x[1]):
        counts = text_relation_counts[text]
        row = f"{text:<22}{total:>13}  "
        row += "  ".join(f"{100*counts.get(rel,0)/total:>17.1f}%" for rel in all_relations)
        print(row)

    print("\nIf IS_QUALIFIED_ASPECT_OF dominates similarly across different source texts regardless")
    print("of which school's commentator wrote it, that points to root-text style (e.g. terse sutra")
    print("phrasing forcing inference from minimal context) as a driver, not a school-specific artifact.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--relation-profile", action="store_true",
                        help="Print relation-type distribution normalized per school")
    parser.add_argument("--relation-profile-by-text", action="store_true",
                        help="Print relation-type distribution normalized per source text, independent of school")
    parser.add_argument("--min-school-edges", type=int, default=20,
                        help="Minimum specific-attribution edges for a school to appear in --relation-profile (default 20)")
    parser.add_argument("--min-text-edges", type=int, default=20,
                        help="Minimum edges for a source text to appear in --relation-profile-by-text (default 20)")
    args = parser.parse_args()

    files = sorted(TAGGED_DIR.glob("*.jsonl"))
    files = [f for f in files if f.name != "test_verse.jsonl"]

    if args.relation_profile:
        relation_profile_by_school(files, min_school_edges=args.min_school_edges)
        return

    if args.relation_profile_by_text:
        relation_profile_by_text(files, min_text_edges=args.min_text_edges)
        return

    print("=" * 70)
    print("TAGGED OUTPUT AUDIT")
    print("=" * 70)

    grand_total = 0
    grand_with_relationships = 0
    grand_concepts = Counter()
    grand_relations = Counter()
    grand_schools = Counter()
    grand_errors = 0

    # For cross-school comparison preview: concept_pair -> {school: [relations]}
    pair_school_relations = defaultdict(lambda: defaultdict(set))

    for f in files:
        records = load_jsonl(f)
        total = len(records)
        with_concepts = sum(1 for r in records if r.get("concepts"))
        with_relationships = sum(1 for r in records if r.get("relationships"))
        errors = sum(1 for r in records if r.get("error"))
        dropped = sum(r.get("dropped_invalid_relationships", 0) for r in records)

        print(f"\n--- {f.name} ---")
        print(f"  Total tagged: {total}")
        print(f"  With concepts: {with_concepts} ({100*with_concepts//max(total,1)}%)")
        print(f"  With relationships: {with_relationships} ({100*with_relationships//max(total,1)}%)")
        if errors:
            print(f"  Errors: {errors}")
        if dropped:
            print(f"  Invalid relations dropped by validator: {dropped}")

        grand_total += total
        grand_with_relationships += with_relationships
        grand_errors += errors

        for r in records:
            for c in r.get("concepts", []):
                grand_concepts[c.get("name")] += 1
            for rel in r.get("relationships", []):
                grand_relations[rel.get("relation")] += 1
                grand_schools[rel.get("school")] += 1
                pair = tuple(sorted([rel.get("concept_a"), rel.get("concept_b")]))
                pair_school_relations[pair][rel.get("school")].add(rel.get("relation"))

    print("\n" + "=" * 70)
    print("GRAND TOTALS")
    print("=" * 70)
    print(f"Total tagged records: {grand_total}")
    print(f"Records with relationships extracted: {grand_with_relationships} ({100*grand_with_relationships//max(grand_total,1)}%)")
    print(f"Errors: {grand_errors}")

    print(f"\nTop 20 most frequent concepts:")
    for name, count in grand_concepts.most_common(20):
        print(f"  {name}: {count}")

    print(f"\nRelation type distribution:")
    for rel, count in grand_relations.most_common():
        print(f"  {rel}: {count}")

    print(f"\nSchool distribution:")
    for school, count in grand_schools.most_common():
        print(f"  {school}: {count}")

    # Tension preview: concept pairs where multiple schools disagree
    # (different relation types used by different schools for the same pair)
    print("\n" + "=" * 70)
    print("CROSS-SCHOOL TENSION PREVIEW")
    print("(concept pairs where 2+ schools assert DIFFERENT relation types)")
    print("=" * 70)

    tension_list = []
    for pair, school_rels in pair_school_relations.items():
        if len(school_rels) < 2:
            continue
        all_relations = set()
        for rels in school_rels.values():
            all_relations.update(rels)
        if len(all_relations) > 1:
            tension_list.append((pair, school_rels, len(all_relations)))

    tension_list.sort(key=lambda x: -x[2])

    for pair, school_rels, n_distinct in tension_list[:15]:
        print(f"\n{pair[0]} <-> {pair[1]}  ({n_distinct} distinct relation types across schools)")
        for school, rels in school_rels.items():
            print(f"    {school}: {', '.join(rels)}")

    print(f"\nTotal contested concept pairs found: {len(tension_list)}")


if __name__ == "__main__":
    main()
