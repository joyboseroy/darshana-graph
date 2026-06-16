"""
vedanta-viveka-graph: Corpus Scraper
=====================================
Scrapes all source texts into a unified JSON format:

{
  "id":          "bg_2_20",
  "source":      "bhagavad_gita",
  "chapter":     2,
  "verse":       20,
  "text":        "...",          # base translation
  "translator":  "gambhirananda",
  "commentaries": [
    {
      "commentator": "prabhupada",
      "school":      "achintya_bhedabheda",
      "text":        "..."
    }
  ]
}

Sources:
  1. Bhagavad Gita  — vedicscriptures.github.io API (multi-translator)
  2. Prabhupada BG  — vedabase.io (verse + purport)
  3. Brahma Sutras  — sacred-texts.com (Thibaut, Shankara + Ramanuja inline)
  4. Upanishads     — sacred-texts.com (Müller PD translation)
  5. Vivekananda    — cwsv.belurmath.org (Complete Works)

Run:
  python scrape.py --all
  python scrape.py --source bg
  python scrape.py --source bs
  python scrape.py --source upanishads
  python scrape.py --source vivekananda
  python scrape.py --source prabhupada
"""

import requests
import json
import time
import re
import argparse
import logging
from pathlib import Path
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

DELAY = 1.5  # seconds between requests — be polite

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def get(url, retries=3, delay=DELAY):
    """GET with retries and polite delay."""
    for i in range(retries):
        try:
            time.sleep(delay)
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            log.warning(f"Attempt {i+1} failed for {url}: {e}")
            time.sleep(delay * 2)
    log.error(f"All retries failed: {url}")
    return None


def save(records, filename):
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(records)} records → {path}")


# ── 1. Bhagavad Gita via vedicscriptures API ─────────────────────────────────
# URL: https://vedicscriptures.github.io/slok/{chapter}/{verse}
# Returns JSON with keys for multiple translators:
#   gambhirananda, tej (Tejomayananda), san (Sankaracharya),
#   siva (Sivananda), pur (Purohit), abhinav, etc.
# We pick gambhirananda as primary (closest to RKM tradition)

BG_CHAPTERS = {
    1: 47, 2: 72, 3: 43, 4: 42, 5: 29, 6: 47,
    7: 30, 8: 28, 9: 34, 10: 42, 11: 55, 12: 20,
    13: 35, 14: 27, 15: 20, 16: 24, 17: 28, 18: 78,
}

# Map API translator keys → our schema names + school
BG_TRANSLATORS = {
    "gambhirananda": ("gambhirananda", "neo_vedanta"),
    "san":           ("sankaracharya", "advaita"),      # Adi Shankara's Gita Bhashya excerpts
    "siva":          ("sivananda",     "neo_vedanta"),
    "tej":           ("tejomayananda", "neo_vedanta"),
    "pur":           ("purohit",       "general"),
}


def scrape_bg():
    log.info("── Bhagavad Gita (vedicscriptures API) ──")
    records = []
    base = "https://vedicscriptures.github.io/slok"

    for ch, total_verses in BG_CHAPTERS.items():
        log.info(f"  Chapter {ch}/{len(BG_CHAPTERS)} ({total_verses} verses)")
        for v in range(1, total_verses + 1):
            r = get(f"{base}/{ch}/{v}")
            if not r:
                continue
            try:
                d = r.json()
            except Exception:
                log.warning(f"  JSON parse failed BG {ch}.{v}")
                continue

            # Base record — use gambhirananda as primary text
            primary = d.get("gambhirananda", {})
            record = {
                "id":           f"bg_{ch}_{v}",
                "source":       "bhagavad_gita",
                "chapter":      ch,
                "verse":        v,
                "text":         primary.get("et", "").strip(),
                "translator":   "gambhirananda",
                "sanskrit":     d.get("slok", "").strip(),
                "transliteration": d.get("transliteration", "").strip(),
                "commentaries": [],
            }

            # Add other translators as commentaries
            for api_key, (name, school) in BG_TRANSLATORS.items():
                if api_key == "gambhirananda":
                    continue
                t = d.get(api_key, {})
                commentary_text = t.get("et", "") or t.get("ht", "")
                if commentary_text and commentary_text.strip():
                    record["commentaries"].append({
                        "commentator": name,
                        "school":      school,
                        "text":        commentary_text.strip(),
                    })

            records.append(record)

    save(records, "bg.json")
    return records


# ── 2. Prabhupada BG via vedabase.io ─────────────────────────────────────────
# URL pattern: https://vedabase.io/en/library/bg/{ch}/{v}/
# Each page has: .r-verse (Sanskrit), .r-trans (translation), .r-purport (purport)

