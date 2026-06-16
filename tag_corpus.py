"""
tag_corpus.py — LLM tagging pipeline for darshana-graph
===========================================================
Reads corpus/corpus.json (or individual files) and extracts typed
philosophical concept relationships using Groq (fast, cheap).

This is pure classification over text already in front of the model --
no RAG, no retrieval, no world-knowledge requirement. The model reads
a passage (verse + commentary) and tags concepts + relationships from
a FIXED vocabulary, citing the source text as evidence.

Output: corpus/tagged/*.jsonl  (one file per input source, JSONL format
        so it's resumable and streams to disk incrementally)

Setup:
  pip install groq --break-system-packages
  export GROQ_API_KEY="your-key-here"

Run:
  python tag_corpus.py --all                       # tag everything
  python tag_corpus.py --file corpus/bg.json        # tag one file
  python tag_corpus.py --file corpus/bg.json --resume
  python tag_corpus.py --all --limit 50             # test run, 50 records/file
"""

import os
import json
import time
import argparse
import logging
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

CORPUS_DIR = Path("corpus")
TAGGED_DIR = Path("corpus/tagged")
TAGGED_DIR.mkdir(parents=True, exist_ok=True)

# ── Fixed vocabulary -- the model can ONLY use these, nothing invented ──────

CONCEPT_CATEGORIES = [
    "ontological",      # Brahman, Atman, Maya, Prakriti, Purusha, Jiva, Ishvara, Sunyata
    "epistemological",  # Pramana, Viveka, Avidya, Vidya, Prajna
    "soteriological",   # Moksha, Nirvana, Kaivalya, Liberation
    "ethical",          # Dharma, Karma, Ahimsa, Sila
    "practice",         # Yoga, Dhyana, Bhakti, Jnana-marga, Samadhi
    "cosmological",     # Samsara, Srishti, Pratityasamutpada
]

RELATION_VOCAB = [
    "IS_IDENTICAL_TO",          # Advaita-style non-difference
    "IS_DISTINCT_FROM",         # Dvaita-style difference
    "IS_QUALIFIED_ASPECT_OF",   # Vishishtadvaita-style
    "IS_SIMULTANEOUSLY_ONE_AND_DIFFERENT",  # Achintya Bhedabheda / Dvaitadvaita
    "PRESUPPOSES",              # logical dependency
    "SUBLATES",                 # higher truth cancels/supersedes lower
    "LEADS_TO",                 # soteriological path / causes attainment of
    "OBSTRUCTS",                # obstacle relationship
    "IS_CAUSE_OF",               # causal
    "IS_MANIFESTATION_OF",      # appearance / emanation
    "RECONCILES",               # synthesis position (e.g. neo-Vedanta)
    "CONTRADICTS_IN_SCHOOL",    # explicit cross-school disagreement noted in text
    "DEFINED_AS",                # straightforward definitional statement
]

SCHOOL_VOCAB = [
    "advaita", "vishishtadvaita", "dvaita", "dvaitadvaita", "achintya_bhedabheda",
    "neo_vedanta", "samkhya", "yoga", "nyaya", "vaisheshika", "mimamsa",
    "theravada", "jain_digambara", "jain_shvetambara", "jain_common",
    "kashmir_shaivism", "general",
]

SYSTEM_PROMPT = f"""You are a precise philosophical concept tagger for Indian philosophy texts (Hindu, Buddhist, Jain).

CRITICAL RULES:
1. Extract ONLY what is asserted in the provided text. Never use prior knowledge to add concepts or relationships not evidenced in this exact passage.
2. Use ONLY these relationship types: {", ".join(RELATION_VOCAB)}

   Precise definitions (use the MOST SPECIFIC applicable relation, not a default):
   - IS_QUALIFIED_ASPECT_OF: ONLY for genuine part-whole/mode-of relationships (Vishishtadvaita-style: the soul as an attribute/mode of Brahman). Do NOT use this as a generic fallback when unsure -- if the text states two things are the same, use IS_IDENTICAL_TO; if it says one is the cause of the other, use IS_CAUSE_OF; if it merely describes a property, do not force a relationship at all.
   - IS_IDENTICAL_TO: explicit non-difference/identity claim (Advaita-style).
   - IS_DISTINCT_FROM: explicit difference/separateness claim (Dvaita-style).
   - IS_CAUSE_OF: explicit causal claim (X produces/creates Y).
   - DEFINED_AS: the text gives a definition, not a relationship between two distinct concepts.
   If you are tempted to use IS_QUALIFIED_ASPECT_OF simply because no other label feels right, prefer omitting the relationship entirely over forcing an imprecise tag.
3. Use ONLY these school tags: {", ".join(SCHOOL_VOCAB)}
4. Use ONLY these concept categories: {", ".join(CONCEPT_CATEGORIES)}
5. Concept names should be the standard Sanskrit/Pali term (lowercase, IAST if possible): atman, brahman, maya, moksha, karma, dharma, sunyata, anatta, ahimsa, etc.
6. evidence_quote must be a short phrase (max 15 words) copied verbatim from the text below -- this is your citation anchor. CRITICAL: evidence_quote must be a SINGLE LINE with no line breaks, no embedded quotation marks, and no special characters that would break JSON formatting. Strip or paraphrase around any such characters if the source text contains them.
7. If you are not confident a relationship is actually asserted (not just implied or your own inference), set confidence to "low".
8. If the passage contains no clear philosophical concept relationships, return an empty relationships list. Do not force it.
9. Output ONLY valid JSON. No preamble, no markdown fences, no explanation.

OUTPUT SCHEMA:
{{
  "concepts": [
    {{"name": "atman", "category": "ontological"}}
  ],
  "relationships": [
    {{
      "concept_a": "atman",
      "concept_b": "brahman",
      "relation": "IS_IDENTICAL_TO",
      "school": "advaita",
      "confidence": "high",
      "evidence_quote": "the Self is verily Brahman"
    }}
  ]
}}"""

