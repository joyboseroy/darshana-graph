"""
darshana-graph: Extended Corpus Scraper
========================================
Sources:
  1. Buddhism   -- bilara-data git clone (pass path with --bilara)
  2. Jainism    -- scrape_tattvartha.py (Tattvartha Sutra, wisdomlib)
                   sacred-texts.com SBE22/45 (Jacobi: Acaranga, Sutrakritanga)
  3. Darshanas  -- sacred-texts.com + archive.org
                   (Samkhya Karika, Yoga Sutras, Nyaya Sutras, Vaisheshika Sutras)

Usage:
  python scrape_new.py --all --bilara /mnt/c/Users/ebosjoy/Downloads/darshana/bilara-data
  python scrape_new.py --source buddhism --bilara /path/to/bilara-data
  python scrape_new.py --source jainism
  python scrape_new.py --source darshanas
"""

import json
import re
import time
import logging
import argparse
import pathlib
import requests
from bs4 import BeautifulSoup

# Import Tattvartha scraper
from scrape_tattvartha import scrape_tattvartha

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_DIR = pathlib.Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)

BILARA_DIR = pathlib.Path("bilara-data")  # override with --bilara

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
DELAY = 1.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def get(url, retries=3):
    for i in range(retries):
        try:
            time.sleep(DELAY)
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            log.warning(f"Attempt {i+1} failed {url}: {e}")
            time.sleep(DELAY * 2)
    log.error(f"All retries failed: {url}")
    return None


def save(records, filename):
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(records)} records -> {path}")


# ── 1. BUDDHISM via bilara-data git clone ────────────────────────────────────

PHILOSOPHICAL_SN = {
    "sn12": "dependent_origination",
    "sn22": "five_aggregates",
    "sn35": "sense_bases",
    "sn44": "undeclared_questions",
    "sn45": "eightfold_path",
    "sn46": "seven_factors_awakening",
    "sn51": "bases_of_power",
    "sn56": "four_noble_truths",
}


def pali_path_for(trans_path: pathlib.Path, bilara: pathlib.Path) -> pathlib.Path:
    rel = trans_path.relative_to(bilara / "translation/en/sujato")
    pali_name = rel.name.replace("_translation-en-sujato", "_root-pli-ms")
    pali_rel = pathlib.Path("root/pli/ms") / rel.parent / pali_name
    return bilara / pali_rel


def parse_sutta_id(segment_key: str):
    if ":" in segment_key:
        parts = segment_key.split(":", 1)
        return parts[0], parts[1]
    return segment_key, ""


def is_content_segment(key: str, text: str) -> bool:
    pos = key.split(":")[-1] if ":" in key else ""
    if pos.startswith("0."):
        return False
    if len(text.strip()) < 10:
        return False
    return True


