"""Un modèle par agent (contrat : agents.model, max_tokens, limits), lu dans la config.

Le même identifiant d'agent sert de clé ici, pour la toolbox, pour name= de
l'Agent Strands et pour agentId des journaux. max_tokens est TOUJOURS fixé :
sans lui, Bedrock réserve le maximum du modèle contre le quota du compte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.common import config

REGION = "us-east-1"


@dataclass(frozen=True)
class AgentSpec:
    model_id: Callable[[], str | None]
    max_tokens: int
    timeout_seconds: int
    max_turns: int


MODELS: dict[str, AgentSpec] = {
    "agent-orchestrator": AgentSpec(config.model_orchestrator, 4096, 30, 8),
    "agent-auditor": AgentSpec(config.model_auditor, 4096, 60, 18),
    "agent-writer": AgentSpec(config.model_writer, 8192, 60, 6),
}

TRANSLATION_SPEC = AgentSpec(config.model_orchestrator, 8192, 30, 1)

_CACHE: dict[tuple[str, str, int, int], object] = {}


def model_id(agent_id: str) -> str:
    value = MODELS[agent_id].model_id()
    if not value:
        raise RuntimeError(f"No Bedrock model configured for {agent_id}")
    return value


def create_model(agent_id: str, *, spec: AgentSpec | None = None):
    """BedrockModel de l'agent, réutilisé entre invocations chaudes (l'Agent, lui, est recréé)."""
    active_spec = spec or MODELS[agent_id]
    cache_key = (agent_id, model_id(agent_id), active_spec.max_tokens, active_spec.timeout_seconds)
    if cache_key not in _CACHE:
        from botocore.config import Config
        from strands.models.bedrock import BedrockModel

        _CACHE[cache_key] = BedrockModel(
            model_id=cache_key[1],
            max_tokens=active_spec.max_tokens,
            region_name=REGION,
            boto_client_config=Config(read_timeout=active_spec.timeout_seconds + 5, retries={"max_attempts": 2, "mode": "standard"}),
        )
    return _CACHE[cache_key]
