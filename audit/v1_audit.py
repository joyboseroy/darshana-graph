#!/usr/bin/env python3
"""Audit of the published darshana-graph edges, using only the published files.

Subcommands (run in this order):
  fetch      download graph + corpus from Hugging Face into ./data
  quotes     are evidence quotes found in their source record? where?
  null       do relation rates differ by school more than a within-source shuffle predicts?
  voice      rule-based proxy for edges drawn from objection/opponent passages
  nopassage  does a model predict the relation label without the passage?  (needs Groq key)

All outputs go to ./audit_out. Exploratory only: none of this replaces a human gold set.

Graph columns used : edge_id concept_a concept_b relation school source_record_id source_text evidence_quote
Corpus columns used: id text word_meanings commentaries (list of dicts)
"""
import argparse
import json
import math
import os
import random
import re
import sys
import time
import unicodedata

import numpy as np
import pandas as pd

OUT = "audit_out"
DATA = "data"
REPO = "joyboseroy/darshana-graph"
# The real closed vocabulary and definitions from tag_corpus.py (joyboseroy/darshana-graph).
REAL_VOCAB = [
    "IS_IDENTICAL_TO", "IS_DISTINCT_FROM", "IS_QUALIFIED_ASPECT_OF",
    "IS_SIMULTANEOUSLY_ONE_AND_DIFFERENT", "PRESUPPOSES", "SUBLATES", "LEADS_TO",
    "OBSTRUCTS", "IS_CAUSE_OF", "IS_MANIFESTATION_OF", "RECONCILES",
    "CONTRADICTS_IN_SCHOOL", "DEFINED_AS",
]
DEFS = """Definitions (use the most specific applicable relation, not a default):
- IS_QUALIFIED_ASPECT_OF: ONLY for genuine part-whole/mode-of relationships (Vishishtadvaita-style: the soul as an attribute/mode of Brahman). Not a generic fallback.
- IS_IDENTICAL_TO: explicit non-difference/identity claim (Advaita-style).
- IS_DISTINCT_FROM: explicit difference/separateness claim (Dvaita-style).
- IS_CAUSE_OF: explicit causal claim (X produces/creates Y).
- IS_SIMULTANEOUSLY_ONE_AND_DIFFERENT: Achintya Bhedabheda / Dvaitadvaita.
- PRESUPPOSES: logical dependency.
- SUBLATES: higher truth cancels/supersedes lower.
- LEADS_TO: soteriological path / causes attainment of.
- OBSTRUCTS: obstacle relationship.
- IS_MANIFESTATION_OF: appearance / emanation.
- RECONCILES: synthesis position (e.g. neo-Vedanta).
- CONTRADICTS_IN_SCHOOL: explicit cross-school disagreement noted in text.
- DEFINED_AS: the text gives a definition, not a relationship between two distinct concepts."""
PROMPT_VERSION = "v3-real-vocab"
SKIP_KEYS = {"commentator", "school", "author", "name", "lang", "language",
             "translator", "source", "id"}


# ---------------------------------------------------------------- helpers
def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).lower()
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def find_span(text, quote):
    toks = re.findall(r"\w+", quote, flags=re.U)
    if not toks or not text:
        return None
    pat = r"\W+".join(re.escape(t) for t in toks)
    m = re.search(pat, text, flags=re.I | re.U)
    return m.span() if m else None


def record_parts(rec):
    root = " ".join(str(rec[k]) for k in ("text", "word_meanings")
                    if isinstance(rec.get(k), str))
    comms = []
    c = rec.get("commentaries")
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except Exception:
            c = None
    if isinstance(c, dict):
        c = [c]
    if isinstance(c, (list, np.ndarray)):
        for d in c:
            if not isinstance(d, dict):
                continue
            t = " ".join(v for k, v in d.items()
                         if isinstance(v, str) and k not in SKIP_KEYS and len(v) > 20)
            comms.append((str(d.get("commentator", "?")), str(d.get("school", "?")), t))
    return root, comms


def stem_of(x):
    if not isinstance(x, str) or not x:
        return None
    return os.path.splitext(os.path.basename(x))[0]


