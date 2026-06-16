"""
convert_gita.py — convert gita/data/ JSON files to darshana-graph corpus schema
=================================================================================
Input:  gita/data/{verse,translation,commentary,authors}.json
Output: corpus/bg.json

Usage:
  python convert_gita.py
  python convert_gita.py --gita-dir ./gita/data
"""

import json
import argparse
from pathlib import Path

OUTPUT_DIR = Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)

# Map author names to school/commentator tags
# (commentator_id, school, language)
AUTHOR_SCHOOL = {
    "Sri Madhavacharya":                      ("madhva",          "dvaita",             "sa"),
    "Sri Ramanujacharya":                     ("ramanuja",         "vishishtadvaita",    "sa"),
    "Sri Sridhara Swami":                     ("sridhara",         "advaita",            "sa"),
    "Sri Abhinavgupta":                       ("abhinavagupta",    "kashmir_shaivism",   "sa"),
    "Sri Anandgiri":                          ("anandagiri",       "advaita",            "sa"),
    "Sri Dhanpati":                           ("dhanpati",         "advaita",            "sa"),
    "Sri Neelkanth":                          ("nilakantha",       "advaita",            "sa"),
    "Sri Vedantadeshikacharya Venkatanatha":  ("vedanta_desika",   "vishishtadvaita",    "sa"),
    "Swami Ramsukhdas":                       ("ramsukhdas",       "neo_vedanta",        "hi"),
    "Swami Chinmayananda":                    ("chinmayananda",    "neo_vedanta",        "en"),
    "Swami Sivananda":                        ("sivananda",        "neo_vedanta",        "en"),
    "Swami Gambhirananda":                    ("gambhirananda",    "neo_vedanta",        "en"),
    "Swami Adidevananda":                     ("adidevananda",     "vishishtadvaita",    "en"),
    "Dr. S. Sankaranarayan":                  ("sankaranarayan",   "general",            "en"),
    "Shri Purohit Swami":                     ("purohit",          "general",            "en"),
    "Swami Tejomayananda":                    ("tejomayananda",    "neo_vedanta",        "hi"),
}

# English translators we want as primary text
ENGLISH_TRANSLATORS = {
    "Swami Sivananda",
    "Swami Gambhirananda",
    "Swami Chinmayananda",
    "Shri Purohit Swami",
    "Swami Tejomayananda",
    "Dr. S. Sankaranarayan",
    "Swami Adidevananda",
    "Swami Ramsukhdas",
}

# Commentary authors (Sanskrit commentaries)
COMMENTARY_AUTHORS = {
    "Sri Madhavacharya",
    "Sri Ramanujacharya",
    "Sri Sridhara Swami",
    "Sri Abhinavgupta",
    "Sri Anandgiri",
    "Sri Dhanpati",
    "Sri Neelkanth",
    "Sri Vedantadeshikacharya Venkatanatha",
}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def convert(gita_dir="gita/data"):
    gita = Path(gita_dir)
    print(f"Loading from {gita.resolve()} ...")

    authors     = {a["id"]: a["name"] for a in load(gita / "authors.json")}
    verses      = load(gita / "verse.json")
    translations = load(gita / "translation.json")
    commentaries = load(gita / "commentary.json")

    print(f"  {len(verses)} verses")
    print(f"  {len(translations)} translations")
    print(f"  {len(commentaries)} commentaries")
    print(f"  {len(authors)} authors")

    # Index translations by verse_id
    trans_by_verse = {}
    for t in translations:
        vid = t.get("verse_id") or t.get("id")
        if vid not in trans_by_verse:
            trans_by_verse[vid] = []
        trans_by_verse[vid].append(t)

    # Index commentaries by verse_id
    comm_by_verse = {}
    for c in commentaries:
        vid = c.get("verse_id") or c.get("id")
        if vid not in comm_by_verse:
            comm_by_verse[vid] = []
        comm_by_verse[vid].append(c)

    records = []
    for verse in verses:
        vid        = verse["id"]
        ch         = verse["chapter_number"]
        vnum       = verse["verse_number"]
        sanskrit   = verse.get("text", "")
        iast       = verse.get("transliteration", "")
        word_meanings = verse.get("word_meanings", "")

        # Pick best English translation as primary text
        # Priority: Gambhirananda > Sivananda > Chinmayananda > first available
        primary_text = ""
        primary_translator = ""
        priority_order = [
            "Swami Gambhirananda",
            "Swami Sivananda",
            "Swami Chinmayananda",
            "Swami Tejomayananda",
            "Shri Purohit Swami",
        ]

        trans_list = trans_by_verse.get(vid, [])
        trans_by_author = {}
        for t in trans_list:
            aname = authors.get(t.get("author_id"), "")
            if aname in ENGLISH_TRANSLATORS:
                trans_by_author[aname] = t.get("description", "").strip()

        for name in priority_order:
            if name in trans_by_author and trans_by_author[name]:
                primary_text = trans_by_author[name]
                primary_translator = name.lower().replace(" ", "_")
                break

        if not primary_text and trans_by_author:
            first = next(iter(trans_by_author))
            primary_text = trans_by_author[first]
            primary_translator = first.lower().replace(" ", "_")

        # Build commentaries list
        comm_list = comm_by_verse.get(vid, [])
        commentaries_out = []

        # Add all English translations (except primary) as commentaries
        for aname, text in trans_by_author.items():
            if aname == primary_translator.replace("_", " ").title():
                continue
            if not text:
                continue
            commentator, school, lang = AUTHOR_SCHOOL.get(aname, (aname.lower().replace(" ", "_"), "general", "en"))
            commentaries_out.append({
                "commentator": commentator,
                "school":      school,
                "lang":        lang,
                "text":        text,
                "type":        "translation",
            })

        # Add Sanskrit commentaries
        for c in comm_list:
            aname = authors.get(c.get("author_id"), "")
            if aname not in COMMENTARY_AUTHORS:
                continue
            text = c.get("description", "").strip()
            if not text:
                continue
            commentator, school, lang = AUTHOR_SCHOOL.get(aname, (aname.lower().replace(" ", "_"), "general", "en"))
            commentaries_out.append({
                "commentator": commentator,
                "school":      school,
                "lang":        lang,
                "text":        text,
                "type":        "commentary",
            })

        record = {
            "id":            f"bg_{ch}_{vnum}",
            "source":        "bhagavad_gita",
            "tradition":     "hindu_astika",
            "darshana":      "vedanta",
            "chapter":       ch,
            "verse":         vnum,
            "segment_id":    f"bg_{ch}.{vnum}",
            "sanskrit":      sanskrit.strip(),
            "iast":          iast.strip(),
            "word_meanings": word_meanings.strip(),
            "text":          primary_text,
            "translator":    primary_translator,
            "commentaries":  commentaries_out,
        }
        records.append(record)

    # Sort by chapter then verse
    records.sort(key=lambda r: (r["chapter"], r["verse"]))

    out = OUTPUT_DIR / "bg.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print(f"\nSaved {len(records)} verse records -> {out}")

    # Stats
    print(f"\nCommentators found:")
    from collections import Counter
    comm_counts = Counter()
    for r in records:
        for c in r["commentaries"]:
            comm_counts[c["commentator"]] += 1
    for name, count in comm_counts.most_common():
        print(f"  {name}: {count} verses")

    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gita-dir", default="gita/data", help="Path to gita/data directory")
    args = parser.parse_args()
    convert(args.gita_dir)
