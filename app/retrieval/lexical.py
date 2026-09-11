"""BM25 over the chunk corpus.

This is the half of hybrid retrieval that dense embeddings are worst at. A recruiter
asks "¿sabe Go?", "¿ha usado pgvector?", "¿qué es un ISIN?" — short, exact,
low-frequency tokens. Embeddings map those into a neighbourhood of *related*
technologies, which is the wrong answer delivered confidently. Lexical matching
either finds the token or does not.

BM25 rather than plain overlap because term saturation and length normalisation
matter even at this corpus size: a chunk that lists thirty technologies should not
outrank a chunk that is *about* the one being asked for.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

# Spanish function words carry no retrieval signal and inflate short queries.
STOPWORDS = frozenset(
    """
    a al algo alguna algunas alguno algunos ante antes como con contra cual cuales cuando
    de del desde donde dos e el ella ellas ellos en entre era eres es esa esas ese eso esos
    esta estas este esto estos ha hace hacia han hasta hay la las le les lo los mas más me
    mi mis mucho muy no nos o os otra otras otro otros para pero poco por porque que qué
    quien quienes se sea ser si sí sin sobre solo son su sus también tanto te tiene tienen
    tu tus un una uno unos y ya
    the of and to in is a an for with on at by
    """.split()
)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#._\-]*")

# Tuned defaults; k1 controls term saturation, b controls length normalisation.
K1 = 1.2
B = 0.6


def normalize(text: str) -> str:
    """Lowercase and strip accents, so 'liquidación' matches 'liquidacion'."""
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def fold_plural(token: str) -> str:
    """Collapse simple Spanish/English plurals onto their singular.

    Without this, "ISIN" fails to match a corpus that says "ISINs" — a recruiter
    asking about an exact term gets nothing, which is the worst possible failure for
    the half of the system that exists to handle exact terms. Full stemming would be
    overkill and would start merging unrelated technology names; folding the plural
    covers nearly all of the real cases.

    Applied at index time and query time alike, so it can only ever make matching
    symmetric, never skewed.
    """
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Keep technology-shaped tokens intact: c++, .net, node-22, shadcn/ui splits fine."""
    return [
        fold_plural(t) for t in _TOKEN.findall(normalize(text)) if t not in STOPWORDS and len(t) > 1
    ]


@dataclass(frozen=True, slots=True)
class LexicalHit:
    chunk_id: str
    score: float


class BM25Index:
    def __init__(self, documents: dict[str, str]) -> None:
        self._ids: list[str] = list(documents)
        self._tokens: list[list[str]] = [tokenize(documents[i]) for i in self._ids]
        self._freqs: list[Counter[str]] = [Counter(t) for t in self._tokens]
        self._lengths: list[int] = [len(t) for t in self._tokens]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

        document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            document_frequency.update(set(tokens))
        total = len(self._ids)
        # Standard BM25 idf with the +1 smoothing that keeps it non-negative.
        self._idf = {
            term: math.log(1 + (total - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    def search(self, query: str, top_k: int) -> list[LexicalHit]:
        terms = tokenize(query)
        if not terms or not self._ids:
            return []
        scored: list[LexicalHit] = []
        for index, chunk_id in enumerate(self._ids):
            freqs = self._freqs[index]
            length = self._lengths[index] or 1
            score = 0.0
            for term in terms:
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                idf = self._idf.get(term, 0.0)
                denominator = tf + K1 * (1 - B + B * length / (self._avg_length or 1))
                score += idf * (tf * (K1 + 1)) / denominator
            if score > 0:
                scored.append(LexicalHit(chunk_id=chunk_id, score=score))
        # Deterministic ordering: ties break by id, never by dict insertion order.
        scored.sort(key=lambda h: (-h.score, h.chunk_id))
        return scored[:top_k]
