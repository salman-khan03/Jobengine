"""Opt-in TF-IDF cosine-similarity ranking — a second, complementary signal
next to match.py's keyword overlap.

Deliberately *not* branded "semantic AI matching": it's TF-IDF + cosine
similarity, a transparent classical-IR technique, not a neural embedding.
Calling it more than that would be exactly the kind of inflated claim
metrics_audit.py exists to catch — so this module is honest about what it is
in its own docstring and in the CLI output.

What it adds over plain keyword overlap: a keyword either matches or it
doesn't ("kubernetes" != "container orchestration"), and jd_keywords() has no
notion of *how rare/discriminative* a word is ("engineer" and "graphql" get
equal weight if both appear once). TF-IDF fixes the second problem for free —
common words across all your projects contribute less than words unique to
one — and cosine similarity gives a normalized 0..1 score instead of an
unbounded keyword-hit count. It's still bag-of-words: no synonyms, no word
order, no real "meaning". Use --semantic in tailor.py to see it alongside the
keyword ranking, not as a silent replacement for it.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z][a-z0-9+#.]{1,}")

# Same stopword rationale as match.py — words with no discriminative value.
_STOP = {
    "the", "and", "for", "with", "you", "our", "are", "will", "this", "that",
    "have", "has", "your", "who", "can", "not", "all", "any", "but", "into",
    "from", "their", "they", "them", "his", "her", "its", "was", "were",
    "been", "being", "more", "most", "other", "some", "such", "than", "then",
    "also", "each", "may", "must", "should", "would", "could", "about",
    "job", "role", "team", "work", "working", "candidate", "candidates",
    "experience", "years", "ability", "skills", "including", "required",
    "preferred", "qualifications", "responsibilities", "requirements",
    "opportunity", "position", "company", "employees", "benefits", "per",
    "etc", "well", "strong", "join", "help", "new", "using", "use",
}


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]


def _tf(tokens: list[str]) -> Counter:
    """Raw term frequency, not normalized — cosine similarity normalizes for
    document length on its own, so a second normalization pass here would be
    redundant."""
    return Counter(tokens)


def _idf(docs: list[list[str]]) -> dict[str, float]:
    """Inverse document frequency across the corpus (JD + every resume item).

    Smoothed (+1 in numerator and denominator) so a term appearing in every
    document still gets a small positive weight instead of log(1) == 0.
    """
    n = len(docs)
    df: Counter = Counter()
    for doc in docs:
        df.update(set(doc))
    return {term: math.log((1 + n) / (1 + count)) + 1.0 for term, count in df.items()}


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = _tf(tokens)
    return {term: freq * idf.get(term, 0.0) for term, freq in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _item_text(item: dict) -> str:
    parts = [item.get("name", ""), " ".join(item.get("stack", []))]
    parts.extend(item.get("bullets", []))
    return " ".join(parts)


def rank_projects_semantic(
    resume: dict, title: str, category: str, jd_text: str = ""
) -> list[tuple[dict, float]]:
    """Projects ranked by TF-IDF cosine similarity to the target role.

    Returns (project, score) pairs, score in [0, 1], most similar first.
    Falls back gracefully to all-zero scores (stable original order) when
    there's too little text to build a meaningful vocabulary — e.g. no JD
    pasted and a bare-bones title.
    """
    projects = resume.get("projects", [])
    query_text = f"{title} {category} {jd_text}"
    query_tokens = _tokenize(query_text)
    item_token_lists = [_tokenize(_item_text(p)) for p in projects]

    idf = _idf([query_tokens, *item_token_lists])
    query_vec = _tfidf_vector(query_tokens, idf)

    scored = [
        (p, _cosine(query_vec, _tfidf_vector(toks, idf)))
        for p, toks in zip(projects, item_token_lists)
    ]
    scored.sort(key=lambda pair: -pair[1])
    return scored
