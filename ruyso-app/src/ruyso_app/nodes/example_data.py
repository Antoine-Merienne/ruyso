"""
A loader that produces a well-known example DataFrame with no file and
no network -- handy for demos and for trying a pipeline out.

Datasets come from three bundled sources, named ``"<source>/<name>"``:

* ``sklearn/...``     -- scikit-learn's toy datasets (shipped with the
  package, always offline). Returned with a ``target`` column.
* ``statsmodels/...`` -- statsmodels' bundled datasets (offline), good
  for regression / time-series examples.
* ``seaborn/...``     -- seaborn's example datasets. Upstream, seaborn
  fetches these from GitHub on first use and caches them locally; here
  every dataset seaborn offers under this Literal is pre-seeded as a
  CSV under ``data/seaborn/`` and passed as seaborn's ``data_home``, so
  loading one never touches the network (seaborn only downloads when
  its cache is missing the file -- see ``seaborn.utils.load_dataset``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node

#: Pre-seeded seaborn example-dataset cache bundled with the package
#: (one <name>.csv per entry in ``_SEABORN`` below). Passed to
#: ``seaborn.load_dataset(..., data_home=...)`` so seaborn finds every
#: file already cached and never reaches out to the network.
_SEABORN_DATA_HOME = Path(__file__).parent / "data" / "seaborn"

_SKLEARN = ("iris", "wine", "diabetes", "breast_cancer", "linnerud")
_STATSMODELS = (
    "longley", "macrodata", "sunspots", "anes96", "stackloss", "ccard",
    "nile", "engel", "elnino", "grunfeld", "co2",
)
_SEABORN = (
    "tips", "titanic", "penguins", "mpg", "flights", "diamonds", "planets",
    "taxis", "car_crashes", "geyser", "healthexp", "glue", "anscombe",
)


class ExampleDataParams(NodeParams):
    """
    Parameters for ExampleData.

    Attributes:
        dataset: Which bundled dataset to load, as ``"<source>/<name>"``.
    """

    dataset: Literal[
        "sklearn/iris", "sklearn/wine", "sklearn/diabetes",
        "sklearn/breast_cancer", "sklearn/linnerud",
        "statsmodels/longley", "statsmodels/macrodata", "statsmodels/sunspots",
        "statsmodels/anes96", "statsmodels/stackloss", "statsmodels/ccard",
        "statsmodels/nile", "statsmodels/engel", "statsmodels/elnino",
        "statsmodels/grunfeld", "statsmodels/co2",
        "seaborn/tips", "seaborn/titanic", "seaborn/penguins", "seaborn/mpg",
        "seaborn/flights", "seaborn/diamonds", "seaborn/planets", "seaborn/taxis",
        "seaborn/car_crashes", "seaborn/geyser", "seaborn/healthexp",
        "seaborn/glue", "seaborn/anscombe",
    ] = "sklearn/iris"


@register_node
class ExampleData(Node):
    """Load a bundled example dataset (no file, no link)."""

    node_type = "example_data"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ExampleDataParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        source, _, name = self.params.dataset.partition("/")

        if source == "sklearn":
            from sklearn import datasets as skds

            return {"df": getattr(skds, f"load_{name}")(as_frame=True).frame}

        if source == "statsmodels":
            import statsmodels.api as sm

            return {"df": getattr(sm.datasets, name).load_pandas().data}

        if source == "seaborn":
            import seaborn as sns

            try:
                return {"df": sns.load_dataset(name, data_home=str(_SEABORN_DATA_HOME))}
            except Exception as exc:  # noqa: BLE001 - re-raised with context
                raise ValueError(
                    f"example_data: could not load seaborn dataset {name!r} from "
                    f"the bundled cache ({_SEABORN_DATA_HOME}); if the CSV is "
                    f"missing there, seaborn falls back to fetching it from the "
                    f"web, which needs network access ({exc})."
                ) from exc

        raise ValueError(f"example_data: unknown dataset {self.params.dataset!r}.")