USER_PROMPT_TEMPLATE = """SOURCE: {source}
DARSHANA/SCHOOL CONTEXT: {darshana}
COMMENTATOR: {commentator}

TEXT (verse/sutra):
{verse_text}

COMMENTARY:
{commentary_text}

Extract concepts and relationships from the above text only.
IMPORTANT: "{darshana}" above is a broad tradition label, NOT a valid school tag -- never output it as a "school" value. If there is no commentary (commentator is "none"), you may still extract relationships directly asserted by the verse/sutra text itself, using "school": "general" unless the verse text itself clearly names a specific school's position."""


def get_groq_client():
    try:
        from groq import Groq
    except ImportError:
        log.error("Run: pip install groq --break-system-packages")
        raise
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        log.error("Set GROQ_API_KEY environment variable first")
        raise SystemExit(1)
    return Groq(api_key=api_key)


def build_user_prompt(record):
    source = record.get("source", "unknown")
    darshana = record.get("darshana", "unknown")
    verse_text = (record.get("text") or "")[:600]

    # Cap to 2 commentaries and truncate hard -- multi-commentator records
    # (e.g. bg.json with 13 commentators) blow past TPM limits otherwise.
    # Prefer lang=en or lang=sa commentaries over lang=hi, since the
    # evidence_quote citation works best when verse text and commentary
    # text are in the same/compatible language as the primary translation.
    all_commentaries = record.get("commentaries", []) or []
    preferred = [c for c in all_commentaries if c.get("lang") in ("en", "sa")]
    fallback = [c for c in all_commentaries if c.get("lang") not in ("en", "sa")]
    selected = (preferred + fallback)[:2]

    commentary_parts = []
    for c in selected:
        commentator = c.get("commentator", "unknown")
        school = c.get("school", "unknown")
        text = (c.get("text") or "")[:500]
        if text:
            commentary_parts.append(f"[{commentator} / {school}]: {text}")

    commentary_text = "\n\n".join(commentary_parts) if commentary_parts else "(no commentary)"
    commentator_names = ", ".join(c.get("commentator", "?") for c in selected) or "none"

    return USER_PROMPT_TEMPLATE.format(
        source=source,
        darshana=darshana,
        commentator=commentator_names,
        verse_text=verse_text or "(no verse text)",
        commentary_text=commentary_text,
    )


