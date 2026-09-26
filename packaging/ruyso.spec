# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller recipe for the Ruyso desktop app.

Build it with the *build* extra, never the *ui* one:

    python -m venv .venv-build
    .venv-build/bin/pip install -e ".[build]"
    .venv-build/bin/pyinstaller packaging/ruyso.spec --noconfirm --clean

The extra is the single biggest thing in here. ``pyside6-essentials``
carries the four Qt modules this app imports; the full ``PySide6``
meta-package also drags ``PySide6-Addons`` -- 885 MB of WebEngine,
Qt3D, Charts and Multimedia that nothing imports. Not installing it
beats excluding it: a freezer cannot collect what is not on disk. The
``excludes`` list below is belt-and-braces for a contributor whose
environment has the full wheel.

Three things are derived rather than written down, so they cannot
drift from the code:

* the node modules, from ``ruyso_app.nodes.__all__``;
* the scikit-learn estimators, from the ``ESTIMATORS`` tables -- 8
  subpackages reached only through a string lookup, invisible to any
  static analysis (``nodes/models.py``);
* the version, from ``ruyso_app.__version__``.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_delvewheel_libs_directory,
    collect_dynamic_libs,
    collect_submodules,
)

PROJECT_ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import ruyso_app
import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry

# --- what the app must be able to find at runtime -----------------------

NodeRegistry.discover_package(ruyso_app.nodes)
NODE_COUNT = len(NodeRegistry.all())
assert NODE_COUNT >= 130, f"node discovery is broken at build time ({NODE_COUNT} nodes)"

ESTIMATOR_MODULES = sorted(
    {
        target[0] if isinstance(target, tuple) else target
        for cls in NodeRegistry.all().values()
        for target in getattr(cls, "ESTIMATORS", {}).values()
    }
)
assert ESTIMATOR_MODULES, "no estimator modules found -- the ESTIMATORS table moved"

datas = collect_data_files(
    "ruyso_app",
    includes=["nodes/data/seaborn/*.csv", "ui/assets/*"],
)
# NodeGraphQt has no PyInstaller hook and ships one icon its widgets load.
datas += collect_data_files("NodeGraphQt")

# pyogrio is the engine geopandas 1.x reads and writes files with, and it
# has no PyInstaller hook either: it vendors its own GDAL (a 61 MB dylib)
# plus the gdal_data/ and proj_data/ directories that every CRS operation
# reads. Without these the app starts, plots and models perfectly well,
# and every geo node fails.
datas += collect_data_files("pyogrio", excludes=["**/tests/**"])
binaries = collect_dynamic_libs("pyogrio")
# On Windows those DLLs live beside the package, in pyogrio.libs/
# (delvewheel), out of collect_dynamic_libs' reach. No-op elsewhere.
datas, binaries = collect_delvewheel_libs_directory("pyogrio", datas=datas, binaries=binaries)

hiddenimports = (
    [f"ruyso_app.nodes.{name}" for name in ruyso_app.nodes.__all__]
    + [m for m in collect_submodules("pyogrio") if ".tests" not in m]
    + ESTIMATOR_MODULES
    + [
        # Both backends are live: nodes render with Agg, the previews and
        # the pop-out window use the Qt one.
        "matplotlib.backends.backend_agg",
        "matplotlib.backends.backend_qtagg",
        # export_figure writes these formats.
        "matplotlib.backends.backend_pdf",
        "matplotlib.backends.backend_svg",
        "matplotlib.backends.backend_ps",
        # Reached inside run() bodies rather than at module level.
        "sklearn.decomposition",
        "sklearn.manifold",
        "sklearn.metrics",
        "sklearn.model_selection",
        "sklearn.preprocessing",
        "statsmodels.api",
        "statsmodels.tsa.api",
        "scipy.stats",
        "seaborn",
        "optuna",
        "mapclassify",
        "openpyxl",
        "pyarrow.csv",
        # NodeGraphQt still does "from distutils.version import
        # LooseVersion", and 3.12 removed distutils from the stdlib.
        # See packaging/rthooks/pyi_rth_distutils_shim.py.
        "setuptools._distutils",
        "setuptools._distutils.version",
    ]
)

excludes = [
    # Qt the app never imports. Qt.py (NodeGraphQt's binding shim) probes
    # ~23 PySide6 submodules inside try/except, which reads as an import
    # to static analysis -- hence the explicit list.
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtGraphsWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtHttpServer", "PySide6.QtDesigner",
    "PySide6.QtUiTools", "PySide6.QtHelp", "PySide6.QtTest",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtQml",
    # Other bindings Qt.py looks for.
    "PyQt5", "PyQt6", "PySide2",
    # Development tooling that lives in a working venv.
    "tkinter", "IPython", "jupyter", "notebook", "pytest", "_pytest", "pluggy",
    "pip",
    # NOTE: setuptools is deliberately NOT excluded -- its _distutils is
    # what the runtime hook aliases for NodeGraphQt. "wheel" comes with
    # it: excluding a module setuptools asks for is a hard build error
    # ("already imported as ExcludedModule"), not a saving.
    # Test suites shipped inside the dependencies.
    "pyarrow.tests", "pandas.tests", "numpy.tests", "sklearn.tests",
    "statsmodels.tests", "matplotlib.tests", "shapely.tests", "pyogrio.tests",
    # Arrow Flight is an RPC framework; nothing here speaks it.
    "pyarrow.flight", "pyarrow._flight", "pyarrow.substrait",
    # optuna's optional database storages.
    "sqlalchemy", "alembic",
]

# The icon is optional so a build works before the artwork exists.
ICON_ICNS = PROJECT_ROOT / "packaging" / "icons" / "icon.icns"
ICON_ICO = PROJECT_ROOT / "packaging" / "icons" / "icon.ico"
icon_for_exe = str(ICON_ICO) if ICON_ICO.exists() else None
icon_for_bundle = str(ICON_ICNS) if ICON_ICNS.exists() else None

a = Analysis(
    [str(PROJECT_ROOT / "src" / "ruyso_app" / "ui" / "__main__.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_ROOT / "packaging" / "rthooks" / "pyi_rth_distutils_shim.py")],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ruyso",
    debug=False,
    bootloader_ignore_signals=False,
    # UPX on Qt and NumPy shared libraries is a well-known source of
    # "works here, crashes there", and on macOS it invalidates the
    # signature. The compression is not worth the class of bug.
    # strip only on macOS: on Linux it breaks auditwheel-patched libraries
    # (numpy's OpenBLAS: "ELF load command address/offset not page-aligned").
    strip=sys.platform == "darwin",
    upx=False,
    console=False,
    icon=icon_for_exe,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=sys.platform == "darwin",
    upx=False,
    name="ruyso",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Ruyso.app",
        icon=icon_for_bundle,
        bundle_identifier="app.ruyso.Ruyso",
        version=ruyso_app.__version__,
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "CFBundleShortVersionString": ruyso_app.__version__,
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Ruyso pipeline",
                    "CFBundleTypeExtensions": ["json"],
                    "CFBundleTypeRole": "Editor",
                }
            ],
        },
    )