def scrape_prabhupada():
    log.info("── Prabhupada BG purports (vedabase.io) ──")
    records = []
    base = "https://vedabase.io/en/library/bg"

    for ch, total_verses in BG_CHAPTERS.items():
        log.info(f"  Chapter {ch} ({total_verses} verses)")
        for v in range(1, total_verses + 1):
            url = f"{base}/{ch}/{v}/"
            r = get(url)
            if not r:
                continue

            soup = BeautifulSoup(r.text, "lxml")

            # Extract translation
            trans_el = soup.select_one(".r-trans, [class*='translation']")
            trans = trans_el.get_text(" ", strip=True) if trans_el else ""

            # Extract purport — may be multiple paragraphs
            purport_el = soup.select(".r-purport p, [class*='purport'] p")
            purport = " ".join(p.get_text(" ", strip=True) for p in purport_el)

            # Fallback: try article body
            if not purport:
                article = soup.select_one("article, .content-block")
                if article:
                    purport = article.get_text(" ", strip=True)[:3000]

            if not trans and not purport:
                log.warning(f"  Empty page BG {ch}.{v} — skipping")
                continue

            records.append({
                "id":          f"prabhupada_bg_{ch}_{v}",
                "source":      "bhagavad_gita",
                "chapter":     ch,
                "verse":       v,
                "text":        trans.strip(),
                "translator":  "prabhupada",
                "school":      "achintya_bhedabheda",
                "commentaries": [{
                    "commentator": "prabhupada",
                    "school":      "achintya_bhedabheda",
                    "text":        purport.strip(),
                }],
            })

    save(records, "prabhupada_bg.json")
    return records


# ── 3. Brahma Sutras — Thibaut (sacred-texts.com) ────────────────────────────
# Thibaut Vol 1 (SBE 34) = Shankara's commentary on BS
# Thibaut Vol 2 (SBE 38) = Ramanuja's Sri Bhashya on BS
# URL pattern: sacred-texts.com/hin/sbe34/sbe34XXX.htm (001 to ~060)

BS_VOLUMES = {
    "shankara": {
        "school":      "advaita",
        "commentator": "shankara",
        "base_url":    "https://sacred-texts.com/hin/sbe34",
        "index_url":   "https://sacred-texts.com/hin/sbe34/index.htm",
    },
    "ramanuja": {
        "school":      "vishishtadvaita",
        "commentator": "ramanuja",
        "base_url":    "https://sacred-texts.com/hin/sbe48",
        "index_url":   "https://sacred-texts.com/hin/sbe48/index.htm",
    },
}


