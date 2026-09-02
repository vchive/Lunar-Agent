"""Standalone local Hermes-inspired agent controller."""

from .evolution import (
    Candidate,
    CandidateArchive,
    CandidateDraft,
    CommandCandidateEvaluator,
    CommandCandidateGenerator,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    EvolutionStrategy,
    GenerationRequest,
    LoopStrategy,
    OpenEvolveStrategy,
    PopulationConfig,
    PopulationState,
    PopulationStrategy,
    StrategyResult,
    build_strategy,
    config_from_contract,
)

__version__ = "0.1.0"

__all__ = [
    "Candidate",
    "CandidateArchive",
    "CandidateDraft",
    "CommandCandidateEvaluator",
    "CommandCandidateGenerator",
    "EvolutionConfig",
    "EvolutionContext",
    "EvolutionError",
    "EvolutionStrategy",
    "GenerationRequest",
    "LoopStrategy",
    "OpenEvolveStrategy",
    "PopulationConfig",
    "PopulationState",
    "PopulationStrategy",
    "StrategyResult",
    "build_strategy",
    "config_from_contract",
]
