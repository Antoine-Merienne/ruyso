"""
Display formatting for datetime columns, and the helpers that turn text
dates into real ``datetime64`` columns.

The rule this module exists to enforce: **a datetime column is always a
real ``datetime64`` column**. Never a formatted string. That is what
keeps ``sort`` chronological, keeps time-series graphers able to place
points on a date axis, and keeps ``resample_datetime`` / ``diff`` able
to do arithmetic on it. Formatting a datetime into text is a *rendering*
concern, so it happens at the very edge -- the Table tab's cell
renderer, a plot's tick formatter -- and never in the data itself.

A node that knows how its datetime column should read (``combine_datetime``,
say, which knows you only mapped year + month and so should show
``2020-02`` rather than ``2020-02-01 00:00:00``) records that intent with
:func:`set_display_format`, which stashes it in ``DataFrame.attrs`` --
metadata pandas carries through copies, filters, sorts, merges and
resamples, so the format survives the rest of the pipeline without any
node having to forward it by hand.

Where no format was set explicitly, :func:`display_format_for` infers
the coarsest ISO pattern that loses nothing: a column whose values are
all at midnight renders as ``%Y-%m-%d`` rather than dragging a constant
``00:00:00`` across the table. Explicit beats inferred; inferred beats
the raw ``str(Timestamp)`` the UI used to fall back on.
"""

from __future__ import annotations

from typing import Any

#: Key under which the ``{column: strftime pattern}`` map is stored in
#: ``DataFrame.attrs``. Namespaced so it cannot collide with metadata
#: another library put there.
ATTRS_KEY = "ruyso_datetime_formats"

#: strptime/strftime patterns offered (non-bindingly) by every
#: datetime-related field in ``nodes/``. Lives here rather than in
#: ``nodes/transforms.py`` so the loaders can offer the same list
#: without importing a sibling node module.
COMMON_DATETIME_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d", "ISO8601",
]

#: Progressively finer ISO patterns, used by :func:`infer_display_format`.
ISO_DATE = "%Y-%m-%d"
ISO_MINUTE = "%Y-%m-%d %H:%M"
ISO_SECOND = "%Y-%m-%d %H:%M:%S"
ISO_MICROSECOND = "%Y-%m-%d %H:%M:%S.%f"


# --------------------------------------------------------------------------
# the attrs-carried format map
# --------------------------------------------------------------------------


def display_formats(df: Any) -> dict[str, str]:
    """
    The explicit ``{column: strftime pattern}`` map carried by ``df``.

    Returns a copy, so a caller can mutate it freely without touching
    the DataFrame's own metadata (several DataFrames can share one
    ``attrs`` dict after a copy).
    """
    attrs = getattr(df, "attrs", None)
    if not isinstance(attrs, dict):
        return {}
    formats = attrs.get(ATTRS_KEY)
    return {
        str(k): str(v) for k, v in formats.items() if v
    } if isinstance(formats, dict) else {}


def set_display_format(df: Any, column: str, fmt: str | None) -> None:
    """
    Record how ``column`` should be *rendered*, without touching its values.

    A falsy ``fmt`` clears any format previously set for that column
    (falling back to :func:`infer_display_format`). Always writes a
    fresh dict rather than mutating in place, so a DataFrame that
    inherited its ``attrs`` from an upstream copy does not retroactively
    change what the upstream one says.
    """
    formats = display_formats(df)
    if fmt:
        formats[column] = fmt
    else:
        formats.pop(column, None)
    if formats:
        df.attrs[ATTRS_KEY] = formats
    else:
        df.attrs.pop(ATTRS_KEY, None)


def carry_formats(target: Any, *sources: Any) -> Any:
    """
    Copy display formats from ``sources`` onto ``target`` and return it.

    pandas propagates ``attrs`` on its own for any operation with a
    *single* parent -- copy, filter, sort, assign, resample and so on --
    but drops them the moment a result has two, because it has no way to
    decide which side's metadata should win. ``pd.merge`` is the case
    that bites: joining a formatted datetime column to another frame
    silently loses the format, and the column falls back to rendering as
    ``2020-02-01 00:00:00``.

    So: earlier sources win over later ones (pass the left frame first,
    matching how a merge's own column names are prioritised), a format
    already on ``target`` is never overwritten, and only columns that
    actually survived into ``target`` are carried -- a format for a
    column the operation dropped would just be dead weight.
    """
    columns = set(getattr(target, "columns", ()))
    merged = dict(display_formats(target))
    for source in sources:
        for column, fmt in display_formats(source).items():
            if column in columns and column not in merged:
                merged[column] = fmt
    if merged:
        target.attrs[ATTRS_KEY] = merged
    return target