def scrape_sacred_texts_index(index_url, base_url):
    """Get list of chapter page URLs from sacred-texts index page."""
    r = get(index_url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    links = []
    for a in soup.select("a[href]"):
        href = a["href"]
        if re.match(r"sbe\d+\d+\.htm", href):
            links.append(f"{base_url}/{href}")
    return links


def parse_sacred_texts_page(html, source_id, commentator, school):
    """
    Parse a sacred-texts.com page into verse records.
    These pages mix sutra text + commentary in running prose.
    We split on sutra markers like 'I, 1, 1.' or bold headings.
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove nav/header cruft
    for tag in soup.select("table, .navbar, hr"):
        tag.decompose()

    body = soup.select_one("body")
    if not body:
        return []

    text = body.get_text("\n", strip=True)

    # Split on sutra numbering patterns like "1. ", "2. " at line start
    # or "Sutra 1" markers
    blocks = re.split(
        r'\n(?=(?:Adhyaya|Pada|Sutra|\d+\.\s))',
        text
    )

    records = []
    for i, block in enumerate(blocks):
        block = block.strip()
        if len(block) < 50:  # skip tiny fragments
            continue

        # Try to extract sutra reference from block start
        ref_match = re.match(r'^([\w\s,\.]+?\d[\d,\. ]*)', block)
        ref = ref_match.group(1).strip() if ref_match else f"block_{i}"

        records.append({
            "id":          f"{source_id}_{commentator}_{i:04d}",
            "source":      source_id,
            "block_index": i,
            "sutra_ref":   ref,
            "text":        block[:5000],  # cap very long commentary blocks
            "translator":  f"thibaut_{commentator}",
            "commentaries": [{
                "commentator": commentator,
                "school":      school,
                "text":        block[:5000],
            }],
        })

    return records


def scrape_brahma_sutras():
    log.info("── Brahma Sutras (sacred-texts.com / Thibaut) ──")
    all_records = []

    for name, cfg in BS_VOLUMES.items():
        log.info(f"  Volume: {name} ({cfg['commentator']})")
        page_urls = scrape_sacred_texts_index(cfg["index_url"], cfg["base_url"])
        log.info(f"  Found {len(page_urls)} pages")

        for url in page_urls:
            r = get(url)
            if not r:
                continue
            records = parse_sacred_texts_page(
                r.text, "brahma_sutras",
                cfg["commentator"], cfg["school"]
            )
            all_records.extend(records)
            log.info(f"    {url.split('/')[-1]} → {len(records)} blocks")

    save(all_records, "brahma_sutras.json")
    return all_records


# ── 4. Principal Upanishads — Müller (sacred-texts.com) ──────────────────────
# SBE Vol 1 = Chandogya, Talavakara (Kena), Aitareya, Kaushitaki, Vajasaneyi
# SBE Vol 15 = Katha, Mundaka, Taittiriya, Brihadaranyaka, Svetasvatara, Maitri, Mandukya

UPANISHAD_VOLUMES = [
    {
        "vol":       "sbe01",
        "index_url": "https://sacred-texts.com/hin/sbe01/index.htm",
        "base_url":  "https://sacred-texts.com/hin/sbe01",
        "texts":     ["chandogya", "kena", "aitareya", "kaushitaki"],
    },
    {
        "vol":       "sbe15",
        "index_url": "https://sacred-texts.com/hin/sbe15/index.htm",
        "base_url":  "https://sacred-texts.com/hin/sbe15",
        "texts":     ["katha", "mundaka", "taittiriya", "brihadaranyaka",
                      "svetasvatara", "maitri", "mandukya"],
    },
]

# Map Upanishad name fragments in page titles to our IDs
UPANISHAD_NAME_MAP = {
    "chandogya":     "chandogya_upanishad",
    "kena":          "kena_upanishad",
    "aitareya":      "aitareya_upanishad",
    "kaushitaki":    "kaushitaki_upanishad",
    "katha":         "katha_upanishad",
    "mundaka":       "mundaka_upanishad",
    "taittiriya":    "taittiriya_upanishad",
    "brihadaranyaka":"brihadaranyaka_upanishad",
    "svetasvatara":  "svetasvatara_upanishad",
    "maitri":        "maitri_upanishad",
    "mandukya":      "mandukya_upanishad",
}


def detect_upanishad(soup, url):
    """Guess which Upanishad a page belongs to from title/heading."""
    title = (soup.title.string or "").lower() if soup.title else ""
    heading = ""
    h = soup.find(["h1", "h2", "h3"])
    if h:
        heading = h.get_text().lower()
    combined = title + " " + heading + " " + url.lower()
    for key, uid in UPANISHAD_NAME_MAP.items():
        if key in combined:
            return uid
    return "upanishad_unknown"


def parse_upanishad_page(html, url):
    """Parse a sacred-texts Upanishad page into section records."""
    soup = BeautifulSoup(html, "lxml")
    upanishad_id = detect_upanishad(soup, url)

    for tag in soup.select("table, .navbar"):
        tag.decompose()

    body = soup.select_one("body")
    if not body:
        return []

    text = body.get_text("\n", strip=True)

    # Split on verse/section markers — Müller uses "1.", "2." etc
    blocks = re.split(r'\n(?=\d+\.?\s+[A-Z"\'])', text)

    records = []
    for i, block in enumerate(blocks):
        block = block.strip()
        if len(block) < 40:
            continue

        records.append({
            "id":          f"{upanishad_id}_muller_{i:04d}",
            "source":      upanishad_id,
            "block_index": i,
            "text":        block[:4000],
            "translator":  "muller",
            "school":      "general",
            "commentaries": [],
        })

    return records


def scrape_upanishads():
    log.info("── Principal Upanishads (sacred-texts.com / Müller) ──")
    all_records = []

    for vol in UPANISHAD_VOLUMES:
        log.info(f"  Volume {vol['vol']}")
        page_urls = scrape_sacred_texts_index(vol["index_url"], vol["base_url"])
        log.info(f"  Found {len(page_urls)} pages")

        for url in page_urls:
            r = get(url)
            if not r:
                continue
            records = parse_upanishad_page(r.text, url)
            all_records.extend(records)
            log.info(f"    {url.split('/')[-1]} → {len(records)} blocks")

    save(all_records, "upanishads.json")
    return all_records


# ── 5. Vivekananda Complete Works ─────────────────────────────────────────────
# URL: https://cwsv.belurmath.org/volume_{1-9}/vol_{1-9}_frame.htm
# Most relevant volumes for Vedanta KG:
#   Vol 1: Addresses at Parliament, Jnana Yoga
#   Vol 2: Jnana Yoga (continued)
#   Vol 3: Bhakti Yoga, Karma Yoga
#   Vol 8: Lectures & Discourses on Vedanta

VIVEKANANDA_VOLUMES = [
    {
        "vol": 1,
        "index": "https://cwsv.belurmath.org/volume_1/vol_1_frame.htm",
        "base":  "https://cwsv.belurmath.org/volume_1",
        "priority": True,
    },
    {
        "vol": 2,
        "index": "https://cwsv.belurmath.org/volume_2/vol_2_frame.htm",
        "base":  "https://cwsv.belurmath.org/volume_2",
        "priority": True,
    },
    {
        "vol": 3,
        "index": "https://cwsv.belurmath.org/volume_3/vol_3_frame.htm",
        "base":  "https://cwsv.belurmath.org/volume_3",
        "priority": False,
    },
    {
        "vol": 8,
        "index": "https://cwsv.belurmath.org/volume_8/vol_8_frame.htm",
        "base":  "https://cwsv.belurmath.org/volume_8",
        "priority": True,
    },
]


def scrape_vivekananda_index(index_url, base_url):
    """Frameset index — extract links from frame src or navigation."""
    r = get(index_url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    links = []
    # Frameset pages use <frame src="...">
    for frame in soup.find_all(["frame", "a"]):
        href = frame.get("src") or frame.get("href", "")
        if href and href.endswith(".htm") and "frame" not in href.lower():
            full = f"{base_url}/{href.lstrip('/')}"
            if full not in links:
                links.append(full)
    return links


def parse_vivekananda_page(html, vol_num, page_url):
    """Parse a Vivekananda lecture page into paragraph-level records."""
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.find(["h1", "h2", "h3", "title"])
    title = title_el.get_text(strip=True) if title_el else f"vol{vol_num}_lecture"

    # Get all substantial paragraphs
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if len(p.get_text(strip=True)) > 80
    ]

    records = []
    for i, para in enumerate(paragraphs):
        slug = re.sub(r'[^a-z0-9]+', '_', title.lower())[:40]
        records.append({
            "id":          f"vivekananda_vol{vol_num}_{slug}_{i:04d}",
            "source":      "vivekananda_complete_works",
            "volume":      vol_num,
            "lecture":     title,
            "para_index":  i,
            "text":        para[:3000],
            "translator":  "vivekananda",
            "school":      "neo_vedanta",
            "commentaries": [{
                "commentator": "vivekananda",
                "school":      "neo_vedanta",
                "text":        para[:3000],
            }],
        })

    return records


def scrape_vivekananda():
    log.info("── Vivekananda Complete Works (cwsv.belurmath.org) ──")
    all_records = []

    for vol_cfg in VIVEKANANDA_VOLUMES:
        vol = vol_cfg["vol"]
        log.info(f"  Volume {vol}")
        page_urls = scrape_vivekananda_index(vol_cfg["index"], vol_cfg["base"])
        log.info(f"  Found {len(page_urls)} pages")

        for url in page_urls:
            r = get(url)
            if not r:
                continue
            records = parse_vivekananda_page(r.text, vol, url)
            all_records.extend(records)
            log.info(f"    {url.split('/')[-1]} → {len(records)} paras")

    save(all_records, "vivekananda.json")
    return all_records


# ── Merge all into single corpus ──────────────────────────────────────────────

def merge_corpus():
    """Merge all individual JSON files into one corpus.json."""
    files = list(OUTPUT_DIR.glob("*.json"))
    files = [f for f in files if f.name != "corpus.json"]

    all_records = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
            all_records.extend(data)
        log.info(f"  Loaded {len(data)} records from {f.name}")

    save(all_records, "corpus.json")
    log.info(f"Total corpus: {len(all_records)} records")
    return all_records


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Vedanta corpus scraper")
    parser.add_argument(
        "--source",
        choices=["bg", "prabhupada", "bs", "upanishads", "vivekananda", "all"],
        default="all",
    )
    args = parser.parse_args()

    if args.source in ("bg", "all"):
        scrape_bg()
    if args.source in ("prabhupada", "all"):
        scrape_prabhupada()
    if args.source in ("bs", "all"):
        scrape_brahma_sutras()
    if args.source in ("upanishads", "all"):
        scrape_upanishads()
    if args.source in ("vivekananda", "all"):
        scrape_vivekananda()
    if args.source == "all":
        merge_corpus()


if __name__ == "__main__":
    main()
