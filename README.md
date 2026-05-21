# Kenya Legal AI — Knowledge Graph & Fine-Tuning Pipeline

A full-stack AI/ML system that ingests Kenyan statutory law and case law into a **Neo4j knowledge graph**, grounds every statute in the **Constitution of Kenya 2010**, and fine-tunes a **Mistral-7B** language model on the resulting graph using QLoRA.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Knowledge Graph Ontology](#knowledge-graph-ontology)
4. [Document Inventory](#document-inventory)
5. [Graph Statistics](#graph-statistics)
6. [Project Structure](#project-structure)
7. [Setup & Prerequisites](#setup--prerequisites)
8. [Pipeline Walkthrough](#pipeline-walkthrough)
9. [Case Law Scraper](#case-law-scraper)
10. [GraphRAG Retrieval](#graphrag-retrieval)
11. [QLoRA Fine-Tuning](#qlora-fine-tuning)
12. [Neo4j Instance](#neo4j-instance)
13. [Known Parsing Notes](#known-parsing-notes)
14. [Constitutional Basis Mapping](#constitutional-basis-mapping)

---

## Overview

Kenya Legal AI builds a constitutionally-anchored knowledge graph from Kenyan statutory documents. The core principle is that **every Act derives its legal authority from the Constitution of Kenya 2010** — this derivation is explicitly encoded as a graph relationship (`DERIVES_AUTHORITY_FROM`) so that any query or retrieval result can be traced back to its constitutional foundation.

The pipeline covers three layers:

```
Constitution → Acts & Sections → Case Law
      ↓               ↓               ↓
  Articles         Penalties       Judgments
  Chapters          Parts          Citations
   Rights          Schedules        Courts
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DOCUMENT LAYER                           │
│  19 Kenyan Acts (Markdown) + Constitution of Kenya 2010     │
└──────────────────────────┬──────────────────────────────────┘
                           │ MarkdownIngester
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  NEO4J KNOWLEDGE GRAPH                      │
│  Aura Free  |  neo4j+s://4830d4c5.databases.neo4j.io        │
│                                                             │
│  Nodes: 4,862  |  Relationships: 8,417                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌─────────────────────┐    ┌────────────────────────┐
│   GraphRAGRetriever  │    │   QA Pair Generator    │
│  (Cypher traversal) │    │  (CELL 15, 700 pairs)  │
└─────────────────────┘    └────────────┬───────────┘
                                        │
                                        ▼
                           ┌────────────────────────┐
                           │   QLoRA Fine-Tuning     │
                           │  Mistral-7B-Instruct    │
                           │  Unsloth + TRL on Colab │
                           └────────────────────────┘
```

---

## Knowledge Graph Ontology

### Node Types

| Node | Description |
|------|-------------|
| `Constitution` | Root node — Constitution of Kenya 2010 |
| `Chapter` | 18 chapters of the Constitution |
| `Article` | 264 constitutional articles |
| `Clause` | Sub-clauses within articles |
| `Right` | Fundamental rights (Chapter 4, Articles 26–51) |
| `Act` | Statutory legislation |
| `Part` | Parts within an Act |
| `Section` | Individual sections of an Act |
| `Schedule` | Schedules appended to Acts |
| `Penalty` | Penalty provisions extracted from sections |
| `Institution` | Regulatory bodies established by Acts |
| `Case` | Court judgments from kenyalaw.org |
| `Court` | Courts of record |
| `LegalConcept` | Cross-cutting legal doctrines (e.g. Rule of Law, Transfer Pricing) |

### Relationship Types

| Relationship | Meaning |
|-------------|---------|
| `PART_OF` | Hierarchical containment (Section→Part→Act, Article→Chapter→Constitution) |
| `DERIVES_AUTHORITY_FROM` | Act → Article — constitutional basis of legislation |
| `GUARANTEES` | Article → Right (Bill of Rights) |
| `EMBODIED_IN` | LegalConcept → Article — constitutional grounding of doctrine |
| `GOVERNS` | LegalConcept → Act — concept applies within this Act |
| `CITES` | Case → Article / Act / Section |
| `DECIDED_BY` | Case → Court |
| `IMPOSES` | Section → Penalty |
| `ESTABLISHED_BY` | Institution → Act |

### Authority Chain

Every section can be traced to the Constitution:

```
Section -[:PART_OF]-> Part -[:PART_OF]-> Act
    -[:DERIVES_AUTHORITY_FROM]-> Article
        -[:PART_OF]-> Chapter
            -[:PART_OF]-> Constitution
```

---

## Document Inventory

### Constitution
| Document | Size |
|----------|------|
| Constitution of Kenya 2010 | 9,308 lines |

### Original 10 Acts
| Act | Cap | File |
|-----|-----|------|
| Income Tax Act (Finance Act 2025) | Cap. 470 | `Income Tax Act (Updated as per Finance Act 2025).md` |
| Value Added Tax Act | Cap. 476 | `VAT Act (Cap. 476) Revised May 2024.md` |
| Companies Act | — | `The_Companies_Act.md` |
| Capital Markets Act | Cap. 485A | `CapitalMarketsAct_Cap485A-Dyiw_m_K.md` |
| Employment Act 2007 | — | `The_Employment_Act_2007.md` |
| Insurance Act | — | `Insurance Act.md` |
| Land Act 2012 | — | `LandAct2012.md` |
| Physical and Land Use Planning Act | — | `Physical and Land Use Planning Act.md` |
| Data Protection Act | — | `Data-Protection-Act-1.md` |

### New Acts (added May 2026)
| Act | Cap | File |
|-----|-----|------|
| Coffee Act | Cap. 485A | `Coffee Act.md` |
| Conflict of Interest Act | Cap. 185B | `Conflict of Interest Act.md` |
| County Licensing (Uniform Procedures) Act | Cap. 265 | `County Licensing (Uniform Procedures) Act.md` |
| Gambling Control Act | Cap. 131 | `Gambling Control Act.md` |
| Government Owned Enterprises Act | Cap. 486 | `Government Owned Enterprises Act.md` |
| Judges Retirement Benefits Act | Cap. 197 | `Judges Retirement Benefits Act.md` |
| Meteorology Act | Cap. 475 | `Meteorology Act.md` |
| Persons with Disabilities Act | Cap. 133 | `Persons with Disabilities Act.md` |
| Privatization Act | Cap. 485B | `Privatization Act.md` |
| Social Work Professionals Act | — | `Social Work Professionals Act.md` |

---

## Graph Statistics

> As of May 2026

| Node Type | Count |
|-----------|------:|
| Constitution | 1 |
| Chapters | 18 |
| Articles | 264 |
| Clauses | 949 |
| Rights | 26 |
| Acts | 19 |
| Parts | 204 |
| Sections | 1,903 |
| Schedules | 25 |
| Penalties | 327 |
| Institutions | 7 |
| Cases | 997 |
| Courts | 5 |
| LegalConcepts | 28 |
| **Total Nodes** | **~4,862** |

| Relationship | Count |
|-------------|------:|
| PART_OF | 5,904 |
| DERIVES_AUTHORITY_FROM | 59 |
| GUARANTEES | 26 |
| EMBODIED_IN | 55 |
| GOVERNS | 56 |
| CITES | 988 |
| DECIDED_BY | 997 |
| IMPOSES | 327 |
| ESTABLISHED_BY | 5 |
| **Total Edges** | **~8,417** |

---

## Project Structure

```
legal agent/
│
├── Kenya_Legal_AI_Knowledge_Graph_Builder.ipynb   # Main notebook (54 cells)
│
├── TheConstitutionOfKenya.md                      # Constitution (body at line 620)
├── Income Tax Act (Updated as per Finance Act 2025).md
├── VAT Act (Cap. 476) Revised May 2024.md
├── The_Companies_Act.md
├── CapitalMarketsAct_Cap485A-Dyiw_m_K.md
├── The_Employment_Act_2007.md
├── Insurance Act.md
├── LandAct2012.md
├── Physical and Land Use Planning Act.md
├── Data-Protection-Act-1.md
│
├── Coffee Act.md                                  # New Acts (May 2026)
├── Conflict of Interest Act.md
├── County Licensing (Uniform Procedures) Act.md
├── Gambling Control Act.md
├── Government Owned Enterprises Act.md
├── Judges Retirement Benefits Act.md
├── Meteorology Act.md
├── Persons with Disabilities Act.md
├── Privatization Act.md
├── Social Work Professionals Act.md
│
├── Neo4j-4830d4c5-Created-2026-05-12 (1).txt     # Neo4j Aura credentials
└── README.md
```

### Notebook Cell Map

| Cell Range | Purpose |
|-----------|---------|
| 1–5 | Setup: dependencies, credentials, ontology constants, schema constraints, constitutional backbone |
| 6–7 | Markdown headers |
| 8–10 | MarkdownIngester class, KGWriter class, constitutional backbone seed |
| 11 | Extended KGWriter (Parts, Sections, Schedules, Institutions) |
| 12–13 | Cell headers |
| 14–16 | Extended schema constraints, Income Tax Act ingestion |
| 17–22 | Batch ingestion: VAT, Companies, Capital Markets, Employment, Insurance, Land, Physical Planning, Data Protection |
| 23 | Seed 7 institutions (KRA, IRA, CMA, NLC, ODPC, CBK, NEMA) |
| 24–25 | New Act ingestion (10 Acts, May 2026) |
| 26–29 | KG statistics dashboard, authority chain validation |
| 30–36 | Case law scraper (KenyaLawScraper, continuation loop) |
| 37–38 | Institutions seed, core legal concepts |
| 39–40 | GraphRAGRetriever class |
| 41–42 | QA training pair generator |
| 43–54 | QLoRA fine-tuning pipeline (Mistral-7B via Unsloth) |

---

## Setup & Prerequisites

### Local / Colab environment

```bash
pip install neo4j requests beautifulsoup4 lxml tqdm
```

### For QLoRA training (Google Colab T4/A100)

```bash
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install --no-deps trl peft accelerate bitsandbytes
pip install cloudscraper   # for case law scraping
```

### Neo4j credentials

Copy from `Neo4j-4830d4c5-Created-2026-05-12 (1).txt` or set environment variables:

```python
NEO4J_URI      = "neo4j+s://4830d4c5.databases.neo4j.io"
NEO4J_USERNAME = "neo4j"
NEO4J_DATABASE = "neo4j"
```

---

## Pipeline Walkthrough

### 1. Schema setup (CELL 5 + extended constraints)

Creates uniqueness constraints and full-text indexes for all node types before any ingestion.

### 2. Constitution ingestion (CELL 8)

```python
articles = ingester.parse_constitution_md("/content/TheConstitutionOfKenya.md")
writer.write_articles(articles)
```

- Skips the TOC (lines 1–619)
- Detects second `**CHAPTER ONE**` as body start (line 620)
- Truncates body before `FIRST SCHEDULE` to prevent county/schedule numbers overwriting article nodes
- Extracts 264 articles, 949 clauses, 26 rights

### 3. Act ingestion

Each Act follows the same pattern:

```python
writer.write_act(act_id, title, cap, year, constitutional_basis_articles)
parsed = ingester.parse_act_md(filepath, act_id, title)
writer.write_parts(parsed["parts"])
writer.write_sections(parsed["sections"])
writer.write_schedules(parsed["schedules"])
```

**Three section detection patterns are used:**
- **Pattern A** — `**N.**` bold number (handles ~95% of Acts)
- **Pattern B** — `**N. Heading**` combined bold span (Data Protection Act style)
- **Pattern C** — `Heading N. text` with no bold (Employment Act style)

**Special character handling for PART separators:**
- `—` U+2014 em dash
- `–` U+2013 en dash
- `―` U+2015 horizontal bar (Employment Act)
- `─` U+2500 box drawings horizontal (Social Work Professionals Act)

### 4. Institutions (CELL 23)

Seven regulatory institutions are seeded with `ESTABLISHED_BY` edges to their founding Acts:

| Institution | Act | Constitutional Basis |
|-------------|-----|---------------------|
| Kenya Revenue Authority (KRA) | Income Tax Act | Art. 209 |
| Insurance Regulatory Authority (IRA) | Insurance Act | Art. 46 |
| Capital Markets Authority (CMA) | Capital Markets Act | Art. 46 |
| National Land Commission (NLC) | Land Act | Art. 67 |
| Office of Data Protection Commissioner (ODPC) | Data Protection Act | Art. 31 |
| Central Bank of Kenya (CBK) | — | Art. 231 |
| National Environment Management Authority (NEMA) | — | Art. 69 |

### 5. Legal Concepts (CELL 38)

28 cross-cutting legal concepts are connected via:
- `EMBODIED_IN` → constitutional Articles
- `GOVERNS` → relevant Acts

Domains covered: `constitutional`, `administrative`, `tax`, `corporate`, `land`, `employment`, `data_protection`.

---

## Case Law Scraper

Scrapes judgments from `new.kenyalaw.org` across five courts:

| Court Code | Court | Domain |
|-----------|-------|--------|
| KESC | Supreme Court of Kenya | Constitutional |
| KECA | Court of Appeal | Appellate |
| KEHC | High Court | Constitutional, Civil |
| KEELRC | Employment & Labour Relations Court | Labour |
| KEELC | Environment & Land Court | Land, Environment |

### Extracted per case
- Title, citation, case number, date, outcome, judges
- `CITES` edges to Articles (constitution references in judgment text)
- `CITES` edges to Acts (from cited-documents section)
- `CITES` edges to Sections (inline `Section N of the X Act` mentions)

### Anti-blocking
The scraper uses `cloudscraper` with a Chrome browser fingerprint to bypass Cloudflare/bot detection on kenyalaw.org:

```python
import cloudscraper
cs = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows"})
```

### Continuation scraping (idempotent)
Re-running the scraper is safe — it pulls existing URLs from Neo4j first and skips already-ingested cases:

```python
existing_urls = set(r["url"] for r in s.run("MATCH (c:Case) RETURN c.url").data())
```

---

## GraphRAG Retrieval

`GraphRAGRetriever` (CELL 14 / 40) traverses the graph to assemble context for a user query:

```
Query → keyword match on Sections/Articles
      → traverse PART_OF chain to Act and Constitution
      → collect DERIVES_AUTHORITY_FROM articles
      → find Cases that CITE the relevant nodes
      → return structured context string for LLM prompt
```

The retriever returns a grounded context block anchored to specific constitutional articles, making every LLM answer traceable to its legal source.

---

## QLoRA Fine-Tuning

Runs on **Google Colab T4 or A100** using Unsloth for 2–4× faster training.

### Model
- Base: `unsloth/mistral-7b-instruct-v0.3-bnb-4bit` (pre-quantized 4-bit)
- Adapter: LoRA rank 16, alpha 16
- Target modules: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`

### Training config

| Parameter | T4 | A100 |
|-----------|-----|------|
| Batch size | 2 | 4 |
| Grad accumulation | 4 | 4 |
| Epochs | 3 | 3 |
| Learning rate | 2e-4 | 2e-4 |
| LR scheduler | cosine | cosine |
| Optimizer | adamw_8bit | adamw_8bit |

### Dataset
- 700 QA pairs generated from the KG (CELL 15 / 42)
- Alpaca instruction format
- Pre-truncated to 2,048 tokens before training

### Known Unsloth compatibility fix
`SFTConfig.max_length` must be explicitly set to `None` after construction — Unsloth's `padding_free=True` mode raises `ValueError` if `max_length` is set and `packing=False`:

```python
training_args = SFTConfig(...)
training_args.max_length     = None   # must be patched post-construction
training_args.max_seq_length = None
```

---

## Neo4j Instance

| Property | Value |
|----------|-------|
| URI | `neo4j+s://4830d4c5.databases.neo4j.io` |
| Instance | Instance01 (Aura Free) |
| Database | `neo4j` |
| Node limit | 200,000 |
| Relationship limit | 400,000 |
| Current nodes | ~4,862 |
| Current relationships | ~8,417 |

---

## Known Parsing Notes

| Issue | Affected Act | Fix Applied |
|-------|-------------|-------------|
| Body start has no bold markers | Employment Act | Extended `ACT_BODY_RE` with non-bold patterns |
| Part separator is U+2015 `―` | Employment Act | Added to character class in `PART_ACT_RE` |
| Part separator is U+2500 `─` | Social Work Professionals Act | Added to character class in `PART_ACT_RE` |
| Sections use `**N. Heading**` combined bold | Data Protection Act | Pattern B added to `_extract_sections` |
| Sections use `Heading N. text` no bold | Employment Act | Pattern C added to `_extract_sections` |
| Constitution TOC shares text with body | Constitution | Second `**CHAPTER ONE**` used as body start |
| Schedule numbering overwrites articles | Constitution | Body truncated at `FIRST SCHEDULE` before parsing |

---

## Constitutional Basis Mapping

| Act | Constitutional Articles | Basis |
|-----|------------------------|-------|
| Income Tax Act | 201, 209, 210 | Public finance, taxation powers |
| VAT Act | 201, 209, 210 | Public finance, taxation powers |
| Companies Act | 46, 201 | Consumer rights, public finance |
| Capital Markets Act | 46, 201 | Consumer rights, public finance |
| Employment Act | 41, 43, 77 | Labour relations, economic rights |
| Insurance Act | 46, 201 | Consumer rights, public finance |
| Land Act | 60, 61, 62, 63, 68 | Land system, NLC mandate |
| Physical & Land Use Planning Act | 60, 61, 66 | Land use, planning |
| Data Protection Act | 31, 35 | Privacy, access to information |
| Coffee Act | 40, 43, 46, 209 | Property, economic rights, consumer, taxation |
| Conflict of Interest Act | 10, 73, 75, 232 | National values, leadership, public service |
| County Licensing Act | 174, 175, 186 | Devolution, county functions |
| Gambling Control Act | 43, 46, 209 | Economic rights, consumer, taxation |
| Government Owned Enterprises Act | 10, 201, 226, 232 | National values, public finance, audit |
| Judges Retirement Benefits Act | 160, 167, 230 | Judicial independence, tenure, remuneration |
| Meteorology Act | 10, 42, 69 | National values, clean environment |
| Persons with Disabilities Act | 27, 43, 54 | Equality, social rights, rights of PWDs |
| Privatization Act | 10, 40, 201 | National values, property, public finance |
| Social Work Professionals Act | 43, 46, 55, 232 | Economic rights, consumer, youth, public service |

---

## License

This project is for academic and research purposes. All Kenyan legal documents are sourced from the Kenya Law Reform Commission and Kenya Law Reports (kenyalaw.org) and remain subject to their respective terms of use.
