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

## Example: the same verse, five readings

Bhagavad Gita 2.20 describes the soul as unborn, eternal, and untouched by the body's death. All five schools in this dataset agree on that much. Where they sharply diverge is on what this soul's relationship to Brahman, the ultimate reality, actually is.

**Shankara (Advaita Vedanta)**: "The Self spoken of here is, in its true nature, not different from Brahman at all. What appears as an individual soul, distinct and embodied, is a limitation imposed by ignorance. Remove the ignorance, and what remains is Brahman alone, without a second."

**Ramanuja (Vishishtadvaita)**: "The soul is eternally real and eternally distinct from the Lord, even in liberation. It is not annihilated into Brahman but exists as an eternal mode, dependent on and inseparable from the Supreme, the way light depends on its source without becoming identical to it."

**Madhva (Dvaita)**: "This verse proves the soul's eternal, irreducible distinctness. There is no stage, in bondage or in release, where the individual soul becomes one with God. To read identity into this verse is to ignore its plain sense in favor of a borrowed doctrine."

**Prabhupada (Achintya Bhedabheda)**: "The living entity is an eternal, individual spirit soul, simultaneously one with and different from the Supreme, in a manner beyond ordinary logical resolution."

Three schools call this the same one Self appearing as many. Two schools call it eternally distinct souls dependent on or related to one Supreme. The verse never changes. The reading does.

A second example, Bhagavad Gita 18.61, on whether the Lord directing all beings through maya overrides individual free will:

**Shankara**: maya is the power of ignorance through which the one Self appears divided into many; in truth, nothing moves and no one is directed.

**Ramanuja**: the Lord directs each soul strictly according to that soul's own past actions, using maya as the instrument of just governance, never overriding the soul's own agency.

**Madhva**: maya is not illusion but God's real power to ordain the movements of real, distinct souls, an assertion of divine sovereignty rather than a denial of individual reality.

## Example: pulled directly from the tagged graph data

This isn't a hand-picked illustration. The script `generate_readme_examples.py` queries the actual tagged dataset and surfaces real disagreements with real evidence quotes.

### Atman and Brahman: the central debate of Vedanta

**Advaita Vedanta** (822 relevant passages found): holds atman and brahman are identical.

**Vishishtadvaita** (191 relevant passages found): holds atman and brahman are distinct. From the text (Brahma Sutras): "Our text teaches that the creation of the aggregate of sentient and non-sentient things results from the mere wish of a being free from all connexion with non-sentient matter."

**Dvaita** (57 relevant passages found): holds atman and brahman are distinct, but for a different reason than Vishishtadvaita. From the text (Brahma Sutras): "difference of degree is clearly seen in the bliss enjoyed by the souls from the best of men upwards to Brahma the four-faced."

**Achintya Bhedabheda** (21 relevant passages found): holds atman and brahman are identical, in the specific devotional sense that "everything is born of Him, everything is sustained by Him, and everything, after annihilation, rests in Him."

Three schools land on "identical," two land on "distinct," and they don't even agree with each other on what distinct means. That's the kind of disagreement this dataset is built to surface.

### Atman and Jiva: is the individual soul the same as the self?

**Advaita Vedanta** (39 relevant passages found): holds atman and jiva are distinct. From the text (Brahma Sutras): "the waking being may be either the original soul, or he may be God, or some other individual soul."

**Vishishtadvaita** (12 relevant passages found): holds atman and jiva are identical. From the Bhagavad Gita: "the Jiva itself is eternal, indestructible, and incomprehensible."

**Dvaita** (8 relevant passages found): holds atman and jiva are identical, but reads the relationship very differently within its broader system. From the text (Brahma Sutras): "Now, being but one individual he goes forth separated."

Generate more examples yourself with `python generate_readme_examples.py --concept-a X --concept-b Y`, or run `--top-pairs N` to see the most contested concept pairs in the dataset.

## How differently do these commentators actually argue?

Beyond what each school concludes, the corpus lets you measure how they argue. Running `stylometric_comparison.py` on commentators with enough substantial prose passages in the corpus shows real differences in argumentative style:

| Commentator | School | Avg length (chars) | Cites scripture explicitly | Names and refutes an opponent |
|---|---|---|---|---|
| Shankara | Advaita | 1,848 | 2.8% of passages | 7.2% of passages |
| Ramanuja | Vishishtadvaita | 1,136 | 5.2% | 4.6% |
| Madhva | Dvaita | 513 | 17.1% | 2.0% |
| Prabhupada | Achintya Bhedabheda | 1,740 | 8.2% | 0.3% |
| Nimbarka | Dvaitadvaita | 328 | 0.0% | 16.5% |
| Srinivasa | Dvaitadvaita (sub-commentary) | 2,138 | 1.4% | 43.1% |
| Pujyapada | Jain | 1,306 | 0.3% | 1.1% |

