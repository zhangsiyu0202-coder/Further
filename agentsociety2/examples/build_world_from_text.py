"""
Example: Build a virtual world from a text seed material.

Usage:
    python examples/build_world_from_text.py

Requires:
    AGENTSOCIETY_LLM_API_KEY, AGENTSOCIETY_LLM_API_BASE, AGENTSOCIETY_LLM_MODEL
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from agentsociety2.world import (
    SeedIngest,
    WorldExtractor,
    PersonaBuilder,
    GraphBuilder,
    WorldStateManager,
    WorldRepository,
)


SEED_TEXT = """
The parliament of Westland is deeply divided over the Renewable Energy Reform Act (RERA).
The Progressive Alliance, led by Prime Minister Elena Voss, champions RERA as essential
for climate goals. The Conservative Coalition, led by opposition leader Marcus Webb,
argues it will raise energy prices and harm manufacturing jobs.

DigiForce, a powerful technology lobbying group, has quietly donated to both parties,
hoping to secure lucrative contracts for smart-grid infrastructure regardless of who wins.
The national newspaper 'Westland Tribune' leans conservative but has been running
investigative stories suggesting DigiForce's influence on Webb.

Public opinion is split: urban voters support the reform; rural and industrial regions oppose it.
A key swing vote is independent Senator Lyra Marsh, who has not declared her position.
"""


async def main():
    print("=== Building World from Text ===\n")

    # 1. Ingest seed materials
    ingest = SeedIngest()
    materials = ingest.ingest(SEED_TEXT)
    print(f"Ingested {len(materials)} seed material(s)\n")

    # 2. Extract world elements via LLM
    print("Running LLM extraction...")
    extractor = WorldExtractor()
    extraction = await extractor.extract(
        seed_materials=materials,
        world_goal="Simulate the political dynamics and predict the outcome of the vote on RERA.",
        constraints=[
            "Do not invent entities not implied by the seed material",
            "Focus on political and social dynamics",
        ],
    )
    print(f"Extracted: {len(extraction.entities)} entities, "
          f"{len(extraction.relations)} relations, "
          f"{len(extraction.events)} events\n")

    print("Build summary:")
    print(f"  {extraction.build_summary}\n")

    # 3. Generate agent personas
    print("Generating personas...")
    persona_builder = PersonaBuilder(max_agents=10)
    personas = await persona_builder.build_all(
        entities=extraction.entities,
        relations=extraction.relations,
        world_context=extraction.build_summary,
    )
    print(f"Generated {len(personas)} persona(s)\n")

    # 4. Assemble world graph
    print("Assembling world graph...")
    graph_builder = GraphBuilder()
    world_state = await graph_builder.build(
        world_id="westland_001",
        world_name="Westland Political Simulation",
        extraction=extraction,
        personas=personas,
    )

    manager = WorldStateManager(world_state)
    print("World state assembled!\n")
    print(manager.to_summary_text())

    # 5. Persist world
    db_path = os.getenv("WORLD_DB_PATH", "westland_world.db")
    repo = WorldRepository(db_path=db_path)
    repo.save_world_state(world_state)
    repo.save_snapshot(world_state)
    print(f"\nWorld saved to: {db_path}")
    print(f"World ID: {world_state.world_id}")
    print("\nNext step: run examples/run_world_simulation.py")


if __name__ == "__main__":
    asyncio.run(main())
