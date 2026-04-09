"""Intelligent text chunker using unstructured.io with simple fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

__all__ = ["ChunkingStrategy", "ChunkerConfig", "Chunk", "UnstructuredChunker"]

logger = logging.getLogger("agentsociety2.graph.chunker")


class ChunkingStrategy(str, Enum):
    BASIC = "basic"
    BY_TITLE = "by_title"
    SIMPLE = "simple"


@dataclass
class ChunkerConfig:
    strategy: ChunkingStrategy = ChunkingStrategy.BY_TITLE
    max_characters: int = 1000
    new_after_n_chars: int = 800
    overlap: int = 100
    overlap_all: bool = False
    combine_text_under_n_chars: int = 200


@dataclass
class Chunk:
    text: str
    index: int
    metadata: dict = field(default_factory=dict)
    element_types: list[str] = field(default_factory=list)


class UnstructuredChunker:
    """
    Text chunker backed by unstructured.io when available, with a
    simple character-sliding fallback.

    Supported strategies:
    - BASIC     : combine sequential elements up to max_characters
    - BY_TITLE  : respect section headings as chunk boundaries
    - SIMPLE    : character-based sliding window (always available)
    """

    def __init__(self, config: ChunkerConfig | None = None):
        self.config = config or ChunkerConfig()
        self._available = self._probe_unstructured()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk_text(self, text: str) -> list[Chunk]:
        """Chunk *text* and return a list of Chunk objects."""
        if not text or not text.strip():
            return []

        strategy = self.config.strategy
        if strategy == ChunkingStrategy.SIMPLE or not self._available:
            return self._chunk_simple(text)
        return self._chunk_with_unstructured(text)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _probe_unstructured() -> bool:
        try:
            from unstructured.partition.text import partition_text  # noqa: F401
            return True
        except Exception:
            logger.debug("unstructured not available — using simple chunker")
            return False

    def _chunk_with_unstructured(self, text: str) -> list[Chunk]:
        try:
            from unstructured.partition.text import partition_text

            elements = partition_text(text=text)

            if self.config.strategy == ChunkingStrategy.BASIC:
                from unstructured.chunking.basic import chunk_elements
                raw_chunks = chunk_elements(
                    elements,
                    max_characters=self.config.max_characters,
                    new_after_n_chars=self.config.new_after_n_chars,
                    overlap=self.config.overlap,
                    overlap_all=self.config.overlap_all,
                )
            else:
                from unstructured.chunking.title import chunk_by_title
                raw_chunks = chunk_by_title(
                    elements,
                    max_characters=self.config.max_characters,
                    new_after_n_chars=self.config.new_after_n_chars,
                    overlap=self.config.overlap,
                    overlap_all=self.config.overlap_all,
                    combine_text_under_n_chars=self.config.combine_text_under_n_chars,
                )

            result: list[Chunk] = []
            for i, chunk in enumerate(raw_chunks):
                chunk_text = str(chunk).strip()
                if not chunk_text:
                    continue
                meta: dict = {}
                if hasattr(chunk, "metadata") and chunk.metadata is not None:
                    try:
                        meta = chunk.metadata.to_dict()
                    except Exception:
                        pass
                result.append(
                    Chunk(
                        text=chunk_text,
                        index=i,
                        metadata=meta,
                        element_types=[type(chunk).__name__],
                    )
                )
            return result

        except Exception as exc:
            logger.warning("unstructured chunking failed (%s), falling back to simple", exc)
            return self._chunk_simple(text)

    def _chunk_simple(self, text: str) -> list[Chunk]:
        """Character-based sliding window chunker."""
        chunks: list[Chunk] = []
        max_ch = self.config.max_characters
        overlap = self.config.overlap
        start = 0
        idx = 0
        while start < len(text):
            end = min(start + max_ch, len(text))
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=idx,
                        metadata={"start": start, "end": end},
                        element_types=["Text"],
                    )
                )
            if end == len(text):
                break
            start = end - overlap
            idx += 1
        return chunks
