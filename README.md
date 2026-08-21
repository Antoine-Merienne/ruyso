# ruyso
Ruyso is a desktop app for streamlining data science pipeline creation and completion.

The project's structure is as follow (to be edited)

ruyso-app/
├── pyproject.toml
├── README.md
├── .github/
│   └── workflows/
│       └── tests.yml
├── src/
│   └── ruyso_app/
│       ├── __init__.py
│       │
│       ├── core/                      # Couche 1 : modèle de nœuds
│       │   ├── __init__.py
│       │   ├── node.py                # classe abstraite Node
│       │   ├── port.py                # définition Port / typage
│       │   └── registry.py            # NodeRegistry (découverte dynamique)
│       │
│       ├── nodes/                     # Nœuds concrets, un fichier par catégorie
│       │   ├── __init__.py
│       │   ├── loaders.py             # CSVLoader, ExcelLoader...
│       │   ├── transforms.py          # DropNA, StandardScaler...
│       │   ├── models.py              # TrainTestSplit, LinearRegressionFit...
│       │   └── viz.py                 # MatplotlibPlot...
│       │
│       ├── engine/                    # Couche 2 : moteur d'exécution
│       │   ├── __init__.py
│       │   ├── graph.py               # PipelineGraph (wrapper networkx)
│       │   ├── scheduler.py           # exécution + cache (joblib.Memory)
│       │   ├── serialization.py       # graphe <-> JSON
│       │   └── cache.py               # gestion du hash nœud+params+inputs
│       │
│       └── ui/                        # Couche 3 : interface (viendra en Phase 3)
│           ├── __init__.py
│           ├── canvas.py              # intégration NodeGraphQt
│           ├── property_forms.py      # génération formulaires depuis pydantic
│           └── main_window.py
│
├── tests/
│   ├── core/
│   │   └── test_node.py
│   ├── nodes/
│   │   ├── test_loaders.py
│   │   ├── test_transforms.py
│   │   └── test_models.py
│   └── engine/
│       ├── test_graph.py
│       └── test_scheduler.py
│
└── examples/
    └── simple_regression_pipeline.json   # graphe de démo écrit à la main