"""
SeedIngest: Normalize and validate seed materials before LLM extraction.

职责：
- 接收文本、文档摘要、结构化种子数据
- 统一转换为内部 ingestion format (list[SeedMaterial])
- 基本清洗与去重
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Union

from agentsociety2.world.models import SeedMaterial

__all__ = ["SeedIngest"]


class SeedIngest:
    """
    Normalize various input formats into a list of SeedMaterial objects.
    """

    def ingest(
        self,
        inputs: Union[
            str,
            List[str],
            List[Dict[str, Any]],
            List[SeedMaterial],
        ],
    ) -> List[SeedMaterial]:
        """
        Accept a variety of input formats and return normalized SeedMaterial list.

        Args:
            inputs: Can be:
                - str: Single text snippet
                - list[str]: Multiple text snippets
                - list[dict]: Raw dicts matching SeedMaterial schema (partially)
                - list[SeedMaterial]: Already-typed objects (pass-through)

        Returns:
            Deduplicated list of SeedMaterial objects.
        """
        materials: List[SeedMaterial] = []

        if isinstance(inputs, str):
            materials.append(self._from_text(inputs))

        elif isinstance(inputs, list):
            for item in inputs:
                if isinstance(item, SeedMaterial):
                    materials.append(item)
                elif isinstance(item, str):
                    materials.append(self._from_text(item))
                elif isinstance(item, dict):
                    materials.append(self._from_dict(item))
                else:
                    raise TypeError(
                        f"Unsupported seed material type: {type(item)}"
                    )
        else:
            raise TypeError(f"Unsupported input type: {type(inputs)}")

        return self._deduplicate(materials)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _from_text(self, text: str) -> SeedMaterial:
        title = text[:60].strip().replace("\n", " ")
        return SeedMaterial(
            kind="text",
            title=title,
            content=text.strip(),
        )

    def _from_dict(self, d: Dict[str, Any]) -> SeedMaterial:
        if "content" not in d:
            raise ValueError("SeedMaterial dict must contain 'content' key")
        import uuid as _uuid
        default_id = d.get("id") or f"seed_{str(_uuid.uuid4()).replace('-', '')[:12]}"
        return SeedMaterial(
            id=default_id,
            kind=d.get("kind", "text"),
            title=d.get("title", ""),
            content=d["content"],
            source=d.get("source"),
            metadata=d.get("metadata", {}),
        )

    def _deduplicate(self, materials: List[SeedMaterial]) -> List[SeedMaterial]:
        """Remove exact duplicates by content hash."""
        seen: set[str] = set()
        result: List[SeedMaterial] = []
        for m in materials:
            h = hashlib.md5(m.content.encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                result.append(m)
        return result

    def to_text_block(self, materials: List[SeedMaterial]) -> str:
        """
        Concatenate all seed materials into a single formatted text block
        suitable for the LLM extraction prompt.
        """
        parts: List[str] = []
        for i, m in enumerate(materials, start=1):
            header = f"### Seed Material {i}: {m.title or m.id}"
            parts.append(f"{header}\n\n{m.content}")
        return "\n\n---\n\n".join(parts)
