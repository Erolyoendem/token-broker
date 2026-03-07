"""
TokenBroker – Agent Evolution Package
======================================
Reinforcement-learning layer on top of the agent_swarm package.

Components
----------
rl_agent  – DQN agent that learns which prompt variant to use per task
trainer   – Offline trainer that replays SwarmMemory experiences
"""

from .rl_agent import RLAgent, extract_state, ACTIONS
from .trainer import train_from_memory, train_combined
from .train_from_data import train_from_db
from .prompt_optimizer import EvolutionPromptOptimizer, run_optimization_once, schedule_weekly

__all__ = [
    "RLAgent", "extract_state", "ACTIONS",
    "train_from_memory", "train_combined", "train_from_db",
    "EvolutionPromptOptimizer", "run_optimization_once", "schedule_weekly",
]