class Corpus:
    """Holds ALL records per id. The released corpus reuses ids across source files
    (all 621 Gita ids appear in both bg.json and bg_prabhupada_1972.json), so an id alone
    does not identify a passage; the edge's tagged_from_file is matched to the record's
    _source_file to choose between them."""

    def __init__(self, path, needed_ids):
        df = pd.read_json(path, lines=True)
        df = df[df["id"].isin(needed_ids)]
        self.recs = {}
        for r in df.to_dict("records"):
            self.recs.setdefault(r["id"], []).append(r)
        self.n_multi = sum(1 for v in self.recs.values() if len(v) > 1)
        self.cache = {}

    def cands(self, rid, stem=None):
        lst = self.recs.get(rid, [])
        if not stem or len(lst) < 2:
            return lst
        match = [r for r in lst if stem_of(r.get("_source_file")) == stem]
        return match + [r for r in lst if r not in match]

    def parts_of(self, rec):
        k = id(rec)
        if k not in self.cache:
            self.cache[k] = record_parts(rec)
        return self.cache[k]

    def visible(self, rid, stem=None, quote=None):
        """Text the extractor actually saw, replicating build_user_prompt in tag_corpus.py:
        verse[:600] plus up to 2 commentaries (lang en/sa preferred), each cut at 500 chars."""
        lst = self.cands(rid, stem)
        if not lst:
            return None
        rec = lst[0]
        if quote and len(lst) > 1:
            nq = norm(quote)
            for r in lst:
                root, comms = self.parts_of(r)
                if nq in norm(root) or any(nq in norm(t) for _, _, t in comms):
                    rec = r
                    break
        parts = [str(rec.get("text") or "")[:600]]
        cs = rec.get("commentaries")
        if isinstance(cs, str):
            try:
                cs = json.loads(cs)
            except Exception:
                cs = None
        cs = [d for d in (cs if isinstance(cs, (list, np.ndarray)) else []) if isinstance(d, dict)]
        pref = [d for d in cs if d.get("lang") in ("en", "sa")]
        rest = [d for d in cs if d.get("lang") not in ("en", "sa")]
        for d in (pref + rest)[:2]:
            parts.append(str(d.get("text") or "")[:500])
        return " ".join(parts)


def load(args):
    os.makedirs(OUT, exist_ok=True)
    g = pd.read_json(args.graph, lines=True)
    need = {"edge_id", "concept_a", "concept_b", "relation", "school",
            "source_record_id", "source_text", "evidence_quote"}
    missing = need - set(g.columns)
    if missing:
        sys.exit(f"graph file lacks columns: {sorted(missing)} (columns: {list(g.columns)})")
    for col in ("school", "source_text", "relation"):
        g[col] = g[col].fillna("unknown").astype(str)
    if "tagged_from_file" not in g.columns:
        g["tagged_from_file"] = ""
    return g


def restrict_relations(g, a):
    """Keep edges whose relation is in the real extraction vocabulary (default), or the
    k most frequent labels (--vocab top). The v4 graph has ~100 labels; the rest are
    rare and several (e.g. IS_AFFECTED_BY) are not in the extraction vocabulary."""
    vc = g["relation"].value_counts()
    print("\nTop relation labels:")
    print(vc.head(20).to_string())
    if a.vocab == "real":
        keep = set(REAL_VOCAB)
        outside = vc[~vc.index.isin(keep)]
        print(f"\nLabels outside the real 13-label vocabulary: {len(outside)} labels, "
              f"{int(outside.sum())} edges dropped from this test ({outside.sum()/len(g):.3f} of edges)")
        return g[g["relation"].isin(keep)].reset_index(drop=True)
    k = a.top_relations
    if k and len(vc) > k:
        keep = set(vc.index[:k])
        print(f"\nKeeping the top {k} of {len(vc)} labels = {vc.iloc[:k].sum() / len(g):.3f} of edges")
        g = g[g["relation"].isin(keep)].reset_index(drop=True)
    return g


def locate(corpus, rid, quote, stem=None):
    """Return (where, commentator, school, text, span) for the first place the quote is found,
    searching every record that shares this id (edge's source file first)."""
    lst = corpus.cands(rid, stem)
    if not lst:
        return ("no_record", None, None, None, None)
    nq = norm(quote)
    if not nq:
        return ("empty_quote", None, None, None, None)
    for rec in lst:
        root, comms = corpus.parts_of(rec)
        hits = []
        if nq in norm(root):
            hits.append(("root", None, None, root))
        for who, sch, t in comms:
            if nq in norm(t):
                hits.append(("commentary", who, sch, t))
        if not hits:
            continue
        kind = "root" if hits[0][0] == "root" and len(hits) == 1 else (
            "commentary_only" if all(h[0] == "commentary" for h in hits) else "root_and_commentary")
        pick = next((h for h in hits if h[0] == "commentary"), hits[0])
        return (kind, pick[1], pick[2], pick[3], find_span(pick[3], quote))
    return ("not_found", None, None, None, None)


# ---------------------------------------------------------------- fetch
def cmd_fetch(a):
    from huggingface_hub import hf_hub_download
    os.makedirs(DATA, exist_ok=True)
    for fn in (a.graph_file, "darshana_corpus.jsonl"):
        p = hf_hub_download(REPO, fn, repo_type="dataset", local_dir=DATA)
        print("downloaded", p)


