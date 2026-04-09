# AgentSociety2 — LLM World Backend

[![PyPI Version](https://img.shields.io/pypi/v/agentsociety2.svg)](https://pypi.org/project/agentsociety2/)
[![Python Version](https://img.shields.io/pypi/pyversions/agentsociety2.svg)](https://pypi.org/project/agentsociety2/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

> A **pure LLM-driven virtual world simulation backend**. Build worlds from seed materials, run multi-agent simulations, interact with agents, and generate reports.

## What is this?

AgentSociety2 has been transformed from a city-simulation framework into a **seed-driven virtual world engine** inspired by MiroFish:

1. **Input** real-world seed materials (news, documents, policy text, etc.)
2. **LLM extracts** entities, relations, personas, events, and world rules
3. **Build** a virtual world graph with active agents
4. **Simulate** — agents observe, decide, and act each tick
5. **Interact** — chat with the world or individual agents, inject interventions
6. **Report** — generate predictions, analyses, and summaries

No maps. No mobility. No code generation router. Pure LLM + structured tools.

## Quick Start

### Configuration

```bash
export AGENTSOCIETY_LLM_API_KEY="your-api-key"
export AGENTSOCIETY_LLM_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_LLM_MODEL="gpt-4o-mini"
```

Or copy `.env.example` to `.env` and fill in your credentials.

### Start the Backend Server

```bash
# From packages/agentsociety2
python -m agentsociety2.backend.run
# API docs: http://localhost:8001/docs
```

### Build a World (Python API)

```python
import asyncio
from agentsociety2.world import (
    SeedIngest, WorldExtractor, PersonaBuilder,
    GraphBuilder, WorldStateManager
)

async def main():
    seed_text = """
    The Westland parliament is deadlocked between the Progressive Alliance
    and the Conservative Coalition. The Alliance backs renewable energy reform;
    the Coalition opposes it citing economic costs. Tech lobby group DigiForce
    funds both sides and is playing them against each other.
    """

    # 1. Ingest
    ingest = SeedIngest()
    materials = ingest.ingest(seed_text)

    # 2. Extract world elements
    extractor = WorldExtractor()
    extraction = await extractor.extract(materials, world_goal="simulate policy deadlock")

    print(f"Extracted {len(extraction.entities)} entities, {len(extraction.relations)} relations")

    # 3. Build personas for agents
    persona_builder = PersonaBuilder()
    personas = await persona_builder.build_all(
        entities=extraction.entities,
        relations=extraction.relations,
        world_context=extraction.build_summary,
    )

    # 4. Assemble world state
    graph_builder = GraphBuilder()
    world_state = await graph_builder.build(
        world_id="world_001",
        world_name="Westland Political Simulation",
        extraction=extraction,
        personas=personas,
    )

    manager = WorldStateManager(world_state)
    print(manager.to_summary_text())

asyncio.run(main())
```

See `examples/build_world_from_text.py` for the full example.

### Run Simulation (Python API)

```python
from agentsociety2.world import SimulationEngine, WorldStateManager, WorldRepository
from agentsociety2.agent.world_sim_agent import WorldSimAgent
from agentsociety2.env.router_world import WorldRouter
from agentsociety2.contrib.env.llm_world import (
    ObservationEnv, RelationGraphEnv, CommunicationEnv, EventTimelineEnv
)

# ... (load world_state from repository or build it)
world_manager = WorldStateManager(world_state)

# Build agents from personas
agents = [WorldSimAgent(id=i, profile={...}) for i, p in enumerate(world_state.personas)]

# Build router with world env modules
router = WorldRouter(env_modules=[
    ObservationEnv(world_manager),
    RelationGraphEnv(world_manager),
    CommunicationEnv(world_manager),
    EventTimelineEnv(world_manager),
])

# Run simulation
engine = SimulationEngine(world_manager=world_manager, agents=agents, router=router)
run = await engine.run(steps=5, tick_seconds=300)
print(f"Completed {run.steps_executed} steps, {run.new_event_count} new events")
```

### REST API

```bash
# Build a world
curl -X POST http://localhost:8001/api/v1/worlds/build \
  -H "Content-Type: application/json" \
  -d '{"name": "Westland Simulation", "seed_materials": [{"kind": "text", "content": "..."}]}'

# Run simulation
curl -X POST http://localhost:8001/api/v1/worlds/{world_id}/simulate \
  -d '{"steps": 5}'

# Chat with the world
curl -X POST http://localhost:8001/api/v1/worlds/{world_id}/chat \
  -d '{"message": "What are the major tensions?"}'

# Chat with an agent
curl -X POST http://localhost:8001/api/v1/worlds/{world_id}/agents/{agent_id}/chat \
  -d '{"message": "Why are you opposing this policy?"}'

# Inject intervention
curl -X POST http://localhost:8001/api/v1/worlds/{world_id}/interventions \
  -d '{"intervention_type": "policy_shock", "payload": {"policy_name": "emergency tax", "severity": 0.8}}'

# Generate report
curl -X POST http://localhost:8001/api/v1/worlds/{world_id}/report \
  -d '{"report_type": "prediction", "focus": "What happens in the next 24 virtual hours?"}'
```

## Architecture

```
Seed Materials → SeedIngest → WorldExtractor → PersonaBuilder → GraphBuilder
                                                                       ↓
                                                               WorldState
                                                                       ↓
                                                           SimulationEngine
                                                     (WorldSimAgent × WorldRouter)
                                                                       ↓
                                                     WorldInteraction / ReportAgent
                                                                       ↓
                                                           FastAPI Backend
```

## Workspace Layout

- `agentsociety2/` - Python package source
- `backend/` - FastAPI backend implementation
- `examples/` - runnable world-building and simulation examples
- `experiments/legacy/` - legacy game-theory experiment entry scripts
- `configs/lab/` - legacy experiment configs and sample profiles
- `docs/` - package documentation and planning notes

### Key Modules

- **`agentsociety2/world/`** — Core world engine (models, extraction, simulation, interaction, reporting)
- **`agentsociety2/agent/world_sim_agent.py`** — Default agent for world simulation
- **`agentsociety2/env/router_world.py`** — WorldRouter (structured tool calling, no code gen)
- **`agentsociety2/contrib/env/llm_world/`** — Semantic world env modules (observation, relations, communication, events, interventions, reports)
- **`agentsociety2/backend/`** — FastAPI world simulation API

## Configuration

```bash
# Required
export AGENTSOCIETY_LLM_API_KEY="your-api-key"
export AGENTSOCIETY_LLM_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_LLM_MODEL="gpt-4o-mini"

# Optional: specialized models
export AGENTSOCIETY_CODER_LLM_MODEL="gpt-4o"         # for agent action calls
export AGENTSOCIETY_NANO_LLM_MODEL="gpt-4o-mini"      # for fast operations

# Backend
export BACKEND_HOST="0.0.0.0"
export BACKEND_PORT="8001"
export WORLD_DB_PATH="agentsociety_world.db"           # SQLite path
```

## Legacy / Reference Modules

The following modules are retained for reference but are **not part of the default pipeline**:

- `PersonAgent` — legacy human-centric agent (use `WorldSimAgent` instead)
- `SimpleSocialSpace`, `EventSpace` — legacy env modules (use `llm_world/` instead)
- `ReActRouter`, `PlanExecuteRouter` etc. — still available; `WorldRouter` is now default

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
