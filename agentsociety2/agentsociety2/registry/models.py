"""
Data models for module initialization and configuration.
"""

from datetime import datetime
from typing import Any, Dict, List
from pydantic import BaseModel, Field

__all__ = [
    "EnvModuleInitConfig",
    "AgentInitConfig",
    "CreateInstanceRequest",
    "AskRequest",
    "InterventionRequest",
]


class EnvModuleInitConfig(BaseModel):
    """Configuration for initializing an environment module."""

    module_type: str = Field(
        ...,
        description="The type of environment module (e.g., 'global_information', 'economy_space', 'social_space', 'observation_env', 'communication_env', 'event_timeline_env')",
    )

    args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Module initialization arguments (excluding llm). These arguments are passed directly to the module constructor. See mcp_description() for the module's expected parameters and JSON schemas.",
    )


class AgentInitConfig(BaseModel):
    """Configuration for initializing an agent."""

    agent_type: str = Field(
        ..., description="The type of agent (e.g., 'person_agent', 'custom_agent')"
    )

    agent_id: int = Field(..., description="Unique ID for the agent")

    args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Agent initialization arguments (excluding llm and env which are set via init() method). All other parameters including 'id', 'profile', 'memory_config', etc. should be included here. See mcp_description() for the agent's expected parameters.",
    )


class CreateInstanceRequest(BaseModel):
    """Request to create a new AgentSociety instance."""

    instance_id: str = Field(
        ..., description="Unique identifier for this society instance"
    )

    env_modules: List[EnvModuleInitConfig] = Field(
        ..., min_length=1, description="List of environment modules to initialize"
    )

    agents: List[AgentInitConfig] = Field(
        ..., min_length=1, description="List of agents to initialize"
    )

    start_t: datetime = Field(..., description="Simulation start time")

    tick: int = Field(
        1, ge=1, description="Tick duration in seconds for run operations"
    )


class AskRequest(BaseModel):
    """Request to ask or intervene in a society instance."""

    instance_id: str = Field(..., description="The ID of the society instance")

    question: str = Field(..., description="The question to ask")


class InterventionRequest(BaseModel):
    """Request to intervene in a society instance."""

    instance_id: str = Field(..., description="The ID of the society instance")

    instruction: str = Field(..., description="The intervention instruction")
