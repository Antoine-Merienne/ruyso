"""
Port definitions for pipeline nodes.

A Port describes a single named input or output of a Node, including
the kind of data it carries (its ``dtype``) and whether it is mandatory.
Ports are pure metadata: they contain no logic and no reference to any
UI or execution engine, so this module has zero dependencies beyond
pydantic. Both the engine (layer 2) and the UI (layer 3) can rely on
this same definition to validate connections between nodes.
"""

from typing import Literal

from pydantic import BaseModel

# Allowed data kinds flowing between nodes.
# Kept as a closed set (Literal) so that the engine and UI can safely
# switch/validate on it without guessing at arbitrary strings.
# "geodataframe" is a specialisation of "dataframe": a geopandas
# GeoDataFrame is a pandas DataFrame subclass, so a "geodataframe"
# output may feed a plain "dataframe" input (but not the reverse) --
# see ``engine.graph`` for that compatibility rule.
PortDType = Literal[
    "dataframe", "geodataframe", "array", "model", "figure", "scalar"
]


class Port(BaseModel):
    """
    Describes a single input or output slot of a Node.

    Attributes:
        name: Unique identifier of the port within its node
            (e.g. "df", "model", "figure"). Used as the key in the
            dict passed to / returned from Node.run().
        dtype: The kind of data carried by this port. Used to validate
            that two connected ports are compatible.
        required: Whether this port must be connected (for inputs) or
            is always produced (for outputs). Optional inputs may be
            omitted by the user in the graph.
    """

    name: str
    dtype: PortDType
    required: bool = True
