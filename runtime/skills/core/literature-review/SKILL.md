---
name: literature-review
description: Primary entry point for all scientific literature search, topic surveys, and state-of-the-art reviews. Powered by MindSearch (DAG sub-question decomposition), FlowSearch (Dynamic Knowledge Flow + gap audit), and multi-source connectors (`sciverse`, `openalex`, `arxiv`, `crossref`, `atlas`) via the native `sci_research` tool (`action="search"`).
---

# Deep Literature Review & Knowledge Flow Search (`literature-review`)

Use this skill whenever the user asks for a literature review, recent advances, paper search, or scientific claim verification. **Prefer calling the native `sci_research` tool directly** so parameters are validated automatically:

```json
{
  "action": "search",
  "query": "<scientific research topic>",
  "mode": "flow",
  "sources": "sciverse,openalex,arxiv,crossref,atlas",
  "limit": 6,
  "outDir": "work/<slug>/literature"
}
```

## 1. Capabilities & Search Channels

Run `crux-sci-research doctor` to inspect active channels and API keys:

```bash
crux-sci-research doctor
```

| Channel (`--sources`) | Coverage | API Key Requirement |
| :--- | :--- | :--- |
| `sciverse` | Peer-reviewed semantic RAG chunks & full-text sections | Uses `SCIVERSE_API_TOKEN` (pre-configured in `.env`) |
| `openalex` | 250M+ scholarly works, citation counts, reconstructed abstracts | **Free / No key required** (`OPENALEX_EMAIL` optional) |
| `arxiv` | Physics, CS, math, q-bio, and computational chemistry preprints | **Free / No key required** |
| `crossref` | 150M+ verified DOIs and publication metadata | **Free / No key required** (`CROSSREF_EMAIL` optional) |
| `atlas` | Intern-Atlas causal method evolution subgraphs & frontier gaps | **Free / No key required** (`INTERN_ATLAS_BASE_URL`) |
| `ddg` / `web` | General web search (Tavily / Serper when key present, else DuckDuckGo) | **Free (`ddg`)** or `TAVILY_API_KEY` / `SERPER_API_KEY` |

---

## 2. Three Search Modes (`fast` | `dag` | `flow`)

### Mode A: Fast Single-Node Multi-Source Retrieval (`--mode fast`)
Use for quick fact-checking, locating a specific paper/DOI, or verifying a baseline metric:

```bash
crux-sci-research search "<scientific query>" \
  --mode fast \
  --sources sciverse,openalex,arxiv,crossref \
  --limit 5
```

### Mode B: MindSearch Topological DAG Search (`--mode dag`)
Decomposes a complex scientific question into a directed acyclic graph (DAG) of sub-questions (`n1_foundations`, `n2_methods`, `n3_limitations`), dispatches parallel multi-source searchers per node, deduplicates by normalized DOI/title, and ranks evidence by two-step lexical + entity specificity:

```bash
crux-sci-research search "<complex research topic>" \
  --mode dag \
  --sources sciverse,openalex,arxiv,crossref,atlas \
  --limit 5 \
  --out work/<slug>/literature
```

### Mode C: FlowSearch Dynamic Knowledge Flow + Coordinator Loop (`--mode flow`)
Executes Round 1 DAG retrieval, runs the **Coordinator Completeness Audit** on under-covered nodes, spawns targeted Round 2 follow-up queries (`--max-iter`), and persists both `knowledge_flow.json` and `search_report.md`:

```bash
crux-sci-research search "<long-horizon research topic>" \
  --mode flow \
  --max-iter 2 \
  --sources sciverse,openalex,arxiv,crossref,atlas,ddg \
  --limit 6 \
  --out work/<slug>/literature
```

---

## 3. Two-Step "Triage -> Read -> Verify" Discipline

Never cite a paper from memory or from a title alone:
1. **Step 1 (Search & Triage)**: Run `crux-sci-research search ... --out work/<slug>/literature` to collect deduplicated candidate papers (`[ref_1]`, `[ref_2]`, ...) with verified DOIs/`doc_id`s and relevance scores.
2. **Step 2 (High-Fidelity Read)**: For top-ranked PDFs or full-text documents, invoke `crux-sci-research read` (see skill `paper-to-report`) to parse equations, tables, and methods sections into `work/<slug>/literature/corpus/`.
3. **Step 3 (Anti-Hallucination Gate)**: Before synthesizing claims into a report or hypothesis, run `crux-sci-research ask "<claim>" --corpus work/<slug>/literature` to enforce the HuixiangDou `reject_throttle` evidence gate.
