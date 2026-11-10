---
name: paper-to-report
description: Primary entry point for reading any scientific PDF/paper, extracting formulas/tables, and verifying claims with zero hallucination. Powered by MinerU (`pdf-craft` dual-column layout, LaTeX equations, and `[doc:<id>/page:<p>/block:<b>]` locators) and HuixiangDou (`reject_throttle` evidence gate) via the native `sci_research` tool (`action="read"` and `action="ask"`).
---

# High-Fidelity Paper Reading & Anti-Hallucination Verification (`paper-to-report`)

Use this skill whenever reading local or remote scientific PDFs, extracting equations/tables without layout corruption, or answering technical questions against a paper corpus. **Prefer calling the native `sci_research` tool directly**:

```json
{
  "action": "read",
  "target": "path/to/paper.pdf",
  "pages": "1-10",
  "outDir": "work/<slug>/corpus"
}
```

```json
{
  "action": "ask",
  "query": "<scientific claim or question to verify>",
  "corpusDir": "work/<slug>/corpus",
  "threshold": 0.25
}
```

## 1. Stage 1 — High-Fidelity Parsing & Incremental Locator Reading (`MinerU`)

`crux-sci-research read` uses the **MinerU Cloud API** (`MINERU_API_KEY`, with `enable_table=True, enable_formula=True`) to preserve dual-column academic layouts, cross-page tables, and LaTeX mathematical/chemical formulas, and automatically falls back to local `PyMuPDF` (`fitz`) / `pypdf` extraction when offline.

### Parse a PDF (or Markdown) into Locator-Addressed Blocks
Instead of dumping a 40-page PDF into the context window at once, parse by `--pages` or filter by `--section` and persist to a local corpus directory (`--out`):

```bash
# Parse pages 1-10 and save structured locator Markdown into work/<slug>/corpus/
crux-sci-research read "/path/to/paper.pdf" \
  --pages "1-10" \
  --out work/<slug>/corpus

# Filter only blocks matching a specific section or technical concept
crux-sci-research read "/path/to/paper.pdf" \
  --pages "1-15" \
  --section "Transition State" \
  --out work/<slug>/corpus
```

Every returned paragraph is tagged with a stable **MinerU Locator**:
`[doc:<doc_slug>/page:<page_no>/block:<block_no>]`

Use these exact locators when quoting equations, experimental parameters, or table entries.

---

## 2. Stage 2 — Two-Stage Filtering & Rejection Gate (`HuixiangDou` / 茴香豆)

Traditional RAG systems force an answer from top-k chunks even when the corpus does not contain valid evidence. `crux-sci-research ask` implements **HuixiangDou's two-stage retrieval + `reject_throttle` gate**:
1. **Stage 1 (BM25 + Lexical/Entity Specificity Reranking)**: Scores all locator blocks in `--corpus` (including parsed `.md` papers and `knowledge_flow.json` from `crux-sci-research search`).
2. **Stage 2 (`reject_throttle` Gate)**:
   - **`PASS` (`max_score >= threshold`)**: Returns the verified evidence blocks with `[doc:.../page:.../block:...]` locators.
   - **`REJECT` (`max_score < threshold`)**: Explicitly returns `REJECT (BELOW_REJECT_THROTTLE)` and suggests a follow-up `crux-sci-research search` command.

```bash
# Verify a scientific question or hypothesis against the local parsed corpus
crux-sci-research ask "<scientific question or claim>" \
  --corpus work/<slug>/corpus \
  --threshold 0.25 \
  --top-k 5
```

---

## 3. Synthesis Contract (Zero Hallucination)

When generating a technical report, table, or review from parsed papers:
1. **Mandatory Citation Binding**: Every quantitative claim, equation, or methodological comparison must cite its `[doc:<slug>/page:<p>/block:<b>]` locator or verified `DOI` / `doc_id`.
2. **Respect `REJECT` Decisions**: If `crux-sci-research ask` returns `REJECT`, either run `crux-sci-research search "<missing topic>" --mode flow` to acquire the missing primary literature or explicitly state `[INSUFFICIENT_EVIDENCE]` in the report — never fabricate citations or parameters.
