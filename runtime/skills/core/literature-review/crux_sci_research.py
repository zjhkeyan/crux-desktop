#!/usr/bin/env python3
"""crux-sci-research: Lightweight unified Scientific Search (MindSearch + FlowSearch + Lagent)
and High-Fidelity Reading / Anti-Hallucination Verification (MinerU + HuixiangDou) CLI.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

DEFAULT_ENV_PATHS = (
    Path.cwd() / ".env",
    Path("/root/scientific_agents_collection/.env"),
)


def load_env_files(extra_env: str | Path | None = None) -> dict[str, str]:
    """Load credentials from .env files without overwriting existing environment variables."""
    loaded: dict[str, str] = {}
    paths = ([Path(extra_env)] if extra_env else []) + list(DEFAULT_ENV_PATHS)
    for path in paths:
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip().removeprefix("export ")
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw_val = line.partition("=")
            key = key.strip()
            if not key:
                continue
            try:
                val = " ".join(shlex.split(raw_val, comments=True))
            except ValueError:
                val = raw_val.split("#", 1)[0].strip().strip("\"'")
            loaded[key] = val
            os.environ.setdefault(key, val)
    return loaded


def slugify(text: str, max_len: int = 40) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len].rstrip("-")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{clean or 'doc'}-{digest}"


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


# ---------------------------------------------------------------------------
# 1. Multi-Source Search Connectors (Lagent + FlowSearch + Sciverse + Atlas)
# ---------------------------------------------------------------------------

def search_openalex(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Query OpenAlex (250M+ scholarly works, free, no API key required)."""
    params: dict[str, Any] = {"search": query, "per-page": max(1, min(limit, 25))}
    email = os.getenv("OPENALEX_EMAIL", "")
    if email:
        params["mailto"] = email
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        resp = client.get("https://api.openalex.org/works", params=params)
        resp.raise_for_status()
        results = resp.json().get("results", [])

    papers: list[dict[str, Any]] = []
    for item in results[:limit]:
        inv = item.get("abstract_inverted_index") or {}
        words_by_pos: dict[int, str] = {}
        if isinstance(inv, dict):
            for word, positions in inv.items():
                if isinstance(positions, list):
                    for pos in positions:
                        if isinstance(pos, int):
                            words_by_pos[pos] = word
        abstract = " ".join(words_by_pos[k] for k in sorted(words_by_pos))
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in (item.get("authorships") or [])
            if isinstance(a, dict) and a.get("author", {}).get("display_name")
        ]
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "")
        oa_id = (item.get("id") or "").rsplit("/", 1)[-1]
        papers.append(
            {
                "doc_id": f"openalex:{oa_id}" if oa_id else doi,
                "title": item.get("title") or item.get("display_name") or "",
                "authors": authors[:8],
                "year": item.get("publication_year"),
                "doi": doi,
                "url": doi_raw or item.get("id") or "",
                "citations": item.get("cited_by_count", 0),
                "chunk": abstract[:1500],
                "source": "openalex",
            }
        )
    return papers


def search_arxiv(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Query arXiv Atom API (free, no API key required)."""
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max(1, min(limit, 20)),
    }
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        resp = client.get("https://export.arxiv.org/api/query", params=params)
        resp.raise_for_status()
        xml_text = resp.text

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text)
    papers: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns)[:limit]:
        raw_id = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id
        title = re.sub(r"\s+", " ", entry.findtext("atom:title", default="", namespaces=ns)).strip()
        summary = re.sub(r"\s+", " ", entry.findtext("atom:summary", default="", namespaces=ns)).strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "")[:4]
        authors = [
            (a.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for a in entry.findall("atom:author", ns)
        ]
        pdf_url = raw_id.replace("/abs/", "/pdf/") if "/abs/" in raw_id else raw_id
        papers.append(
            {
                "doc_id": f"arxiv:{arxiv_id}",
                "title": title,
                "authors": [a for a in authors if a][:8],
                "year": int(published) if published.isdigit() else None,
                "doi": f"10.48550/arXiv.{arxiv_id.split('v')[0]}" if arxiv_id else "",
                "url": raw_id,
                "pdf_url": pdf_url,
                "chunk": summary[:1500],
                "source": "arxiv",
            }
        )
    return papers


def search_crossref(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Query CrossRef DOI registry (150M+ records, free, no API key required)."""
    params: dict[str, Any] = {"query": query, "rows": max(1, min(limit, 20))}
    email = os.getenv("CROSSREF_EMAIL", "")
    if email:
        params["mailto"] = email
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        resp = client.get("https://api.crossref.org/works", params=params)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])

    papers: list[dict[str, Any]] = []
    for item in items[:limit]:
        titles = item.get("title") or []
        title = titles[0] if titles else ""
        doi = item.get("DOI") or ""
        authors = [
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in (item.get("author") or [])
            if isinstance(a, dict)
        ]
        year = None
        for date_key in ("published-print", "published-online", "created"):
            parts = (item.get(date_key) or {}).get("date-parts") or []
            if parts and parts[0]:
                year = parts[0][0]
                break
        abstract = re.sub(r"<[^>]+>", " ", item.get("abstract") or "").strip()
        papers.append(
            {
                "doc_id": f"doi:{doi}" if doi else normalize_title(title)[:24],
                "title": title,
                "authors": [a for a in authors if a][:8],
                "year": year,
                "doi": doi,
                "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                "citations": item.get("is-referenced-by-count", 0),
                "chunk": abstract[:1500],
                "source": "crossref",
            }
        )
    return papers