# ---------------------------------------------------------------- quotes
def cmd_quotes(a):
    g = load(a)
    c = Corpus(a.corpus, set(g["source_record_id"]))
    print(f"corpus ids used by edges that map to more than one record: {c.n_multi}")
    rows = []
    for r in g.itertuples(index=False):
        kind, who, sch, _, _ = locate(c, r.source_record_id, str(r.evidence_quote), stem_of(r.tagged_from_file))
        vis = c.visible(r.source_record_id, stem_of(r.tagged_from_file), str(r.evidence_quote))
        inwin = None if vis is None else (norm(str(r.evidence_quote)) in norm(vis))
        rows.append((r.edge_id, r.school, r.source_text, kind, who, sch, inwin))
    d = pd.DataFrame(rows, columns=["edge_id", "school", "source_text", "status",
                                    "commentator", "commentary_school", "in_prompt_window"])
    d.to_csv(f"{OUT}/quotes_by_edge.csv", index=False)
    tr = d[d["in_prompt_window"].notna()].copy()
    tr["in_prompt_window"] = tr["in_prompt_window"].astype(bool)
    tr["quote_class"] = np.where(tr["in_prompt_window"], "in_prompt_window",
                         np.where(tr["status"] == "not_found", "not_in_record_at_all",
                                  "in_record_but_outside_prompt_window"))
    print("\nQUOTE vs WHAT THE EXTRACTOR SAW (edges with a corpus record):")
    print(tr["quote_class"].value_counts(normalize=True).round(3).to_string())
    for col in ("school", "source_text"):
        t = pd.crosstab(tr[col], tr["quote_class"], normalize="index").round(3)
        t["n_edges"] = tr[col].value_counts()
        t.to_csv(f"{OUT}/quote_window_by_{col}.csv")
        print(f"\nBY {col.upper()}")
        print(t.sort_values("n_edges", ascending=False).head(15).to_string())
    print("\nOVERALL status share")
    print(d["status"].value_counts(normalize=True).round(3).to_string())
    for col in ("school", "source_text"):
        t = pd.crosstab(d[col], d["status"], normalize="index").round(3)
        t["n_edges"] = d[col].value_counts()
        t.to_csv(f"{OUT}/quotes_by_{col}.csv")
        print(f"\nBY {col.upper()} (row shares)")
        print(t.sort_values("n_edges", ascending=False).head(25).to_string())
    x = pd.crosstab(d["school"], d["commentary_school"])
    x.to_csv(f"{OUT}/edge_school_vs_commentary_school.csv")
    print("\nEdge school vs school of the commentary containing the quote saved to "
          f"{OUT}/edge_school_vs_commentary_school.csv")
    print("Read it: a quote found only in commentary X but labelled school Y needs explaining.")


# ---------------------------------------------------------------- null model
def cramers_v(x, y, nx, ny):
    tab = np.bincount(x * ny + y, minlength=nx * ny).reshape(nx, ny).astype(float)
    n = tab.sum()
    exp = np.outer(tab.sum(1), tab.sum(0)) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        chi = np.where(exp > 0, (tab - exp) ** 2 / exp, 0).sum()
    k = min(nx, ny) - 1
    return math.sqrt(chi / (n * k)) if k > 0 and n > 0 else 0.0


