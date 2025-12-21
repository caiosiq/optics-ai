from pydantic import ValidationError
from optics_mcp.models.types import OpticsAgentResponse

def validate_ui_output(candidate: dict) -> dict:
    try:
        OpticsAgentResponse.model_validate(candidate)
        return {"ok": True, "errors": []}
    except ValidationError as ve:
        return {"ok": False, "errors": [str(ve)]}
