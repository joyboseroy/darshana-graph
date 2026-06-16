"""
filter_buddhism_philosophical.py
==================================
Extracts only the philosophically tagged records from buddhism.json
(those with a theme_tag set during scraping: dependent_origination,
four_noble_truths, five_aggregates, eightfold_path, etc) plus the
Dhammapada (concise verse-form philosophy, high density of content
per token -- ideal for tagging on a budget).

This avoids tagging all 110k Pali segments (mostly narrative frame
material: "Thus have I heard", formulaic mendicant exchanges, etc)
and instead prioritizes the densest philosophical content first.

Run:
  python filter_buddhism_philosophical.py
"""
import json
from pathlib import Path

data = json.loads(Path("corpus/buddhism.json").read_text(encoding="utf-8"))

# Records with a real theme tag (the philosophically curated SN samyuttas)
themed = [r for r in data if r.get("theme_tag")]

# Dhammapada -- dense, self-contained philosophical verses
dhammapada = [r for r in data if r.get("source") == "kn_dhammapada_nikaya"]

# Combine, dedupe by id
seen = set()
combined = []
for r in themed + dhammapada:
    if r["id"] not in seen:
        seen.add(r["id"])
        combined.append(r)

print(f"Themed SN records (pre-sample): {len(themed)}")
print(f"Dhammapada records (pre-sample): {len(dhammapada)}")
print(f"Combined (deduped, pre-sample): {len(combined)}")

# Sample down per theme_tag to a manageable cap. The Pali suttas repeat
# heavy formulaic boilerplate across segments ("Mendicants, this is how
# you should...") so most of the philosophical signal per theme is
# captured well before tagging every single segment.
import random
random.seed(42)
CAP_PER_THEME = 300

by_theme = {}
for r in combined:
    by_theme.setdefault(r.get("theme_tag"), []).append(r)

sampled = []
for theme, recs in by_theme.items():
    if len(recs) > CAP_PER_THEME:
        sampled.extend(random.sample(recs, CAP_PER_THEME))
    else:
        sampled.extend(recs)

out = Path("corpus/buddhism_philosophical_subset.json")
out.write_text(json.dumps(sampled, ensure_ascii=False, indent=2))

print(f"\\nAfter capping at {CAP_PER_THEME} per theme:")
print(f"Final sampled total: {len(sampled)}")
print(f"Saved -> {out}")

from collections import Counter
print("\nBy theme_tag:")
for tag, count in Counter(r.get("theme_tag") for r in combined).most_common():
    print(f"  {tag}: {count}")