def cmd_null(a):
    g = restrict_relations(load(a), a)
    if a.unit == "tagged_from_file":
        g = g.copy()
        g["source_text"] = g["tagged_from_file"].fillna("unknown").astype(str)
    n_unk = int((g["source_text"] == "unknown").sum())
    if n_unk and not a.keep_unknown:
        print(f"\nDropping {n_unk} edges with no source unit: pooling unrelated books into one "
              "'source' would make the within-source shuffle meaningless.")
        g = g[g["source_text"] != "unknown"].reset_index(drop=True)
    rng = np.random.default_rng(a.seed)
    rel, rel_names = pd.factorize(g["relation"])
    sch, sch_names = pd.factorize(g["school"])
    src, src_names = pd.factorize(g["source_text"])
    nr, ns, nsrc = len(rel_names), len(sch_names), len(src_names)

    print(f"edges {len(g)}, relations {nr}, schools {ns}, source texts {nsrc}")
    print("V(relation, school)      =", round(cramers_v(rel, sch, nr, ns), 3))
    print("V(relation, source_text) =", round(cramers_v(rel, src, nr, nsrc), 3))

    # multi-school sources: source with >=2 schools each having >= min_edges edges
    cnt = g.groupby(["source_text", "school"]).size().reset_index(name="n")
    cnt = cnt[cnt["n"] >= a.min_edges]
    multi = cnt.groupby("source_text").filter(lambda x: len(x) >= 2)
    keep = set(zip(multi["source_text"], multi["school"]))
    mask = np.array([(s, c) in keep for s, c in zip(g["source_text"], g["school"])])
    single = g.groupby("source_text")["school"].nunique()
    print(f"\nsources with one school: {(single == 1).sum()} of {len(single)}")
    print(f"edges inside multi-school sources (>= {a.min_edges} edges per school): {mask.sum()}")
    if mask.sum() == 0:
        print("No multi-school sources, so school cannot be separated from source here.")
        return
    m = g[mask].reset_index(drop=True)
    r2, rn2 = pd.factorize(m["relation"])
    s2, sn2 = pd.factorize(m["school"])
    src2 = pd.factorize(m["source_text"])[0]
    groups = [np.where(src2 == k)[0] for k in np.unique(src2)]
    obs = cramers_v(r2, s2, len(rn2), len(sn2))
    tabs = np.zeros((a.perms, len(sn2), len(rn2)))
    null_v = np.zeros(a.perms)
    for p in range(a.perms):
        sp = s2.copy()
        for idx in groups:
            sp[idx] = rng.permutation(s2[idx])
        null_v[p] = cramers_v(r2, sp, len(rn2), len(sn2))
        tabs[p] = np.bincount(sp * len(rn2) + r2, minlength=len(sn2) * len(rn2)).reshape(len(sn2), len(rn2))
    p_val = (1 + (null_v >= obs).sum()) / (1 + a.perms)
    print(f"\nWithin multi-school sources: V(relation, school) observed {obs:.3f}, "
          f"null mean {null_v.mean():.3f} (95% {np.percentile(null_v, 97.5):.3f}), perm p = {p_val:.4f}")
    obs_tab = np.bincount(s2 * len(rn2) + r2, minlength=len(sn2) * len(rn2)).reshape(len(sn2), len(rn2))
    rows = []
    for i, sname in enumerate(sn2):
        n_s = obs_tab[i].sum()
        for j, rname in enumerate(rn2):
            o = obs_tab[i, j]
            lo, hi = np.percentile(tabs[:, i, j], [2.5, 97.5])
            rows.append((sname, rname, int(n_s), int(o), round(o / n_s, 3),
                         round(tabs[:, i, j].mean() / n_s, 3), o < lo or o > hi))
    out = pd.DataFrame(rows, columns=["school", "relation", "n_school_edges", "observed",
                                      "obs_share", "null_share", "outside_95pct"])
    out.to_csv(f"{OUT}/null_school_relation.csv", index=False)
    print("\nSchool x relation cells outside the within-source null (95%):")
    print(out[out["outside_95pct"]].sort_values("n_school_edges", ascending=False).head(25).to_string(index=False))


# ---------------------------------------------------------------- voice proxy
MARKERS = [
    r"it may be objected", r"it is objected", r"\bobjects?\b", r"\bobjection\b",
    r"\bopponents?\b", r"p[uū]rva-?pak[sṣs]h?a", r"\bsome say\b", r"\bsome hold\b",
    r"\bsome maintain\b", r"\bit is said that\b", r"\bif it be said\b",
    r"\bif you say\b", r"\bthe (?:buddhists?|jains?|s[aā][mṅ]khyas?|naiy[aā]yikas?|"
    r"vai[sṣ]e[sṣ]ikas?|c[aā]rv[aā]kas?|m[iī]m[aā][mṃ]sakas?|bauddhas?)\b",
    r"\bcontends?\b", r"\bmaintains? that\b", r"\bargues? that\b", r"\bassert that\b",
    r"\bmay say\b", r"\bwho (?:says|say|hold|holds|maintain)\b",
]
MARK_RE = re.compile("|".join(MARKERS), flags=re.I | re.U)


def cmd_voice(a):
    g = load(a)
    c = Corpus(a.corpus, set(g["source_record_id"]))
    rows = []
    for r in g.itertuples(index=False):
        kind, who, sch, text, span = locate(c, r.source_record_id, str(r.evidence_quote), stem_of(r.tagged_from_file))
        if kind not in ("commentary_only", "root_and_commentary") or text is None or span is None:
            rows.append((r.edge_id, r.school, r.source_text, kind, None, None, ""))
            continue
        s, e = span
        window = text[max(0, s - a.window): e + 100]
        m = MARK_RE.search(window)
        rows.append((r.edge_id, r.school, r.source_text, kind, bool(m),
                     m.group(0) if m else None, window.replace("\n", " ")))
    d = pd.DataFrame(rows, columns=["edge_id", "school", "source_text", "status",
                                    "flagged", "marker", "window"])
    d.to_csv(f"{OUT}/voice_proxy.csv", index=False)
    ok = d[d["flagged"].notna()].copy()
    ok["flagged"] = ok["flagged"].astype(bool)
    print(f"edges with a locatable commentary span: {len(ok)} of {len(d)}")
    print(f"flagged as near an objection marker: {ok['flagged'].mean():.3f}")
    for col in ("school", "source_text"):
        t = ok.groupby(col)["flagged"].agg(["mean", "sum", "count"]).round(3)
        print(f"\nBY {col.upper()} (flag share)")
        print(t.sort_values("count", ascending=False).head(20).to_string())
    rng = np.random.default_rng(a.seed)
    fl = ok[ok["flagged"]]
    nf = ok[~ok["flagged"]]
    pick = pd.concat([fl.sample(min(50, len(fl)), random_state=int(rng.integers(1e9))),
                      nf.sample(min(50, len(nf)), random_state=int(rng.integers(1e9)))])
    pick = pick.sample(frac=1, random_state=a.seed)[["edge_id", "school", "window"]].copy()
    pick["human_is_opponent_voice"] = ""
    pick.to_csv(f"{OUT}/voice_spotcheck_100.csv", index=False)
    print(f"\nFill the last column of {OUT}/voice_spotcheck_100.csv (yes/no/unclear) for the proxy's precision.")
    print("A flag is a proxy: the marker list misses cases and the 300-char window is crude.")


