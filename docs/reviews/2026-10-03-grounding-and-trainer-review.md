# Grounding and model-trainer review — 3 October 2026

## Scope and conclusion

Reviewed the pasted implementation output and changes since `35a21a3`, including dashboard commits `8502945`/`690ec0d`, grounding commit `73b7347`, calculator adjustments `69baf45`, and SHAP panel `611decb`. The checkout started on `codex/real-data-grounding`; another actor merged that work and switched the shared checkout to `main` during this review, ending at `87c83d1`. This review did not switch branches or create those commits.

The new grounding section implements the intended separation: Wincanton's annual disclosure and the official-factor sensitivity calculator do not replace the synthetic optimization company. The new calculator and grid arithmetic pass their tests. The dashboard has also changed independently through the feature-explorer/model-trainer commits; it is not accurate to describe the entire branch as only adding a reference panel.

The pasted report is largely consistent with the implementation, but its test results were not an all-green verification. Its known failures remain, and the successful-refresh path has a fallback defect that the original five integration tests do not cover.

## Findings

### P1 — Training jobs share and delete the same output directory

`src/dashboard/trainer.py:89–99` deletes `ml_core/temp_outputs/dashboard_run` when every job starts and passes that same directory to every subprocess. The running-job guard is per Streamlit session, not application-wide. Opening two sessions and starting training in each can delete the first job's results while it is running. Even sequential jobs from separate sessions can cause an older session to display the newer session's metrics: `_report` reads the global directory at line 193 instead of a directory owned by its job.

Reproduced with two `TrainingJob` instances while mocking filesystem deletion, process launch and threads. Both jobs request deletion of, and write to, the identical directory. No real output files were deleted or training processes launched during this reproduction.

Recommended correction: give each job a unique output directory stored on that job, pass it to the CLI and make `_report` read from it. This also avoids needing to delete previous runs on startup.

### P2 — Failed refresh claims recorded fallback but continues showing the previous live response

`src/dashboard/grounding_panel.py:113–134` shows “showing the recorded example instead” on a fetch error, but retains `co_grounding_grid_live`. The next lines prefer that existing response and label it “Live forecast.” Cache TTL does not expire copies stored in Session State, so freshness is also unchecked on later reruns.

Reproduced through AppTest with an existing live response in Session State and a refresh failure. The error said recorded fallback, while the panel still displayed “Live forecast.” The existing integration test covers failure before any successful refresh, so it misses this case.

Recommended correction: either clear the prior response on failure and replay the recorded snapshot, or retain it with an explicit cached/stale label and truthful error text. Check response age before labelling a forecast live or recommending an upcoming window. Add a successful-refresh-then-failure test.

### P2 — Fixture evaluation can appear to be an actual model backtest

Commit `8502945` removed visible provider banners and the fixture-backtest explanation. `src/dashboard/components.py:130–150` now presents fixture MAE/RMSE/R² as “Forecast evaluation (temporal backtest)” without an adjacent fixture label in the default hybrid preset. The baseline caption still identifies data kind/provider and detailed provenance is available in an expander, but those do not explain that this evaluation table's metrics are fixture values. The genuine new trainer report directly above it increases the likelihood of confusing the two evaluations.

Recommended correction: label fixture backtest metrics next to the table and make synthetic input provenance visible in the feature-explorer/trainer. Updating old assertions alone would remove the symptom without resolving the interpretation problem.

## Existing failing checks

- `test_hybrid_startup_labels_every_provider_and_disabled_shap`: expects the removed partially-mocked banner.
- `test_real_mode_starts_with_all_real_providers_and_synthetic_data_label`: expects the removed computational-provider success banner.
- `test_streamlit_app_starts_offline_in_mock_mode`: the contract's optional-library blocker raises `ModuleNotFoundError` inside `_available_models()` at `trainer.py:140`. The unhandled probe aborts the fragment. Installing the libraries does not fix this guarded contract test; after the probe is made robust, its missing mock-banner assertion will also need consideration.

These failures originate in the earlier dashboard changes, rather than the new company snapshot or calculator.

## Current behavior and scope boundaries

