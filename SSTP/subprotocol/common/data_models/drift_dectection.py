from pydantic import BaseModel, Field

class DriftDetectionOutput(BaseModel): ## Formerly SAVOutput
    name: str = Field(..., description="Name of the drift detection method")