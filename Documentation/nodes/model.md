# Model nodes

Model nodes (green) fit machine-learning models with scikit-learn, and the model-consuming nodes use a fitted model to predict, score or explain.

## Fitting models

**Model family.** Every fit node has the same shape: inputs
`X_train` (dataframe), `y_train` (array), optional `X_test`/`y_test`
(carried alongside, unused by a plain fit); outputs `model` — the
fitted scikit-learn estimator object — and `optim` (see below).
Evaluation is done downstream by `model_scores` / `residuals` / the
model plots. Supervised: `linear_regression_fit`,
`logistic_regression_fit`, `ridge_fit`, `lasso_fit`,
`elastic_net_fit`, `decision_tree_fit`, `random_forest_fit`,
`gradient_boosting_fit`, `adaboost_fit`, `svm_fit`, `knn_fit`,
`naive_bayes_fit`. Where an algorithm exists in both flavours the
node has a **`task`** dropdown (classifier / regressor) that selects
the estimator class; task-specific args (`class_weight`,
`classifier_criterion` vs `regressor_criterion`, `epsilon`, …) are
shown only for the matching task. The parameter forms expose every
constructor argument that maps onto an existing widget (int / float /
bool / dropdown); `nodes/models.py` `SklearnFitNode` filters the
chosen params against the estimator's signature and maps UI sentinels
back (`"none"` → `None`, `0` → `None` for `max_depth` / `n_jobs` /
`max_iter` / …). Clustering (unsupervised): `kmeans_fit`,
`minibatch_kmeans_fit`, `dbscan_fit`, `hdbscan_fit`,
`agglomerative_clustering_fit`, `spectral_clustering_fit`,
`gaussian_mixture_fit` — `SklearnClusterFitNode` is shaped like a
*transform*, not a fit: input `df` → output `df` with a `cluster`
label column appended (`-1` = noise for DBSCAN/HDBSCAN or a row with
missing numeric values), plus the fitted estimator on a secondary
optional `model` port. Every numeric column is used; a shared
`standardize` (default on) and a `cluster_column` name come from
`ClusterParams`. The `model` port's value differs: KMeans /
MiniBatchKMeans / GaussianMixture can `predict` new rows, the others
are transductive (their `model` just carries `labels_`, already in
the output `df`). The Micro type dropdown groups the whole `model`
macro type into *utilities* (the model-consuming nodes below), then
*supervised fits*, then *unsupervised fits* (the clustering nodes) —
separator lines between
each (`ui.micro_type_groups`).

## Hyperparameter optimization

Every supervised fit node's params also
carry a shared `optimize` toggle (`SklearnFitParams`). Ticked, its
section reveals `optimize_bounds` — a table of that node's own
numeric hyperparameters, each with a checkbox and a `[lo, hi]`
range — plus `optimize_metric`, an Optuna `optimize_method` (tpe /
random / cmaes / grid) and `optimize_n_trials`. `X_test`/`y_test`
become required inputs only when `optimize` is on: every trial
refits on `X_train`/`y_train` and is scored against them, and the
`model` output becomes the best trial's estimator. The `optim`
output (a plain dict; `None` when `optimize` is off) carries
`method` / `metric` / `direction` / `n_trials` / `best_value` /
`best_params` / a per-trial `trials` DataFrame (`train_score` +
`test_score` + the sampled values), for `optim_diagnostic` /
`optim_scores` to read.

## Using a fitted model

**Model-consuming nodes** (`model` macro type, `nodes/model_ops.py`).
All take a fitted `model` port; the evaluation ones also take the
`X` (dataframe) + `y` (array) that `train_test_split` produces.
`predict` — `df` + `model` → the df with a `prediction` column
appended (and, for a classifier, a `probabilities` toggle adds one
`proba_<class>` column each); features are aligned to the model's
`feature_names_in_` when present, else positionally. `model_coeffs`
— `model` → a tidy `feature` / value DataFrame (`coef_` +
`intercept` row, one value column per class for multiclass; falls
back to `feature_importances_` for trees / forests). `model_scores`
— `model` + `X` + `y` → a `metric` / `value` DataFrame; classification
and regression metrics (tickboxes, both always editable) with an
`average` for multiclass precision / recall / f1. Which set is
actually computed is detected from the model itself
(`sklearn.base.is_classifier`), not a separate toggle — the node
produces a sensible result with its defaults as soon as it is wired
up, whichever kind of model that is. `residuals`
— `model` + `X` + `y` → per-row `y_true` / `y_pred` / `residual`
(+ `std_residual`), regression only. `optim_diagnostic` — `optim` →
a one-row summary (method, metric, trial count, best score,
`best_<param>` per searched parameter). `optim_scores` — `optim` →
the per-trial `trials` DataFrame. All five DataFrame outputs are
browsable in the Table tab automatically.
