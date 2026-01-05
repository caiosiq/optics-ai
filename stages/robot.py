from .base import BaseStage
from pipelines.assembly import AssemblyPipeline

class RobotStage(BaseStage):
    def __init__(self, state: dict, client=None, logger=None):
        super().__init__(state, client, logger)
        self.pipeline = AssemblyPipeline(client, logger)

    def generate_code(self) -> dict:
        """
        Generates the Robot Python Code.
        """
        lab_plan = self.state.get("lab_plan", [])
        if not lab_plan:
             return {"error": "No lab plan found in state. Please complete Construction stage first."}

        result = self.pipeline.run(lab_plan)
        
        # Update state
        self.state["robot_code"] = result.get("robot_code", "")
        
        return {
            "robot_code": self.state["robot_code"]
        }

    def run(self, user_text: str):
        """
        Legacy run method if called via chat flow.
        """
        yield {"type": "error", "message": "Robot stage does not support chat. Use /generate_robot_code."}
