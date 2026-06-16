# darshana-graph

A text-grounded knowledge graph of Indian philosophy, covering Hindu
darshanas, the Buddhist Pali Canon, and Jain philosophical texts, built
entirely from public-domain and openly-licensed source texts, with
LLM-assisted concept tagging constrained to a closed vocabulary.

**Dataset on HuggingFace**: [joyboseroy/darshana-graph](https://huggingface.co/datasets/joyboseroy/darshana-graph)

## What this is

Most digital resources for Indian philosophy are single-text,
single-translator. This project instead aligns the same root texts
(principally the Bhagavad Gita and Brahma Sutras) across multiple
independent historical commentators, so the same verse or sutra can be
read side by side through 18 distinct commentators spanning Advaita,
Vishishtadvaita, Dvaita, Dvaitadvaita, Achintya Bhedabheda, and more,
plus the full Pali Canon and core Jain texts.

Every concept and relationship in the resulting graph is anchored to a
specific passage in a real source text, with a verbatim evidence quote.
The LLM tagging step is pure classification over text already in front
of the model. There is no retrieval and no reliance on the model's prior
knowledge of Indian philosophy.

## Repository structure

```
darshana-graph/
  corpus/                          raw scraped/converted text, per source
    bg.json                        Bhagavad Gita, 13 commentators
    bg_prabhupada_1972.json        Prabhupada's "As It Is" (1972)
    brahma_sutras.json             Thibaut: Shankara + Ramanuja
    brahma_sutras_madhva.json      Madhva's Brahma Sutra Bhashya
    brahma_sutras_nimbarka.json    Nimbarka + Srinivasa (partial)
    gambhirananda_*.json           Gambhirananda's Upanishads + Brahma Sutra
    upanishads_muller.json         Muller's 10 principal Upanishads
    darshanas.json                 Samkhya, Yoga, Nyaya, Vaisheshika
    tattvartha_sutra.json          Jain Tattvartha Sutra
    jainism.json                   Acaranga + Sutrakritanga
    buddhism.json                  Full Pali Canon (110k+ segments)
    buddhism_philosophical_subset.json   curated subset used for tagging
  corpus/tagged/                   LLM-tagged output, one .jsonl per source
  hf_dataset/                      final merged files pushed to HuggingFace
    darshana_corpus.jsonl
    darshana_graph.jsonl
    README.md                      HuggingFace dataset card
  scrape.py                        Vedanta scrapers (Gita API, sacred-texts.com)
  scrape_new.py                    Buddhism (bilara-data), Jainism, Darshanas
  scrape_tattvartha.py             Tattvartha Sutra (wisdomlib, resumable)
  scrape_nimbarka.py               Nimbarka commentary (wisdomlib, resumable)
  convert_gita.py                  gita/gita repo -> corpus schema
  convert_muller.py                Max Muller SBE text files -> corpus schema
  convert_madhva.py                Madhva djvu OCR text -> corpus schema
  convert_prabhupada_1972.py       Prabhupada 1972 PDF text -> corpus schema
  extract_gambhirananda.py         OCR pipeline for scanned Gambhirananda PDFs
  filter_buddhism_philosophical.py Sample/filter Pali Canon for tagging
  fix_duplicate_ids.py             ID-collision detection and repair
  tag_corpus.py                    LLM tagging pipeline (Groq + closed vocab)
  audit_tagged.py                  Coverage/quality audit + tension preview
  prepare_hf_dataset.py            Merge corpus + tagged output for release
  inventory.py                     Full corpus status/coverage report
  test_sources.py                  Connectivity check for all scrape targets
```

## Pipeline overview

1. **Scrape/convert** source texts into a unified JSON schema (see Schema
   below). Each script in the repo root handles one source or source
   family; run `inventory.py` at any point to see what's collected and
   what's missing.
2. **Fix data hygiene issues** as needed. `fix_duplicate_ids.py` checks
   every corpus file for ID collisions, a real issue that affected three
   files in this project, traced to scrapers that reset per-page block
   counters across hundreds of HTML pages.
3. **Tag** the corpus with `tag_corpus.py`, which calls an LLM (default:
   Llama 3.1 8B via Groq) to extract concepts and typed relationships from
   each record's verse text plus up to two associated commentaries. The
   model is constrained to a closed vocabulary defined in the script; any
   output outside that vocabulary is dropped post-hoc by
   `validate_and_filter()`, regardless of whether the underlying JSON
   parsed successfully.
4. **Audit** with `audit_tagged.py` for coverage percentages, relation/
   school distributions, and a preview of cross-school "tension":
   concept pairs where different schools assert different relation types.
5. **Merge and release** with `prepare_hf_dataset.py`, which produces the
   two files pushed to HuggingFace.

## Schema

See the [HuggingFace dataset card](hf_dataset/README.md) for the full
schema definition, relation vocabulary, and per-tradition breakdown.

## Setup

```bash
pip install requests beautifulsoup4 lxml groq --break-system-packages

# For OCR-based extraction (Gambhirananda PDFs):
sudo apt-get install -y poppler-utils tesseract-ocr
pip install pytesseract pillow pdf2image --break-system-packages

export GROQ_API_KEY="your-key-here"
```

External clones needed before running the Buddhism/Gita pipelines:

```bash
git clone --depth=1 https://github.com/suttacentral/bilara-data
git clone --depth=1 https://github.com/gita/gita
```

## Reproducing the pipeline

```bash
# 1. Scrape everything (each is independently resumable where noted)
python scrape.py --all
python scrape_new.py --all --bilara ./bilara-data
python scrape_tattvartha.py --resume
python convert_gita.py --gita-dir ./gita/data

# 2. Check for ID collisions before tagging
python fix_duplicate_ids.py

# 3. Tag (slow on Groq free tier; a paid Developer tier key removes the
#    rate-limit bottleneck for a few dollars total at this corpus size)
python tag_corpus.py --all --workers 6 --resume

# 4. Audit and merge
python audit_tagged.py
python prepare_hf_dataset.py
```

## Known limitations

See the "Known limitations" section of the
[HuggingFace dataset card](hf_dataset/README.md) for the full, honest
accounting. In short: no human expert review, single-pass LLM tagging
with an estimated 70-85% precision, a tendency for the tagging model to
over-use the `IS_QUALIFIED_ASPECT_OF` relation and the `general` school
tag rather than committing to a more specific label, and partial coverage
for Nimbarka/Srinivasa due to source-site reliability during scraping.

## License

Code in this repository (the scraping, conversion, and tagging pipeline)
is released under MIT. The corpus and graph data follow the licensing
described in the HuggingFace dataset card, CC-BY-4.0 for the
aggregation/tagging work, with underlying source texts retaining their
original licenses (public domain, CC BY-NC 4.0 for Pali Canon
translations, or explicit free-reproduction grants as noted per source).

## Acknowledgements

Built on public-domain translations by George Thibaut, Max Muller,
S. Subba Rau, Roma Bose, Hermann Jacobi, and Vijay K. Jain; the SuttaCentral
bilara-data project and Bhikkhu Sujato's Pali Canon translations; and the
gita/gita open dataset of Bhagavad Gita translations and commentaries.
