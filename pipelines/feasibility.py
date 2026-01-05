from typing import Any
from .base import BasePipeline
from agents.feasibility import FeasibilityAgent

class FeasibilityPipeline(BasePipeline):
    def __init__(self, client=None, logger=None):
        super().__init__(logger)
        self.agent = FeasibilityAgent(client, logger)

    def run(self, goal: str, inventory: str) -> dict:
        if self.logger:
            self.logger.log_text("feasibility_start", f"Goal: {goal}")

        return self.agent.run(goal, inventory)
