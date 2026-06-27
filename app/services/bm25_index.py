"""Pre-built inverted-index BM25 for fast repeated retrieval over a fixed chunk corpus.

Ported from NITRAG's retriever_manager.py (BM25 strategy).

The key difference from the previous inline BM25: this class builds the inverted
index once (postings: term → {chunk_id: tf}) and reuses it across queries,
so retrieval touches only chunks that contain query terms rather than scoring
every chunk on every call.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from app.services.claim_utils import tokenize


@dataclass
class BM25Index:
    """Okapi BM25 (k1=1.5, b=0.75) over a fixed set of chunks.

    Build once per corpus, query many times without recomputing document
    frequencies or term frequencies.
    """

    # term → {chunk_id: raw_tf}
    _postings: dict[str, dict[str, int]] = field(default_factory=dict)
    # chunk_id → token count
    _chunk_lengths: dict[str, int] = field(default_factory=dict)
    # precomputed IDF per term
    _idf: dict[str, float] = field(default_factory=dict)
    _avg_length: float = 0.0
    _num_docs: int = 0

    _k1: float = 1.5
    _b: float = 0.75

    @classmethod
    def build(cls, chunk_ids: list[str], chunk_texts: list[str]) -> "BM25Index":
        """Build the index from parallel lists of chunk IDs and raw text."""
        index = cls()
        index._num_docs = len(chunk_ids)
        if not chunk_ids:
            return index

        postings: dict[str, dict[str, int]] = defaultdict(dict)
        doc_freq: dict[str, int] = defaultdict(int)
        total_length = 0

        for chunk_id, text in zip(chunk_ids, chunk_texts):
            tokens = tokenize(text)
            index._chunk_lengths[chunk_id] = len(tokens)
            total_length += len(tokens)

            tf_map: dict[str, int] = defaultdict(int)
            for token in tokens:
                tf_map[token] += 1

            for term, tf in tf_map.items():
                postings[term][chunk_id] = tf
                doc_freq[term] += 1

        index._postings = {term: dict(posting) for term, posting in postings.items()}
        index._avg_length = total_length / max(index._num_docs, 1)

        n = max(index._num_docs, 1)
        index._idf = {
            term: math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            for term, df in doc_freq.items()
        }

        return index

    def retrieve(self, query_tokens: list[str], top_k: int) -> list[tuple[str, float]]:
        """Return up to ``top_k`` ``(chunk_id, bm25_score)`` pairs, descending by score.

        Only visits chunks that contain at least one query term (inverted index).
        """
        if not query_tokens or not self._postings:
            return []

        scores: dict[str, float] = defaultdict(float)
        k1, b = self._k1, self._b
        avg_len = max(self._avg_length, 1.0)

        for token in set(query_tokens):
            idf = self._idf.get(token, 0.0)
            if idf == 0.0:
                continue
            posting = self._postings.get(token)
            if not posting:
                continue
            for chunk_id, tf in posting.items():
                doc_len = self._chunk_lengths.get(chunk_id, 1)
                norm = tf + k1 * (1.0 - b + b * (doc_len / avg_len))
                scores[chunk_id] += idf * (tf * (k1 + 1.0)) / norm

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(cid, score) for cid, score in ranked[:top_k] if score > 0.0]

    def __len__(self) -> int:
        return self._num_docs