- `data/synthetic_data.csv`, `config/`, and `tests/fixtures/` have no changes between `35a21a3` and current HEAD.
- Wincanton remains a historical reference; the 2026 electricity factor is clearly a scenario proxy, not a reconstruction of FY2024 reported emissions.
- The calculator adjustment in `69baf45` correctly converts 25 p/kWh to £0.25/kWh and uses wrapping metric containers. Its updated integration checks pass.
- The feature explorer and trainer use the synthetic logistics CSV. The trainer runs a separate three-month comparison and saves under `ml_core/temp_outputs/dashboard_run`.
- Pressing TRAIN does not install its selected model into the optimizer's forecast provider. In hybrid mode the main baseline remains a fixture; real mode uses the separate WS1 lifecycle and `models/ws1` artifacts with a configured 12-month horizon. Treat the trainer as a comparison tool unless an explicit apply/integration workflow is added.
- A WS1 forecast provider now exists. The old design note saying it is absent no longer describes the current codebase.
- The grounding implementation is now committed in `73b7347`; the pasted report's “not committed” statement described an earlier state.
- The latest SHAP panel (`611decb`) refits a selected tree model before explaining it, rather than loading the exact fitted estimator from the trainer. Its training-summary lookup also uses the shared output directory. Any job-directory correction must update both trainer and SHAP summary loading. The same commit changes RandomForest to `n_jobs=1`, which trades parallel execution for avoiding the prior warning behavior.

## Additional dependency discovered in the latest commit

The new SHAP panel imports `shap` unconditionally once a tree training job completes. The existing `adahack` environment did not contain it even though the new `environment.yml` declares `shap==0.51.0`. AppTest with a simulated completed tree job reproduced an uncaught `ModuleNotFoundError: No module named 'shap'`. The three requested model libraries alone would therefore leave the dashboard unable to complete its new post-training workflow. Installing the already-declared SHAP dependency is part of making that workflow runnable; fresh environments created only from core `requirements.txt` still need the optional requirements or graceful missing-library handling.

## Package installation and verification

Installed into the environment actually used by the running Streamlit app:

`/Users/cemsarp/miniconda3/envs/adahack/bin/python` — Python 3.11.16.

| Package | Verified installed version |
|---|---|
| XGBoost | 3.2.0 |
| LightGBM | 4.7.0 |
| Prophet | 1.4.0 |
| CmdStanPy, Prophet dependency | 1.3.0 |
| SHAP, required by the newly added panel | 0.51.0 |

The pip dry run required only additive installs, and did not require replacing existing numerical/application dependencies. Homebrew `libomp` 23.1.2 was already installed. No system Python installation or unrelated Conda environment was modified. The packages are already declared in `environment.yml`, so no manifest change was required.

Installation guidance was checked against the official [XGBoost documentation](https://xgboost.readthedocs.io/en/stable/install.html), [LightGBM documentation](https://lightgbm.readthedocs.io/en/stable/Installation-Guide.html), and [Prophet repository](https://github.com/facebook/prophet).

Verified imports, all five model options in the dashboard's availability function, and actual fit/predict calls through the project's XGBoost, LightGBM and Prophet factories for **both emissions and profit**, using the last 96 synthetic months and a one-month smoke-test horizon. All six calls passed. `python -m pip check` returned **No broken requirements found** before and after installation.

After the latest panel exposed its missing dependency, installed the manifest's exact `shap==0.51.0`, plus additive `numba`, `llvmlite` and `slicer` dependencies. No existing numerical packages needed replacement. Exercised the panel's actual `_explain` function for XGBoost, LightGBM and RandomForest on both targets with 96 rows from the synthetic CSV: all six cases produced finite SHAP values for horizons 1, 2 and 3. `pip check` passed again. The missing-SHAP environment failure is resolved locally; graceful optional-dependency handling remains an improvement for installations that use only core requirements.

The repeated missing-package warnings occurred because the registry is constructed separately for the two targets. Fresh processes now include all three candidates. A process or notebook that already imported `ml_core.modelling` before installation can retain its old optional-import state; restart that process/kernel before relying on it. A new trainer subprocess uses the installed packages.

## Fresh test evidence

- Focused review command covering new public-data/panel tests, hybrid dashboard tests and offline-startup tests: **44 passed, 3 failed**.
- After installing all dependencies and checking the latest SHAP commit, `python -m pytest tests/contracts tests/unit tests/integration/test_grounding_panel.py -q`: **455 passed, 1 failed**; the failure is the guarded offline-startup test above.
- The 29 public-data unit tests and 5 grounding integration tests are green. Test sets overlap; counts must not be added together.
- A completed-job AppTest with controlled training-summary metadata and actual full-data RandomForest SHAP computation rendered the new post-training panel without exceptions after installation. This exercised the previously failing missing-SHAP path without deleting trainer output or launching a training job.
- The review exercised rendered output with AppTest. It did not perform a browser screenshot review or a full production-length training/optimization run after installing the extra models.

No product-code fixes were made as part of this review. Concurrent edits and commits made by other actors were preserved.
