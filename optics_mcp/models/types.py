from typing import Optional, List
from pydantic import BaseModel, Field

class Element(BaseModel):
    type: str
    material: str
    radius_front_mm: float
    radius_back_mm: float
    thickness_mm: float

class JsonFile(BaseModel):
    system: str
    elements: List[Element]
    spacing_mm: List[float]
    wavelength_nm: float

class CodeMeta(BaseModel):
    files_expected: List[str] = Field(default_factory=list)

class OpticsAgentResponse(BaseModel):
    text: Optional[str] = None
    code: Optional[str] = None
    code_meta: Optional[CodeMeta] = None
    json_file: Optional[JsonFile] = None
