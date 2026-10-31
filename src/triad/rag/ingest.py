"""Corpus ingestion for the three per-agent RAG indexes.

Layout::

    corpus/atc/*.md
    corpus/pilot/*.md
    corpus/ground/*.md

Markdown files use YAML front matter::

    ---
    doc: "14 CFR 121.639 -- Fuel supply: All domestic operations"
    url: "https://www.ecfr.gov/current/title-14/section-121.639"
    synthetic: false
    licence: "US Government work (public domain)"
    edition: "eCFR current"
    paraphrase: false
    ---

Each heading becomes a section. Sections longer than ~300 words are split on
paragraph boundaries. Chunk ids are deterministic: ``{role}-{file_slug}-{n:02d}``.

``index_main(args)`` is called by the frozen CLI for ``uv run triad index
[--eval]``. It rebuilds all three indexes into ``.cache/rag/<role>.json`` and
optionally runs the per-role retrieval evaluation.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from triad.config import ROOT
from triad.schemas import AgentRole

CORPUS_DIR = ROOT / "corpus"
CACHE_DIR = ROOT / ".cache" / "rag"

ROLES: tuple[str, ...] = ("atc", "pilot", "ground")
CORPUS_SUFFIXES = {".md", ".markdown", ".txt"}
EXCLUDED_NAMES = {"SOURCES.md", "sources.md", "eval.yaml"}

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_CHUNK_WORDS = 300


# --------------------------------------------------------------------------- paths / roles


def role_key(role: AgentRole | str) -> str:
    """Normalise ``AgentRole.ATC`` / ``"ATC"`` / ``"atc"`` to ``"atc"``."""

    if isinstance(role, AgentRole):
        return role.value.lower()
    value = str(role).strip().lower()
    if value not in ROLES:
        raise ValueError(f"unknown agent role {role!r}; expected one of {ROLES}")
    return value


def corpus_role_dir(role: AgentRole | str) -> Path:
    return CORPUS_DIR / role_key(role)


def cache_role_path(role: AgentRole | str) -> Path:
    return CACHE_DIR / f"{role_key(role)}.json"


def _corpus_files(role: AgentRole | str) -> list[Path]:
    root = corpus_role_dir(role)
    if not root.exists():
        return []
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in CORPUS_SUFFIXES
        and path.name not in EXCLUDED_NAMES
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
    ]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


# --------------------------------------------------------------------------- hashing


def _sha_files(files: Iterable[Path], base: Path) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(base).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def role_corpus_sha256(role: AgentRole | str) -> str:
    """SHA-256 of one role's indexed corpus files (paths + bytes)."""

    root = corpus_role_dir(role)
    files = _corpus_files(role)
    if not root.exists():
        return hashlib.sha256(b"").hexdigest()
    return _sha_files(files, root)