Running the stylometric comparison on commentators with reliable sentence-level data in the corpus surfaces real differences. Within the Dvaita-Dvaitadvaita family specifically, three commentators writing across roughly six centuries show a clear trajectory: Madhva (13th century) leans heavily on direct scriptural citation (17.1% of passages) and rarely refutes opponents explicitly (2.0%). Nimbarka, founder of the related but distinct Dvaitadvaita school, refutes more often (13.2%). Srinivasa, writing a sub-commentary defending Nimbarka's school against later criticism, refutes opponents in 42.0% of his passages, by far the highest rate of any commentator measured, consistent with a school whose argumentative posture hardened as it had to defend itself on multiple fronts over time.

Within the Pali Canon itself, distinct collections show measurably different prose styles even without any cross-tradition comparison: the Dhammapada's verses average 31 characters per segment, the most aphoristic and compressed text in the collection, while Samyutta Nikaya and Udana prose segments average around 70-74 characters, consistent with their more discursive, doctrinally elaborated style.

A caveat worth stating plainly: words-per-sentence is not meaningful for several commentators and for the Pali Canon collections generally, since much of this text is captured as short segments without standard sentence-ending punctuation. We report this honestly via a `%NoPunct` diagnostic column in the script's output rather than silently showing a misleading number; treat any words-per-sentence figure with high %NoPunct as unreliable.

## Embeddings vs LLM tagging: two methods measuring different things

A natural question once you have both an LLM-tagged graph and a passage corpus is whether a model-free method agrees with the LLM's findings. We tried this with `embedding_disagreement_finder.py`: group commentary passages by school using literal concept-name matching, embed them locally, and measure cosine distance between each school's centroid per concept.

| Concept | Avg. cross-school distance | Schools compared | Reliable sample size? |
|---|---|---|---|
| moksha | 0.363 | 7 | Mixed, some pairs thin |
| jiva | 0.313 | 3 | No, 3 schools only, small samples |
| maya | 0.289 | 7 | Mixed |
| dharma | 0.277 | 8 | Mostly yes |
| atman | 0.250 | 5 | No, samples range 1 to 47 passages |
| karma | 0.162 | 7 | Mostly yes |
| brahman | 0.153 | 6 | Yes, samples range 19 to 1,173 passages |

The result is genuinely interesting, but not in the way we expected. Atman's ranking is unreliable, since the literal word "atman" appears far less often than equivalent phrasing like "the Self" or "soul," leaving some schools with single-digit sample sizes. Brahman's ranking, by contrast, rests on a solid sample (1,173 passages for Advaita alone, hundreds for other schools), and yet brahman shows the lowest embedding distance of any concept tested, despite being the single most contested concept in the LLM-tagged graph (570 contested pairs found, atman-brahman the most frequent).

We think this is a real finding rather than a failure of the method: schools can discuss the same concept in similar topical register, vocabulary, and sentence structure while asserting opposite metaphysical claims about it. An embedding model trained for topical and stylistic similarity has no particular reason to separate "X is identical to Y" from "X is distinct from Y" if both sentences otherwise read as typical philosophical prose about the same subject. This is a useful caution against treating off-the-shelf sentence embeddings as a proxy for philosophical agreement: semantic similarity of discussion is not the same thing as propositional agreement.

Full per-school passage counts are reproducible via `python embedding_disagreement_finder.py --concept X`. Disentangling topical similarity from propositional agreement, perhaps via a model fine-tuned or prompted to embed claims rather than passages, is a meaningful direction for future work.

## Insights from running the analysis scripts

These are results from the stylometric and embedding scripts included in this repository, run on the corpus as released. Numbers are flagged where the underlying sample is thin or where sentence-level statistics are unreliable, rather than presented uniformly.

### Citation versus refutation: two different ways to make an argument

Across the eight commentators with enough data for a meaningful comparison, scriptural citation density and explicit refutation rate are moderately negatively correlated (Pearson r approximately -0.32 across all eight, -0.46 restricted to the four commentators with the cleanest sentence-level data: Shankara, Prabhupada, Srinivasa, and Pujyapada). Commentators who lean heavily on quoting scripture as proof tend to spend less time explicitly naming and refuting opponents, and vice versa. Madhva sits at one extreme (17.1% scripture citation, 2.0% refutation), Srinivasa at the other (0.7% citation, 42.0% refutation). With only eight data points this is suggestive rather than statistically conclusive, but it points at something real: there appear to be at least two distinct argumentative postures available within the same broad tradition, prove your point by accumulating textual authority, or prove your point by dismantling the alternative.

### A school's argumentative posture can harden across generations

