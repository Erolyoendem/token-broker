"""
TokenBroker – Agent Swarm Package
==================================
Self-optimising multi-agent system for code conversion tasks.

Components
----------
memory           – Persistent storage of conversions, scores, prompt variants
base_agent       – Abstract lifecycle base class shared by all agents
generation_agent – Produces Python code from Ruby using prompt-variant selection
evaluation_agent – Scores generated code (syntax + structural quality)
orchestrator     – Coordinates agents, meta-cognition, prompt optimisation
"""

from .memory import SwarmMemory
from .base_agent import BaseAgent
from .generation_agent import GenerationAgent
from .evaluation_agent import EvaluationAgent
from .orchestrator import Orchestrator

__all__ = [
    "SwarmMemory",
    "BaseAgent",
    "GenerationAgent",
    "EvaluationAgent",
    "Orchestrator",
]
