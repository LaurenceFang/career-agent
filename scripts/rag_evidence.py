#!/usr/bin/env python3
"""Retrieval layer for the career agent: BM25 evidence index over the master
profile, imported job snapshots and internship evidence documents.

Design notes
- Corpus units are "chunks": profile facts, job bullets/paragraphs, and
  markdown sections of evidence files. Each chunk carries a stable id, a
  source path and (where known) fact ids, so retrieval results stay
  provenance-traceable for the resume evidence gate.
- Stage 1 scoring is pure-Python Okapi BM25 (no new dependencies). A future
  --embed flag can swap in an HF embedding model behind the same interface.
- Read-only with respect to all inputs; the index is written under .scratch.

Usage:
    python rag_evidence.py index
    python rag_evidence.py search "autoregressive sequence models"
    python rag_evidence.py match-req cohere_ml_intern_winter2027
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = ROOT / ".scratch" / "rag_index"
INDEX_FILE = INDEX_DIR / "chunks.json"
K1, B = 1.5, 0.75

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-/][a-z0-9]+)*|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _iter_json(obj, path=""):
    """Yield (key_path, string_values) pairs from nested JSON."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_json(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_json(v, f"{path}[{i}]")
    elif isinstance(obj, str) and obj.strip():
        yield path, obj


def chunk_profile(profile_path: Path) -> list[dict]:
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    chunks: list[dict] = []
    for section in ("identity", "education", "projects", "experience", "leadership", "skills", "awards", "certificates", "availability"):
        value = data.get(section)
        items = value if isinstance(value, list) else [value] if value else []
        for item in items:
            fact_id = item.get("id") if isinstance(item, dict) else None
            for path, text in _iter_json(item):
                if fact_id and path.endswith("sha256"):
                    continue
                chunks.append({
                    "chunk_id": f"profile:{section}:{fact_id or path}:{len(chunks)}",
                    "kind": "profile_fact",
                    "fact_ids": [fact_id] if fact_id else [],
                    "source": str(profile_path),
                    "text": text.strip(),
                })
    return chunks


def chunk_job(job_md: Path) -> list[dict]:
    text = job_md.read_text(encoding="utf-8")
    body = text.split("---", 2)[-1]
    chunks = []
    parts = re.split(r"\n(?=\d+\.\s|[A-Z][^\n:]{2,70}:\n)", body)
    for i, part in enumerate(parts):
        part = part.strip()
        if len(part) > 40:
            chunks.append({
                "chunk_id": f"job:{job_md.parent.name}:{i}",
                "kind": "job_requirement",
                "fact_ids": [],
                "source": str(job_md),
                "text": part,
            })
    return chunks


def chunk_markdown(path: Path, limit: int = 8000) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return []
    chunks = []
    for i, section in enumerate(re.split(r"\n(?=#{1,3}\s)", text)):
        section = section.strip()
        if len(section) > 40:
            chunks.append({
                "chunk_id": f"doc:{path.name}:{i}",
                "kind": "evidence_doc",
                "fact_ids": [],
                "source": str(path),
                "text": section,
            })
    return chunks


def chunk_provenance(path: Path) -> list[dict]:
    """Resume provenance bullets: English claims already mapped to fact ids."""
    chunks = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return chunks
    for i, item in enumerate(data.get("bullets", [])):
        text = str(item.get("text", "")).strip()
        if len(text) < 40:
            continue
        chunks.append({
            "chunk_id": f"prov:{path.parent.name}:{path.stem}:{i}",
            "kind": "provenance_claim",
            "fact_ids": [f for f in item.get("fact_ids", []) if isinstance(f, str)],
            "source": str(path),
            "text": text,
        })
    return chunks


EVIDENCE_DOCS = [
            ]


def build_index() -> list[dict]:
    chunks: list[dict] = []
    chunks += chunk_profile(ROOT / "profile" / "master" / "profile.json")
    for job_md in (ROOT / "jobs" / "inbox").glob("*/job.md"):
        chunks += chunk_job(job_md)
    for prov in (ROOT / "resumes" / "generated").glob("*/hermes_provenance.json"):
        chunks += chunk_provenance(prov)
    for doc in EVIDENCE_DOCS:
        if doc.exists():
            chunks += chunk_markdown(doc)
    # dedupe near-identical tiny chunks
    seen = set()
    kept = []
    for c in chunks:
        key = c["text"][:120].lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(c)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(),
        "scorer": "okapi-bm25",
        "params": {"k1": K1, "b": B},
        "chunks": kept,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return kept


class BM25:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.docs = [tokenize(c["text"]) for c in chunks]
        self.tfs = [Counter(d) for d in self.docs]
        self.avgdl = sum(len(d) for d in self.docs) / max(1, len(self.docs))
        self.df: Counter = Counter()
        for d in self.docs:
            self.df.update(set(d))
        self.n = len(chunks)

    def score(self, query: str) -> list[tuple[float, int]]:
        q = set(tokenize(query))
        scores = []
        for i, tf in enumerate(self.tfs):
            s = 0.0
            dl = len(self.docs[i])
            for term in q:
                f = tf.get(term, 0)
                if not f:
                    continue
                df = self.df.get(term, 0)
                idf = math.log(1 + (self.n - df + 0.5) / (df + 0.5))
                s += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / max(1.0, self.avgdl)))
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        return scores


def load_index() -> tuple[dict, BM25]:
    if not INDEX_FILE.exists():
        build_index()
    data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return data, BM25(data["chunks"])


def search(query: str, top: int = 6, kind: str | None = None) -> list[dict]:
    data, bm = load_index()
    out = []
    for s, i in bm.score(query):
        c = dict(bm.chunks[i])
        c["score"] = round(s, 3)
        if kind and c["kind"] != kind:
            continue
        out.append(c)
        if len(out) >= top:
            break
    return out


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "index"
    if cmd == "index":
        chunks = build_index()
        print(f"indexed {len(chunks)} chunks -> {INDEX_FILE}")
    elif cmd == "search" and len(sys.argv) > 2:
        for c in search(" ".join(sys.argv[2:])):
            print(f"[{c['score']:>7}] {c['kind']:<16} {c['source']}\n    {c['text'][:220].replace(chr(10), ' ')}\n")
    elif cmd == "match-req" and len(sys.argv) > 2:
        job = sys.argv[2]
        data, _ = load_index()
        reqs = [c for c in data["chunks"] if c["kind"] == "job_requirement" and job in c["source"]]
        for r in reqs:
            hits = search(r["text"], top=40, kind=None)
            ev = [h for h in hits if h["kind"] in ("profile_fact", "evidence_doc", "provenance_claim")]
            print("=" * 6, r["text"][:100])
            for h in ev[:2]:
                print(f"   <- [{h['score']}] {h['source']}: {h['text'][:150].replace(chr(10), ' ')}")
            if not ev:
                print("   <- (no evidence retrieved)")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