def corpus_sha256() -> str:
    """Combined SHA-256 of all three indexed corpora (for run manifests)."""

    digest = hashlib.sha256()
    for role in ROLES:
        digest.update(role.encode("utf-8"))
        digest.update(b"\0")
        digest.update(role_corpus_sha256(role).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


# --------------------------------------------------------------------------- parsing


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Strip a leading ``---`` YAML block; return ``(metadata, body)``."""

    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() in {"---", "..."}:
            fm_text = "\n".join(lines[1:i])
            try:
                meta = yaml.safe_load(fm_text) or {}
            except yaml.YAMLError as exc:  # pragma: no cover - malformed corpus is a build error
                raise ValueError(f"invalid YAML front matter: {exc}") from exc
            if not isinstance(meta, dict):
                raise ValueError("YAML front matter must be a mapping")
            return meta, "\n".join(lines[i + 1 :])
    return {}, text


def file_slug(path: Path) -> str:
    slug = _SLUG_RE.sub("-", path.stem.lower()).strip("-")
    return slug or "document"


def _split_section(text: str, max_words: int = _MAX_CHUNK_WORDS) -> list[str]:
    """Split a section body into <=``max_words`` paragraph-aligned chunks."""

    text = text.strip()
    if not text:
        return []
    if len(text.split()) <= max_words:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n[ \t]*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    def flush() -> None:
        nonlocal current, current_words
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0

    for paragraph in paragraphs:
        words = paragraph.split()
        if len(words) > max_words:
            flush()
            for start in range(0, len(words), max_words):
                chunks.append(" ".join(words[start : start + max_words]))
            continue
        if current and current_words + len(words) > max_words:
            flush()
        current.append(paragraph)
        current_words += len(words)
    flush()
    return chunks


def _sections(body: str) -> list[tuple[str | None, str]]:
    """Split Markdown by headings. Text before the first heading becomes ``None``."""

    sections: list[tuple[str | None, str]] = []
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        if body.strip():
            sections.append((None, body))
        return sections

    intro = body[: matches[0].start()].strip()
    if intro:
        sections.append((None, intro))
    for idx, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        if content:
            sections.append((heading, content))
    return sections


def parse_file(path: Path, role: AgentRole | str) -> list[dict[str, Any]]:
    """Parse one ``.md``/``.txt`` file into chunk dictionaries."""

    role_name = role_key(role)
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".txt":
        meta: dict[str, Any] = {}
        body = raw
    else:
        meta, body = parse_front_matter(raw)

    doc = str(meta.get("doc") or path.stem)
    url = meta.get("url")
    licence = meta.get("licence")
    edition = meta.get("edition")
    synthetic = bool(meta.get("synthetic", True))
    paraphrase = bool(meta.get("paraphrase", False))
    slug = file_slug(path)

    try:
        relative = path.relative_to(corpus_role_dir(role_name)).as_posix()
    except ValueError:
        relative = path.name

    chunks: list[dict[str, Any]] = []
    n = 0
    for section, content in _sections(body):
        for piece in _split_section(content):
            n += 1
            chunks.append(
                {
                    "chunk_id": f"{role_name}-{slug}-{n:02d}",
                    "doc": doc,
                    "section": section,
                    "text": piece,
                    "url": str(url) if url is not None else None,
                    "synthetic": synthetic,
                    "licence": str(licence) if licence is not None else None,
                    "edition": str(edition) if edition is not None else None,
                    "paraphrase": paraphrase,
                    "file": relative,
                    "role": role_name,
                }
            )
    return chunks


# --------------------------------------------------------------------------- build / load


def build_role_index(role: AgentRole | str) -> dict[str, Any]:
    """(Re)build one role's in-memory index and write its JSON cache."""

    role_name = role_key(role)
    chunks: list[dict[str, Any]] = []
    for path in _corpus_files(role_name):
        chunks.extend(parse_file(path, role_name))
    payload = {
        "role": role_name,
        "corpus_sha256": role_corpus_sha256(role_name),
        "chunk_count": len(chunks),
        "chunks": chunks,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache_role_path(role_name).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(cache_role_path(role_name))
    return payload


def _read_cache(role: AgentRole | str) -> dict[str, Any] | None:
    path = cache_role_path(role)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("chunks"), list):
        return None
    return data


def load_role_index(role: AgentRole | str) -> dict[str, Any]:
    """Return a fresh-enough cache, rebuilding when the corpus hash changed."""

    role_name = role_key(role)
    data = _read_cache(role_name)
    if data is not None and data.get("corpus_sha256") == role_corpus_sha256(role_name):
        return data
    return build_role_index(role_name)


# --------------------------------------------------------------------------- evaluation


def _expect_hit(chunk: Any, expect: Any) -> bool:
    if isinstance(expect, (list, tuple, set)):
        return any(_expect_hit(chunk, item) for item in expect)
    target = str(expect).strip()
    if not target:
        return False
    if target == chunk.chunk_id:
        return True
    return target.lower() in (chunk.doc or "").lower()


def _eval_path(role: AgentRole | str) -> Path:
    return corpus_role_dir(role) / "eval.yaml"


def load_eval(role: AgentRole | str) -> list[dict[str, Any]]:
    path = _eval_path(role)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        data = data.get("queries", [])
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a list of queries")
    return [item for item in data if isinstance(item, dict) and item.get("query") and item.get("expect")]


def evaluate_role(role: AgentRole | str, k: int = 3) -> dict[str, Any]:
    """Run one role's ``eval.yaml``; hit = expected chunk_id or doc substring."""

    from triad.rag.retrieve import retrieve  # local import avoids a cycle

    role_name = role_key(role)
    role_enum = AgentRole(role_name.upper())
    items = load_eval(role_name)
    hits_at_1 = 0
    hits_at_k = 0
    for item in items:
        results = retrieve(role_enum, str(item["query"]), k=k)
        if results and _expect_hit(results[0], item["expect"]):
            hits_at_1 += 1
        if any(_expect_hit(chunk, item["expect"]) for chunk in results):
            hits_at_k += 1
    total = len(items)
    return {
        "role": role_name,
        "queries": total,
        "k": k,
        "hit@1": (hits_at_1 / total) if total else 0.0,
        "hit@3": (hits_at_k / total) if total else 0.0,
    }


def index_main(args: Any) -> None:
    """CLI entry point for ``uv run triad index [--eval]``."""

    results: list[dict[str, Any]] = []
    for role in ROLES:
        payload = build_role_index(role)
        print(
            f"{role}: {payload['chunk_count']} chunks  "
            f"(corpus sha256 {payload['corpus_sha256'][:12]})"
        )
        results.append(payload)

    if not getattr(args, "eval", False):
        return

    print("")
    for role in ROLES:
        metrics = evaluate_role(role, k=3)
        if metrics["queries"] == 0:
            print(f"{role} eval: no eval.yaml queries found")
            continue
        status = "OK" if metrics["hit@3"] >= 0.85 else "BELOW TARGET (hit@3 < 0.85)"
        print(
            f"{role} eval: hit@1 {metrics['hit@1']:.2f}  hit@3 {metrics['hit@3']:.2f}  "
            f"({metrics['queries']} queries)  {status}"
        )


def clear_caches() -> None:
    """Drop lru caches in this module (used by tests)."""

    # ingest itself has no lru cache, but keep the API symmetric/future-proof.
    return None


__all__ = [
    "CACHE_DIR",
    "CORPUS_DIR",
    "ROLES",
    "build_role_index",
    "cache_role_path",
    "clear_caches",
    "corpus_role_dir",
    "corpus_sha256",
    "evaluate_role",
    "file_slug",
    "index_main",
    "load_eval",
    "load_role_index",
    "parse_file",
    "parse_front_matter",
    "role_corpus_sha256",
    "role_key",
]
