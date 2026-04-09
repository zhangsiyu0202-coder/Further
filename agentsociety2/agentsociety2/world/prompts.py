"""
World Prompts: Centralized LLM prompt templates for the world engine.

职责：
- 集中存放世界抽取、Agent 决策、报告生成等核心 prompt 模板
- 所有模块通过此文件获取 prompt，避免散落在各处
"""

__all__ = [
    "EXTRACTION_SYSTEM_PROMPT",
    "EXTRACTION_USER_PROMPT",
    "ACTIONABLE_ENTITY_SUPPLEMENT_SYSTEM_PROMPT",
    "ACTIONABLE_ENTITY_SUPPLEMENT_USER_PROMPT",
    "PERSONA_GENERATION_PROMPT",
    "GRAPH_ASSEMBLY_PROMPT",
    "SIMULATION_INIT_PROMPT",
    "REPORT_GENERATION_PROMPT",
    "WORLD_CHAT_PROMPT",
]

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a world-building AI. Your task is to analyze seed materials and extract structured world knowledge.

You will extract:
1. **Entities**: people, organizations, groups, media outlets, locations, concepts
2. **Relations**: directional relationships between entities with type, polarity, and strength
3. **Events**: significant events mentioned or implied
4. **Constraints**: rules or limitations of this world
5. **Stances**: positions that entities hold on topics or toward other entities
6. **Goals**: what entities want to achieve

Prioritize actionable actors for simulation:
- Prefer extracting people, organizations, groups, and media whenever they can act, decide, communicate, organize, buy, sell, govern, mobilize, or react.
- Do not collapse social actors into abstract concepts if they can be represented as actor entities.
- Keep concepts for truly abstract factors only.

Be thorough but grounded — do not invent entities or relations not implied by the materials.
Return valid JSON only."""

EXTRACTION_USER_PROMPT = """Analyze the following seed materials and extract world knowledge.

## Seed Materials

{seed_materials_text}

## World Goal (optional context)
{world_goal}

## Constraints (optional)
{constraints}

## Required Output Format

Return a JSON object with this structure:
```json
{{
  "entities": [
    {{
      "name": "string",
      "entity_type": "person|organization|group|media|location|concept|other",
      "aliases": [],
      "description": "string",
      "attributes": {{}}
    }}
  ],
  "relations": [
    {{
      "source_entity_name": "string",
      "target_entity_name": "string",
      "relation_type": "string (e.g. ally, rival, employs, opposes, supports, funds)",
      "strength": 0.5,
      "polarity": "positive|neutral|negative",
      "description": "string"
    }}
  ],
  "events": [
    {{
      "title": "string",
      "description": "string",
      "participants": ["entity names"],
      "event_type": "string"
    }}
  ],
  "constraints": ["string"],
  "global_variables": [
    {{
      "name": "string",
      "value": "string or number",
      "description": "string"
    }}
  ],
  "build_summary": "A 2-3 sentence summary of this world"
}}
```

Extract now:"""


ACTIONABLE_ENTITY_SUPPLEMENT_SYSTEM_PROMPT = """You are reviewing a draft world extraction and repairing missing actor entities for simulation.

Your only goal is to add missing entities that can plausibly act, decide, speak, organize, buy, sell, govern, mobilize, or respond.

Allowed entity types:
- person
- organization
- group
- media

Rules:
1. Prefer directly mentioned people, institutions, cohorts, audiences, customers, residents, officials, workers, families, factions, or spokesperson-like organizations.
2. You may add strongly implied social actors only when the seed text clearly depends on them.
3. Do not add abstract concepts, materials, devices, locations, events, or metaphors.
4. Do not duplicate entities already present in the draft extraction.
5. Keep the result grounded and compact.

Return valid JSON only."""


ACTIONABLE_ENTITY_SUPPLEMENT_USER_PROMPT = """The current extraction has too few actionable actors for simulation.

## Seed Materials
{seed_materials_text}

## World Goal
{world_goal}

## Existing Entities
{entities_summary}

## Existing Relations
{relations_summary}

## Task
Add only the missing actionable actors needed for a realistic simulation.
Focus on people, organizations, groups, and media that have agency in this world.

Return JSON with this structure:
```json
{{
  "entities": [
    {{
      "name": "string",
      "entity_type": "person|organization|group|media",
      "aliases": [],
      "description": "string",
      "attributes": {{}}
    }}
  ],
  "relations": [
    {{
      "source_entity_name": "string",
      "target_entity_name": "string",
      "relation_type": "string",
      "strength": 0.5,
      "polarity": "positive|neutral|negative",
      "description": "string"
    }}
  ]
}}
```

Return only additional actor entities and their most important relations:"""

# ---------------------------------------------------------------------------
# Persona Generation
# ---------------------------------------------------------------------------

PERSONA_GENERATION_PROMPT = """You are generating a detailed persona for a world entity that will be used to drive a simulated agent.

## Entity Information

Name: {entity_name}
Type: {entity_type}
Description: {entity_description}
Attributes: {entity_attributes}