def search_atlas(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Query Intern-Atlas causal method evolution graph (free, no API key required)."""
    base_url = os.getenv("INTERN_ATLAS_BASE_URL", "https://intern-atlas.opendatalab.org.cn").rstrip("/")
    with httpx.Client(base_url=base_url, timeout=20.0, follow_redirects=True) as client:
        resp = client.post("/api/search", json={"query": query, "limit": limit})
        resp.raise_for_status()
        raw_papers = resp.json().get("papers", [])
    papers: list[dict[str, Any]] = []
    for item in raw_papers[:limit]:
        if not isinstance(item, dict):
            continue
        pid = item.get("doc_id") or item.get("paper_id") or item.get("id") or ""
        papers.append(
            {
                "doc_id": f"atlas:{pid}" if pid else "",
                "title": item.get("title") or "",
                "authors": item.get("authors") or [],
                "year": item.get("year"),
                "doi": item.get("doi") or "",
                "url": item.get("url") or "",
                "chunk": (item.get("abstract") or item.get("summary") or item.get("chunk") or "")[:1500],
                "source": "atlas",
            }
        )
    return papers


def search_sciverse(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Query Sciverse semantic RAG chunks when SCIVERSE_API_TOKEN & script are available."""
    token = os.getenv("SCIVERSE_API_TOKEN", "")
    script = Path("/root/.agents/skills/sciverse/scripts/semantic_search.mjs")
    if not token or not script.is_file():
        return []
    proc = subprocess.run(
        ["node", str(script), json.dumps({"query": query, "top_k": limit})],
        env={**os.environ, "SCIVERSE_API_TOKEN": token},
        capture_output=True,
        text=True,
        timeout=45,
        check=True,
    )
    payload: Any = json.loads(proc.stdout)
    while isinstance(payload, dict):
        payload = next(
            (payload[k] for k in ("data", "hits", "results", "papers", "items", "documents", "chunks") if k in payload),
            [],
        )
    papers: list[dict[str, Any]] = []
    for item in (payload or [])[:limit]:
        if not isinstance(item, dict):
            continue
        meta = {**item, **(item.get("metadata") or {}), **(item.get("paper") or {})}
        authors = meta.get("authors") or meta.get("author") or []
        if isinstance(authors, str):
            authors = [authors]
        chunk = item.get("chunk") or item.get("text") or item.get("content") or ""
        if isinstance(chunk, dict):
            chunk = chunk.get("text", "")
        doc_id = meta.get("doc_id") or ""
        papers.append(
            {
                "doc_id": f"sciverse:{doc_id}" if doc_id else "",
                "title": meta.get("title") or "",
                "authors": [a.get("name", "") if isinstance(a, dict) else str(a) for a in authors][:8],
                "year": meta.get("year") or meta.get("publication_published_year"),
                "doi": meta.get("doi") or "",
                "url": f"https://doi.org/{meta['doi']}" if meta.get("doi") else "",
                "chunk": str(chunk)[:1500],
                "score": item.get("score", 0.0),
                "source": "sciverse",
            }
        )
    return papers


def search_web_lagent(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Lagent-style Web Search: uses Tavily or Serper when API keys exist, else DuckDuckGo HTML."""
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    serper_key = os.getenv("SERPER_API_KEY", "")
    with httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
    ) as client:
        if tavily_key:
            resp = client.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": query, "max_results": limit},
            )
            resp.raise_for_status()
            return [
                {
                    "doc_id": f"web:{i+1}",
                    "title": r.get("title", ""),
                    "authors": [],
                    "year": None,
                    "doi": "",
                    "url": r.get("url", ""),
                    "chunk": (r.get("content") or "")[:1200],
                    "source": "tavily",
                }
                for i, r in enumerate(resp.json().get("results", [])[:limit])
            ]
        if serper_key:
            resp = client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key},
                json={"q": query, "num": limit},
            )
            resp.raise_for_status()
            return [
                {
                    "doc_id": f"web:{i+1}",
                    "title": r.get("title", ""),
                    "authors": [],
                    "year": None,
                    "doi": "",
                    "url": r.get("link", ""),
                    "chunk": (r.get("snippet") or "")[:1200],
                    "source": "serper",
                }
                for i, r in enumerate(resp.json().get("organic", [])[:limit])
            ]
        resp = client.post("https://html.duckduckgo.com/html/", data={"q": query})
        resp.raise_for_status()
        body = resp.text

    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.S,
    )
    hits: list[dict[str, Any]] = []
    for idx, match in enumerate(pattern.finditer(body)):
        if len(hits) >= limit:
            break
        raw_url, raw_title, raw_snippet = match.groups()
        title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
        snippet = html.unescape(re.sub(r"<[^>]+>", "", raw_snippet)).strip()
        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
        url = parsed_qs.get("uddg", [raw_url])[0]
        hits.append(
            {
                "doc_id": f"ddg:{idx+1}",
                "title": title,
                "authors": [],
                "year": None,
                "doi": "",
                "url": url,
                "chunk": snippet[:1200],
                "source": "ddg",
            }
        )
    return hits


SOURCE_DISPATCH = {
    "openalex": search_openalex,
    "arxiv": search_arxiv,
    "crossref": search_crossref,
    "atlas": search_atlas,
    "sciverse": search_sciverse,
    "ddg": search_web_lagent,
    "web": search_web_lagent,
}


# ---------------------------------------------------------------------------
# 2. MindSearch DAG Planner + FlowSearch Dynamic Knowledge Flow Coordinator
# ---------------------------------------------------------------------------

def decompose_query_dag(query: str, mode: str = "dag") -> list[dict[str, Any]]:
    """Decompose a complex scientific topic into a MindSearch-style topological DAG of sub-questions."""
    clean = query.strip()
    if mode == "fast":
        return [{"id": "root", "aspect": "core_query", "query": clean, "depends_on": []}]
    nodes = [
        {
            "id": "n1_foundations",
            "aspect": "mechanisms_and_foundations",
            "query": f"{clean} mechanism theoretical formulation",
            "depends_on": [],
        },
        {
            "id": "n2_methods",
            "aspect": "algorithms_and_methods",
            "query": f"{clean} state of the art algorithm benchmark",
            "depends_on": ["n1_foundations"],
        },
        {
            "id": "n3_limitations",
            "aspect": "open_problems_and_frontiers",
            "query": f"{clean} limitations failure modes open challenges",
            "depends_on": ["n1_foundations", "n2_methods"],
        },
    ]
    return nodes


def tokenize_terms(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]{3,}|[\u4e00-\u9fff]{2,}", (text or "").lower())
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
        "have", "has", "had", "into", "over", "under", "between", "through", "using",
        "study", "paper", "method", "methods", "results", "based", "analysis",
        "how", "what", "when", "where", "which", "who", "why", "can", "does", "did",
        "will", "would", "should", "could", "about", "without", "within", "their",
        "there", "these", "those", "such", "than", "then", "also", "more", "most",
        "some", "any", "each", "other", "both", "after", "before", "during", "while",
    }
    return [t for t in tokens if t not in stop]


def score_relevance(query: str, text: str, title: str = "") -> float:
    """Two-stage lexical + technical entity specificity score in [0.0, 1.0]."""
    q_terms = tokenize_terms(query)
    if not q_terms:
        return 0.0
    doc_terms = tokenize_terms(f"{title} {title} {text}")
    if not doc_terms:
        return 0.0
    doc_set = set(doc_terms)
    q_unique = list(dict.fromkeys(q_terms))
    matched = [
        t
        for t in q_unique
        if t in doc_set
        or (len(t) >= 5 and any(len(d) >= 5 and t[:5] == d[:5] for d in doc_set))
    ]
    coverage = len(matched) / len(q_unique)

    # Bigram / phrase bonus
    q_norm = " ".join(q_terms)
    d_norm = " ".join(doc_terms)
    bigrams = [f"{q_terms[i]} {q_terms[i+1]}" for i in range(len(q_terms) - 1)]
    bigram_hits = sum(1 for bg in bigrams if bg in d_norm)
    phrase_bonus = 0.25 * (bigram_hits / len(bigrams)) if bigrams else 0.0

    # Title hit bonus
    title_terms = set(tokenize_terms(title))
    title_hits = sum(1 for t in q_unique if t in title_terms)
    title_bonus = 0.20 * (title_hits / len(q_unique))

    return round(min(1.0, 0.65 * coverage + phrase_bonus + title_bonus), 4)


def run_multi_source_search(
    query: str,
    sources: list[str],
    limit_per_source: int = 4,
    mode: str = "dag",
    max_iter: int = 2,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute MindSearch DAG parallel retrieval + FlowSearch Coordinator gap-checking loop."""
    load_env_files()
    valid_sources = [s.strip().lower() for s in sources if s.strip().lower() in SOURCE_DISPATCH]
    if not valid_sources:
        valid_sources = ["openalex", "arxiv", "crossref"]

    dag_nodes = decompose_query_dag(query, mode=mode)
    seen_keys: set[str] = set()
    all_papers: list[dict[str, Any]] = []
    node_summaries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    def fetch_one(src: str, sub_q: str) -> tuple[str, list[dict[str, Any]], str | None]:
        try:
            return src, SOURCE_DISPATCH[src](sub_q, limit_per_source), None
        except Exception as exc:
            return src, [], f"{type(exc).__name__}: {exc}"

    rounds = max(1, max_iter if mode == "flow" else 1)
    for round_idx in range(1, rounds + 1):
        tasks: list[tuple[dict[str, Any], str]] = [
            (node, src) for node in dag_nodes for src in valid_sources
        ]
        node_hits: dict[str, list[dict[str, Any]]] = {n["id"]: [] for n in dag_nodes}
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(tasks)))) as pool:
            fut_map = {
                pool.submit(fetch_one, src, node["query"]): (node, src)
                for node, src in tasks
            }
            for fut in as_completed(fut_map):
                node, src = fut_map[fut]
                _, items, err = fut.result()
                if err:
                    errors.append({"node": node["id"], "source": src, "error": err})
                    continue
                for item in items:
                    title_key = normalize_title(item.get("title", ""))
                    doi_key = (item.get("doi") or "").lower().strip()
                    dedup_key = doi_key or title_key
                    if not dedup_key:
                        continue
                    rel = score_relevance(query, item.get("chunk", ""), item.get("title", ""))
                    item["relevance"] = rel
                    item["node_id"] = node["id"]
                    node_hits[node["id"]].append(item)
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        all_papers.append(item)

        for node in dag_nodes:
            hits = sorted(node_hits.get(node["id"], []), key=lambda x: x.get("relevance", 0.0), reverse=True)
            node_summaries.append(
                {
                    "round": round_idx,
                    "node_id": node["id"],
                    "aspect": node["aspect"],
                    "query": node["query"],
                    "hit_count": len(hits),
                    "top_relevance": hits[0]["relevance"] if hits else 0.0,
                    "selected_refs": [h.get("doc_id") for h in hits[:3]],
                }
            )

        # FlowSearch Coordinator Audit: identify under-covered nodes & spawn targeted follow-up
        if mode == "flow" and round_idx < rounds:
            weak_nodes = [n for n in node_summaries if n["round"] == round_idx and n["hit_count"] < 2]
            if not weak_nodes:
                break
            dag_nodes = [
                {
                    "id": f"r{round_idx+1}_followup_{i+1}",
                    "aspect": "coordinator_gap_fill",
                    "query": f"{query} review survey quantitative benchmark",
                    "depends_on": [w["node_id"] for w in weak_nodes],
                }
                for i, _ in enumerate(weak_nodes[:2])
            ]

    all_papers.sort(
        key=lambda p: (p.get("relevance", 0.0), p.get("citations") or 0, p.get("year") or 0),
        reverse=True,
    )
    for idx, paper in enumerate(all_papers, start=1):
        paper["ref_id"] = f"ref_{idx}"

    result = {
        "query": query,
        "mode": mode,
        "sources": valid_sources,
        "total_unique_papers": len(all_papers),
        "dag_nodes": node_summaries,
        "papers": all_papers,
        "warnings": errors[:5],
    }

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "knowledge_flow.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "search_report.md").write_text(
            format_search_markdown(result), encoding="utf-8"
        )
        verification = build_verification_report(all_papers, reject_throttle=0.25)
        (out_dir / "verification_report.json").write_text(
            json.dumps(verification, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return result


def build_verification_report(
    items: list[dict[str, Any]],
    reject_throttle: float = 0.25,
) -> dict[str, Any]:
    """Build a Stage 23 `verification_report.json` payload for the visual VerificationView."""
    results: list[dict[str, Any]] = []
    verified = suspicious = hallucinated = skipped = 0
    for idx, item in enumerate(items, start=1):
        doi = (item.get("doi") or "").strip()
        arxiv_id = (item.get("arxiv_id") or "").strip()
        src = (item.get("source") or "corpus").strip().lower()
        year = item.get("year")
        explicit_verified = item.get("verified")
        raw_rel = item.get("score") or item.get("relevance") or item.get("relevance_score")
        if raw_rel is not None:
            rel = float(raw_rel)
        elif explicit_verified is False:
            rel = 0.1
        elif explicit_verified is True or doi or arxiv_id:
            rel = 0.92
        else:
            rel = 0.0
        if explicit_verified is False or (isinstance(year, int) and year > 2026):
            rel = min(rel, 0.12)
        method = "doi" if doi else ("arxiv_id" if (src == "arxiv" or arxiv_id) else "title_search")
        if rel >= max(0.5, reject_throttle):
            status = "verified"
            verified += 1
        elif rel >= reject_throttle:
            status = "suspicious"
            suspicious += 1
        else:
            status = "hallucinated"
            hallucinated += 1
        results.append(
            {
                "cite_key": item.get("ref_id") or item.get("locator") or item.get("doc_id") or f"ref_{idx}",
                "title": item.get("title") or "Untitled",
                "status": status,
                "confidence": round(min(1.0, max(0.3, rel + (0.2 if doi else 0.0))), 2),
                "method": method,
                "details": (item.get("text") or item.get("chunk") or "")[:280] or None,
                "relevance_score": round(rel, 4),
                "matched_paper": {
                    "title": item.get("title") or "Untitled",
                    "authors": item.get("authors") or [],
                    "year": item.get("year"),
                    "source": src,
                },
            }
        )
    total = len(results)
    integrity = round((verified + 0.5 * suspicious) / total, 4) if total > 0 else None
    return {
        "summary": {
            "total": total,
            "verified": verified,
            "suspicious": suspicious,
            "hallucinated": hallucinated,
            "skipped": skipped,
            "integrity_score": integrity,
        },
        "results": results,
    }


def format_search_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Deep Literature & Knowledge Flow Report: `{result['query']}`",
        "",
        f"- **Mode**: `{result['mode']}` | **Sources**: `{', '.join(result['sources'])}` | **Unique Verified Works**: `{result['total_unique_papers']}`",
        "",
        "## 1. MindSearch / FlowSearch Topological Sub-Question Nodes",
        "",
        "| Round | Node ID | Aspect | Sub-Query | Hits | Top Relevance | Selected Refs |",
        "| :---: | :--- | :--- | :--- | :---: | :---: | :--- |",
    ]
    for n in result.get("dag_nodes", []):
        refs = ", ".join(f"`{r}`" for r in (n.get("selected_refs") or []) if r) or "-"
        lines.append(
            f"| {n['round']} | `{n['node_id']}` | {n['aspect']} | {n['query']} | {n['hit_count']} | {n['top_relevance']:.2f} | {refs} |"
        )
    lines.extend(["", "## 2. Ranked Evidence & Citation Table", ""])
    for p in result.get("papers", [])[:20]:
        authors = ", ".join((p.get("authors") or [])[:4]) or "Unknown"
        year = p.get("year") or "n.d."
        doi = p.get("doi") or "-"
        lines.append(
            f"### [{p['ref_id']}] {p.get('title') or 'Untitled'} ({year})"
        )
        lines.append(
            f"- **ID**: `{p.get('doc_id')}` | **Source**: `{p.get('source')}` | **DOI**: `{doi}` | **Authors**: {authors} | **Relevance**: `{p.get('relevance', 0.0):.2f}`"
        )
        if p.get("url"):
            lines.append(f"- **URL**: {p['url']}")
        if p.get("chunk"):
            lines.append(f"- **Evidence Snippet**: {p['chunk'][:500]}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. MinerU High-Fidelity Reader + Stable Page/Section Locators
# ---------------------------------------------------------------------------

def parse_page_range(spec: str, total_pages: int) -> list[int]:
    """Return 1-based page numbers matching a range spec like '1-5,8'."""
    selected: list[int] = []
    for part in (spec or "1-10").split(","):
        part = part.strip()
        if not part:
            continue
        first_s, sep, last_s = part.partition("-")
        start = max(1, int(first_s))
        end = min(total_pages, int(last_s) if sep and last_s else start)
        selected.extend(range(start, end + 1))
    return sorted(set(p for p in selected if 1 <= p <= total_pages))


def _mineru_remote_parse(source: str | Path, page_range: str = "1-10", language: str = "en") -> dict[str, Any]:
    """Call MinerU Cloud API (https://mineru.net) when MINERU_API_KEY is configured."""
    api_key = os.getenv("MINERU_API_KEY", "")
    base_url = os.getenv("MINERU_BASE_URL", "https://mineru.net").rstrip("/")
    if not api_key:
        raise RuntimeError("MINERU_API_KEY not set")
    is_url = str(source).startswith(("http://", "https://"))
    headers = {"Authorization": f"Bearer {api_key}"}
    payload: dict[str, Any] = {
        "language": language,
        "page_range": page_range,
        "enable_table": True,
        "is_ocr": False,
        "enable_formula": True,
    }
    payload["url" if is_url else "file_name"] = str(source) if is_url else Path(source).name
    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        endpoint = f"{base_url}/api/v1/agent/parse/{'url' if is_url else 'file'}"
        resp = client.post(endpoint, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json().get("data") or resp.json()
        task_id = data["task_id"]
        if not is_url:
            put_resp = client.put(data["file_url"], content=Path(source).read_bytes())
            put_resp.raise_for_status()
        for _ in range(25):
            poll_resp = client.get(f"{base_url}/api/v1/agent/parse/{task_id}", headers=headers)
            poll_resp.raise_for_status()
            state_data = poll_resp.json().get("data") or poll_resp.json()
            state = state_data.get("state")
            if state == "done":
                md_resp = client.get(state_data["markdown_url"])
                md_resp.raise_for_status()
                return {
                    "engine": "mineru-cloud",
                    "task_id": task_id,
                    "markdown": md_resp.text,
                }
            if state in {"failed", "error"}:
                raise RuntimeError(f"MinerU task {task_id} failed: {state_data}")
            time.sleep(1.5)
    raise TimeoutError("MinerU cloud task timed out")


def _local_pdf_parse(pdf_path: Path, page_range: str = "1-10") -> dict[str, Any]:
    """Local PDF fallback preserving page boundaries and equations/tables text."""
    pages_text: list[str] = []
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        try:
            import fitz  # type: ignore
        except ImportError:
            fitz = None

    if fitz is not None:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                pages_text.append(page.get_text("text") or "")
    else:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(pdf_path))
        pages_text = [p.extract_text() or "" for p in reader.pages]

    total = len(pages_text)
    selected_nums = parse_page_range(page_range, total) if total > 0 else []
    blocks: list[str] = []
    for pno in selected_nums:
        blocks.append(f"<!-- page:{pno} -->\n## Page {pno}\n\n{pages_text[pno - 1].strip()}")
    return {
        "engine": "local-pymupdf",
        "total_pages": total,
        "selected_pages": selected_nums,
        "markdown": "\n\n".join(blocks),
    }


def read_scientific_document(
    source: str | Path,
    page_range: str = "1-10",
    section_filter: str | None = None,
    out_dir: Path | None = None,
    prefer_local: bool = False,
) -> dict[str, Any]:
    """Parse and chunk a scientific document into MinerU-style locators (doc:<id>/page:<p>/block:<b>)."""
    load_env_files()
    src_str = str(source)
    doc_slug = slugify(Path(src_str).stem if not src_str.startswith("http") else src_str)

    if not src_str.startswith(("http://", "https://")) and Path(src_str).is_file() and Path(src_str).suffix.lower() in {".md", ".txt"}:
        markdown = Path(src_str).read_text(encoding="utf-8", errors="ignore")
        meta = {"engine": "direct-markdown", "total_pages": 1, "selected_pages": [1]}
    else:
        is_url = src_str.startswith(("http://", "https://"))
        if not is_url and not Path(src_str).is_file():
            raise FileNotFoundError(f"Document not found: {src_str}")
        if not prefer_local and os.getenv("MINERU_API_KEY"):
            try:
                meta = _mineru_remote_parse(src_str, page_range=page_range)
                markdown = meta.pop("markdown")
            except Exception:
                if is_url:
                    raise
                meta = _local_pdf_parse(Path(src_str), page_range=page_range)
                markdown = meta.pop("markdown")
        else:
            if is_url:
                raise RuntimeError("Remote PDF URL requires MINERU_API_KEY or local download first")
            meta = _local_pdf_parse(Path(src_str), page_range=page_range)
            markdown = meta.pop("markdown")

    # Build MinerU-style block locators: doc:<slug>/page:<p>/block:<b>
    blocks: list[dict[str, Any]] = []
    current_page = 1
    raw_paras = [p.strip() for p in re.split(r"\n{2,}", markdown) if p.strip()]
    block_idx = 0
    for para in raw_paras:
        page_match = re.search(r"<!--\s*page:(\d+)\s*-->", para)
        if page_match:
            current_page = int(page_match.group(1))
            para = re.sub(r"<!--\s*page:\d+\s*-->", "", para).strip()
            if not para:
                continue
        block_idx += 1
        locator = f"doc:{doc_slug}/page:{current_page}/block:{block_idx}"
        blocks.append(
            {
                "locator": locator,
                "doc_id": doc_slug,
                "page": current_page,
                "block": block_idx,
                "text": para,
            }
        )

    if section_filter:
        q_lower = section_filter.lower()
        filtered_blocks = [
            b for b in blocks if q_lower in b["text"].lower() or score_relevance(section_filter, b["text"]) > 0.2
        ]
    else:
        filtered_blocks = blocks

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        md_out = out_dir / f"{doc_slug}.md"
        formatted_md = "\n\n".join(f"<!-- {b['locator']} -->\n{b['text']}" for b in blocks)
        md_out.write_text(formatted_md, encoding="utf-8")

    return {
        "doc_id": doc_slug,
        "source": src_str,
        "engine": meta.get("engine", "unknown"),
        "page_range": page_range,
        "total_blocks": len(blocks),
        "returned_blocks": len(filtered_blocks),
        "blocks": filtered_blocks,
        "markdown": "\n\n".join(f"[{b['locator']}]\n{b['text']}" for b in filtered_blocks),
    }


# ---------------------------------------------------------------------------
# 4. HuixiangDou Two-Stage Feature Filtering & Rejection Gate (reject_throttle)
# ---------------------------------------------------------------------------

def load_corpus_blocks(corpus_path: Path) -> list[dict[str, Any]]:
    """Load markdown/text documents from a corpus file or directory into locator-addressed blocks."""
    files = [corpus_path] if corpus_path.is_file() else sorted(
        p for p in corpus_path.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt", ".json"}
    )
    all_blocks: list[dict[str, Any]] = []
    for fpath in files:
        if fpath.name == "knowledge_flow.json":
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                for idx, p in enumerate(data.get("papers", []), start=1):
                    text = f"{p.get('title', '')}. {p.get('chunk', '')}".strip()
                    if text:
                        all_blocks.append(
                            {
                                "locator": f"doc:{p.get('doc_id') or f'paper-{idx}'}/ref:{p.get('ref_id', idx)}",
                                "source_file": str(fpath),
                                "title": p.get("title", ""),
                                "text": text,
                            }
                        )
            except Exception:
                continue
            continue
        raw = fpath.read_text(encoding="utf-8", errors="ignore")
        doc_slug = fpath.stem
        paras = [p.strip() for p in re.split(r"\n{2,}", raw) if len(p.strip()) >= 20]
        for idx, para in enumerate(paras, start=1):
            loc_match = re.search(r"<!--\s*(doc:[^\s>]+)\s*-->", para)
            locator = loc_match.group(1) if loc_match else f"doc:{doc_slug}/block:{idx}"
            clean_para = re.sub(r"<!--.*?-->", "", para).strip()
            if clean_para:
                all_blocks.append(
                    {
                        "locator": locator,
                        "source_file": str(fpath),
                        "title": doc_slug,
                        "text": clean_para,
                    }
                )
    return all_blocks


def huixiangdou_verify_and_retrieve(
    question: str,
    corpus_path: Path,
    reject_throttle: float = 0.25,
    top_k: int = 5,
) -> dict[str, Any]:
    """HuixiangDou 2-stage retrieval (BM25 + specificity reranking) with reject_throttle gate."""
    blocks = load_corpus_blocks(corpus_path)
    if not blocks:
        return {
            "question": question,
            "status": "REJECT",
            "reason": "EMPTY_CORPUS",
            "max_score": 0.0,
            "reject_throttle": reject_throttle,
            "evidence": [],
            "suggested_action": f'crux-sci-research search "{question}" --mode flow',
        }

    q_terms = tokenize_terms(question)
    if not q_terms:
        return {
            "question": question,
            "status": "REJECT",
            "reason": "INVALID_QUERY",
            "max_score": 0.0,
            "reject_throttle": reject_throttle,
            "evidence": [],
        }

    # Stage 1: BM25 inverse-document-frequency weighting across corpus blocks
    n_docs = len(blocks)
    doc_tokens = [tokenize_terms(f"{b['title']} {b['text']}") for b in blocks]
    avgdl = sum(len(dt) for dt in doc_tokens) / max(1, n_docs)
    df: dict[str, int] = {}
    for dt in doc_tokens:
        for tok in set(dt):
            df[tok] = df.get(tok, 0) + 1

    k1, b_param = 1.5, 0.75
    raw_bm25: list[float] = []
    for dt in doc_tokens:
        tf_map: dict[str, int] = {}
        for tok in dt:
            tf_map[tok] = tf_map.get(tok, 0) + 1
        dl = len(dt)
        score = 0.0
        for qt in set(q_terms):
            if qt not in tf_map:
                continue
            idf = math.log(1.0 + (n_docs - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5))
            tf = tf_map[qt]
            score += idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b_param + b_param * dl / max(1.0, avgdl)))
        raw_bm25.append(score)

    max_bm25 = max(raw_bm25) if raw_bm25 else 0.0

    # Stage 2: Calibrated specificity + phrase + entity overlap reranking
    scored_blocks: list[dict[str, Any]] = []
    for block, bm25_val in zip(blocks, raw_bm25):
        norm_bm25 = (bm25_val / max_bm25) if max_bm25 > 0 else 0.0
        sem_score = score_relevance(question, block["text"], block["title"])
        # Calibrated score: requires actual lexical/semantic overlap (sem_score) so a single rare word doesn't false-pass
        combined = round(0.65 * sem_score + 0.35 * norm_bm25 * min(1.0, sem_score * 2.5), 4)
        if combined > 0:
            scored_blocks.append({**block, "score": combined, "semantic_score": sem_score, "bm25": round(bm25_val, 3)})

    scored_blocks.sort(key=lambda x: x["score"], reverse=True)
    top_hits = scored_blocks[:top_k]
    best_score = top_hits[0]["score"] if top_hits else 0.0

    report = build_verification_report(top_hits, reject_throttle=reject_throttle)
    if best_score < reject_throttle:
        return {
            "question": question,
            "status": "REJECT",
            "reason": "BELOW_REJECT_THROTTLE",
            "max_score": best_score,
            "reject_throttle": reject_throttle,
            "evidence": top_hits[:2],
            "verification_report": report,
            "suggested_action": f'crux-sci-research search "{question}" --mode flow',
        }

    return {
        "question": question,
        "status": "PASS",
        "reason": "VERIFIED_HIGH_CONFIDENCE_EVIDENCE",
        "max_score": best_score,
        "reject_throttle": reject_throttle,
        "evidence": top_hits,
        "verification_report": report,
    }


