"""
Example: Chat with the world and with individual agents.

Usage:
    # First build and simulate:
    python examples/build_world_from_text.py
    python examples/run_world_simulation.py

    # Then chat:
    python examples/chat_with_world_agent.py

Requires:
    AGENTSOCIETY_LLM_API_KEY, AGENTSOCIETY_LLM_API_BASE, AGENTSOCIETY_LLM_MODEL
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from agentsociety2.world import WorldRepository, WorldStateManager, WorldInteraction, ReportAgent
from agentsociety2.agent.world_sim_agent import WorldSimAgent

WORLD_ID = "westland_001"


async def main():
    db_path = os.getenv("WORLD_DB_PATH", "westland_world.db")
    repo = WorldRepository(db_path=db_path)

    world_state = repo.load_world_state(WORLD_ID)
    if world_state is None:
        print(f"World '{WORLD_ID}' not found.")
        return

    print(f"=== World: {world_state.name} (tick={world_state.current_tick}) ===\n")

    world_manager = WorldStateManager(world_state)

    # Build agents
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
            "stance_map": persona.stance_map,
            "behavior_style": persona.behavior_style,
            "speech_style": persona.speech_style,
            "memory_seeds": persona.memory_seeds,
        }
        agents.append(WorldSimAgent(id=i, profile=profile, name=profile["name"]))

    interaction = WorldInteraction(world_manager=world_manager, agents=agents)

    # --- Type A: Chat with the world ---
    print("=== Chat with World ===")
    questions = [
        "What are the major factions and their current positions?",
        "What tensions are most likely to escalate next?",
    ]
    for q in questions:
        print(f"\nQ: {q}")
        result = await interaction.chat_with_world(q)
        print(f"A: {result['answer'][:500]}")

    # --- Type B: Chat with a specific agent ---
    if agents:
        first_agent = agents[0]
        agent_entity_id = first_agent._profile.get("entity_id", str(first_agent.id))
        print(f"\n=== Chat with Agent: {first_agent._name} ===")
        agent_questions = [
            "What is your primary goal right now?",
            "What do you think about the Renewable Energy Reform Act?",
        ]
        for q in agent_questions:
            print(f"\nQ: {q}")
            result = await interaction.chat_with_agent(agent_entity_id, q)
            print(f"A: {result['answer'][:500]}")

    # --- Generate a report ---
    print("\n=== Generating Prediction Report ===")
    report_agent = ReportAgent(world_manager)
    report = await report_agent.generate(
        report_type="prediction",
        focus="What is most likely to happen with the RERA vote in the next 24 virtual hours?",
    )
    repo.save_report(report)
    print(f"Report ID: {report.report_id}")
    print(f"\n{report.content[:1000]}")


if __name__ == "__main__":
    asyncio.run(main())
