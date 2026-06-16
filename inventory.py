"""
inventory.py — full corpus status check
=========================================
Run this any time to see exactly what's been ingested,
record counts per source, language coverage, and what's still missing.

Usage:
  python inventory.py
"""

import json
from pathlib import Path
from collections import Counter, defaultdict

CORPUS_DIR = Path("corpus")

# Expected sources per darshana/tradition — used to flag gaps
EXPECTED = {
    "Vedanta (Prasthanatrayi)": [
        ("bhagavad_gita",                    "bg.json"),
        ("brahma_sutras (Thibaut Shankara+Ramanuja)", "brahma_sutras.json"),
        ("brahma_sutras (Gambhirananda)",    "gambhirananda_brahmasutra.json"),
        ("upanishads (Müller, sacred-texts)", "upanishads.json"),
        ("upanishads (Gambhirananda Vol 1)", "gambhirananda_eight-upanisads-vol-1.json"),
        ("upanishads (Gambhirananda Vol 2)", "gambhirananda_eight-upanisads-vol2.json"),
    ],
    "Jainism": [
        ("tattvartha_sutra",   "tattvartha_sutra.json"),
        ("jainism (acaranga + sutrakritanga)", "jainism.json"),
    ],
    "Six Darshanas": [
        ("samkhya/yoga/nyaya/vaisheshika", "darshanas.json"),
    ],
    "Buddhism": [
        ("pali nikayas (DN/MN/SN/AN/KN)", "buddhism.json"),
    ],
}


def load(fname):
    path = CORPUS_DIR / fname
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"ERROR: {e}"


def analyze_file(fname):
    data = load(fname)
    if data is None:
        return None
    if isinstance(data, str):
        return {"error": data}

    n = len(data)
    sources = Counter(r.get("source", "?") for r in data)
    traditions = Counter(r.get("tradition", "?") for r in data)
    darshanas = Counter(r.get("darshana", "?") for r in data)

    # Language coverage from commentaries
    langs = Counter()
    commentators = Counter()
    for r in data:
        for c in r.get("commentaries", []):
            langs[c.get("lang", "?")] += 1
            commentators[c.get("commentator", "?")] += 1

    # Has Sanskrit/IAST fields?
    has_sanskrit = sum(1 for r in data if r.get("sanskrit") or r.get("iast"))

    return {
        "records":      n,
        "sources":      dict(sources.most_common(10)),
        "traditions":   dict(traditions),
        "darshanas":    dict(darshanas),
        "commentators": dict(commentators.most_common(15)),
        "langs":        dict(langs),
        "has_sanskrit": has_sanskrit,
    }


def main():
    print("=" * 70)
    print("DARSHANA-GRAPH CORPUS INVENTORY")
    print("=" * 70)

    if not CORPUS_DIR.exists():
        print(f"\nNo corpus/ directory found at {CORPUS_DIR.resolve()}")
        return

    all_files = sorted(CORPUS_DIR.glob("*.json"))
    progress_files = [f for f in all_files if "progress" in f.name]
    data_files = [f for f in all_files if "progress" not in f.name and f.name != "corpus.json"]

    print(f"\nFound {len(data_files)} data files, {len(progress_files)} progress files\n")

    total_records = 0
    grand_commentators = Counter()
    grand_langs = Counter()

    for f in data_files:
        result = analyze_file(f.name)
        if result is None:
            continue
        if "error" in result:
            print(f"\n--- {f.name} ---  [ERROR: {result['error']}]")
            continue

        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"\n--- {f.name} ({size_mb:.1f} MB) ---")
        print(f"  Records: {result['records']}")
        if result["has_sanskrit"]:
            print(f"  Has Sanskrit/IAST: {result['has_sanskrit']} records")

        if result["darshanas"]:
            print(f"  Darshanas: {result['darshanas']}")

        if result["sources"] and len(result["sources"]) > 1:
            print(f"  Sources breakdown:")
            for src, count in list(result["sources"].items())[:8]:
                print(f"    {src}: {count}")

        if result["commentators"]:
            print(f"  Commentators: {result['commentators']}")
            for k, v in result["commentators"].items():
                grand_commentators[k] += v

        if result["langs"]:
            print(f"  Commentary languages: {result['langs']}")
            for k, v in result["langs"].items():
                grand_langs[k] += v

        total_records += result["records"]

    print("\n" + "=" * 70)
    print("GRAND TOTAL")
    print("=" * 70)
    print(f"Total records across all files: {total_records}")
    print(f"\nAll commentators seen (across corpus):")
    for name, count in grand_commentators.most_common(30):
        print(f"  {name}: {count}")
    print(f"\nLanguage distribution (commentaries):")
    for lang, count in grand_langs.most_common():
        print(f"  {lang}: {count}")

    # Gap check
    print("\n" + "=" * 70)
    print("GAP CHECK — Expected vs Present")
    print("=" * 70)
    existing_names = {f.name for f in data_files}
    for category, items in EXPECTED.items():
        print(f"\n{category}:")
        for label, fname in items:
            status = "✓ present" if fname in existing_names else "✗ MISSING"
            print(f"  [{status}]  {label}  ({fname})")

    # Progress files still in flight
    if progress_files:
        print("\n" + "=" * 70)
        print("IN-PROGRESS / RESUMABLE")
        print("=" * 70)
        for f in progress_files:
            try:
                prog = json.loads(f.read_text())
                done = len(prog.get("done_pages", prog.get("done_urls", [])))
                print(f"  {f.name}: {done} units done — resumable with --resume")
            except Exception:
                print(f"  {f.name}: could not read")


if __name__ == "__main__":
    main()
