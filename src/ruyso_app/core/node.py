"""
Abstract base class for all pipeline nodes.

A Node represents a single unit of work in a data science pipeline
(loading data, transforming it, fitting a model, plotting a figure,
etc.). This module defines only the *contract* every concrete node
must follow — it has no knowledge of pandas, scikit-learn, or any
other library, and no knowledge of the execution engine or the UI.
Concrete nodes (CSVLoader, DropNA, ...) live in the ``nodes/`` package
and import whatever library they need internally.

Design notes
------------
- ``params_schema`` is a pydantic model describing the node's
  configurable parameters. Splitting parameters into their own model
  (rather than plain __init__ arguments) means:
    1. Parameters are validated automatically at construction time.
    2. The same schema can be introspected later (via
       ``model_fields``) to auto-generate a property form in the UI,
       without writing any UI-specific code in the node itself.
- ``run(**inputs)`` takes and returns dictionaries keyed by port name.
  This generic signature lets the engine call any node the same way,
  regardless of how many inputs/outputs it declares.
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from ruyso_app.core.port import Port


class NodeParams(BaseModel):
    """
    Base class for a node's parameter schema.

    Every concrete node should define its own subclass listing its
    configurable fields (with defaults where sensible). ``extra="forbid"``
    ensures a typo in a parameter name fails fast instead of being
    silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    def source_paths(self) -> tuple[str, ...]:
        """
        Files whose *content* this node's result depends on.

        The engine caches a node on its type, parameters and inputs, and
        a loader has no inputs -- so without this a CSV edited under an
        unchanged path was never read again. Declared here, by the
        parameters that know which field is a path, rather than guessed
        by the engine from a field name.
        """
        return ()


class Node(ABC):
    """
    Abstract base class every concrete pipeline node must inherit from.

    Class attributes (set on each subclass, not on instances) describe
    the node's identity and interface, and are what the NodeRegistry
    and the UI introspect to build menus, forms, and connection rules.

    Class attributes:
        node_type: Unique string identifier for this node type
            (e.g. "csv_loader"). Used as the key in the NodeRegistry
            and stored in the serialized graph JSON.
        category: Logical grouping for UI menus / project organization
            (e.g. "loading", "transform", "model", "grapher", "export").
        inputs: List of Port objects this node expects as input.
        outputs: List of Port objects this node produces as output.
        params_schema: The NodeParams subclass describing this node's
            configurable parameters.
        cacheable: Whether the engine is allowed to memoize this
            node's execution (see engine.scheduler). Set to False for
            nodes with an external side effect (writing a file,
            printing, ...) or whose inputs/outputs are not reliably
            hashable/picklable (e.g. matplotlib Figure objects, which
            can contain internal masked arrays that joblib's hasher
            cannot handle) - such nodes should simply always re-run.
    """

    node_type: ClassVar[str]
    category: ClassVar[str]
    #: One or two plain sentences shown read-only in the Options pane
    #: ("what this node does and how it works"). When left blank the UI
    #: falls back to the first line of the class docstring.
    tagline: ClassVar[str] = ""
    inputs: ClassVar[list[Port]] = []
    outputs: ClassVar[list[Port]] = []
    params_schema: ClassVar[type[NodeParams]] = NodeParams
    cacheable: ClassVar[bool] = True

    def __init__(self, params: NodeParams | dict[str, Any] | None = None):
        """
        Create a node instance with validated parameters.

        Args:
            params: Either an already-built NodeParams instance, or a
                plain dict of raw values to validate against
                ``params_schema`` (convenient when loading a graph
                from JSON), or None to use all-default parameters.
        """
        if params is None:
            params = self.params_schema()
        elif isinstance(params, dict):
            params = self.params_schema(**params)
        self.params: NodeParams = params

    @abstractmethod
    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Execute the node's logic.

        Args:
            **inputs: Keyword arguments matching the ``name`` of each
                declared input Port (e.g. run(df=some_dataframe)).

        Returns:
            A dict mapping each declared output Port's ``name`` to its
            produced value (e.g. {"df": transformed_dataframe}).
        """
        raise NotImplementedError

    def validate_inputs(self, inputs: dict[str, Any]) -> None:
        """
        Check that all required input ports are present.

        Args:
            inputs: The dict of inputs that will be passed to run().

        Raises:
            ValueError: If one or more required input ports are missing.
        """
        required = {port.name for port in self.inputs if port.required}
        missing = required - inputs.keys()
        if missing:
            raise ValueError(
                f"Node '{self.node_type}': missing required input port(s): "
                f"{sorted(missing)}"
            )

    def __repr__(self) -> str:  # pragma: no cover - purely for debugging
        return f"<{self.__class__.__name__} node_type={self.node_type!r}>"