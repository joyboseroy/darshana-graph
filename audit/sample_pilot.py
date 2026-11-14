#!/usr/bin/env python3
"""Draw the stratified pilot sample for the Darshana Graph v2 voice/attribution study.

Input : a JSONL file of candidate passages, one object per line, with at least
        id, stratum, text, and (optionally) work, section, language, prior_incongruent.
Output: sample.jsonl (the drawn passages), sample_manifest.json (seed, counts,
        input hash, quotas, shortfalls), and annotation_sheet.csv (blank sheet).

The draw is deterministic: candidates are ranked by sha256(seed + id), so adding
or removing unrelated candidates does not reshuffle the ones already drawn.

Usage:
    python sample_pilot.py candidates.jsonl --out out/ --seed 20261113
"""
import argparse
import csv
import hashlib
import json
import os
import sys

# Default quotas for a 100-passage slice of the 300-passage pilot.
DEFAULT_QUOTAS = {
    "bs22_shankara_ramanuja": 30,
    "sribhashya_1_1_1": 10,
    "kathavatthu_milinda": 12,
    "vv_mmk": 12,
    "samayasara_naya": 8,
    "gita_divergent_gloss": 13,
    "random_commentary": 15,
}
MIN_PRIOR_INCONGRUENT = 20  # across the whole sample


def rank_key(seed, pid):
    return hashlib.sha256(f"{seed}:{pid}".encode("utf-8")).hexdigest()


def load(path):
    rows, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            for k in ("id", "stratum", "text"):
                if k not in obj:
                    sys.exit(f"line {n}: missing field '{k}'")
            if obj["id"] in seen:
                sys.exit(f"line {n}: duplicate id {obj['id']}")
            seen.add(obj["id"])
            rows.append(obj)
    return rows


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def draw(rows, quotas, seed, min_incong):
    by_stratum = {}
    for r in rows:
        by_stratum.setdefault(r["stratum"], []).append(r)
    for s in by_stratum:
        by_stratum[s].sort(key=lambda r: rank_key(seed, r["id"]))

    chosen, shortfalls = [], {}
    for s, q in quotas.items():
        pool = by_stratum.get(s, [])
        take = pool[:q]
        if len(take) < q:
            shortfalls[s] = {"wanted": q, "got": len(take)}
        chosen.extend(take)

    # Top up prior-incongruent passages by swapping out the lowest-ranked
    # prior-congruent picks within the same stratum, never below quota.
    have = sum(1 for r in chosen if r.get("prior_incongruent"))
    swaps = 0
    if have < min_incong:
        chosen_ids = {r["id"] for r in chosen}
        for s in quotas:
            if have >= min_incong:
                break
            pool = by_stratum.get(s, [])
            extra = [r for r in pool if r.get("prior_incongruent") and r["id"] not in chosen_ids]
            victims = [r for r in reversed([c for c in chosen if c["stratum"] == s])
                       if not r.get("prior_incongruent")]
            for add, drop in zip(extra, victims):
                if have >= min_incong:
                    break
                chosen.remove(drop)
                chosen_ids.discard(drop["id"])
                chosen.append(add)
                chosen_ids.add(add["id"])
                have += 1
                swaps += 1
    return chosen, shortfalls, have, swaps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--out", default="out")
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--quotas", help="JSON file overriding the default quotas")
    ap.add_argument("--min-incongruent", type=int, default=MIN_PRIOR_INCONGRUENT)
    a = ap.parse_args()

    quotas = DEFAULT_QUOTAS
    if a.quotas:
        with open(a.quotas, encoding="utf-8") as f:
            quotas = json.load(f)

    rows = load(a.candidates)
    chosen, shortfalls, incong, swaps = draw(rows, quotas, a.seed, a.min_incongruent)
    chosen.sort(key=lambda r: (r["stratum"], rank_key(a.seed, r["id"])))

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "sample.jsonl"), "w", encoding="utf-8") as f:
        for r in chosen:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Annotators must not see the stratum or the prior_incongruent tag.
    cols = ["id", "text", "holder_chain", "holder_basis", "act",
            "author_attitude", "propositional", "confidence_1to3", "notes"]
    with open(os.path.join(a.out, "annotation_sheet.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in sorted(chosen, key=lambda r: rank_key(a.seed + 1, r["id"])):
            w.writerow([r["id"], r["text"]] + [""] * (len(cols) - 2))

    counts = {}
    for r in chosen:
        counts[r["stratum"]] = counts.get(r["stratum"], 0) + 1
    manifest = {
        "seed": a.seed,
        "input_sha256": sha256_file(a.candidates),
        "n_candidates": len(rows),
        "n_sampled": len(chosen),
        "quotas": quotas,
        "counts": counts,
        "prior_incongruent_in_sample": incong,
        "prior_incongruent_swaps": swaps,
        "min_incongruent_target": a.min_incongruent,
        "shortfalls": shortfalls,
    }
    with open(os.path.join(a.out, "sample_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if shortfalls:
        print("WARNING: some strata are short; see shortfalls.", file=sys.stderr)
    if incong < a.min_incongruent:
        print("WARNING: prior-incongruent target not met.", file=sys.stderr)


if __name__ == "__main__":
    main()