def validate_and_filter(parsed):
    """
    Hard enforcement of the closed vocabulary. The model is instructed to
    only use RELATION_VOCAB/SCHOOL_VOCAB/CONCEPT_CATEGORIES, but smaller
    models (llama-3.1-8b-instant) sometimes invent their own relation types
    (e.g. IS_UNBORN, IS_ETERNAL) despite the system prompt. Rather than trust
    compliance, we filter post-hoc: any relationship using a non-vocabulary
    relation or school is dropped rather than silently kept as noise.
    Self-referential edges (concept_a == concept_b) are also dropped.
    """
    concepts = parsed.get("concepts", []) or []
    relationships = parsed.get("relationships", []) or []

    clean_concepts = []
    for c in concepts:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip().lower()
        category = c.get("category")
        if name and category in CONCEPT_CATEGORIES:
            clean_concepts.append({"name": name, "category": category})

    clean_relationships = []
    dropped = 0
    dropped_relations_seen = Counter()
    dropped_schools_seen = Counter()
    for r in relationships:
        if not isinstance(r, dict):
            continue
        relation = r.get("relation")
        school = r.get("school")
        concept_a = (r.get("concept_a") or "").strip().lower()
        concept_b = (r.get("concept_b") or "").strip().lower()

        if relation not in RELATION_VOCAB:
            dropped += 1
            dropped_relations_seen[relation] += 1
            continue
        if school not in SCHOOL_VOCAB:
            dropped += 1
            dropped_schools_seen[school] += 1
            continue
        if not concept_a or not concept_b or concept_a == concept_b:
            dropped += 1
            continue

        clean_relationships.append({
            "concept_a": concept_a,
            "concept_b": concept_b,
            "relation": relation,
            "school": school,
            "confidence": r.get("confidence", "low"),
            "evidence_quote": (r.get("evidence_quote") or "")[:200],
        })

    result = {"concepts": clean_concepts, "relationships": clean_relationships}
    if dropped:
        result["dropped_invalid_relationships"] = dropped
        if dropped_relations_seen:
            result["dropped_relation_values"] = dict(dropped_relations_seen)
        if dropped_schools_seen:
            result["dropped_school_values"] = dict(dropped_schools_seen)
    return result


def tag_record(client, record, model="llama-3.1-8b-instant", retries=3):
    """Call Groq to tag a single record. Returns dict or None on failure."""
    user_prompt = build_user_prompt(record)

    # Skip records with essentially no content
    if len(user_prompt) < 80:
        return {"record_id": record.get("id"), "concepts": [], "relationships": [], "skipped": "too_short"}

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=700,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            parsed = json.loads(raw)
            parsed = validate_and_filter(parsed)
            parsed["record_id"] = record.get("id")
            parsed["source"] = record.get("source")
            parsed["darshana"] = record.get("darshana")
            time.sleep(1.0)  # pace requests to respect free-tier TPM limit
            return parsed
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "413" in err_str or "rate_limit" in err_str:
                wait = 20 * (attempt + 1)  # rate limits need real cooldown, not just backoff
            else:
                wait = 2 ** attempt
            log.warning(f"  Retry {attempt+1} for {record.get('id')}: {e} (wait {wait}s)")
            time.sleep(wait)

    log.warning(f"  GIVING UP on {record.get('id')} after {retries} retries -- likely malformed JSON from source text quirks")
    return {"record_id": record.get("id"), "concepts": [], "relationships": [], "error": "failed_all_retries"}


def load_done_ids(out_path):
    """Read JSONL output file and collect already-processed record IDs."""
    done = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    done.add(obj.get("record_id"))
                except Exception:
                    continue
    return done


def tag_file(client, input_path, limit=None, resume=False, workers=4, model="llama-3.1-8b-instant"):
    records = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if limit:
        records = records[:limit]

    out_path = TAGGED_DIR / (Path(input_path).stem + ".jsonl")

    done_ids = load_done_ids(out_path) if resume else set()
    todo = [r for r in records if r.get("id") not in done_ids]

    log.info(f"{input_path}: {len(records)} total, {len(done_ids)} already done, {len(todo)} to process")

    if not todo:
        log.info("  Nothing to do.")
        return

    mode = "a" if resume else "w"
    processed = 0
    errors = 0

    with open(out_path, mode, encoding="utf-8") as out_f:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(tag_record, client, r, model): r for r in todo}
            for future in as_completed(futures):
                result = future.result()
                out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                out_f.flush()
                processed += 1
                if result.get("error"):
                    errors += 1
                if processed % 25 == 0:
                    log.info(f"  {processed}/{len(todo)} processed ({errors} errors) -- {input_path}")

    log.info(f"Done: {input_path} -- {processed} processed, {errors} errors -> {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Tag a single corpus JSON file")
    parser.add_argument("--all", action="store_true", help="Tag every JSON file in corpus/")
    parser.add_argument("--limit", type=int, default=None, help="Limit records per file (testing)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent API calls")
    parser.add_argument("--model", default="llama-3.1-8b-instant")
    args = parser.parse_args()

    client = get_groq_client()

    if args.file:
        tag_file(client, args.file, limit=args.limit, resume=args.resume,
                  workers=args.workers, model=args.model)
    elif args.all:
        skip_names = {"corpus.json"}
        files = sorted(
            f for f in CORPUS_DIR.glob("*.json")
            if f.name not in skip_names and "progress" not in f.name
        )
        log.info(f"Found {len(files)} corpus files to tag")
        for f in files:
            tag_file(client, f, limit=args.limit, resume=args.resume,
                      workers=args.workers, model=args.model)
    else:
        parser.error("Specify --file <path> or --all")


if __name__ == "__main__":
    main()
