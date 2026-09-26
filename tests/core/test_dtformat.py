"""
Tests for ``core.dtformat`` -- the datetime display-format convention,
period-end arithmetic, and text-to-datetime detection.

The invariant every one of these guards: a datetime column stays a real
``datetime64`` column, and formatting is something that happens to it at
render time, never to the data.
"""

import pandas as pd
import pytest

from ruyso_app.core import dtformat


# -- the attrs-carried format map ----------------------------------------


def test_set_and_read_a_display_format():
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(df, "t", "%Y-%m")
    assert dtformat.display_formats(df) == {"t": "%Y-%m"}


def test_a_blank_format_clears_the_entry():
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(df, "t", "%Y-%m")
    dtformat.set_display_format(df, "t", "")
    assert dtformat.display_formats(df) == {}
    assert dtformat.ATTRS_KEY not in df.attrs


def test_display_formats_returns_a_copy():
    """Mutating the result must not rewrite the DataFrame's own metadata."""
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(df, "t", "%Y-%m")
    dtformat.display_formats(df)["t"] = "%d"
    assert dtformat.display_formats(df) == {"t": "%Y-%m"}


def test_setting_a_format_does_not_leak_into_an_upstream_frame():
    upstream = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(upstream, "t", "%Y-%m")
    downstream = upstream.copy()
    dtformat.set_display_format(downstream, "t", "%Y")
    assert dtformat.display_formats(upstream) == {"t": "%Y-%m"}


def test_the_format_survives_the_pipeline_operations_nodes_use():
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01", "2019-07-15"]), "v": [1, 2]})
    dtformat.set_display_format(df, "t", "%Y-%m")
    for result in (
        df.copy(),
        df.sort_values("v"),
        df.head(1),
        df[df["v"] > 0],
        df.assign(z=1),
        df.reset_index(drop=True),
    ):
        assert dtformat.display_formats(result) == {"t": "%Y-%m"}


def test_a_frame_with_no_metadata_reports_no_formats():
    assert dtformat.display_formats(pd.DataFrame({"a": [1]})) == {}


# -- inference ----------------------------------------------------------


@pytest.mark.parametrize(
    "values, expected",
    [
        (["2020-02-01", "2019-07-15"], dtformat.ISO_DATE),
        (["2020-02-01 09:30", "2020-02-02 14:00"], dtformat.ISO_MINUTE),
        (["2020-02-01 09:30:15", "2020-02-02 14:00:00"], dtformat.ISO_SECOND),
        (["2020-02-01 09:30:15.250000"], dtformat.ISO_MICROSECOND),
    ],
)
def test_inference_picks_the_coarsest_lossless_pattern(values, expected):
    assert dtformat.infer_display_format(pd.to_datetime(pd.Series(values))) == expected


def test_an_all_empty_datetime_column_infers_dates():
    series = pd.to_datetime(pd.Series([None, None]))
    assert dtformat.infer_display_format(series) == dtformat.ISO_DATE


def test_explicit_format_beats_inference():
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    assert dtformat.display_format_for(df, "t") == dtformat.ISO_DATE
    dtformat.set_display_format(df, "t", "%Y-%m")
    assert dtformat.display_format_for(df, "t") == "%Y-%m"


def test_a_non_datetime_column_has_no_display_format():
    df = pd.DataFrame({"v": [1, 2], "s": ["a", "b"]})
    assert dtformat.display_format_for(df, "v") is None
    assert dtformat.display_format_for(df, "s") is None


def test_an_absent_column_has_no_display_format():
    assert dtformat.display_format_for(pd.DataFrame({"a": [1]}), "nope") is None


# -- rendering ----------------------------------------------------------


def test_format_value_renders_and_degrades_gracefully():
    assert dtformat.format_value(pd.Timestamp("2020-02-01"), "%Y-%m") == "2020-02"
    assert dtformat.format_value("not a date", "%Y") == "not a date"


def test_missing_values_render_as_an_empty_cell_not_nat():
    assert dtformat.format_value(pd.NaT, "%Y-%m") == ""
    assert dtformat.format_value(None, "%Y-%m") == ""


def test_format_series_renders_a_whole_column():
    series = pd.to_datetime(pd.Series(["2020-02-01", "2019-07-15"]))
    assert dtformat.format_series(series, "%Y-%m").tolist() == ["2020-02", "2019-07"]


# -- period ends --------------------------------------------------------


@pytest.mark.parametrize(
    "components, expected",
    [
        (["year"], "Y"),
        (["year", "quarter"], "Q"),
        (["year", "month"], "M"),
        (["year", "week"], "W"),
        # A day-level component makes the period one day long, so there
        # is no "last unit" distinct from the first.
        (["year", "month", "day"], None),
        (["year", "dayofyear"], None),
        ([], None),
    ],
)
def test_period_code_follows_the_finest_date_component(components, expected):
    assert dtformat.period_code_for_components(components) == expected


@pytest.mark.parametrize(
    "rule, expected", [("MS", "M"), ("ME", "M"), ("YS", "Y"), ("QS", "Q"), ("W", "W")]
)
def test_resample_rules_map_to_period_codes(rule, expected):
    assert dtformat.period_code_for_rule(rule) == expected


def test_period_code_for_a_blank_rule_is_none():
    assert dtformat.period_code_for_rule("") is None


