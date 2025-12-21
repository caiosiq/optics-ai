from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class Parameter(BaseModel):
    name: str
    description: str
    unit: Optional[str] = None
    value: Any = None
    status: str = "missing" # missing, set, inferred

class DesignState(BaseModel):
    stage: str = "INIT" # INIT, DESIGN, OPTIMIZATION, DONE
    goal: str
    inventory: str
    component_properties: List[Parameter] = Field(default_factory=list)
    design_parameters: List[Parameter] = Field(default_factory=list)
    design_scheme: str = "" # Text description of the layout/scheme
    feasibility: bool = False
    reason: str = ""
    history: List[str] = Field(default_factory=list)

    def update_param(self, name: str, value: Any, section: str = "both"):
        """
        Update a parameter value by name.
        section: 'component', 'design', or 'both'
        """
        found = False
        
        # Check component_properties
        if section in ["component", "both"]:
            for p in self.component_properties:
                if p.name == name:
                    p.value = value
                    p.status = "set" if value is not None else "missing"
                    found = True
        
        # Check design_parameters
        if section in ["design", "both"]:
            for p in self.design_parameters:
                if p.name == name:
                    p.value = value
                    p.status = "set" if value is not None else "missing"
                    found = True
                    
        return found

    def is_complete(self) -> bool:
        c_ok = all(p.value is not None for p in self.component_properties)
        d_ok = all(p.value is not None for p in self.design_parameters)
        return c_ok and d_ok
