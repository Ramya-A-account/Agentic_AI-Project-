"""
Every AgentCare agent (Simulation, Cleaning, Analysis, Alert Detection, ...)
implements this same contract. This is what lets the Orchestrator call any
agent uniformly and log its execution status consistently (Assumption 11/13).
"""
from abc import ABC, abstractmethod
from datetime import datetime


class Agent(ABC):
    """Base class every agent inherits from."""

    name: str = "UnnamedAgent"

    @abstractmethod
    def run(self, context: dict) -> dict:
        """
        Execute the agent's job.

        context: dict of inputs the Orchestrator passes in (e.g. window_start,
                 window_end, session, etc.)

        Returns a dict that MUST include at least:
            {"status": "SUCCESS" | "FAILED", ...agent-specific outputs}

        Agents should never raise uncaught exceptions back to the Orchestrator;
        catch internally and return status="FAILED" with an "error" message,
        so the Orchestrator can log it and decide whether to halt downstream
        agents (Assumption 13 — failure handling).
        """
        raise NotImplementedError


def utcnow():
    return datetime.utcnow()
