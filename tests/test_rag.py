"""Fast, offline tests for the per-agent RAG lane."""

from __future__ import annotations

import pytest
import yaml

from triad.config import ROOT, load_yaml
from triad.rag import index, ingest, retrieve
from triad.rag.types import AgentRole


@pytest.fixture(autouse=True)
def _fresh_caches():
    ingest.clear_caches()
    retrieve.clear_caches()
    yield
    ingest.clear_caches()
    retrieve.clear_caches()


def test_front_matter_parsing_and_stable_chunk_ids(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    atc = corpus / "atc"
    atc.mkdir(parents=True)
    source = atc / "wake-test.md"
    source.write_text(
        "---\n"
        'doc: "Test wake document"\n'
        'url: "https://example.test/wake"\n'
        "synthetic: false\n"
        'licence: "public domain"\n'
        "---\n"
        "\n"
        "# Heading one\n"
        "\n"
        "Heavy behind a Medium requires five nautical miles.\n"
        "\n"
        "# Heading two\n"
        "\n"
        "A Super leading a Light requires eight nautical miles.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ingest, "CORPUS_DIR", corpus)

    chunks = ingest.parse_file(source, "ATC")
    assert [c["chunk_id"] for c in chunks] == ["atc-wake-test-01", "atc-wake-test-02"]
    assert chunks[0]["doc"] == "Test wake document"
    assert chunks[0]["section"] == "Heading one"
    assert chunks[0]["synthetic"] is False
    assert chunks[0]["url"] == "https://example.test/wake"

    again = ingest.parse_file(source, "ATC")
    assert [c["chunk_id"] for c in again] == [c["chunk_id"] for c in chunks]
    assert [c["text"] for c in again] == [c["text"] for c in chunks]


def test_tokenizer_keeps_aviation_codes():
    tokens = index.tokenize(
        "TWY K CLSD BTN 29-11-01 at FL340; 121.639, B737, ATA-29, QMXLC!"
    )
    for expected in ("twy", "k", "clsd", "btn", "29-11-01", "fl340", "121.639", "b737", "qmxlc"):
        assert expected in tokens
    assert "and" not in index.tokenize("wake AND separation")


def test_role_isolation():
    atc_hits = retrieve.retrieve(AgentRole.ATC, "TWY K CLSD BTN K3 AND K5", k=8)
    assert atc_hits
    assert all(hit.chunk_id.startswith("atc-") for hit in atc_hits)

    pilot_hits = retrieve.retrieve(AgentRole.PILOT, "fuel reserve alternate 45 minutes", k=8)
    assert pilot_hits
    assert all(hit.chunk_id.startswith("pilot-") for hit in pilot_hits)

    ground_hits = retrieve.retrieve(AgentRole.GROUND, "MEL category C deferrable", k=8)
    assert ground_hits
    assert all(hit.chunk_id.startswith("ground-") for hit in ground_hits)


def test_each_defect_text_finds_its_synthetic_mel_entry():
    defects = load_yaml("defects")["defects"]
    for defect_id, item in defects.items():
        hits = retrieve.retrieve(AgentRole.GROUND, item["text"], k=3)
        assert any(
            hit.chunk_id.startswith("ground-airline-mel-excerpt")
            and (defect_id in hit.text or defect_id in (hit.section or ""))
            for hit in hits
        ), (defect_id, [hit.chunk_id for hit in hits])


def test_retrieval_eval_hit_at_3_meets_target():
    for role in ingest.ROLES:
        metrics = ingest.evaluate_role(role, k=3)
        assert 15 <= metrics["queries"] <= 20, (role, metrics)
        assert metrics["hit@3"] >= 0.85, (role, metrics)


def test_retrieve_missing_corpus_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "CORPUS_DIR", tmp_path / "corpus")
    monkeypatch.setattr(ingest, "CACHE_DIR", tmp_path / "cache")
    retrieve.clear_caches()

    assert retrieve.retrieve(AgentRole.ATC, "wake separation", k=4) == []
    assert retrieve.retrieve(AgentRole.PILOT, "fuel reserve", k=4) == []
    assert retrieve.retrieve(AgentRole.GROUND, "MEL category", k=4) == []


def test_perception_eval_set_is_complete():
    path = ROOT / "corpus" / "eval" / "perception.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(data["atc_notams"]) == 8
    assert len(data["pireps"]) == 8
    assert len(data["defects"]) == 8

    defects = load_yaml("defects")["defects"]
    for item in data["defects"]:
        expected = defects[item["defect_id"]]
        assert item["expected"]["ata_chapter"] == expected["ata_chapter"]
        assert item["expected"]["deferrable"] is expected["deferrable"]
        assert item["expected"]["repair_min"] == expected["repair_min"]