def carry_formats_through(outputs: Any, inputs: Any) -> None:
    """
    Re-attach input display formats to every DataFrame a node returned.

    The safety net behind :func:`carry_formats`: the scheduler calls this
    after each node runs, so a node that builds a fresh frame out of two
    parents keeps the metadata without having to remember to ask. Nodes
    that *do* set a format (``combine_datetime``) or carry it themselves
    are unaffected -- an existing entry is never overwritten.

    Duck-typed on purpose: it touches only ``.columns`` and ``.attrs``,
    so the engine stays free of any pandas import.
    """
    if not isinstance(outputs, dict) or not isinstance(inputs, dict):
        return
    sources = [v for v in inputs.values() if hasattr(v, "attrs") and hasattr(v, "columns")]
    if not sources:
        return
    for value in outputs.values():
        if hasattr(value, "attrs") and hasattr(value, "columns"):
            carry_formats(value, *sources)


# --------------------------------------------------------------------------
# inference + rendering
# --------------------------------------------------------------------------


def infer_display_format(series: Any) -> str:
    """
    The coarsest ISO pattern that renders ``series`` without losing anything.

    A column of pure dates gives ``%Y-%m-%d`` (not ``%Y-%m-%d 00:00:00``),
    one with times but whole minutes gives ``%Y-%m-%d %H:%M``, and so on
    down to microseconds. An all-empty column is treated as dates.
    """
    from pandas.api.types import is_datetime64_any_dtype

    if not is_datetime64_any_dtype(series):
        return ISO_SECOND
    values = series.dropna()
    if values.empty:
        return ISO_DATE
    parts = values.dt
    if (parts.microsecond != 0).any() or (parts.nanosecond != 0).any():
        return ISO_MICROSECOND
    if (parts.second != 0).any():
        return ISO_SECOND
    if (parts.hour != 0).any() or (parts.minute != 0).any():
        return ISO_MINUTE
    return ISO_DATE


def display_format_for(df: Any, column: str) -> str | None:
    """
    How ``column`` of ``df`` should be rendered, or ``None`` if it is not
    a datetime column at all.

    An explicit format set by a node wins; otherwise the format is
    inferred from the values (see :func:`infer_display_format`).
    """
    from pandas.api.types import is_datetime64_any_dtype

    explicit = display_formats(df).get(column)
    if explicit:
        return explicit
    try:
        series = df[column]
    except Exception:  # noqa: BLE001 - a duplicate/absent label is not our problem
        return None
    if not is_datetime64_any_dtype(series):
        return None
    return infer_display_format(series)


def format_value(value: Any, fmt: str) -> str:
    """
    Render one timestamp with ``fmt``, degrading to ``str`` if it cannot be.

    Missing values render as an empty cell rather than the literal
    ``"NaT"``, which reads as data.
    """
    if value is None:
        return ""
    try:
        import pandas as pd

        if value is pd.NaT or (value != value):  # NaT / NaN
            return ""
    except (ImportError, TypeError, ValueError):
        pass
    try:
        return value.strftime(fmt)
    except (AttributeError, ValueError, TypeError):
        return str(value)


def format_series(series: Any, fmt: str) -> Any:
    """Render a whole datetime column as text (used for export, not for data)."""
    return series.dt.strftime(fmt)


# --------------------------------------------------------------------------
# period ends ("last of period")
# --------------------------------------------------------------------------

#: Coarse-to-fine date components a period can be anchored on, mapped to
#: the pandas period code used to find that period's end.
_PERIOD_CODES = [("week", "W"), ("month", "M"), ("quarter", "Q"), ("year", "Y")]

#: Resample rule alias -> period code. Period frequencies have no
#: start/end variants, so ``MS`` (month *start*) and ``ME`` both describe
#: a monthly period; anything absent here is tried as-is.
_RULE_TO_PERIOD = {
    "YS": "Y", "YE": "Y", "Y": "Y", "A": "Y", "AS": "Y",
    "QS": "Q", "QE": "Q", "Q": "Q",
    "MS": "M", "ME": "M", "M": "M",
}


def period_code_for_components(components: Any) -> str | None:
    """
    The period code implied by the finest *date* component in ``components``.

    Returns ``None`` when the period is already a day or finer -- the
    last day of a one-day period is that same day, so there is nothing
    to snap to and "last of period" is a no-op.
    """
    present = set(components)
    if "day" in present or "dayofyear" in present:
        return None
    for name, code in _PERIOD_CODES:
        if name in present:
            return code
    return None