# ---------------------------------------------------------------- no-passage test
def build_prompt(rels, ca, cb, school=None, passage=None, defs=False):
    lines = ["You label the relation between two philosophical concepts.",
             "Choose exactly one label from: " + ", ".join(rels) + ".",
             "Answer with the label only.", ""]
    if defs:
        lines += [DEFS, ""]
    lines += [
              f"Concept A: {ca}", f"Concept B: {cb}"]
    if school:
        lines.append(f"School: {school}")
    if passage:
        lines.append(f"Passage: {passage}")
    lines.append("Label:")
    return "\n".join(lines)


def parse_label(reply, rels):
    r = (reply or "").upper()
    best, pos = "UNPARSED", 10 ** 9
    for lab in rels:
        i = r.find(lab)
        if i != -1 and i < pos:
            best, pos = lab, i
    return best


def make_client(a, rels, truth):
    if a.mock:
        rnd = random.Random(0)

        def call(prompt, edge_id):
            return truth[edge_id] if rnd.random() < 0.5 else rnd.choice(rels)
        return call
    import groq
    client = groq.Groq(api_key=os.environ["GROQ_API_KEY"])
    ids = sorted(m.id for m in client.models.list().data)
    if a.model not in ids:
        sys.exit(f"Model '{a.model}' is not available to this key. Models you can use:\n  "
                 + "\n  ".join(ids) + "\nRerun with --model <one of these>.")
    extra = {"reasoning_effort": "low"} if "gpt-oss" in a.model else {}
    transient = (groq.RateLimitError, groq.APIConnectionError,
                 groq.APITimeoutError, groq.InternalServerError)

    def call(prompt, edge_id):
        # Only transient errors are retried. Anything else (bad model, bad key,
        # bad request) is raised so it cannot be mistaken for a model answer.
        for k in range(6):
            try:
                r = client.chat.completions.create(
                    model=a.model, temperature=0, max_tokens=a.max_tokens,
                    messages=[{"role": "user", "content": prompt}], **extra)
                return r.choices[0].message.content or ""
            except transient:
                time.sleep(2 ** k)
        return None
    return call


