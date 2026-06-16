"""
scrape_nimbarka.py — Nimbarka's Brahma Sutra commentary (wisdomlib.org)
==========================================================================
Source: "Brahma Sutras (Nimbarka commentary)" by Roma Bose, 1940
         Vedanta-parijata-saurabha (Nimbarka's root commentary)
         Vedanta-kaustubha (Srinivasa's sub-commentary)

Each leaf page (one per sutra) contains:
  - Sutra translation (Roma Bose), in a blockquote
  - "## Nimbārka's commentary (Vedānta-pārijāta-saurabha):" section
  - "## Śrīnivāsa's commentary (Vedānta-kaustubha)" section
  - Often footnotes comparing Nimbarka's reading to Shankara/Ramanuja/
    Bhaskara/Srikantha/Baladeva -- valuable cross-school tension data,
    captured separately as 'comparative_notes'

Navigation: pages link forward via "Next >" with sequential doc IDs.
Starting point: Brahma-Sutra 1.1.1 = doc376139

Run:
  python scrape_nimbarka.py
  python scrape_nimbarka.py --resume
  python scrape_nimbarka.py --start-doc 376139 --max-pages 50   # test run
"""

import re
import json
import time
import logging
import argparse
import requests
from pathlib import Path
from bs4 import BeautifulSoup

OUTPUT_DIR    = Path("corpus")
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_FILE   = OUTPUT_DIR / "brahma_sutras_nimbarka.json"
PROGRESS_FILE = OUTPUT_DIR / "nimbarka_progress.json"

BASE = "https://www.wisdomlib.org/hinduism/book/brahma-sutras-nimbarka/d"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0"}
DELAY = 3.0  # wisdomlib rate-limits; same caution as Tattvartha scraper

START_DOC_ID = 376139  # Brahma-Sutra 1.1.1

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
            wait = DELAY * (2 ** i)
            log.warning(f"Attempt {i+1} failed {url}: {e} — waiting {wait:.0f}s")
            time.sleep(wait)
    log.error(f"All retries failed: {url}")
    return None


def extract_sutra_ref(title):
    """'Brahma-Sūtra 4.4.17' -> (4, 4, 17)"""
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', title)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None, None, None


def parse_page(html, doc_id):
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else ""

    # Skip non-sutra pages (Adhikarana index pages, chapter/pada index pages)
    if not re.search(r'\d+\.\d+\.\d+', title):
        # Try to find "Next >" link so we can still continue navigation
        next_link = find_next_link(soup)
        return None, next_link

    adhyaya, pada, sutra_num = extract_sutra_ref(title)

    # Sutra translation -- in the first <blockquote>
    sutra_text = ""
    bq = soup.find("blockquote")
    if bq:
        sutra_text = bq.get_text(" ", strip=True)
        # Strip the "English translation ... by Roma Bose:" preamble if present
        sutra_text = re.sub(r'^English (of )?translation of Brahmasutra[^:]*:\s*', '', sutra_text)

    # Nimbarka's commentary and Srinivasa's commentary -- under H2 headers.
    # Use the LAST matching header on the page (in case site metadata/boilerplate
    # contains an earlier false-positive mention), and verify the collected text
    # isn't just boilerplate before accepting it.
    nimbarka_text = ""
    srinivasa_text = ""

    headers = soup.find_all(["h2", "h3"])
    nimbarka_header = None
    srinivasa_header = None
    for h in headers:
        htext = h.get_text(strip=True)
        if "Nimb" in htext and "commentary" in htext.lower():
            nimbarka_header = h
        elif "Śrīnivāsa" in htext or "Srinivasa" in htext or "rinivāsa" in htext:
            srinivasa_header = h

    if nimbarka_header:
        stop_markers = ["Śrīnivāsa", "Srinivasa", "rinivāsa"]
        nimbarka_text = collect_section_text(nimbarka_header, stop_at_headers=stop_markers)
    if srinivasa_header:
        nimbarka_markers = ["Nimb"]
        srinivasa_text = collect_section_text(srinivasa_header, stop_at_headers=nimbarka_markers)

    # Boilerplate guard: if the captured text looks like site metadata
    # ("by Roma Bose | 1940 | ..."), it means collect_section_text walked
    # into the wrong sibling chain -- discard it rather than keep noise.
    BOILERPLATE_RE = re.compile(r'by Roma Bose\s*\|\s*1940\s*\|', re.IGNORECASE)
    if BOILERPLATE_RE.search(nimbarka_text):
        nimbarka_text = ""
    if BOILERPLATE_RE.search(srinivasa_text):
        srinivasa_text = ""

    # Minimum content length guard: real commentary is always more than a
    # few words; anything shorter is likely a stray fragment, not genuine
    # content, so treat it as missing rather than keep noise.
    MIN_COMMENTARY_LENGTH = 15
    if nimbarka_text and len(nimbarka_text) < MIN_COMMENTARY_LENGTH:
        nimbarka_text = ""
    if srinivasa_text and len(srinivasa_text) < MIN_COMMENTARY_LENGTH:
        srinivasa_text = ""

    # Comparative notes -- footnotes mentioning other schools
    comparative_notes = []
    footnotes_section = soup.find(id="footnotes") or soup.find("footer")
    if footnotes_section:
        for li in footnotes_section.find_all(["li", "p"]):
            text = li.get_text(" ", strip=True)
            if any(name in text for name in
                   ["Śaṅkara", "Shankara", "Rāmānuja", "Ramanuja",
                    "Bhāskara", "Bhaskara", "Śrīkaṇṭha", "Srikantha", "Baladeva"]):
                comparative_notes.append(text)

    record = {
        "id":          f"brahma_sutras_nimbarka_{adhyaya}_{pada}_{sutra_num:03d}",
        "source":      "brahma_sutras",
        "tradition":   "hindu_astika",
        "darshana":    "vedanta",
        "chapter":     adhyaya,
        "section":     pada,
        "verse":       sutra_num,
        "segment_id":  f"bs_{adhyaya}.{pada}.{sutra_num}",
        "text":        sutra_text,
        "translator":  "roma_bose_1940",
        "comparative_notes": comparative_notes,
        "commentaries": [
            {
                "commentator": "nimbarka",
                "school":      "dvaitadvaita",
                "lang":        "en",
                "text":        nimbarka_text,
            },
            {
                "commentator": "srinivasa",
                "school":      "dvaitadvaita",
                "lang":        "en",
                "text":        srinivasa_text,
            },
        ] if (nimbarka_text or srinivasa_text) else [],
    }

    next_link = find_next_link(soup)
    return record, next_link


