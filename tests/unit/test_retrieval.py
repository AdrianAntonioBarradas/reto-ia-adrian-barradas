"""Retrieval behaviour that must not regress.

The lexical tests run everywhere. The dense and hybrid tests need the ONNX encoder,
so they are marked ``embeddings`` and excluded from the default run — CI should not
download a 220 MB model to check a BM25 tokenizer.
"""

from __future__ import annotations

import pytest

from app.knowledge.chunker import build_chunks
from app.knowledge.corpus import load_corpus
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.lexical import BM25Index, fold_plural, tokenize


@pytest.fixture(scope="module")
def chunks() -> list:
    return build_chunks(load_corpus())


@pytest.fixture(scope="module")
def bm25(chunks: list) -> BM25Index:
    return BM25Index({c.id: c.embedding_text for c in chunks})


# --- tokenisation -----------------------------------------------------------


def test_accents_are_folded_so_liquidacion_matches_liquidación() -> None:
    assert tokenize("liquidación") == tokenize("liquidacion")


def test_technology_shaped_tokens_survive() -> None:
    tokens = tokenize("Usó Node-22, .NET y recall@k")
    assert "node-22" in tokens
    assert any(t.startswith("recall") for t in tokens)


def test_plural_folding_is_symmetric() -> None:
    """The ISIN/ISINs mismatch that made an exact-term query return nothing."""
    assert fold_plural("isins") == fold_plural("isin") == "isin"
    assert fold_plural("go") == "go"
    assert fold_plural("aws") == "aws"


def test_short_acronyms_are_not_stemmed_away() -> None:
    for acronym in ("go", "js", "aws", "sql", "abm"):
        assert fold_plural(acronym) == acronym


# --- lexical retrieval ------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected_chunk_id"),
    [
        ("ISIN", "skills:domain_knowledge"),
        ("TanStack", "skill:frontend:TanStack (Query, Table)"),
        ("LocalStack", "project:localstack-lab"),
        ("MinIO", "experience:cicada:s3_storage"),
    ],
)
def test_exact_terms_reach_their_chunk(bm25: BM25Index, query: str, expected_chunk_id: str) -> None:
    """Exact technology names are what dense retrieval handles worst."""
    hits = [h.chunk_id for h in bm25.search(query, 3)]
    assert expected_chunk_id in hits, f"{query!r} did not retrieve {expected_chunk_id!r}: {hits}"


def test_absent_topics_retrieve_nothing(bm25: BM25Index) -> None:
    """Compensation is not in the corpus, so there is nothing to find."""
    assert bm25.search("¿cuánto ganaba de sueldo?", 5) == []


def test_search_is_deterministic(bm25: BM25Index) -> None:
    first = [(h.chunk_id, h.score) for h in bm25.search("experiencia con Go", 5)]
    second = [(h.chunk_id, h.score) for h in bm25.search("experiencia con Go", 5)]
    assert first == second


# --- fusion -----------------------------------------------------------------


def test_rrf_rewards_appearing_in_both_lists() -> None:
    """Agreement between two notions of relevance beats topping one of them.

    Note what this does *not* claim. The reciprocal is convex, so a document at
    ranks 1 and 3 scores slightly higher than one at ranks 2 and 2 — fusion rewards
    a strong showing, it does not penalise it. The property that matters is that
    being found twice beats being found once, however highly.
    """
    dense = ["top_only", "shared", "dense_tail"]
    lexical = ["lexical_head", "shared", "lexical_tail"]
    fused = dict(reciprocal_rank_fusion([dense, lexical]))
    assert fused["shared"] > fused["top_only"]
    assert fused["shared"] > fused["lexical_head"]


def test_rrf_preserves_rank_order_within_a_single_list() -> None:
    fused = reciprocal_rank_fusion([["first", "second", "third"]])
    assert [doc for doc, _ in fused] == ["first", "second", "third"]


def test_rrf_is_deterministic_under_ties() -> None:
    ranking = reciprocal_rank_fusion([["x", "y"], ["y", "x"]])
    assert [doc for doc, _ in ranking] == sorted(doc for doc, _ in ranking)


# --- chunking ---------------------------------------------------------------


def test_every_chunk_is_self_contained(chunks: list) -> None:
    """A chunk that starts with a bare pronoun is useless once retrieved alone."""
    for chunk in chunks:
        first_word = chunk.text.split()[0].lower().strip(".,:")
        assert first_word not in {"esto", "eso", "lo", "redujo", "it", "this"}, (
            f"{chunk.id} opens without naming its subject: {chunk.text[:60]!r}"
        )


def test_learning_skills_state_the_absence_of_experience(chunks: list) -> None:
    """The honest phrasing must be in the retrieved text, not inferred from a tag."""
    learning = [c for c in chunks if c.metadata.get("proficiency") == "LEARNING"]
    assert learning, "no LEARNING skill chunks were produced"
    for chunk in learning:
        assert "NO tiene experiencia profesional" in chunk.text, (
            f"{chunk.id} does not state the absence of experience"
        )


def test_projects_carry_attribution_in_their_text(chunks: list) -> None:
    """Metadata alone is not enough: the model may only ever see the body."""
    for chunk in chunks:
        if chunk.entity_type != "project":
            continue
        attribution = chunk.metadata.get("attribution")
        if attribution == "not_mine":
            assert "NO lo construyó" in chunk.text, f"{chunk.id} omits its disclaimer"
        elif attribution == "contribution":
            assert "no es suyo" in chunk.text, f"{chunk.id} omits its disclaimer"


def test_caveats_travel_with_their_claim(chunks: list) -> None:
    """Retrieving an achievement without its qualifier is how FAMILIAR becomes expertise."""
    with_caveat = [c for c in chunks if c.metadata.get("has_caveat")]
    assert with_caveat, "no caveated highlights were produced"
    for chunk in with_caveat:
        assert "MATIZ IMPORTANTE" in chunk.text