def cmd_nopassage(a):
    from sklearn.metrics import cohen_kappa_score
    g = restrict_relations(load(a), a)
    rels = sorted(g["relation"].unique())
    c = Corpus(a.corpus, set(g["source_record_id"]))
    rng = random.Random(a.seed)
    cand = []
    for r in g.itertuples(index=False):
        kind, _, _, text, span = locate(c, r.source_record_id, str(r.evidence_quote), stem_of(r.tagged_from_file))
        if text is not None and span is not None:
            s, e = span
            cand.append((r, text[max(0, s - 700): e + 700]))
    if len(cand) < a.n:
        print(f"only {len(cand)} edges have a locatable passage; using those")
    sample = rng.sample(cand, min(a.n, len(cand)))
    schools = sorted(g["school"].unique())
    truth = {r.edge_id: r.relation for r, _ in sample}
    call = make_client(a, rels, truth)
    import hashlib
    tag = hashlib.md5(("|".join(rels) + PROMPT_VERSION + a.model).encode()).hexdigest()[:8]
    cache_path = f"{OUT}/nopassage_responses_{tag}.jsonl"
    print(f"label set ({len(rels)}): {', '.join(rels)}\ncache file: {cache_path}")
    cache = {}
    if os.path.exists(cache_path):
        for line in open(cache_path, encoding="utf-8"):
            o = json.loads(line)
            cache[(o["edge_id"], o["cond"])] = o["label"]
    out = open(cache_path, "a", encoding="utf-8")
    preds = {k: {} for k in ("pair", "pair_repeat", "pair_school", "pair_school_swapped", "passage", "passage_defs")}
    swapped_school = {}
    fails = 0
    for r, window in sample:
        alt = [s for s in schools if s != r.school] or [r.school]
        swapped_school[r.edge_id] = rng.choice(alt)
        prompts = {
            "pair": build_prompt(rels, r.concept_a, r.concept_b),
            "pair_repeat": build_prompt(rels, r.concept_a, r.concept_b),  # noise floor
            "pair_school": build_prompt(rels, r.concept_a, r.concept_b, school=r.school),
            "pair_school_swapped": build_prompt(rels, r.concept_a, r.concept_b,
                                                school=swapped_school[r.edge_id]),
            "passage": build_prompt(rels, r.concept_a, r.concept_b, passage=window),
            "passage_defs": build_prompt(rels, r.concept_a, r.concept_b, passage=window, defs=True),
        }
        for cond, pr in prompts.items():
            key = (r.edge_id, cond)
            if key not in cache:
                reply = call(pr, r.edge_id)
                if reply is None:  # transient failure after retries: do not cache
                    fails += 1
                    if fails >= 20:
                        sys.exit("20 calls failed after retries (rate limit or network). "
                                 "Wait a few minutes and rerun; finished calls are cached.")
                    continue
                cache[key] = parse_label(reply, rels)
                out.write(json.dumps({"edge_id": r.edge_id, "cond": cond, "label": cache[key]}) + "\n")
                out.flush()
            preds[cond][r.edge_id] = cache[key]
    out.close()
    ids = [r.edge_id for r, _ in sample if all(r.edge_id in preds[c] for c in preds)]
    print(f"edges with all four conditions answered: {len(ids)} of {len(sample)}")
    y = [truth[i] for i in ids]
    maj = pd.Series(y).value_counts(normalize=True).iloc[0]
    print(f"\nn = {len(ids)} edges; majority-label baseline accuracy = {maj:.3f}")
    rows = []
    for cond in preds:
        p = [preds[cond][i] for i in ids]
        acc = np.mean([a_ == b_ for a_, b_ in zip(p, y)])
        rows.append((cond, round(acc, 3), round(cohen_kappa_score(y, p), 3),
                     round(np.mean([x == "UNPARSED" for x in p]), 3)))
    res = pd.DataFrame(rows, columns=["condition", "accuracy_vs_graph", "kappa_vs_graph", "unparsed_share"])
    print(res.to_string(index=False))
    flip = np.mean([preds["pair_school"][i] != preds["pair_school_swapped"][i] for i in ids])
    agree = np.mean([preds["pair"][i] == preds["passage"][i] for i in ids])
    noise = np.mean([preds["pair"][i] != preds["pair_repeat"][i] for i in ids])
    print(f"\nNOISE FLOOR: identical prompt gives a different label {noise:.3f} of the time")
    print(f"label changes when the school name is swapped: {flip:.3f}  (compare with the noise floor)")
    for cond in ("pair", "passage", "passage_defs"):
        cm = pd.crosstab(pd.Series(y, name="graph_label"),
                         pd.Series([preds[cond][i] for i in ids], name="model_label"))
        cm.to_csv(f"{OUT}/nopassage_confusion_{cond}.csv")
        print(f"\nCONFUSION ({cond}), share of each graph label, top 5 graph labels:")
        top = pd.Series(y).value_counts().index[:5]
        print(cm.loc[top].div(cm.loc[top].sum(1), axis=0).round(2).to_string())
    print(f"pair-only prediction equals passage prediction:  {agree:.3f}")
    res.to_csv(f"{OUT}/nopassage_summary.csv", index=False)
    print("\nIf 'pair' is close to 'passage', the labels are mostly predictable from priors.")
    print("The graph labels came from an LLM, so this shows consistency with that LLM, not truth.")



# ---------------------------------------------------------------- masked-school re-extraction
def make_chat(a):
    """Return chat(system, user) -> text or None. Mock mode fakes labels that follow the header school."""
    if a.mock:
        rnd = random.Random(1)

        def chat(system, user):
            hdr = re.search(r"\[(.*?)\]:", user)
            h = hdr.group(1) if hdr else ""
            p_iqao = 0.55 if "vishishtadvaita" in h else 0.30
            rels = []
            for _ in range(rnd.randint(2, 5)):
                r = "IS_QUALIFIED_ASPECT_OF" if rnd.random() < p_iqao else rnd.choice(
                    ["IS_IDENTICAL_TO", "IS_DISTINCT_FROM", "IS_CAUSE_OF", "LEADS_TO"])
                rels.append({"concept_a": "a", "concept_b": "b", "relation": r,
                             "school": h.split("/")[-1].strip() if "/" in h else "general",
                             "confidence": "high", "evidence_quote": "x"})
            return json.dumps({"concepts": [], "relationships": rels})
        return chat
    import groq
    client = groq.Groq(api_key=os.environ["GROQ_API_KEY"])
    ids = sorted(m.id for m in client.models.list().data)
    if a.model not in ids:
        sys.exit(f"Model '{a.model}' not available. Use --model with one of:\n  " + "\n  ".join(ids))
    extra = {"reasoning_effort": "low"} if "gpt-oss" in a.model else {}
    state = {"json_mode": True}
    transient = (groq.RateLimitError, groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError)

    def chat(system, user):
        for k in range(6):
            kw = dict(extra)
            if state["json_mode"]:
                kw["response_format"] = {"type": "json_object"}
            try:
                r = client.chat.completions.create(
                    model=a.model, temperature=0, max_tokens=a.max_tokens_json,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)
                return r.choices[0].message.content or ""
            except transient:
                time.sleep(2 ** k)
            except groq.BadRequestError:
                if state["json_mode"]:
                    state["json_mode"] = False  # model/endpoint rejects JSON mode: retry without it
                    continue
                raise
        return None
    return chat