def load_sutta_file(trans_file, bilara, nikaya, darshana="theravada", theme_tag=None):
    try:
        trans = json.loads(trans_file.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Failed to read {trans_file}: {e}")
        return []

    pali_file = pali_path_for(trans_file, bilara)
    pali_data = {}
    if pali_file.exists():
        try:
            pali_data = json.loads(pali_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    records = []
    for seg_key, seg_text in trans.items():
        if not is_content_segment(seg_key, seg_text):
            continue
        sutta_id, position = parse_sutta_id(seg_key)
        pali_text = pali_data.get(seg_key, "")
        records.append({
            "id":          f"bilara_{seg_key.replace(':', '_').replace('.', '_')}",
            "source":      f"{nikaya}_nikaya",
            "tradition":   "buddhism",
            "darshana":    darshana,
            "sutta_id":    sutta_id,
            "segment_id":  seg_key,
            "position":    position,
            "text":        seg_text.strip(),
            "pali":        pali_text.strip(),
            "translator":  "bhikkhu_sujato",
            "theme_tag":   theme_tag,
            "commentaries": [],
        })
    return records


def scrape_buddhism(bilara_dir=None):
    log.info("== Buddhism: reading bilara-data ==")
    bilara = pathlib.Path(bilara_dir) if bilara_dir else BILARA_DIR

    if not bilara.exists():
        log.error(
            f"bilara-data not found at {bilara}\n"
            f"Run: git clone --depth=1 https://github.com/suttacentral/bilara-data\n"
            f"Then pass: --bilara /path/to/bilara-data"
        )
        return []

    trans_root = bilara / "translation/en/sujato/sutta"
    all_records = []

    # DN
    log.info("  DN (Long Discourses) ...")
    for f in sorted((trans_root / "dn").glob("*.json")):
        all_records.extend(load_sutta_file(f, bilara, "dn"))
    log.info(f"    DN: {len(all_records)} segments")

    # MN
    mn_start = len(all_records)
    log.info("  MN (Middle Length Discourses) ...")
    for f in sorted((trans_root / "mn").glob("*.json")):
        all_records.extend(load_sutta_file(f, bilara, "mn"))
    log.info(f"    MN: {len(all_records)-mn_start} segments")

    # SN
    sn_start = len(all_records)
    log.info("  SN (Linked Discourses) ...")
    for samyutta_dir in sorted((trans_root / "sn").iterdir()):
        if not samyutta_dir.is_dir():
            continue
        theme = PHILOSOPHICAL_SN.get(samyutta_dir.name)
        for f in sorted(samyutta_dir.glob("*.json")):
            all_records.extend(load_sutta_file(f, bilara, "sn", theme_tag=theme))
    log.info(f"    SN: {len(all_records)-sn_start} segments")

    # AN
    an_start = len(all_records)
    log.info("  AN (Numbered Discourses) ...")
    for nipata_dir in sorted((trans_root / "an").iterdir()):
        if not nipata_dir.is_dir():
            continue
        for f in sorted(nipata_dir.glob("*.json")):
            all_records.extend(load_sutta_file(f, bilara, "an"))
    log.info(f"    AN: {len(all_records)-an_start} segments")

    # KN selected
    log.info("  KN (DHP, UD, ITI, SNP, KP) ...")
    kn_texts = {
        "dhp": "dhammapada",
        "ud":  "udana",
        "iti": "itivuttaka",
        "snp": "sutta_nipata",
        "kp":  "khuddakapatha",
    }
    kn_start = len(all_records)
    for subdir, label in kn_texts.items():
        p = trans_root / "kn" / subdir
        if not p.exists():
            continue
        for f in sorted(p.rglob("*.json")):
            all_records.extend(load_sutta_file(f, bilara, f"kn_{label}", theme_tag=label))
    log.info(f"    KN selected: {len(all_records)-kn_start} segments")

    save(all_records, "buddhism.json")
    return all_records


# ── 2. JAINISM ────────────────────────────────────────────────────────────────

JAIN_SACRED_TEXTS = {
    "acaranga_sutra": {
        "index_url":  "https://sacred-texts.com/jai/sbe22/index.htm",
        "base_url":   "https://sacred-texts.com/jai/sbe22",
        "darshana":   "jain_shvetambara",
        "tradition":  "jainism",
        "translator": "jacobi_1884",
    },
    "sutrakritanga": {
        "index_url":  "https://sacred-texts.com/jai/sbe45/index.htm",
        "base_url":   "https://sacred-texts.com/jai/sbe45",
        "darshana":   "jain_shvetambara",
        "tradition":  "jainism",
        "translator": "jacobi_1895",
    },
}


def scrape_sacred_texts_jain(source_key):
    cfg = JAIN_SACRED_TEXTS[source_key]
    log.info(f"  {source_key} (sacred-texts.com) ...")
    records = []

    r = get(cfg["index_url"])
    if not r:
        return records

    soup = BeautifulSoup(r.text, "lxml")
    base = cfg["base_url"]

    page_links = []
    for a in soup.select("a[href]"):
        href = a["href"]
        if re.match(r'sbe\d+\d+\.htm', href):
            full = f"{base}/{href}"
            if full not in page_links:
                page_links.append(full)

    log.info(f"    Found {len(page_links)} pages")

    for page_url in page_links:
        r = get(page_url)
        if not r:
            continue

        page_soup = BeautifulSoup(r.text, "lxml")
        for tag in page_soup.select("table, .navbar, hr"):
            tag.decompose()

        body = page_soup.select_one("body")
        if not body:
            continue

        text = body.get_text("\n", strip=True)
        blocks = re.split(r'\n(?=\d+\.\s+[A-Z"\'\(])', text)

        for i, block in enumerate(blocks):
            block = block.strip()
            if len(block) < 40:
                continue
            num_match = re.match(r'^(\d+)\.\s+', block)
            verse_num = int(num_match.group(1)) if num_match else i
            records.append({
                "id":          f"{source_key}_{page_url.split('/')[-1].replace('.htm','')}_{i:04d}",
                "source":      source_key,
                "tradition":   cfg["tradition"],
                "darshana":    cfg["darshana"],
                "chapter":     None,
                "verse":       verse_num,
                "segment_id":  f"{source_key}_{i}",
                "text":        block[:4000],
                "sanskrit":    "",
                "translator":  cfg["translator"],
                "commentaries": [],
            })

    return records


def scrape_jainism():
    log.info("== Jainism ==")
    all_records = []

    # Tattvartha Sutra via wisdomlib (dedicated scraper)
    log.info("  Tattvartha Sutra (wisdomlib) ...")
    tattvartha_records = scrape_tattvartha()
    all_records.extend(tattvartha_records)
    log.info(f"    Tattvartha: {len(tattvartha_records)} sutras")

    # Acaranga + Sutrakritanga via sacred-texts
    for source_key in JAIN_SACRED_TEXTS:
        recs = scrape_sacred_texts_jain(source_key)
        all_records.extend(recs)
        log.info(f"    {source_key}: {len(recs)} records")

    save(all_records, "jainism.json")
    return all_records


# ── 3. SIX DARSHANAS ─────────────────────────────────────────────────────────

DARSHANA_SOURCES = {
    "samkhya_karika": {
        # 6 book pages — hardcoded since index links are nav-heavy
        "pages": [
            "https://sacred-texts.com/hin/sak/sak1.htm",
            "https://sacred-texts.com/hin/sak/sak2.htm",
            "https://sacred-texts.com/hin/sak/sak3.htm",
            "https://sacred-texts.com/hin/sak/sak4.htm",
            "https://sacred-texts.com/hin/sak/sak5.htm",
            "https://sacred-texts.com/hin/sak/sak6.htm",
        ],
        "darshana":   "samkhya",
        "tradition":  "hindu_astika",
        "translator": "ballantyne_1885",
        "type":       "hardcoded_pages",
    },
    "yoga_sutras": {
        "index_url":  "https://sacred-texts.com/hin/ysp/index.htm",
        "base_url":   "https://sacred-texts.com/hin/ysp",
        "darshana":   "yoga",
        "tradition":  "hindu_astika",
        "translator": "johnston_1912",
        "type":       "multi_page",
    },
    "nyaya_sutras": {
        "url":        "https://archive.org/stream/NyayaSutra/nyaya_sutras_of_gautama_djvu.txt",
        "darshana":   "nyaya",
        "tradition":  "hindu_astika",
        "translator": "vidyabhusana_1913",
        "type":       "archive_txt",
    },
    "vaisheshika_sutras": {
        "url":        "https://archive.org/stream/Sacred_Books_of_the_Hindus/SBH%2006%20-%20Vaiseshika%20Sutras%20of%20Kanada%20English%20Translation%20-%20Nandalal%20Sinha%201923_djvu.txt",
        "darshana":   "vaisheshika",
        "tradition":  "hindu_astika",
        "translator": "sinha_1923",
        "type":       "archive_txt",
    },
}


def parse_single_page_darshana(html, source_key, cfg):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.select("table, .navbar, hr, head"):
        tag.decompose()
    text = soup.get_text("\n", strip=True)

    # Samkhya Karika uses * to mark aphorisms; split on * or numbers
    if source_key == "samkhya_karika":
        # Each aphorism starts with * on its own line
        blocks = re.split(r'\n(?=\*\s)', text)
        # Also try splitting long blocks on sentence boundaries
        if len(blocks) < 10:
            blocks = [b for line in text.split("\n") 
                     for b in [line.strip()] if len(b) > 40]
    else:
        blocks = re.split(r'\n(?=(?:\d+\.|[IVX]+\.\d+\.|Sutra \d+))', text)

    records = []
    verse_counter = 0
    for i, block in enumerate(blocks):
        block = block.strip()
        if len(block) < 20:
            continue
        num_match = re.match(r'^(\d+)\.', block)
        if num_match:
            verse_counter = int(num_match.group(1))
        else:
            verse_counter += 1
        records.append({
            "id":          f"{source_key}_{verse_counter:04d}",
            "source":      source_key,
            "tradition":   cfg["tradition"],
            "darshana":    cfg["darshana"],
            "chapter":     None,
            "verse":       verse_counter,
            "segment_id":  f"{source_key}_{verse_counter}",
            "text":        block[:3000],
            "sanskrit":    "",
            "translator":  cfg["translator"],
            "commentaries": [],
        })
    return records


def parse_archive_txt_darshana(text, source_key, cfg):
    text = re.sub(r'\f', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    start_match = re.search(
        r'(BOOK\s+I|APHORISM\s+1\.?|SUTRA\s+1\.?|\n1\.\s+[A-Z])',
        text, re.IGNORECASE
    )
    if start_match:
        text = text[start_match.start():]

    blocks = re.split(r'\n(?=(?:\d+\.\s+[A-Z]|Aphorism \d+|Sutra \d+))', text)

    records = []
    verse_counter = 0
    for i, block in enumerate(blocks):
        block = block.strip()
        if len(block) < 30:
            continue
        ascii_ratio = sum(1 for c in block if ord(c) < 128) / max(len(block), 1)
        if ascii_ratio < 0.7:
            continue
        num_match = re.match(r'^(\d+)\.', block)
        if num_match:
            verse_counter = int(num_match.group(1))
        else:
            verse_counter += 1
        records.append({
            "id":          f"{source_key}_{verse_counter:04d}",
            "source":      source_key,
            "tradition":   cfg["tradition"],
            "darshana":    cfg["darshana"],
            "chapter":     None,
            "verse":       verse_counter,
            "segment_id":  f"{source_key}_{verse_counter}",
            "text":        block[:3000],
            "sanskrit":    "",
            "translator":  cfg["translator"],
            "commentaries": [],
        })
    return records


def scrape_sacred_texts_multipage(source_key, cfg):
    """Scrape a multi-page sacred-texts book via its index page."""
    records = []
    r = get(cfg["index_url"])
    if not r:
        return records

    soup = BeautifulSoup(r.text, "lxml")
    base = cfg["base_url"]

    page_links = []
    for a in soup.select("a[href]"):
        href = a["href"]
        if href.endswith(".htm") and "index" not in href.lower():
            full = f"{base}/{href.lstrip(chr(47))}"
            if full not in page_links:
                page_links.append(full)

    log.info(f"    Found {len(page_links)} pages")

    for page_url in page_links:
        r = get(page_url)
        if not r:
            continue
        recs = parse_single_page_darshana(r.text, source_key, cfg)
        records.extend(recs)

    return records


def scrape_darshanas():
    log.info("== Six Darshanas ==")
    all_records = []

    for source_key, cfg in DARSHANA_SOURCES.items():
        log.info(f"  {source_key} ({cfg['darshana']}) ...")

        if cfg["type"] == "hardcoded_pages":
            records = []
            for page_url in cfg["pages"]:
                r = get(page_url)
                if r:
                    records.extend(parse_single_page_darshana(r.text, source_key, cfg))
        elif cfg["type"] == "multi_page":
            records = scrape_sacred_texts_multipage(source_key, cfg)
        elif cfg["type"] == "archive_txt":
            r = get(cfg["url"])
            if not r:
                log.warning(f"  Skipping {source_key} - could not fetch")
                continue
            records = parse_archive_txt_darshana(r.text, source_key, cfg)
        else:
            records = []

        log.info(f"    -> {len(records)} records")
        all_records.extend(records)

    save(all_records, "darshanas.json")
    return all_records


# ── Merge all corpus files ────────────────────────────────────────────────────

def merge_all():
    files = [f for f in OUTPUT_DIR.glob("*.json") if f.name != "corpus.json"]
    all_records = []
    for f in sorted(files):
        data = json.loads(f.read_text(encoding="utf-8"))
        all_records.extend(data)
        log.info(f"  {f.name}: {len(data)} records")
    save(all_records, "corpus.json")
    log.info(f"Total corpus: {len(all_records)} records")
    return all_records


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="darshana-graph extended scraper")
    parser.add_argument(
        "--source",
        choices=["buddhism", "jainism", "darshanas", "all"],
        default="all",
    )
    parser.add_argument(
        "--bilara",
        default=str(BILARA_DIR),
        help="Path to bilara-data clone (required for --source buddhism)",
    )
    args = parser.parse_args()

    if args.source in ("buddhism", "all"):
        scrape_buddhism(args.bilara)
    if args.source in ("jainism", "all"):
        scrape_jainism()
    if args.source in ("darshanas", "all"):
        scrape_darshanas()
    if args.source == "all":
        merge_all()


if __name__ == "__main__":
    main()
