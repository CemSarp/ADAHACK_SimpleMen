# ADAHACK_SimpleMen

## Current project plan

CarbonOpt AI is a single-company decision tool built with **Streamlit + Plotly**. Specs live in [carbonopt-ai-docs/](carbonopt-ai-docs/README.md). The WS4 dashboard is integrated with the real WS2 action engine, optimizer and recommendation. WS1 (forecasting) and WS3 (risk, benchmark) are not integrated yet, so the working setup is a **labelled hybrid**: a fixture baseline with real WS2 computation. It is not the all-real C4 MVP. Handoffs: [WS2](docs/handoffs/WS2_HANDOFF.md) · [WS4](docs/handoffs/WS4_DASHBOARD_HANDOFF.md).

### Run the dashboard (from the repository root, Python 3.11)

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
CARBONOPT_PROVIDER_MODE=hybrid .venv/bin/python -m streamlit run app.py
```

`hybrid` opens the **Fixture forecast + real WS2** preset. You can also pick it in the sidebar: *Provider mode → hybrid → Hybrid configuration*.

| Mode | Baseline | Simulator, constraints | Optimizer, recommendation | Risk / SHAP / benchmark |
|---|---|---|---|---|
| `mock` (default) | fixture | behavioral mock | behavioral mock (random search) | fixtures |
| `hybrid` (WS2 preset) | fixture (labelled) | **real WS2** | **real WS2** (NSGA-II, Pareto, P0 policy) | unavailable, with the reason shown |
| `real` | WS1 required | real WS2 | real WS2 | WS1/WS3 when published |

`real` stops with *"required P0 providers are not available … forecast: src.forecasting.provider is not implemented yet"* until WS1 publishes its provider. It never substitutes a fixture. The sidebar's default inputs (budget £500,000, cumulative profit floor £1,000,000, 20% CO₂ reduction, seed 42, 2,048 evaluations) are a feasible demonstration: the real search returns a 289-point frontier in about 12 s on the reference laptop. A £0 budget demonstrates the infeasible, no-recommendation state. The WS2 handoff has details.

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
