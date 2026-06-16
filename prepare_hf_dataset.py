"""
prepare_hf_dataset.py — merge corpus + tagged output into HF-ready files
============================================================================
Produces two clean, documented files for HuggingFace upload:

  darshana_corpus.jsonl   -- every raw text record (verse/sutra + commentaries)
  darshana_graph.jsonl    -- every extracted concept/relationship edge,
                             with full provenance back to source record

Run:
  python prepare_hf_dataset.py
"""

import json
from pathlib import Path
from collections import Counter

CORPUS_DIR = Path("corpus")
TAGGED_DIR = Path("corpus/tagged")
OUT_DIR = Path("hf_dataset")
OUT_DIR.mkdir(exist_ok=True)

SKIP_CORPUS_FILES = {"corpus.json"}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path):
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    return records


def build_corpus_file():
    print("=== Building darshana_corpus.jsonl ===")
    files = sorted(
        f for f in CORPUS_DIR.glob("*.json")
        if f.name not in SKIP_CORPUS_FILES and "progress" not in f.name
        and not f.name.endswith(".bak") and not f.name.endswith(".bak2")
    )

    all_records = []
    for f in files:
        data = load_json(f)
        if not isinstance(data, list):
            continue
        for r in data:
            r["_source_file"] = f.name
        all_records.extend(data)
        print(f"  {f.name}: {len(data)} records")

    out_path = OUT_DIR / "darshana_corpus.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Total corpus records: {len(all_records)}")
    print(f"Saved -> {out_path}\n")
    return all_records


def build_graph_file():
    print("=== Building darshana_graph.jsonl ===")
    files = sorted(TAGGED_DIR.glob("*.jsonl"))
    files = [f for f in files if f.name != "test_verse.jsonl"]

    all_edges = []
    edge_id = 0

    for f in files:
        records = load_jsonl(f)
        file_edges = 0
        for r in records:
            record_id = r.get("record_id")
            source = r.get("source")
            for rel in r.get("relationships", []):
                edge_id += 1
                all_edges.append({
                    "edge_id": f"edge_{edge_id:06d}",
                    "concept_a": rel.get("concept_a"),
                    "concept_b": rel.get("concept_b"),
                    "relation": rel.get("relation"),
                    "school": rel.get("school"),
                    "confidence": rel.get("confidence"),
                    "evidence_quote": rel.get("evidence_quote"),
                    "source_record_id": record_id,
                    "source_text": source,
                    "tagged_from_file": f.name,
                })
                file_edges += 1
        print(f"  {f.name}: {file_edges} edges")

    out_path = OUT_DIR / "darshana_graph.jsonl"
    with open(out_path, "w", encoding="utf-8") as out_f:
        for e in all_edges:
            out_f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"Total graph edges: {len(all_edges)}")
    print(f"Saved -> {out_path}\n")
    return all_edges


def print_summary_stats(corpus_records, graph_edges):
    print("=== SUMMARY STATS (for dataset card) ===\n")

    print(f"Total corpus records: {len(corpus_records)}")
    print(f"Total graph edges: {len(graph_edges)}")

    traditions = Counter(r.get("tradition") for r in corpus_records if r.get("tradition"))
    print(f"\nTraditions represented:")
    for t, c in traditions.most_common():
        print(f"  {t}: {c}")

    schools = Counter(e.get("school") for e in graph_edges)
    print(f"\nSchools in graph edges:")
    for s, c in schools.most_common():
        print(f"  {s}: {c}")

    relations = Counter(e.get("relation") for e in graph_edges)
    print(f"\nRelation types:")
    for r, c in relations.most_common():
        print(f"  {r}: {c}")

    commentators = set()
    for r in corpus_records:
        for c in r.get("commentaries", []):
            if c.get("commentator"):
                commentators.add(c["commentator"])
    print(f"\nTotal distinct commentators: {len(commentators)}")
    print(f"  {sorted(commentators)}")


if __name__ == "__main__":
    corpus_records = build_corpus_file()
    graph_edges = build_graph_file()
    print_summary_stats(corpus_records, graph_edges)
