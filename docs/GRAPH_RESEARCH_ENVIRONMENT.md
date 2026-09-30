# Graph research environment

PyTorch stays out of the desktop virtual environment and out of `ETFGenome.exe`.

Create the research environment with Python 3.12:

```powershell
py -3.12 -m venv .venv-graph
.\.venv-graph\Scripts\python.exe -m pip install -U pip
.\.venv-graph\Scripts\python.exe -m pip install torch
.\.venv-graph\Scripts\python.exe -m pip install -e .
```

Check the install:

```powershell
.\.venv-graph\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"
```

CPU execution is required. CUDA is used only when that import succeeds and a CUDA tensor can be created. Do not change Windows security policy if a native library is blocked.

PyTorch Geometric is optional. If its native extensions are blocked, the representation baseline in `research/graph/baseline.py` is pure PyTorch. `torch-geometric-temporal` is not required and is not used. It remains a candidate for a later temporal model only after snapshots and a working PyTorch import exist.

The desktop package does not import `research.graph`. The packaging spec excludes `torch` and `torch_geometric`.

Graph data commands use the main environment, because they only need Polars and the existing SEC client:

```powershell
.\.venv\Scripts\python.exe scripts\sync_graph_universe.py
.\.venv\Scripts\python.exe scripts\build_shock_graph.py 2026-09-26
.\.venv\Scripts\python.exe scripts\run_shock_scenario.py 2026-09-26 scenario.json
```

Training uses the graph environment:

```powershell
.\.venv-graph\Scripts\python.exe scripts\train_graph_baseline.py 2026-09-26
```

Airflow and Kubeflow are not required to build or train the graph. The same `etf_genome.graph` functions can be called by those orchestrators later.
