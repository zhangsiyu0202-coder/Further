"""
Example: Run a multi-step simulation on an existing world.

Usage:
    # First build the world:
    python examples/build_world_from_text.py

    # Then run the simulation:
    python examples/run_world_simulation.py

Requires:
    AGENTSOCIETY_LLM_API_KEY, AGENTSOCIETY_LLM_API_BASE, AGENTSOCIETY_LLM_MODEL
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from agentsociety2.world import (
    WorldRepository,
    WorldStateManager,
    SimulationEngine,
)
from agentsociety2.agent.world_sim_agent import WorldSimAgent
from agentsociety2.env.router_world import WorldRouter
from agentsociety2.contrib.env.llm_world import (
    ObservationEnv,
    RelationGraphEnv,
    CommunicationEnv,
    EventTimelineEnv,
)

WORLD_ID = "westland_001"
STEPS = 3


async def main():
    db_path = os.getenv("WORLD_DB_PATH", "westland_world.db")
    repo = WorldRepository(db_path=db_path)

    # Load world
    world_state = repo.load_world_state(WORLD_ID)
    if world_state is None:
        print(f"World '{WORLD_ID}' not found. Run build_world_from_text.py first.")
        return

    print(f"=== Running Simulation: {world_state.name} ===")
    print(f"Starting tick: {world_state.current_tick}")
    print(f"Entities: {len(world_state.entities)}, Agents: {len(world_state.personas)}\n")

    # Build world manager
    world_manager = WorldStateManager(world_state)

    # Build agents from personas
    entity_map = {e.id: e for e in world_state.entities}
    agents = []
    for i, persona in enumerate(world_state.personas):
        entity = entity_map.get(persona.entity_id)
        profile = {
            "entity_id": persona.entity_id,
            "name": entity.name if entity else f"Agent_{i}",
            "entity_kind": entity.entity_type if entity else "person",
            "identity_summary": persona.identity_summary,
            "goals": persona.goals,
            "fears": persona.fears,
            "preferences": persona.preferences,
            "stance_map": persona.stance_map,
            "behavior_style": persona.behavior_style,
            "speech_style": persona.speech_style,
            "memory_seeds": persona.memory_seeds,
        }
        agents.append(WorldSimAgent(id=i, profile=profile, name=profile["name"]))

    # Build env modules
    env_modules = [
        ObservationEnv(world_manager),
        RelationGraphEnv(world_manager),
        CommunicationEnv(world_manager),
        EventTimelineEnv(world_manager),
    ]

    # Build router
    router = WorldRouter(env_modules=env_modules)

    # Run simulation
    engine = SimulationEngine(
        world_manager=world_manager,
        agents=agents,
        router=router,
    )

    print(f"Running {STEPS} simulation steps...\n")
    run = await engine.run(steps=STEPS, tick_seconds=300)

    print(f"\n=== Simulation Complete ===")
    print(f"Run ID:         {run.run_id}")
    print(f"Steps executed: {run.steps_executed}")
    print(f"New events:     {run.new_event_count}")
    print(f"Final tick:     {world_manager.current_tick}")

    print("\n=== Recent Events ===")
    for evt in world_manager.get_recent_events(limit=10):
        print(f"  [tick {evt.tick}] [{evt.event_type}] {evt.title}")
        print(f"    {evt.description[:100]}")

    # Persist updated state
    snapshot = world_manager.snapshot()
    repo.save_world_state(snapshot)
    repo.save_snapshot(snapshot)
    repo.save_run(run)
    repo.save_events(WORLD_ID, world_manager.get_recent_events(limit=100), run.run_id)
    print(f"\nWorld saved. Next step: run examples/chat_with_world_agent.py")


if __name__ == "__main__":
    asyncio.run(main())
