# Code snippet from Claude

# core/port.py
from pydantic import BaseModel
from typing import Any, Literal

class Port(BaseModel):
    name: str
    dtype: Literal["dataframe", "array", "model", "figure", "scalar"]
    required: bool = True


# core/node.py
from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict
from typing import ClassVar

class NodeParams(BaseModel):
    """À sous-classer par chaque nœud pour typer ses paramètres."""
    model_config = ConfigDict(extra="forbid")


class Node(ABC):
    # Métadonnées de classe, utilisées par le registry et l'UI
    node_type: ClassVar[str]                # identifiant unique, ex: "csv_loader"
    category: ClassVar[str]                 # "loading" | "transform" | "model" | "viz" | "export"
    inputs: ClassVar[list[Port]] = []
    outputs: ClassVar[list[Port]] = []
    params_schema: ClassVar[type[NodeParams]] = NodeParams

    def __init__(self, params: NodeParams):
        self.params = params

    @abstractmethod
    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Reçoit les inputs par nom de port (ex: inputs["df"]),
        retourne un dict {nom_de_port_sortie: valeur}.
        """
        ...

    def validate_inputs(self, inputs: dict[str, Any]) -> None:
        required = {p.name for p in self.inputs if p.required}
        missing = required - inputs.keys()
        if missing:
            raise ValueError(f"{self.node_type}: ports manquants {missing}")