Madhva (13th century, founder of Dvaita), Nimbarka (founder of the related Dvaitadvaita school), and Srinivasa (a later sub-commentator defending Dvaitadvaita) show a striking generational trend in refutation rate: 2.0%, 13.2%, and 42.0% respectively. This is consistent with a school's argumentative posture shifting over time from confidently citing scripture to extensively defending itself against rival schools, though we have not verified this against independent historical scholarship and present it as a pattern worth a specialist's attention rather than a settled claim.

### The least and most polemical commentators in the corpus

Restricting to the four commentators with the most reliable sentence-level data, Prabhupada (0.3% refutation rate) and Pujyapada (1.1%) are by far the least likely to explicitly name and refute an opposing view, while Srinivasa (42.0%) is the most. Shankara sits in between (7.2%). This is a small, reliable sample rather than a comprehensive ranking, since most other commentators in the corpus have too little continuous prose with standard punctuation for the sentence-level statistics to be trustworthy (see the `%NoPunct` diagnostic in the script's output).

### The Pali Canon has its own internal genre structure

Without any comparison to Hindu or Jain material at all, the six Pali Canon collections tagged in this corpus show real differences in passage length: the Dhammapada averages 31 characters per segment, the most compressed and aphoristic text in the set, while Samyutta Nikaya and Udana average 70-74 characters, consistent with their more discursive, doctrinally elaborated style. Sentence-level statistics (words per sentence) are not meaningful for any Pali Canon collection in this corpus, since 89-100% of segments lack standard sentence-ending punctuation by construction (they are typically single clauses or stock phrases rather than full paragraphs).

### What we could not yet test

Jainism's two major sub-traditions, Digambara and Shvetambara, are not separately distinguishable in the current corpus: the Tattvartha Sutra is tagged only under Pujyapada's Digambara commentary, with no Shvetambara commentator currently represented in the tagged data, even though Shvetambara acceptance of the text is mentioned in the dataset's documentation. A within-Advaita stylistic comparison (Shankara versus the corpus's other four nominally Advaita commentators: Sridhara, Anandagiri, Nilakantha, Dhanpati) is also not currently possible at the embedding level, since only Shankara's passages carry a populated `school` field in the tagged commentary data; the others are present in the corpus but not yet attributable to a specific school in a way the analysis scripts can use.

## Future work

Beyond fixing the gaps noted above, this corpus and pipeline support a substantial range of further work we have not attempted:

- A formal, randomly sampled, multi-annotator precision evaluation of the LLM-tagged concept graph, which currently rests on informal spot-checking rather than a reported metric.
- Tracing how the meaning of a single concept (such as maya) shifts across the roughly thirteen centuries separating Shankara from Prabhupada, using each commentator's known era as an additional axis alongside school.
- Cross-tradition concept bridging: quantifying how much functional overlap exists between concepts traditionally treated as opposites or unrelated across traditions, such as Buddhist anatta and Vedantic atman, or dukkha and the Hindu and Jain treatments of bondage and suffering.
- Reconstructing implied historical debates by pairing each commentator's explicit refutation passages with the specific rival-school passage most likely being refuted, surfacing arguments that were never written as direct dialogue but functioned as one.
- A school-conditioned dialogue or question-answering system that draws only on a specific commentator's extracted concept relationships as its grounding, rather than general language model knowledge, to test whether a model can argue consistently from a specific historical position rather than merely describing it.
- Transitive reasoning over the concept graph: given two directly asserted relationships, checking whether any third passage explicitly confirms or contradicts the logically implied relationship between concepts that were never directly compared by the original commentator.
- A larger, more linguistically validated stylometric feature set, extending beyond the simple regular-expression and sentence-length statistics used here to syntactic complexity measures and a learned, rather than hand-specified, citation and refutation classifier.
- Resolving the Jainism Digambara and Shvetambara tagging gap and the within-Advaita school-attribution gap noted above, both of which are data completeness issues rather than fundamental limitations of the approach.

Several additional analyses are enabled by the existing corpus, graph, and scripts without requiring new data collection, but were not completed in this release:

- School-distinctiveness ranking via embedding centroid divergence across a wider concept list than atman/brahman alone
- A formal stylometry-based school classifier (logistic regression or random forest on citation/refutation/length features), pending a larger set of reliably-punctuated commentators than currently available
- Within-Advaita stylistic comparison once Sridhara, Anandagiri, Nilakantha, and Dhanpati receive verified school attribution in the source data (see known gaps above); we deliberately avoided assigning this label ourselves without source verification
- Century-stratified stylistic drift analysis, pending resolution of disputed dates for Nimbarka and Srinivasa
- Graph relation-type profiles and concept centrality (degree, PageRank) computed per school over the existing edge set
- Cross-file duplicate-ID auditing as a general data-hygiene check beyond the within-file fix already applied
- An ablation comparing extraction quality across LLMs of different scale on a small fixed verse sample

We would welcome contributions on any of these, or on directions we have not anticipated; the corpus and all analysis code are released specifically to make this kind of follow-on work possible.

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
