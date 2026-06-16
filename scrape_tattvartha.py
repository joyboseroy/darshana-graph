"""
Tattvartha Sutra scraper — wisdomlib.org
=========================================
Handles rate limiting with longer delays and resume capability.
Saves progress after every 10 verses so you can resume if interrupted.

Run:
  python scrape_tattvartha.py           # full run
  python scrape_tattvartha.py --resume  # resume from last saved verse

Output: corpus/tattvartha_sutra.json
"""

import re, json, time, logging, argparse
import requests
from bs4 import BeautifulSoup
from pathlib import Path

OUTPUT_DIR  = Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)

PROGRESS_FILE = OUTPUT_DIR / "tattvartha_progress.json"
OUTPUT_FILE   = OUTPUT_DIR / "tattvartha_sutra.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0"}
DELAY   = 3.0   # wisdomlib rate limits at 1.5s — use 3s to be safe
BASE    = "https://www.wisdomlib.org"
INDEX   = f"{BASE}/jainism/book/tattvartha-sutra-with-commentary"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def get(url, retries=4):
    for i in range(retries):
        try:
            time.sleep(DELAY)
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            return r
        except Exception as e:
            wait = DELAY * (2 ** i)  # exponential backoff: 3, 6, 12, 24s
            log.warning(f"Attempt {i+1} failed {url}: {e} — waiting {wait:.0f}s")
            time.sleep(wait)
    log.error(f"All retries failed: {url}")
    return None


def collect_doc_links():
    r = get(INDEX)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    seen = set()
    links = []
    for a in soup.select("a[href]"):
        href = a["href"]
        if "/d/doc" in href and href.endswith(".html"):
            full = BASE + href if href.startswith("/") else href
            if full not in seen:
                seen.add(full)
                links.append(full)
    log.info(f"Found {len(links)} doc links from index")
    return links


def parse_verse_page(html, url):
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else ""

    if title.startswith("Chapter") or not re.search(r'Verse\s+\d+\.\d+', title):
        return None

    m = re.search(r'Verse\s+(\d+)\.(\d+)', title)
    if not m:
        return None
    ch, v = int(m.group(1)), int(m.group(2))

    sanskrit   = ""
    iast       = ""
    english    = ""
    commentary = ""

    blockquote = soup.find("blockquote")
    if blockquote:
        paras = blockquote.find_all("p")
        for p in paras:
            text = p.get_text(" ", strip=True)
            if re.search(r'[\u0900-\u097F]', text) and "॥" in text:
                sanskrit = text
            em = p.find("em")
            if em and not iast:
                iast = em.get_text(" ", strip=True)
            if text and not re.search(r'[\u0900-\u097F]', text) and not em:
                if not english and len(text) > 20:
                    english = text

    puja_h = soup.find(lambda t: t.name in ["h2","h3"] and "Pūjyapāda" in t.get_text())
    if puja_h:
        paras = []
        sib = puja_h.find_next_sibling()
        while sib and sib.name == "p":
            paras.append(sib.get_text(" ", strip=True))
            sib = sib.find_next_sibling()
        commentary = " ".join(paras)[:4000]

    if not english and not sanskrit:
        return None

    return {
        "id":          f"tattvartha_{ch:02d}_{v:03d}",
        "source":      "tattvartha_sutra",
        "tradition":   "jainism",
        "darshana":    "jain_common",
        "chapter":     ch,
        "verse":       v,
        "segment_id":  f"ts_{ch}.{v}",
        "title":       title,
        "sanskrit":    sanskrit,
        "iast":        iast,
        "text":        english,
        "translator":  "vijay_k_jain_pujyapada",
        "commentaries": [{
            "commentator": "pujyapada",
            "school":      "jain_digambara",
            "text":        commentary,
        }] if commentary else [],
    }


def scrape_tattvartha(resume=False):
    log.info("=== Tattvartha Sutra (wisdomlib.org) ===")

    # Load progress if resuming
    done_urls = set()
    existing_records = []
    if resume and PROGRESS_FILE.exists():
        progress = json.loads(PROGRESS_FILE.read_text())
        done_urls = set(progress.get("done_urls", []))
        if OUTPUT_FILE.exists():
            existing_records = json.loads(OUTPUT_FILE.read_text())
        log.info(f"Resuming: {len(done_urls)} pages done, {len(existing_records)} records saved")

    doc_links = collect_doc_links()
    if not doc_links:
        log.error("No links found")
        return []

    # Filter already done
    remaining = [u for u in doc_links if u not in done_urls]
    log.info(f"Remaining: {len(remaining)} pages to fetch")

    records = list(existing_records)
    skipped = 0

    for i, url in enumerate(remaining):
        r = get(url)
        if not r:
            log.warning(f"Skipping {url} after all retries")
            continue

        record = parse_verse_page(r.text, url)
        done_urls.add(url)

        if record:
            records.append(record)
            if len(records) % 20 == 0:
                log.info(f"  {len(records)} verses scraped ({i+1}/{len(remaining)} pages this run)")
        else:
            skipped += 1

        # Save progress every 10 pages
        if (i + 1) % 10 == 0:
            records_sorted = sorted(records, key=lambda r: (r["chapter"], r["verse"]))
            OUTPUT_FILE.write_text(json.dumps(records_sorted, ensure_ascii=False, indent=2))
            PROGRESS_FILE.write_text(json.dumps({"done_urls": list(done_urls)}))

    # Final save
    records.sort(key=lambda r: (r["chapter"], r["verse"]))
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    PROGRESS_FILE.write_text(json.dumps({"done_urls": list(done_urls)}))

    log.info(f"Done: {len(records)} verse records, {skipped} chapter pages skipped")

    chapters = {}
    for r in records:
        chapters[r["chapter"]] = chapters.get(r["chapter"], 0) + 1
    for ch, count in sorted(chapters.items()):
        log.info(f"  Chapter {ch}: {count} sutras")

    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="Resume from last saved progress")
    args = parser.parse_args()
    scrape_tattvartha(resume=args.resume)