def collect_section_text(header_tag, stop_at_headers=None):
    """
    Collect all paragraph text between this header and the next boundary.
    Defensive: walks find_next_siblings, stops at h1/h2/h3/hr, AND stops
    early if it encounters another known section header's text content
    (passed via stop_at_headers) even if it isn't marked as an h1-h3 tag,
    since wisdomlib sometimes uses inconsistent heading levels.
    """
    parts = []
    for sib in header_tag.find_next_siblings():
        if sib.name in ("h1", "h2", "h3", "hr"):
            break
        text = sib.get_text(" ", strip=True) if sib.name in ("p", "blockquote", "div") else ""
        if not text:
            continue
        if stop_at_headers and any(marker in text for marker in stop_at_headers):
            break
        parts.append(text)
    return " ".join(parts).strip()


def find_next_link(soup):
    """Find the 'Next >' navigation link and extract its doc ID."""
    for a in soup.find_all("a", href=True):
        if "Next" in a.get_text() or a.get("title", "").startswith("previous page:") is False and "next" in a.get("title", "").lower():
            m = re.search(r'doc(\d+)\.html', a["href"])
            if m:
                return int(m.group(1))
    # Fallback: look for href pattern with "Next >" text content
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True) == "Next >" or a.get_text(strip=True) == ">":
            m = re.search(r'doc(\d+)\.html', a["href"])
            if m:
                return int(m.group(1))
    return None


def scrape(start_doc_id=START_DOC_ID, max_pages=None, resume=False):
    records = []
    visited = set()

    if resume and PROGRESS_FILE.exists():
        prog = json.loads(PROGRESS_FILE.read_text())
        visited = set(prog.get("visited", []))
        start_doc_id = prog.get("next_doc_id", start_doc_id)
        if OUTPUT_FILE.exists():
            records = json.loads(OUTPUT_FILE.read_text())
        log.info(f"Resuming from doc{start_doc_id}, {len(records)} records, {len(visited)} visited")

    current_doc_id = start_doc_id
    pages_processed = 0
    consecutive_failures = 0

    while current_doc_id:
        if max_pages and pages_processed >= max_pages:
            log.info(f"Reached max_pages={max_pages}, stopping")
            break
        if current_doc_id in visited:
            log.warning(f"doc{current_doc_id} already visited — stopping to avoid loop")
            break

        url = f"{BASE}/doc{current_doc_id}.html"
        r = get(url)
        if not r:
            consecutive_failures += 1
            if consecutive_failures >= 5:
                log.error("5 consecutive failures, stopping")
                break
            current_doc_id += 1  # try next sequential ID as fallback
            continue

        consecutive_failures = 0
        visited.add(current_doc_id)

        record, next_doc_id = parse_page(r.text, current_doc_id)
        if record:
            records.append(record)
            pages_processed += 1
            if pages_processed % 10 == 0:
                log.info(f"  {pages_processed} sutras scraped, current: {record['segment_id']}")
                _save(records, visited, next_doc_id)

        if next_doc_id is None:
            log.info(f"No 'Next' link found on doc{current_doc_id} — reached end or navigation broke")
            break

        current_doc_id = next_doc_id

    _save(records, visited, current_doc_id)
    log.info(f"Done: {len(records)} sutra records")

    from collections import Counter
    by_chapter = Counter(r["chapter"] for r in records)
    for ch, count in sorted(by_chapter.items()):
        log.info(f"  Adhyaya {ch}: {count} sutras")

    return records


def _save(records, visited, next_doc_id):
    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    PROGRESS_FILE.write_text(json.dumps({
        "visited": list(visited),
        "next_doc_id": next_doc_id,
    }))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-doc", type=int, default=START_DOC_ID)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    scrape(start_doc_id=args.start_doc, max_pages=args.max_pages, resume=args.resume)
