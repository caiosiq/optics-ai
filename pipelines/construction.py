from typing import Any
from .base import BasePipeline
from agents.constructor import ConstructorAgent

class ConstructorPipeline(BasePipeline):
    def __init__(self, client=None, logger=None):
        super().__init__(logger)
        self.agent = ConstructorAgent(client, logger)

    def run(self, goal: str, params: list, inventory: str) -> dict:
        if self.logger:
            self.logger.log_text("construction_start", f"Goal: {goal}")

        return self.agent.run(goal, params, inventory)
