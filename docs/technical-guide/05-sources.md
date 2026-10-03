# CarbonOpt sources and reference status

## Authoritative project inputs

1. **CarbonOpt_AI_Technical_Implementation_Plan.pdf** supplied by the team: monthly synthetic company data, forecasting, central action simulation, NSGA-II, risk, SHAP, benchmarking and optional LLM tools.
2. **User-confirmed framework choice:** Django + Plotly replaces the PDF's Streamlit example.
3. [CENTER.md](../team-execution/CENTER.md): current shared contracts, units, ownership and execution gates, with four linked role plans.
4. **G-Research.docx:** original challenge and judging criteria. The challenge does not independently require any particular ML/optimisation library.

The earlier CarbonOpt concept PDF is background; where it differs, follow the latest technical plan and confirmed framework decision. Source PDFs were supplied in the user's Downloads directory; the team center describes their content so agents do not require access to another teammate's personal filesystem.

## Data provenance for implementation

- Synthetic company history: A records seed, generation dependencies, units, structural changes and assumptions. Synthetic validation is not evidence of real-world accuracy.
- Action parameters: B records estimated effects, eligible components, costs and accounting rules. They are declared model assumptions unless supported by external evidence.
- Uncertainty: C records distributions, correlations, included uncertainty sources and sample counts. Simulation intervals are conditional on these assumptions.
- Benchmarks: C records the actual source, reporting period, peer definition, scope and normalization. Return unavailable if comparable evidence is missing.
- External APIs remain optional P1 context; their failure must not block P0.

## Earlier research retained for reference

The unchanged JSON files under `research/` and their original manifest belong to the previous FlexValue exploration. They contain Octopus tariff and NESO regional electricity-intensity responses, not company financial history, intervention outcomes or industry peer data.

They are **not required CarbonOpt inputs**. Do not use them to train the company's profit model, claim company benchmarking percentiles or revive the previous scheduling product. If a relevant P1 context panel reuses any observation, verify its timestamp, units, geographic boundary and licence, and label it separately from company CO2e.

Preserve raw files and hashes as historical evidence; do not rewrite their contents to look like new CarbonOpt data. They remain documented by their original `research/manifest.json`.

## Technical reference starting points

Use primary documentation when implementing the chosen versions. These links are references, not evidence that dependencies have already been installed or that a particular model is accurate.

| Component | Official reference | Implementation question |
|---|---|---|
| Django | https://docs.djangoproject.com/ | Forms, CSRF, templates, static assets and tests |
| Plotly Python | https://plotly.com/python/ | Charts, selections and serialization |
| LightGBM | https://lightgbm.readthedocs.io/ | One possible forecasting family and its parameters |
| XGBoost | https://xgboost.readthedocs.io/ | Alternative forecasting family; choose one with A |
| scikit-learn | https://scikit-learn.org/stable/ | Metrics and temporal evaluation utilities |
| pymoo | https://pymoo.org/ | NSGA-II problem definitions, constraints and termination |
| SHAP | https://shap.readthedocs.io/ | Explaining the actual fitted forecast model |
| UK conversion factors | https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting | Optional sourced activity-to-emission assumptions with the proper year/boundary |

## Evidence checklist for each artifact

Data artifacts should record a stable ID, source or generator, creation/retrieval time, date coverage, units, schema version, hash and synthetic/observed status. Model artifacts add training cutoff, feature order, algorithm/version and evaluation method. Strategies add baseline/config/parameter identities. Risk outputs add distributions, dependence assumptions, targets and actual sample count. Benchmarks add comparable peer definition, sample size and normalization.

Do not present a worked example as a measured saving, a simulator assumption as a learned causal effect, a temporal holdout on synthetic data as real-business validation, or grid average intensity as the full company lifecycle footprint. This evidence discipline supports the PDF's intended decision-support narrative without adding another product subsystem.
