from .base import BasePipeline
from agents.robotics import RoboticsEngineerAgent

class AssemblyPipeline(BasePipeline):
    def __init__(self, client=None, logger=None):
        super().__init__(logger)
        self.agent = RoboticsEngineerAgent(client, logger)

    def run(self, lab_plan: list) -> dict:
        if self.logger:
            self.logger.log_text("assembly_start", "Generating robot code")
            
        code = self.agent.run(lab_plan)
        
        if self.logger:
            self.logger.log_text("assembly_complete", "Code generated")
            
        return {
            "robot_code": code
        }
