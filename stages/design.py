from .base import BaseStage
from pipelines.architect import ArchitectPipeline
from core.state import DesignState
import json

class DesignStage(BaseStage):
    def __init__(self, state: dict, client=None, logger=None):
        super().__init__(state, client, logger)
        # We wrap the ArchitectPipeline here
        self.pipeline = ArchitectPipeline("session", state, client, logger) 

    def run(self, user_text: str):
        """
        Returns a generator yielding events.
        """
        try:
            # Sync pipeline state with stage state (which comes from session)
            # This ensures manual UI updates are reflected in the pipeline
            if self.state:
                self.pipeline.state = DesignState(**self.state)

            # Consume the generator from the pipeline
            # The pipeline is the governor. The stage is the adapter.
            gen = self.pipeline.run(user_text)
            
            for event in gen:
                event_type = event.get("type")
                
                if event_type == "status":
                    yield f"event: status\ndata: {json.dumps({'message': event['message']})}\n\n"
                    
                elif event_type == "state_update":
                    self.state = event["state"] # Sync local state
                    yield f"event: state_update\ndata: {json.dumps({'state': self.state})}\n\n"
                    
                elif event_type == "result":
                    payload = {
                        "response": {
                            "text": event["text"],
                            "code": event.get("code")
                        },
                        "metrics": event.get("metrics", {})
                    }
                    yield f"event: review\ndata: {json.dumps(payload)}\n\n"
                    
                elif event_type == "error":
                    yield f"event: error\ndata: {json.dumps({'error': event['message']})}\n\n"
            
            yield "event: done\ndata: {}\n\n"
            
        except Exception as e:
            yield "event: error\ndata: " + json.dumps({"error": str(e)}) + "\n\n"
