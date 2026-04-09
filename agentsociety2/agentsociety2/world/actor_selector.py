"""
ActorSelector: Select actionable entities that should become simulated agents.

职责：
- 从结构化实体/关系中挑选 actor 实体集合
- 优先保留 person / organization / group / media
- 在 actor 数量过少时按关系参与度补齐高相关主体
"""

from __future__ import annotations

from collections import Counter

from agentsociety2.world.models import Entity, Relation

__all__ = ["ActorSelector"]


class ActorSelector:
    """Select the actor entity set from structured world facts."""

    def __init__(self, min_actors: int = 4, max_actors: int = 12):
        self.min_actors = min_actors
        self.max_actors = max_actors
        self._actor_types = {"person", "organization", "group", "media"}

    def select(self, entities: list[Entity], relations: list[Relation]) -> list[str]:
        actor_candidates = [entity for entity in entities if entity.entity_type in self._actor_types]
        if not actor_candidates:
            return []

        degree = Counter()
        for relation in relations:
            degree[relation.source_entity_id] += 1
            degree[relation.target_entity_id] += 1

        actor_candidates.sort(
            key=lambda entity: (
                degree.get(entity.id, 0),
                1 if entity.entity_type == "person" else 0,
                len(entity.description or ""),
                entity.name,
            ),
            reverse=True,
        )

        selected = actor_candidates[: self.max_actors]

        if len(selected) < self.min_actors:
            remaining = [entity for entity in actor_candidates if entity.id not in {item.id for item in selected}]
            selected.extend(remaining[: max(0, self.min_actors - len(selected))])

        return [entity.id for entity in selected]
