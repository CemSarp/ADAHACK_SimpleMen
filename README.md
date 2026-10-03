# ADAHACK_SimpleMen

## Current project plan

CarbonOpt AI is a single-company decision tool built with **Streamlit + Plotly**. Specs live in [carbonopt-ai-docs/](carbonopt-ai-docs/README.md). All four workstreams are integrated: `real` mode runs WS1 forecasting from the configured company CSV, WS2 simulation/optimization/recommendation, WS3 risk and benchmarking, and the WS4 dashboard, with every provider real. The input CSV is **synthetic** and labelled as such. Team acceptance of the all-real C4 milestone has not been recorded. Handoffs: [integration](docs/handoffs/INTEGRATION_HANDOFF.md) · [WS2](docs/handoffs/WS2_HANDOFF.md) · [WS3](carbonopt-ai-docs/docs/handoffs/ws3/WS3_DELIVERY.md) · [WS4](docs/handoffs/WS4_DASHBOARD_HANDOFF.md).

### Run the integrated application (from the repository root, Python 3.11)

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-p1.txt       # P0 stack + WS1 libraries + shap
.venv/bin/python -m src.forecasting.train                     # optional: pre-train WS1 (about 6 min cold, then cached)
.venv/bin/python -m pytest
CARBONOPT_PROVIDER_MODE=real .venv/bin/python -m streamlit run app.py
```

macOS: XGBoost and LightGBM need the OpenMP runtime (`brew install libomp`). Without it WS1 reports a typed error naming this fix.

- **Input:** `data/synthetic_data.csv` (synthetic, EUR, 2001–2025; provenance in `data/synthetic_data_provenance.json`), imported through the explicit mapping in `config/company_import.json` (fixed illustrative 0.85 GBP/EUR; EBITDA used as operating profit).
- **Configuration:** `config/integration.json` names the CSV, mapping, WS1 settings and the company-specific assumption, uncertainty and benchmark files. Set `CARBONOPT_CONFIG` to use another file.
- **Training:** WS1 models train on the first baseline request (or with the command above). They are stored under `models/ws1/<model_id>/` (git-ignored) and reused while the data, mapping, settings, WS1 code and library versions are unchanged.
- **Defaults** for this company: budget £20M, cumulative profit floor £30M, 10% CO₂ reduction. Optimize returns a feasible frontier; a £0 budget demonstrates the infeasible state.
- **Headless reproduction with timings:** `.venv/bin/python scripts/run_integrated_analysis.py`.

| Mode | Baseline | Simulator, optimizer | Risk / SHAP / benchmark |
|---|---|---|---|
| `mock` (default) | fixture | behavioral mocks | fixtures |
| `hybrid` (preset) | fixture (labelled, demo company) | real WS2 with demo assumptions | WS3 risk/benchmark real, SHAP disabled |
| `real` | **WS1 from the CSV** | real WS2 with the company's assumptions | WS3 risk, WS1 SHAP, WS3 benchmark (unavailable: no compatible logistics peers) |

### Assistant (chatbot)

A floating assistant button sits at the bottom-left of the dashboard. By default it uses a labelled **MOCK MODEL** (rule-based, offline). The real language model is **not** run on your machine: it is a separate remote Ollama server running `llama3.1:8b`, and this repository only contains the client. No weights are downloaded and no server is installed by this project.

Configuration is by environment variables (copy [`.env.example`](.env.example); the app does not auto-load it, so export the variables in your shell):

| Variable | Meaning | Default |
| --- | --- | --- |
| `CHATBOT_PROVIDER` | `mock` or `ollama` | `mock` |
| `OLLAMA_BASE_URL` | Remote endpoint, required for `ollama` | none |
| `OLLAMA_MODEL` | Model tag | `llama3.1:8b` |
| `OLLAMA_TIMEOUT_SECONDS` / `OLLAMA_MAX_OUTPUT_TOKENS` | Limits | `60` / `512` |
| `OLLAMA_API_KEY` | Optional gateway bearer token | none |

```bash
# mock model (default)
.venv/bin/python -m streamlit run app.py

# remote model, once an endpoint is supplied
CHATBOT_PROVIDER=ollama OLLAMA_BASE_URL=https://<your-ollama-host> .venv/bin/python -m streamlit run app.py
```

Use **Check connection** in the panel to test the endpoint. Remote failures are shown as errors; the mock is never used as a fallback. Details: [docs/CHATBOT_IMPLEMENTATION.md](docs/CHATBOT_IMPLEMENTATION.md).

## Getting Started

### Prerequisites

- [Git](https://git-scm.com/downloads)
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or [Anaconda](https://www.anaconda.com/download)

Check that conda is installed:

```bash
conda --version
```

### 1. Clone the repository

```bash
git clone https://github.com/alimert05/ADAHACK_SimpleMen.git
cd ADAHACK_SimpleMen
```

### 2. Create the conda environment

The project's dependencies are defined in [`environment.yml`](environment.yml). Create the `adahack` environment from it:

```bash
conda env create -f environment.yml
```

### 3. Activate the environment

```bash
conda activate adahack
```

Run this each time you open a new terminal to work on the project.

### 4. Verify the installation

```bash
python -c "import numpy, pandas, sklearn, matplotlib; print('Environment ready')"
```

### 5. (Optional) Register the Jupyter kernel

To select the environment as a kernel in Jupyter or VS Code:

```bash
python -m ipykernel install --user --name adahack --display-name "Python (adahack)"
```

Launch JupyterLab with:

```bash
jupyter lab
```

## Managing the Environment

| Task | Command |
|------|---------|
| Update after `environment.yml` changes | `conda env update -f environment.yml` |
| Deactivate the environment | `conda deactivate` |
| List installed packages | `conda list` |
| Remove the environment | `conda env remove -n adahack` |

### Adding a new dependency

1. Add the package under `dependencies:` in `environment.yml`. If it's only on pip, add it under a `- pip:` subsection instead.
2. Update your environment:

   ```bash
   conda env update -f environment.yml
   ```

3. Commit the updated `environment.yml` so the rest of the team picks it up.

## Included Libraries

| Category | Packages |
|----------|----------|
| Core data | numpy, pandas, scipy |
| Visualisation | matplotlib, seaborn, plotly |
| Machine learning & statistics | scikit-learn, statsmodels |
| Notebooks | jupyterlab, ipykernel |
| Utilities | requests, python-dotenv, tqdm |


deneme1
