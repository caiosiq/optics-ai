from typing import Any
from .base import BasePipeline
from agents.thinker import ThinkerAgent
from agents.drafter import DrafterAgent
from agents.reviewer import ReviewerAgent
from optics_mcp.tools.execution import exec_python_sandbox

class PhysicsPipeline(BasePipeline):
    def __init__(self, client=None, logger=None):
        super().__init__(logger)
        self.thinker = ThinkerAgent(client, logger)
        self.drafter = DrafterAgent(client, logger)
        self.reviewer = ReviewerAgent(client, logger)

    def run(self, task: str, context: str, state: dict) -> dict:
        if self.logger:
            self.logger.log_text("physics_request", f"Task: {task}\nContext: {context}")

        # 1. THINKER
        plan = self.thinker.run(task, context, state.get("params", []))
        
        if self.logger:
            self.logger.log_text("physics_thinker_output", plan)

        # 2. DRAFTER
        code = self.drafter.run(task, plan)
        
        if self.logger:
            self.logger.log_text("physics_drafter_output", code)

        # 3. EXECUTOR
        if self.logger:
            self.logger.log_text("physics_execution_start", "Running sandbox...")
            
        exec_result = exec_python_sandbox(code, timeout_s=60)
        exec_output = exec_result.get("output", "")
        exec_images = exec_result.get("images", [])
        
        if self.logger:
            self.logger.log_json("physics_execution_result", exec_result)

        # 4. REVIEWER
        review_result = self.reviewer.run(task, plan, code, exec_output)
        
        if self.logger:
            self.logger.log_json("physics_reviewer_output", review_result)

        return {
            "plan": plan,
            "code": review_result.get("final_code", code),
            "review": review_result,
            "exec_output": exec_output,
            "exec_images": exec_images
        }
