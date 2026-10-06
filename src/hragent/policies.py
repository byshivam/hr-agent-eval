"""Keyword search over the HR policy documents.

Policies are short and well-structured, so plain lexical scoring per section is enough
and keeps the project dependency-free. Every section carries an ID such as [LV-04] that
the agent is asked to cite.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SECTION_RE = re.compile(r"^## \[([A-Z]{2}-\d{2})\] (.+)$", re.M)
STOPWORDS = set(
    "a an and are as at be by can do does for from how i in is it its my me of on or the to what when "
    "which who will with you your this that there their any much many".split()
)


@dataclass(frozen=True)
class PolicySection:
    section_id: str
    title: str
    text: str
    source: str


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words if w not in STOPWORDS]


@lru_cache(maxsize=4)
def load_sections(policies_dir: Path) -> tuple[PolicySection, ...]:
    sections: list[PolicySection] = []
    for path in sorted(policies_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        matches = list(SECTION_RE.finditer(text))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.end():end].strip()
            sections.append(PolicySection(m.group(1), m.group(2).strip(), body, path.name))
    return tuple(sections)


def search(policies_dir: Path, query: str, top_k: int = 3) -> list[dict]:
    sections = load_sections(policies_dir)
    docs = [_tokens(s.title + " " + s.title + " " + s.text) for s in sections]
    n = len(docs)
    df = Counter(t for d in docs for t in set(d))
    q = _tokens(query)
    scored = []
    for section, doc in zip(sections, docs):
        tf = Counter(doc)
        score = sum((1 + math.log(tf[t])) * math.log(1 + n / df[t]) for t in q if tf[t])
        if score > 0:
            scored.append((score, section))
    scored.sort(key=lambda x: -x[0])
    return [
        {"section_id": s.section_id, "title": s.title, "text": s.text, "source": s.source}
        for _, s in scored[:top_k]
    ]
