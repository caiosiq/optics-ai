from typing import Any, Optional, Generator
from stages.base import BaseStage
from stages.feasibility import FeasibilityStage
from stages.design import DesignStage
from stages.construction import ConstructionStage
from stages.robot import RobotStage
from core.logging import SessionLogger

class Session:
    def __init__(self, session_id: str, state: dict = None, client=None):
        self.session_id = session_id
        self.state = state or {}
        self.client = client
        self.logger = SessionLogger(session_id)
        
        # Initialize Stage based on state
        self.current_stage = self._get_stage_from_state()

    def _get_stage_from_state(self) -> BaseStage:
        stage_name = self.state.get("stage", "FEASIBILITY")
        
        if stage_name == "DESIGN":
            return DesignStage(self.state, self.client, self.logger)
        elif stage_name == "CONSTRUCTION":
            return ConstructionStage(self.state, self.client, self.logger)
        elif stage_name == "ROBOT_ASSEMBLY":
            return RobotStage(self.state, self.client, self.logger)
        else:
            # Default or Feasibility
            return FeasibilityStage(self.state, self.client, self.logger)

    def update_state(self, new_state: dict):
        self.state = new_state
        # Check if stage changed
        current_stage_name = self.state.get("stage")
        
        # Transition logic
        # Ideally we could just re-instantiate based on name, but we want to keep instances if same
        # But for simplicity and to handle transitions cleanly:
        
        # Check current class vs expected class
        expected_class = FeasibilityStage
        if current_stage_name == "DESIGN":
            expected_class = DesignStage
        elif current_stage_name == "CONSTRUCTION":
            expected_class = ConstructionStage
        elif current_stage_name == "ROBOT_ASSEMBLY":
            expected_class = RobotStage
            
        if not isinstance(self.current_stage, expected_class):
            if expected_class == DesignStage:
                self.current_stage = DesignStage(self.state, self.client, self.logger)
            elif expected_class == ConstructionStage:
                self.current_stage = ConstructionStage(self.state, self.client, self.logger)
            elif expected_class == RobotStage:
                self.current_stage = RobotStage(self.state, self.client, self.logger)
            else:
                self.current_stage = FeasibilityStage(self.state, self.client, self.logger)
        
        # Update stage's internal state reference
        self.current_stage.state = self.state

    def run_init(self, goal: str, inventory: str) -> dict:
        """Helper for Feasibility Stage (sync)"""
        if isinstance(self.current_stage, FeasibilityStage):
            res = self.current_stage.run(goal, inventory)
            if "state" in res:
                self.update_state(res["state"])
            return res
        return {"error": "Invalid stage for init"}

    def run_generation(self) -> dict:
        """Helper for Construction Stage (sync)"""
        if isinstance(self.current_stage, ConstructionStage):
            res = self.current_stage.generate_plan()
            # Construction stage updates state internally in generate_plan
            self.state = self.current_stage.state
            # Check if we should auto-transition? 
            # User said: "I can press to download it, or to load it to the next stage"
            # So transition is manual via another call.
            return res
        return {"error": "Invalid stage for generation"}

    def run_assembly(self) -> dict:
        """Helper for Robot Stage (sync)"""
        if isinstance(self.current_stage, RobotStage):
            res = self.current_stage.generate_code()
            self.state = self.current_stage.state
            return res
        return {"error": "Invalid stage for assembly"}

    def run_chat(self, message: str) -> Generator[Any, None, None]:
        """Helper for Design/Robot Stage (async/generator)"""
        if isinstance(self.current_stage, (DesignStage, RobotStage)):
            gen = self.current_stage.run(message)
            for event in gen:
                if isinstance(event, str) and "state_update" in event:
                    try:
                        import json
                        data_line = [line for line in event.splitlines() if line.startswith("data:")][0]
                        data_json = data_line[5:].strip()
                        data = json.loads(data_json)
                        if "state" in data:
                            self.state = data["state"]
                    except Exception as e:
                        if self.logger:
                            self.logger.log_text("session_state_update_error", str(e))
                yield event
            
            self.state = self.current_stage.state
            self.update_state(self.state)
        else:
            yield "event: error\ndata: {\"error\": \"Current stage does not support chat\"}\n\n"
