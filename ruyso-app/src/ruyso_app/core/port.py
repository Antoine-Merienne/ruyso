# Code snippet from Claude

# core/port.py
from pydantic import BaseModel
from typing import Any, Literal

class Port(BaseModel):
    name: str
    dtype: Literal["dataframe", "array", "model", "figure", "scalar"]
    required: bool = True