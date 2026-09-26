"""
Turning the exceptions nodes raise into sentences a person can act on.

A pipeline step fails for reasons that are almost always about *the
data or the settings*, not about Python -- a column name that is not in
the table, a text column fed to something that needs numbers, a
parameter left blank. The exception carrying that information is
written for a developer reading a traceback, so surfacing it verbatim
asks the user to read pydantic's or pandas' internals:

    1 validation error for SortParams
    columns
      Input should be a valid list [type=list_type, input_value='nope',
      input_type=str]
        For further information visit https://errors.pydantic.dev/2.13/v/list_type

:func:`translate` rewrites that as "The "columns" setting expects a list
of column names, not the text 'nope'.", and records *which* setting is
at fault so the UI can point at the right row. The original text is
never thrown away -- it is kept on :attr:`NodeError.raw` for a "show
technical details" disclosure, because the friendly version is a
best-effort reading and the developer one is the ground truth.

Deliberately GUI-free and dependency-light: it inspects exceptions by
type and by message, and duck-types anything DataFrame-shaped, so it can
be unit-tested with no Qt and no pipeline. Everything it cannot
recognise falls through to ``TypeName: message``, which is exactly what
the app showed before -- a node whose failure mode is not modelled here
is never *worse* off than it was.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

#: What sort of problem a :class:`NodeError` describes.
#:
#: ``param``   -- a setting on the node is missing or invalid; the node
#:                never started. Carries :attr:`NodeError.field`.
#: ``input``   -- a required input port had nothing connected.
#: ``runtime`` -- the node ran and raised part-way through.
#: ``blocked`` -- the node never ran because something upstream failed.
KINDS = ("param", "input", "runtime", "blocked")

#: How many alternatives to list before truncating (a Literal field can
#: have thirty options and the message has to stay one readable line).
_MAX_LISTED = 8


@dataclass(frozen=True)
class NodeError:
    """
    One failure, described for the person who has to fix it.

    Attributes:
        node_id: The failing node's id (its display name on the canvas).
        node_type: Registry key, e.g. ``"sort"``.
        kind: One of :data:`KINDS`.
        title: A single plain sentence -- what is wrong. This is what
            ``str()`` returns, so anywhere the old code interpolated the
            exception now reads as prose.
        detail: Optional further sentences (the other invalid fields,
            the columns that *are* available, ...).
        field: Name of the ``params_schema`` field at fault, when one can
            be identified -- lets the UI focus that row.
        blocked_by: For ``kind="blocked"``, the node that actually failed.
        raw: The original exception text / traceback, kept verbatim.
    """

    node_id: str
    node_type: str
    kind: str
    title: str
    detail: str = ""
    field: str | None = None
    blocked_by: str | None = None
    raw: str = ""

    def __str__(self) -> str:
        return self.title

    def full_text(self) -> str:
        """Title plus detail, for a log line or a tooltip."""
        return f"{self.title}\n{self.detail}".strip() if self.detail else self.title


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def field_label(name: str) -> str:
    """
    A parameter's name as the Options panel spells it.

    The panel labels rows with the field name and underscores turned
    into spaces (``na_position`` -> ``na position``), so quoting the same
    string is what lets someone scan the form for the row a message is
    talking about.
    """
    return name.replace("_", " ")


def _quoted(name: str) -> str:
    return f'"{field_label(name)}"'


def _listed(values: Any) -> str:
    """Render a set of allowed values, truncated if there are many."""
    items = [str(v) for v in values]
    if len(items) > _MAX_LISTED:
        shown = ", ".join(items[:_MAX_LISTED])
        return f"{shown}, ... ({len(items) - _MAX_LISTED} more)"
    if len(items) > 1:
        return ", ".join(items[:-1]) + f" or {items[-1]}"
    return "".join(items)


def _truncate_expected(text: str) -> str:
    """
    Shorten pydantic's already-joined list of allowed values.

    ``ctx["expected"]`` arrives pre-formatted (``"'a', 'b' or 'c'"``), and
    a ``Literal`` can hold thirty options -- ``example_data``'s dataset
    list runs to 29 -- which turns "must be one of ..." into a paragraph.
    Split it back apart so the same cap applies as everywhere else.
    """
    parts = [p for p in text.replace(" or ", ", ").split(", ") if p]
    return _listed(parts) if len(parts) > _MAX_LISTED else text


def _did_you_mean(name: str, candidates: Any) -> str:
    """" -- did you mean "x"?" when a close match exists, else ""."""
    matches = difflib.get_close_matches(str(name), [str(c) for c in candidates], n=1)
    return f' -- did you mean "{matches[0]}"?' if matches else ""


def _safe_str(exc: BaseException) -> str:
    """``str(exc)`` that cannot itself raise -- some ``__str__`` do."""
    try:
        return str(exc)
    except Exception:  # noqa: BLE001 - the point of the function
        return ""


def _param_names(node_cls: Any) -> list[str]:
    schema = getattr(node_cls, "params_schema", None)
    return list(getattr(schema, "model_fields", {}) or {})


def columns_from_inputs(inputs: Any) -> dict[str, list[str]]:
    """
    ``{port name: [column, ...]}`` for every DataFrame-shaped input.

    Duck-typed on ``.columns`` so the engine keeps needing no pandas
    import; a non-tabular input (a model, a figure) is simply absent.
    """
    found: dict[str, list[str]] = {}
    if not isinstance(inputs, dict):
        return found
    for port, value in inputs.items():
        columns = getattr(value, "columns", None)
        if columns is None:
            continue
        try:
            found[str(port)] = [str(c) for c in columns]
        except TypeError:  # noqa: PERF203 - not iterable after all
            continue
    return found


def _all_columns(input_columns: dict[str, list[str]] | None) -> list[str]:
    """Every column across every tabular input, de-duplicated, in order."""
    seen: list[str] = []
    for columns in (input_columns or {}).values():
        for column in columns:
            if column not in seen:
                seen.append(column)
    return seen


# --------------------------------------------------------------------------
# the per-exception readings
# --------------------------------------------------------------------------


def _from_validation_error(exc: Any, node_cls: Any) -> tuple[str, str, str | None]:
    """``(title, detail, field)`` for a pydantic ``ValidationError``."""
    try:
        problems = list(exc.errors())
    except Exception:  # noqa: BLE001 - not the pydantic shape we expected
        return str(exc), "", None

    known = _param_names(node_cls)
    sentences: list[str] = []
    first_field: str | None = None

    for problem in problems:
        loc = problem.get("loc") or ()
        name = str(loc[0]) if loc else ""
        if first_field is None:
            if name in known:
                first_field = name
            elif problem.get("type") == "extra_forbidden":
                # The name is a typo, so point at what it probably meant --
                # that is the row the UI should take the person to.
                near = difflib.get_close_matches(name, known, n=1)
                first_field = near[0] if near else None
        sentences.append(_one_field_sentence(problem, name, known))

    title = sentences[0] if sentences else str(exc)
    if len(sentences) > 1:
        title = f"{title} (and {len(sentences) - 1} more problem"
        title += ")" if len(sentences) == 2 else "s)"
    detail = "\n".join(sentences[1:]) if len(sentences) > 1 else ""
    return title, detail, first_field


def _one_field_sentence(problem: dict, name: str, known: list[str]) -> str:
    """Rewrite one pydantic error dict as a sentence."""
    kind = problem.get("type", "")
    given = problem.get("input", None)
    ctx = problem.get("ctx") or {}
    label = _quoted(name) if name else "a setting"

    if kind == "missing":
        return f"The {label} setting is required, but nothing is set."

    if kind == "extra_forbidden":
        return (
            f"{label} is not a setting on this node"
            f"{_did_you_mean(name, known)}"
        )

    if kind == "literal_error":
        allowed = ctx.get("expected")
        allowed_text = (
            _truncate_expected(str(allowed))
            if allowed is not None
            else "one of its listed values"
        )
        return (
            f"The {label} setting must be {allowed_text} -- "
            f"it is currently {given!r}."
        )

    if kind in ("list_type", "set_type", "tuple_type"):
        return (
            f"The {label} setting expects a list of values, "
            f"not the text {given!r}."
        )

    if kind in ("int_parsing", "int_type", "float_parsing", "float_type"):
        return f"The {label} setting needs a number, but is set to {given!r}."

    if kind in ("bool_parsing", "bool_type"):
        return f"The {label} setting needs a yes/no value, but is set to {given!r}."

    if kind == "string_type":
        return f"The {label} setting needs text, but is set to {given!r}."

    if kind in ("greater_than", "greater_than_equal"):
        limit = ctx.get("gt", ctx.get("ge"))
        return f"The {label} setting must be greater than {limit} -- it is {given!r}."

    if kind in ("less_than", "less_than_equal"):
        limit = ctx.get("lt", ctx.get("le"))
        return f"The {label} setting must be less than {limit} -- it is {given!r}."

    # Anything pydantic grows later still reads as a sentence about a
    # named setting, rather than as a bare error code.
    return f"The {label} setting is not valid: {problem.get('msg', kind)}."


def _from_key_error(
    exc: KeyError, input_columns: dict[str, list[str]] | None
) -> tuple[str, str]:
    """A missing column, which is what a bare KeyError almost always is."""
    key = exc.args[0] if exc.args else ""
    available = _all_columns(input_columns)
    title = f"There is no column named {key!r} in the incoming data."
    if available:
        title += _did_you_mean(key, available)
        detail = f"Columns available here: {_listed(available)}."
    else:
        detail = ""
    return title, detail


def _from_value_error(
    exc: ValueError, input_columns: dict[str, list[str]] | None
) -> tuple[str, str]:
    """Messages worth rewriting that arrive as a plain ``ValueError``."""
    text = str(exc)
    lowered = text.lower()

    if "could not convert string to float" in lowered:
        value = text.split(":", 1)[1].strip() if ":" in text else ""
        title = "This node needs numeric columns, but one of them contains text"
        title = f"{title} ({value})." if value else f"{title}."
        return title, "Convert it first with the change_type transform."

    if "inconsistent numbers of samples" in lowered:
        return (
            "The inputs have different numbers of rows, so they cannot be "
            "lined up row for row.",
            text,
        )

    if "could not broadcast" in lowered or "operands could not be broadcast" in lowered:
        return (
            "Two sets of values have different lengths and cannot be combined.",
            text,
        )

    if "missing required input port" in lowered:
        # Raised by Node.validate_inputs -- reworded, keeping the ports.
        ports = text.split(":", 2)[-1].strip()
        return f"Nothing is connected to the required input {ports}.", ""

    if "no numeric" in lowered or "at least" in lowered:
        # Nodes raise their own already-plain messages; keep them as-is.
        return text, ""

    return text, ""


def _from_file_error(exc: OSError) -> tuple[str, str, str | None]:
    path = getattr(exc, "filename", None) or ""
    if isinstance(exc, FileNotFoundError):
        title = f"There is no file at {path!r}." if path else "The file could not be found."
        return title, "Check the file path setting on this node.", "filepath"
    if isinstance(exc, PermissionError):
        title = (
            f"Not allowed to open {path!r}." if path else "Not allowed to open that file."
        )
        return title, "Check the file's permissions, or pick another location.", "filepath"
    return str(exc), "", None


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------


def translate(
    exc: BaseException,
    *,
    node_id: str,
    node_type: str,
    node_cls: Any = None,
    input_columns: dict[str, list[str]] | None = None,
    raw: str = "",
) -> NodeError:
    """
    Read ``exc`` as a sentence about ``node_id``.

    Args:
        exc: The exception the node raised.
        node_id: The failing node's id (its canvas name).
        node_type: Its registry key.
        node_cls: The ``Node`` subclass, used to suggest a correct
            setting name when one is misspelled.
        input_columns: ``{port: [column, ...]}`` for its tabular inputs
            (see :func:`columns_from_inputs`), used to say which columns
            *are* available when one is missing.
        raw: The original traceback, kept on the result. Defaults to
            ``TypeName: message`` when not supplied.

    Returns:
        A :class:`NodeError`. Never raises: an exception this function
        cannot read produces ``TypeName: message``, the same text the
        app showed before it existed.
    """
    raw = raw or f"{type(exc).__name__}: {_safe_str(exc)}"
    kind = "runtime"
    title, detail, at_field = _safe_str(exc), "", None

    try:
        name = type(exc).__name__
        if name == "ValidationError" and hasattr(exc, "errors"):
            kind = "param"
            title, detail, at_field = _from_validation_error(exc, node_cls)
        elif name == "NotFittedError":
            title = "This model has not been fitted yet."
            detail = "Connect a fit node upstream, or run the pipeline first."
        elif isinstance(exc, KeyError):
            title, detail = _from_key_error(exc, input_columns)
        elif isinstance(exc, (FileNotFoundError, PermissionError)):
            title, detail, at_field = _from_file_error(exc)
        elif isinstance(exc, MemoryError):
            title = "Ran out of memory running this step."
            detail = "Try fewer rows or columns upstream (head, sample, column_filter)."
        elif isinstance(exc, ValueError):
            if "missing required input port" in str(exc).lower():
                kind = "input"
            title, detail = _from_value_error(exc, input_columns)
    except Exception:  # noqa: BLE001 - a bad reading must never mask the error
        title, detail, at_field = _safe_str(exc), "", None

    if not title:
        title = f"{type(exc).__name__}: {_safe_str(exc)}"

    return NodeError(
        node_id=node_id,
        node_type=node_type,
        kind=kind,
        title=title,
        detail=detail,
        field=at_field,
        raw=raw,
    )


def blocked_error(
    node_id: str, node_type: str, blocked_by: str | None = None
) -> NodeError:
    """
    A node that never ran, and why.

    ``blocked_by`` names the node that actually failed; ``None`` means
    the node is simply not wired up yet, which is the normal state of a
    half-built pipeline rather than a fault.
    """
    if blocked_by:
        title = f"Not run -- waiting on {blocked_by}, which failed."
    else:
        title = "Not run -- one of its inputs is not connected."
    return NodeError(
        node_id=node_id,
        node_type=node_type,
        kind="blocked",
        title=title,
        blocked_by=blocked_by,
    )
