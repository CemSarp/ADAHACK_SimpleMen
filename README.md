# ADAHACK_SimpleMen

## Current project plan

Build **CarbonOpt with Django + Plotly**. Start with [the shared team center](docs/carbonopt-team/CENTER.md) and its four role files. The [supporting guides](docs/flexvalue/README.md) now describe this same CarbonOpt plan; their legacy directory name is retained for existing links.

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
