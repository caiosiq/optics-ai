from .base import BaseStage
from pipelines.construction import ConstructorPipeline
from core.state import Parameter

class ConstructionStage(BaseStage):
    def __init__(self, state: dict, client=None, logger=None):
        super().__init__(state, client, logger)
        self.pipeline = ConstructorPipeline(client, logger)

    def generate_plan(self) -> dict:
        """
        Generates the Lab Plan.
        """
        # Prepare parameters
        params_dicts = self.state.get("design_parameters", [])
        params_objs = [Parameter(**p) for p in params_dicts]
        
        goal = self.state.get("goal", "")
        inventory = self.state.get("inventory", "")
        
        result = self.pipeline.run(goal, params_objs, inventory)
        
        # Update state with the plan
        self.state["lab_plan"] = result.get("lab_plan", [])
        self.state["construction_thought"] = result.get("thought_process", "")
        
        return {
            "lab_plan": self.state["lab_plan"],
            "thought_process": self.state["construction_thought"]
        }

    def run(self, user_text: str):
        """
        Legacy run method if called via chat flow.
        """
        yield {"type": "error", "message": "Construction stage does not support chat. Use /generate_lab_plan."}