def doctor_status() -> dict[str, Any]:
    load_env_files()
    keys = {
        "TOKENPLAN_API_KEY": bool(os.getenv("TOKENPLAN_API_KEY") or os.getenv("OPENAI_API_KEY")),
        "SCIVERSE_API_TOKEN": bool(os.getenv("SCIVERSE_API_TOKEN")),
        "MINERU_API_KEY": bool(os.getenv("MINERU_API_KEY")),
        "SCP_HUB_API_KEY": bool(os.getenv("SCP_HUB_API_KEY")),
        "TAVILY_API_KEY": bool(os.getenv("TAVILY_API_KEY")),
        "SERPER_API_KEY": bool(os.getenv("SERPER_API_KEY")),
    }
    free_channels = ["openalex", "arxiv", "crossref", "atlas", "ddg"]
    active_channels = free_channels + (["sciverse"] if keys["SCIVERSE_API_TOKEN"] else [])
    return {
        "ok": True,
        "configured_api_keys": keys,
        "active_search_channels": active_channels,
        "mineru_mode": "cloud+local_fallback" if keys["MINERU_API_KEY"] else "local_pymupdf_only",
        "huixiangdou_gate": "ready (two-stage BM25 + specificity reranker + reject_throttle)",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crux-sci-research",
        description="Unified Scientific Deep Search (MindSearch + FlowSearch) & High-Fidelity Reader / Verifier (MinerU + HuixiangDou).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doc = sub.add_parser("doctor", help="Check configured API keys and active search/read channels")
    p_doc.add_argument("--json", action="store_true", help="Output JSON")

    p_search = sub.add_parser("search", help="Run multi-source academic + web search (fast / MindSearch DAG / FlowSearch)")
    p_search.add_argument("query", help="Research question or topic")
    p_search.add_argument("--mode", choices=["fast", "dag", "flow"], default="dag", help="Search depth mode")
    p_search.add_argument(
        "--sources",
        default="openalex,arxiv,crossref,atlas,sciverse",
        help="Comma-separated sources (openalex,arxiv,crossref,atlas,sciverse,ddg)",
    )
    p_search.add_argument("--limit", type=int, default=4, help="Max results per source per node")
    p_search.add_argument("--max-iter", type=int, default=2, help="Max FlowSearch coordinator iterations")
    p_search.add_argument("--out", type=Path, default=None, help="Output directory for knowledge_flow.json and search_report.md")
    p_search.add_argument("--json", action="store_true", help="Emit JSON output")

    p_read = sub.add_parser("read", help="Parse PDF / URL / Markdown with MinerU + local fallback into locator blocks")
    p_read.add_argument("source", help="Path or URL to PDF/Markdown document")
    p_read.add_argument("--pages", default="1-10", help="1-based page range, e.g. '1-5' or '1-3,7'")
    p_read.add_argument("--section", default=None, help="Filter blocks matching a section/topic keyword")
    p_read.add_argument("--out", type=Path, default=None, help="Directory to persist parsed Markdown corpus")
    p_read.add_argument("--local", action="store_true", help="Force local PyMuPDF parsing without MinerU cloud API")
    p_read.add_argument("--json", action="store_true", help="Emit JSON output")

    p_ask = sub.add_parser("ask", help="HuixiangDou two-stage evidence retrieval with reject_throttle anti-hallucination gate")
    p_ask.add_argument("question", help="Scientific question or claim to verify against corpus")
    p_ask.add_argument("--corpus", type=Path, required=True, help="Corpus directory or file (parsed Markdown / knowledge_flow.json)")
    p_ask.add_argument("--threshold", type=float, default=0.25, help="Rejection threshold in [0, 1] (default: 0.25)")
    p_ask.add_argument("--top-k", type=int, default=5, help="Max evidence blocks to return")
    p_ask.add_argument("--json", action="store_true", help="Emit JSON output")

    args = parser.parse_args(argv)

    if args.cmd == "doctor":
        info = doctor_status()
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "search":
        res = run_multi_source_search(
            query=args.query,
            sources=args.sources.split(","),
            limit_per_source=args.limit,
            mode=args.mode,
            max_iter=args.max_iter,
            out_dir=args.out,
        )
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(format_search_markdown(res))
        return 0

    if args.cmd == "read":
        res = read_scientific_document(
            source=args.source,
            page_range=args.pages,
            section_filter=args.section,
            out_dir=args.out,
            prefer_local=args.local,
        )
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"# Parsed Document `{res['doc_id']}` (Engine: `{res['engine']}`, Blocks: `{res['returned_blocks']}/{res['total_blocks']}`)\n")
            print(res["markdown"])
        return 0

    if args.cmd == "ask":
        res = huixiangdou_verify_and_retrieve(
            question=args.question,
            corpus_path=args.corpus,
            reject_throttle=args.threshold,
            top_k=args.top_k,
        )
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"## HuixiangDou Evidence Gate: `{res['status']}` (Max Score: `{res['max_score']:.3f}`, Threshold: `{res['reject_throttle']:.3f}`)")
            if res["status"] == "REJECT":
                print(f"- **Reason**: `{res['reason']}` — Insufficient grounding in local corpus. Refusing to hallucinate.")
                if res.get("suggested_action"):
                    print(f"- **Suggested Follow-up**: `{res['suggested_action']}`")
            else:
                for hit in res["evidence"]:
                    print(f"\n### [{hit['locator']}] (Score: `{hit['score']:.3f}`)")
                    print(hit["text"][:600])
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