@pytest.mark.parametrize(
    "code, expected",
    [
        ("Y", "2020-12-31"),
        ("Q", "2020-03-31"),
        ("M", "2020-01-31"),
    ],
)
def test_to_period_end_lands_on_the_last_unit_at_midnight(code, expected):
    series = pd.to_datetime(pd.Series(["2020-01-01"]))
    result = dtformat.to_period_end(series, code)
    assert result.iloc[0] == pd.Timestamp(expected)
    assert result.iloc[0].hour == 0 and result.iloc[0].minute == 0


def test_to_period_end_handles_a_leap_february():
    series = pd.to_datetime(pd.Series(["2024-02-01"]))
    assert dtformat.to_period_end(series, "M").iloc[0] == pd.Timestamp("2024-02-29")


def test_to_period_end_works_on_an_index_too():
    index = pd.DatetimeIndex(["2020-01-01", "2020-02-01"])
    assert list(dtformat.to_period_end(index, "M")) == [
        pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")
    ]


def test_to_period_end_passes_values_through_on_an_unknown_code():
    series = pd.to_datetime(pd.Series(["2020-01-01"]))
    assert dtformat.to_period_end(series, "nonsense").iloc[0] == pd.Timestamp("2020-01-01")


def test_to_period_end_preserves_missing_values():
    series = pd.to_datetime(pd.Series(["2020-01-01", None]))
    assert pd.isna(dtformat.to_period_end(series, "M").iloc[1])


# -- text -> datetime64 --------------------------------------------------


def test_detection_finds_a_date_column():
    df = pd.DataFrame({"d": ["01/02/2020", "15/07/2019"], "n": [1, 2]})
    assert dtformat.detect_datetime_columns(df, "%d/%m/%Y") == ["d"]


def test_detection_leaves_version_strings_and_ids_alone():
    """The heuristic's whole job: never silently rewrite non-date text."""
    df = pd.DataFrame(
        {
            "version": ["1.2.3", "1.10.0"],
            "ratio": ["1/2", "3/4"],
            "word": ["alpha", "beta"],
        }
    )
    assert dtformat.detect_datetime_columns(df) == []


def test_detection_ignores_columns_that_mostly_fail_to_parse():
    df = pd.DataFrame({"d": ["2020-01-01"] + ["not-a-date-1234"] * 9})
    assert dtformat.detect_datetime_columns(df) == []


def test_parse_converts_only_the_named_column():
    df = pd.DataFrame({"d": ["01/02/2020"], "other": ["03/04/2021"]})
    out = dtformat.parse_datetime_columns(df, columns="d", fmt="%d/%m/%Y")
    assert pd.api.types.is_datetime64_any_dtype(out["d"])
    assert not pd.api.types.is_datetime64_any_dtype(out["other"])


def test_parse_reports_a_column_name_typo_rather_than_silently_skipping():
    df = pd.DataFrame({"d": ["01/02/2020"]})
    with pytest.raises(ValueError, match="not in the file"):
        dtformat.parse_datetime_columns(df, columns="dat")


def test_parse_with_nothing_detected_returns_the_frame_untouched():
    df = pd.DataFrame({"word": ["alpha", "beta"]})
    assert dtformat.parse_datetime_columns(df) is df


def test_parse_coerces_an_unparseable_value_rather_than_failing():
    df = pd.DataFrame({"d": ["01/02/2020", "rubbish"]})
    out = dtformat.parse_datetime_columns(df, columns="d", fmt="%d/%m/%Y")
    assert out["d"].iloc[0] == pd.Timestamp("2020-02-01")
    assert pd.isna(out["d"].iloc[1])


# -- carrying formats across multi-parent operations ---------------------


def test_carry_formats_fills_in_a_missing_entry():
    left = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"]), "k": [1]})
    dtformat.set_display_format(left, "t", "%Y-%m")
    target = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"]), "w": [9]})

    dtformat.carry_formats(target, left)
    assert dtformat.display_formats(target) == {"t": "%Y-%m"}


def test_carry_formats_does_not_overwrite_the_target():
    left = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(left, "t", "%Y-%m")
    target = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(target, "t", "%d/%m/%Y")

    dtformat.carry_formats(target, left)
    assert dtformat.display_formats(target) == {"t": "%d/%m/%Y"}


def test_carry_formats_prefers_the_earlier_source():
    first = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(first, "t", "%Y-%m")
    second = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(second, "t", "%Y")
    target = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})

    dtformat.carry_formats(target, first, second)
    assert dtformat.display_formats(target) == {"t": "%Y-%m"}


def test_carry_formats_skips_columns_the_operation_dropped():
    source = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"]), "k": [1]})
    dtformat.set_display_format(source, "t", "%Y-%m")
    target = pd.DataFrame({"k": [1]})  # t did not survive

    dtformat.carry_formats(target, source)
    assert dtformat.display_formats(target) == {}


def test_carry_formats_through_covers_every_output_frame():
    source = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    dtformat.set_display_format(source, "t", "%Y-%m")
    a = pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])})
    b = pd.DataFrame({"t": pd.to_datetime(["2019-07-15"])})

    dtformat.carry_formats_through({"x": a, "y": b, "n": 7}, {"df": source})
    assert dtformat.display_formats(a) == {"t": "%Y-%m"}
    assert dtformat.display_formats(b) == {"t": "%Y-%m"}


def test_carry_formats_through_ignores_non_frame_inputs():
    out = {"figure": object()}
    dtformat.carry_formats_through(out, {"model": object()})  # must not raise
