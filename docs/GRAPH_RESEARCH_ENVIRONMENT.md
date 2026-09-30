# Graph research environment

Graph training is isolated from the desktop environment. PyTorch is excluded from `ETFGenome.exe`, and the desktop does not import `research.graph`.

Native Windows PyTorch loading was blocked by Windows Application Control in the observed development environment. This is an environment-specific constraint, not a general Windows limitation. Use a dedicated Linux or WSL2 research environment without weakening Windows security policy.

## Isolated Linux or WSL setup

From the repository root in Linux/WSL, with Python 3.12 available:

```bash
python3.12 -m venv .venv-graph
.venv-graph/bin/python -m pip install -U pip
.venv-graph/bin/python -m pip install -e .
```

Install PyTorch into that environment using the [official installation selector](https://pytorch.org/get-started/locally/) with Linux, Pip, Python, and CPU selected. Run its installer command through `.venv-graph/bin/python -m pip`. Package installation and successful tensor creation must be checked in the target environment; these instructions do not establish completed graph training.

Verify the installed package and CPU tensor path:

```bash
.venv-graph/bin/python -c "import torch; print(torch.__version__); print(torch.rand(2, 2)); print(torch.cuda.is_available())"
```

CPU execution is the baseline. CUDA is optional and is selected by the research code only when availability checks and CUDA tensor creation succeed. PyTorch Geometric is not required by the pure-PyTorch baseline, and `torch-geometric-temporal` is not used.

## Build graph data

Graph ingestion and analytical commands require the core project dependencies, not PyTorch. In a Windows source checkout:

```powershell
.\.venv\Scripts\python.exe scripts\sync_graph_universe.py
.\.venv\Scripts\python.exe scripts\build_shock_graph.py 2026-09-26
.\.venv\Scripts\python.exe scripts\run_shock_scenario.py 2026-09-26 scenario.json
```

The date selects a stored publication-aware snapshot; the commands require configured SEC access and local graph data. Supply your own scenario JSON. These examples are not automatic downloads performed during environment setup.

## Experimental baseline

Once the selected graph artifacts exist and PyTorch runs in the research environment:

```bash
.venv-graph/bin/python scripts/train_graph_baseline.py 2026-09-26
```

The script invokes the held-link reconstruction baseline. Its existence does not imply validated embeddings, a trained temporal model, or causal shock propagation. [Project Status](PROJECT_STATUS.md) records current evidence, and the [Roadmap](ROADMAP.md#temporal-shock-graph-research) owns temporal graph plans.

Airflow and Kubeflow are not required for these commands. See [Orchestration Architecture](ORCHESTRATION_ARCHITECTURE.md) for their separate roles.