## World Context

{world_context}

## Task

Generate a rich persona for this entity. The persona should be internally consistent and grounded in the world context.

Return JSON:
```json
{{
  "identity_summary": "2-3 sentences describing who this entity is",
  "goals": ["goal 1", "goal 2", "goal 3"],
  "fears": ["fear 1", "fear 2"],
  "preferences": ["tendency 1", "tendency 2"],
  "stance_map": {{
    "topic or entity name": "stance description"
  }},
  "behavior_style": "how this entity typically acts",
  "speech_style": "how this entity typically communicates",
  "memory_seeds": ["initial memory 1", "initial memory 2"]
}}
```"""

# ---------------------------------------------------------------------------
# Graph Assembly
# ---------------------------------------------------------------------------

GRAPH_ASSEMBLY_PROMPT = """You are reviewing extracted world elements for consistency and completeness.

## Extracted Entities
{entities_summary}

## Extracted Relations
{relations_summary}

## Task

1. Identify any obvious missing relations between major entities.
2. Identify any entity duplicates (different names for the same entity).
3. Suggest up to 5 additional relations that are strongly implied but not extracted.

Return JSON:
```json
{{
  "entity_merges": [
    {{"keep": "name to keep", "merge": "name to remove as duplicate"}}
  ],
  "additional_relations": [
    {{
      "source_entity_name": "string",
      "target_entity_name": "string",
      "relation_type": "string",
      "strength": 0.5,
      "polarity": "positive|neutral|negative",
      "description": "string"
    }}
  ],
  "notes": "any other observations"
}}
```"""

# ---------------------------------------------------------------------------
# Simulation Init
# ---------------------------------------------------------------------------

SIMULATION_INIT_PROMPT = """You are designing the initial simulation setup for a virtual world.

## Simulation Goal

{simulation_goal}

## Seed Materials

{seed_materials_text}

## World Summary

{world_summary}

## Entities

{entities_summary}

## Current Relations

{relations_summary}

## Task

Convert the simulation goal into structured initialization outputs for world init.
Do not rewrite the whole world. Only add system-level initialization context that makes the simulation more focused.
Be grounded in the seed materials and existing world summary.

Return JSON only:
```json
{{
  "summary": "1-2 sentence description of how the simulation should be initialized",
  "narrative_direction": "string",
  "time_config": {{
    "horizon_days": 1,
    "recommended_steps": 24,
    "tick_seconds": 3600,
    "peak_hours": [9, 10, 11, 14, 15, 16, 20, 21],
    "off_peak_hours": [0, 1, 2, 3, 4, 5],
    "agents_per_tick_min": 1,
    "agents_per_tick_max": 3
  }},
  "event_config": {{
    "hot_topics": ["topic 1", "topic 2"]
  }},
  "agent_priorities": [
    {{
      "entity_name": "string",
      "priority_topics": ["topic 1", "topic 2"],
      "priority_targets": ["entity A", "entity B"],
      "activity_bias": "string"
    }}
  ],
  "agent_activity_config": [
    {{
      "entity_name": "string",
      "activity_level": "low|medium|high",
      "active_hours": [9, 10, 11, 14, 15, 16],
      "response_delay_ticks": 0
    }}
  ],
  "global_variables": [
    {{
      "name": "string",
      "value": "string | number | boolean | list | object",
      "description": "string"
    }}
  ],
  "initial_events": [
    {{
      "event_type": "string",
      "title": "string",
      "description": "string",
      "participants": ["entity names"]
    }}
  ],
  "assumptions": ["string"]
}}
```"""

# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

REPORT_GENERATION_PROMPT = """You are a world analyst generating a report on a virtual world simulation.

## World Snapshot Summary

{world_snapshot_summary}

## Event Timeline (recent)

{timeline_summary}

## Relation Changes

{relation_changes_summary}

## Report Request

Type: {report_type}
Focus: {focus}

## Task

Generate a structured, insightful report based on the simulation data.
The report should be analytical, specific, and grounded in the simulation evidence.

Return the report as a JSON object:
```json
{{
  "title": "string",
  "executive_summary": "string",
  "key_findings": ["finding 1", "finding 2"],
  "entity_analysis": [
    {{"entity": "name", "status": "string", "trajectory": "string"}}
  ],
  "relation_dynamics": "string",
  "timeline_highlights": ["event description"],
  "prediction": "string (if report_type is prediction)",
  "recommendations": ["string"],
  "full_report": "detailed narrative text"
}}
```"""

# ---------------------------------------------------------------------------
# World Chat
# ---------------------------------------------------------------------------

WORLD_CHAT_PROMPT = """You are an AI analyst with full knowledge of a virtual world simulation.

## World State

{world_snapshot_summary}

## Recent Events (Timeline)

{timeline_summary}

## Key Relations

{relations_summary}

## User Question

{question}

## Task

Answer the question based on the simulation data. Be specific, cite simulation evidence where relevant.
Keep your answer focused and informative."""
