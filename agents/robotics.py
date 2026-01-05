from .base import BaseAgent
from core.llm import call_openrouter
from core.config import load_config
import pathlib

class RoboticsEngineerAgent(BaseAgent):
    def __init__(self, client=None, logger=None):
        super().__init__(client, logger)
        self.role = "Senior Robotics Integration Engineer"
        
        # Load API specs
        try:
            specs_path = pathlib.Path("knowledge/robot_api_specs.txt")
            if specs_path.exists():
                self.api_specs = specs_path.read_text(encoding="utf-8")
            else:
                self.api_specs = "API Specs not found."
        except Exception:
            self.api_specs = "API Specs not found."

    def run(self, lab_plan: list) -> str:
        print(f"[RoboticsEngineerAgent] Generating code for {len(lab_plan)} components")
        
        system_prompt = f"""
Role: You are the Senior Robotics Integration Engineer for an experimental physics lab. Your job is to take a theoretical optical design (JSON) and write an executable Python script to build it using the lab_automation library.

Inputs:
Design JSON: A list of optical components with relative coordinates.
Lab Context:
Robot Base is located 300mm away from the Optical Table Start in X and 100mm in Y.
Library import: from lab_automation.builder import OpticalBuilderBot

Instructions:
1. Analyze the JSON: Identify the sequence of components. The order in the JSON is the order of assembly.
2. Initialize the Bot: Use the specific Lab Context calibration values (x=300, y=100).
3. Generate the Build Loop: For each item in the JSON:
    - Call bot.fetch_component() using the type field.
    - Call bot.place_component() using the position.x, position.y, and orientation fields.
4. Safety First: Ensure the script ends with bot.finish_assembly().
5. Output Format: Output ONLY the Python code block. No conversational filler. Use comments to explain which component is being placed.

Context - Robot API Specs:
{self.api_specs}
"""
        
        user_message = f"Generate the robot assembly script for this lab plan:\n{lab_plan}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        try:
            response_tuple = call_openrouter(messages, model=load_config().get("models", {}).get("drafter_model", "google/gemini-2.0-flash-exp"))
            content = response_tuple[0]
            
            if not content:
                return "# Error: No response from LLM."

            # Clean up response (remove markdown code fences if present)
            if isinstance(content, str):
                code = content.strip()
            else:
                code = str(content).strip()
                
            if code.startswith("```python"):
                code = code[9:]
            if code.startswith("```"):
                code = code[3:]
            if code.endswith("```"):
                code = code[:-3]
                
            return code.strip()
        except Exception as e:
            print(f"[RoboticsEngineerAgent] Error: {e}")
            return f"# Error generating code: {e}"
