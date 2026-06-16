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


def main():
    files = sorted(TAGGED_DIR.glob("*.jsonl"))
    files = [f for f in files if f.name != "test_verse.jsonl"]

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