def period_code_for_rule(rule: str) -> str | None:
    """The period code for a resample ``rule`` (``MS`` -> ``M``), or ``None``."""
    if not rule:
        return None
    return _RULE_TO_PERIOD.get(rule.strip().upper(), rule.strip())


def to_period_end(values: Any, code: str) -> Any:
    """
    Move each timestamp to the **last unit of its period, at midnight**.

    With ``code="M"``, a value anywhere in February 2020 becomes
    ``2020-02-29 00:00:00`` -- the last day of the month rather than the
    last *instant* of it, so the result still reads as a plain date.
    Returns ``values`` unchanged if ``code`` is not a period frequency
    pandas understands.
    """
    if not code:
        return values
    try:
        if hasattr(values, "dt"):  # a Series
            return values.dt.to_period(code).dt.end_time.dt.normalize()
        return values.to_period(code).end_time.normalize()  # a DatetimeIndex
    except (ValueError, AttributeError, TypeError):
        return values


# --------------------------------------------------------------------------
# text -> datetime64 (the loaders' "parse dates" option)
# --------------------------------------------------------------------------

#: Characters that separate the parts of a written date/time. A text
#: column with none of them (``"1.2.3"``, ``"00123"``) is never guessed
#: to be dates.
_DATE_SEPARATORS = "-/:"

#: How many of a column's values must parse for auto-detection to adopt it.
_DETECT_THRESHOLD = 0.95

#: Values sampled per column when auto-detecting (a full parse of every
#: column of a large file would cost more than the load itself).
_DETECT_SAMPLE = 200


def _looks_like_dates(values: Any) -> bool:
    """
    Cheap structural check applied before trying to parse a text column.

    Requires a date separator and a four-digit run (a year) in every
    sampled value, which is what keeps version strings, identifiers and
    zero-padded numbers from being read as dates.
    """
    import re

    pattern = re.compile(r"\d{4}")
    for value in values:
        if not isinstance(value, str):
            return False
        if not any(sep in value for sep in _DATE_SEPARATORS):
            return False
        if not pattern.search(value):
            return False
    return True


def detect_datetime_columns(df: Any, fmt: str = "") -> list[str]:
    """
    Text columns of ``df`` that are confidently dates.

    Deliberately conservative -- a column is only reported when every
    sampled value looks structurally like a date *and* at least
    ``_DETECT_THRESHOLD`` of them actually parse. A false positive here
    silently rewrites someone's data, so the bar is high.
    """
    import pandas as pd
    from pandas.api.types import is_object_dtype, is_string_dtype

    found: list[str] = []
    for column in df.columns:
        series = df[column]
        if not (is_object_dtype(series) or is_string_dtype(series)):
            continue
        sample = series.dropna().head(_DETECT_SAMPLE)
        if sample.empty or not _looks_like_dates(sample):
            continue
        parsed = pd.to_datetime(sample, format=fmt or None, errors="coerce")
        if parsed.notna().mean() >= _DETECT_THRESHOLD:
            found.append(str(column))
    return found


def parse_datetime_columns(
    df: Any, columns: str = "", fmt: str = "", errors: str = "coerce"
) -> Any:
    """
    Return ``df`` with its date columns converted to real ``datetime64``.

    Args:
        df: The freshly loaded DataFrame.
        columns: Comma-separated column names to convert. Blank means
            auto-detect with :func:`detect_datetime_columns`.
        fmt: strptime pattern for every converted column (blank = let
            pandas infer per column).
        errors: Passed to ``pd.to_datetime``; ``"coerce"`` turns
            unparseable values into ``NaT`` rather than failing the load.

    Raises:
        ValueError: If a column named explicitly is not in the data --
            silently ignoring a typo would leave the column as text and
            reintroduce exactly the lexical-sort bug this option exists
            to prevent.
    """
    import pandas as pd

    wanted = [name.strip() for name in (columns or "").split(",") if name.strip()]
    if wanted:
        missing = [name for name in wanted if name not in df.columns]
        if missing:
            available = ", ".join(str(c) for c in df.columns)
            raise ValueError(
                f"parse dates: column(s) {missing} are not in the file. "
                f"Available columns: {available}"
            )
    else:
        wanted = detect_datetime_columns(df, fmt)
    if not wanted:
        return df

    out = df.copy()
    for column in wanted:
        out[column] = pd.to_datetime(
            out[column], format=fmt or None, errors=errors
        )
    return out