def parse_json_edges(text):
    if not text:
        return None
    i, j = text.find("{"), text.rfind("}")
    if i == -1 or j <= i:
        return None
    try:
        return json.loads(text[i:j + 1]).get("relationships", []) or []
    except Exception:
        return None


def cmd_mask(a):
    import importlib.util
    import hashlib
    tc_path = a.tag_corpus
    if not os.path.exists(tc_path):
        sys.exit(f"tag_corpus.py not found at {tc_path}. In Colab: "
                 "!git clone https://github.com/joyboseroy/darshana-graph  and pass "
                 "--tag-corpus darshana-graph/tag_corpus.py")
    spec = importlib.util.spec_from_file_location("tag_corpus", tc_path)
    tc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tc)

    df = pd.read_json(a.corpus, lines=True)
    df = df[df["_source_file"].astype(str).str.startswith("brahma_sutras.json")]
    recs = []
    for r in df.to_dict("records"):
        cs = r.get("commentaries")
        if isinstance(cs, str):
            try:
                cs = json.loads(cs)
            except Exception:
                cs = None
        if isinstance(cs, (list, np.ndarray)) and len(cs) == 1 and isinstance(cs[0], dict):
            d = cs[0]
            if d.get("school") in ("advaita", "vishishtadvaita") and len(str(d.get("text") or "")) >= 300:
                recs.append((r, d))
    by = {"advaita": [x for x in recs if x[1]["school"] == "advaita"],
          "vishishtadvaita": [x for x in recs if x[1]["school"] == "vishishtadvaita"]}
    print({k: len(v) for k, v in by.items()}, "eligible single-commentary Thibaut records")
    rng = random.Random(a.seed)
    chosen = []
    for k, v in by.items():
        chosen += [(k,) + x for x in rng.sample(v, min(a.n_per_school, len(v)))]

    other = {"advaita": ("ramanuja", "vishishtadvaita"), "vishishtadvaita": ("shankara", "advaita")}
    chat = make_chat(a)
    tag = hashlib.md5((a.model + "mask-v1" + str(a.n_per_school) + str(a.seed)).encode()).hexdigest()[:8]
    cache_path = f"{OUT}/mask_responses_{tag}.jsonl"
    cache = {}
    if os.path.exists(cache_path):
        for line in open(cache_path, encoding="utf-8"):
            o = json.loads(line)
            cache[(o["rid"], o["cond"])] = o["edges"]
    out = open(cache_path, "a", encoding="utf-8")
    fails = 0
    rows = []
    for ts, rec, d in chosen:
        for cond in ("own", "masked", "other"):
            d2 = dict(d)
            if cond == "masked":
                d2["commentator"], d2["school"] = "unknown", "unknown"
            elif cond == "other":
                d2["commentator"], d2["school"] = other[ts]
            header_school = d2["school"]
            key = (rec["id"], cond)
            if key not in cache:
                r2 = dict(rec)
                r2["commentaries"] = [d2]
                reply = chat(tc.SYSTEM_PROMPT, tc.build_user_prompt(r2))
                edges = parse_json_edges(reply)
                if edges is None:
                    fails += 1
                    if fails >= 25:
                        sys.exit("25 calls failed or returned unparseable output. "
                                 "Rerun later; finished calls are cached.")
                    continue
                cache[key] = edges
                out.write(json.dumps({"rid": rec["id"], "cond": cond, "edges": edges}) + "\n")
                out.flush()
            for e in cache[key]:
                if isinstance(e, dict) and e.get("relation") in REAL_VOCAB:
                    rows.append((rec["id"], ts, cond, e["relation"], e.get("school"), header_school))
            rows.append((rec["id"], ts, cond, "__record__", None, header_school))  # marks the record was answered
    out.close()
    df = pd.DataFrame(rows, columns=["rid", "text_school", "cond", "relation", "out_school", "header_school"])
    df.to_csv(f"{OUT}/mask_edges.csv", index=False)
    answered = df[df.relation == "__record__"]
    ed = df[df.relation != "__record__"]
    print(f"\nrecords answered per (text school, condition):")
    print(answered.groupby(["text_school", "cond"]).size().unstack().to_string())

    key_rels = ["IS_QUALIFIED_ASPECT_OF", "IS_IDENTICAL_TO", "IS_DISTINCT_FROM", "IS_CAUSE_OF"]
    tab = []
    for (ts, cond), g in ed.groupby(["text_school", "cond"]):
        n = len(g)
        row = {"text_school": ts, "label": cond, "edges": n}
        for r_ in key_rels:
            row[r_.replace("IS_", "")] = round((g.relation == r_).mean(), 3)
        tab.append(row)
    tab = pd.DataFrame(tab).sort_values(["text_school", "label"])
    print("\nRELATION SHARES BY TEXT AUTHOR AND SCHOOL LABEL SHOWN TO THE MODEL")
    print(tab.to_string(index=False))
    tab.to_csv(f"{OUT}/mask_shares.csv", index=False)

    # label effect within the same text: share(label A) - share(label B), bootstrap over records
    nb = a.boot
    nprng = np.random.default_rng(a.seed)

    def share(sub, rel):
        return (sub.relation == rel).mean() if len(sub) else np.nan

    print("\nLABEL EFFECT HOLDING THE TEXT FIXED (bootstrap over records, 95% interval)")
    for ts in ("vishishtadvaita", "advaita"):
        rids = ed[ed.text_school == ts].rid.unique()
        rids_all = answered[answered.text_school == ts].rid.unique()
        for rel in ("IS_QUALIFIED_ASPECT_OF", "IS_IDENTICAL_TO"):
            for a_, b_ in (("own", "masked"), ("own", "other")):
                vals = []
                for _ in range(nb):
                    pick = nprng.choice(rids_all, len(rids_all), replace=True)
                    sa = ed[(ed.cond == a_) & ed.rid.isin(pick)]
                    sb = ed[(ed.cond == b_) & ed.rid.isin(pick)]
                    # weight by resampled multiplicity
                    cnt = pd.Series(pick).value_counts()
                    wa = sa.rid.map(cnt)
                    wb = sb.rid.map(cnt)
                    pa = ((sa.relation == rel) * wa).sum() / wa.sum() if wa.sum() else np.nan
                    pb = ((sb.relation == rel) * wb).sum() / wb.sum() if wb.sum() else np.nan
                    vals.append(pa - pb)
                lo, hi = np.nanpercentile(vals, [2.5, 97.5])
                obs = share(ed[(ed.text_school == ts) & (ed.cond == a_)], rel) - \
                    share(ed[(ed.text_school == ts) & (ed.cond == b_)], rel)
                print(f"  {ts:16s} {rel:24s} share({a_}) - share({b_}) = {obs:+.3f}  [{lo:+.3f}, {hi:+.3f}]")

    cp = ed[ed.cond.isin(["own", "other"])]
    copy = (cp.out_school == cp.header_school).groupby(cp.cond).mean().round(3)
    print("\nShare of extracted edges whose school field equals the school shown in the header:")
    print(copy.to_string())
    ms = ed[ed.cond == "masked"].out_school.value_counts(normalize=True).round(3).head(6)
    print("\nSchool field chosen when the header says 'unknown':")
    print(ms.to_string())
    print("\nHow to read it: if Ramanuja's IS_QUALIFIED_ASPECT_OF share stays high when the label is masked "
          "or swapped, the text carries it. If it collapses, the label did the work. "
          "The model is not the original Llama 3.1 8B, and records are cut as in the original prompt "
          "(verse 600 chars, commentary 500 chars), so treat the sizes as indicative.")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "quotes", "null", "voice", "nopassage", "mask"])
    ap.add_argument("--graph", default=f"{DATA}/darshana_graph_v4.jsonl")
    ap.add_argument("--graph-file", default="darshana_graph_v4.jsonl", help="file to fetch")
    ap.add_argument("--corpus", default=f"{DATA}/darshana_corpus.jsonl")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--perms", type=int, default=500)
    ap.add_argument("--min-edges", type=int, default=30)
    ap.add_argument("--window", type=int, default=300)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--unit", choices=["source_text", "tagged_from_file"], default="source_text",
                    help="grouping unit for the within-source shuffle in 'null'")
    ap.add_argument("--keep-unknown", action="store_true",
                    help="keep edges whose source_text is unknown (not recommended)")
    ap.add_argument("--vocab", choices=["real", "top"], default="real",
                    help="real = the 13 labels in tag_corpus.py (default); top = k most frequent")
    ap.add_argument("--top-relations", type=int, default=13,
                    help="null and nopassage use only the k most frequent relation labels (0 = all)")
    ap.add_argument("--model", default="openai/gpt-oss-20b",
                    help="llama-3.1-8b-instant was shut down for developer-tier keys on 2026-08-16")
    ap.add_argument("--tag-corpus", default="darshana-graph/tag_corpus.py",
                    help="path to the repo's tag_corpus.py (for the exact extraction prompt)")
    ap.add_argument("--n-per-school", type=int, default=100)
    ap.add_argument("--boot", type=int, default=500)
    ap.add_argument("--max-tokens-json", type=int, default=3000)
    ap.add_argument("--max-tokens", type=int, default=300,
                    help="gpt-oss models spend tokens on reasoning before the label")
    ap.add_argument("--mock", action="store_true", help="fake model, for testing the plumbing")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    {"fetch": cmd_fetch, "quotes": cmd_quotes, "null": cmd_null,
     "voice": cmd_voice, "nopassage": cmd_nopassage, "mask": cmd_mask}[a.cmd](a)


if __name__ == "__main__":
    main()
