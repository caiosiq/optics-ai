from .base import BaseStage
from pipelines.feasibility import FeasibilityPipeline

class FeasibilityStage(BaseStage):
    def __init__(self, state: dict = None, client=None, logger=None):
        # Feasibility might not have state yet, or creates it
        super().__init__(state, client, logger)
        self.pipeline = FeasibilityPipeline(client, logger)

    def run(self, goal: str, inventory: str) -> dict:
        # Delegate to pipeline
        resp = self.pipeline.run(goal, inventory)
        
        # Initialize Design State structure from response
        # The Stage is responsible for state transition logic
        state_dict = {
            "stage": "DESIGN", # Transition to Design if feasible
            "goal": goal,
            "inventory": inventory,
            "component_properties": resp.get("component_properties", []),
            "design_parameters": resp.get("design_parameters", []),
            "design_scheme": resp.get("design_scheme", ""),
            "feasibility": resp.get("feasible"),
            "reason": resp.get("reason")
        }
        
        if not resp.get("feasible"):
            state_dict["stage"] = "FEASIBILITY_FAILED"

        return {
            "state": state_dict,
            "message": f"**Feasibility Analysis**: {resp.get('reason')}\n\n" + 
                       ("I have initialized the design state." if resp.get('feasible') else "WARNING: Not feasible.")
        }
