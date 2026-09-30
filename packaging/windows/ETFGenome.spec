# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Phase 1 desktop proof of concept.

Build from the repository root:

    .\\.venv\\Scripts\\pyinstaller.exe packaging\\windows\\ETFGenome.spec --noconfirm --clean

The production result is an onedir build without a console window.
Set ETF_GENOME_PYINSTALLER_CONSOLE=1 before this spec for a developer build.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parents[1]
polars_datas, polars_binaries, polars_hidden = collect_all("polars")
try:
    duck_datas, duck_binaries, duck_hidden = collect_all("duckdb")
except Exception as exc:
    # Some Windows application-control policies block the DuckDB native
    # library. The app then uses the Polars summary fallback.
    print(f"DuckDB was not collected: {exc}")
    duck_datas, duck_binaries, duck_hidden = [], [], []
# collect_all("xgboost") imports xgboost.testing, which skips unless hypothesis
# is installed. Collect the package modules and the DLL directly instead.
import xgboost as _xgboost

_xgb_root = Path(_xgboost.__file__).resolve().parent
xgb_hidden = []
for _path in _xgb_root.rglob("*.py"):
    if any(part in {"testing", "spark", "dask"} for part in _path.parts):
        continue
    _name = ".".join(_path.relative_to(_xgb_root.parent).with_suffix("").parts)
    if _name.endswith(".__init__"):
        _name = _name[: -len(".__init__")]
    if _name in {"xgboost.sklearn", "xgboost.plotting", "xgboost.federated"}:
        continue
    xgb_hidden.append(_name)
_xgb_dll = _xgb_root / "lib" / "xgboost.dll"
xgb_binaries = [(str(_xgb_dll), "xgboost/lib")] if _xgb_dll.is_file() else []
_version_file = _xgb_root / "VERSION"
xgb_datas = [(str(_version_file), "xgboost")] if _version_file.is_file() else []

model_dir = root / "models" / "risk_baseline"
model_datas = [(str(model_dir), "models/risk_baseline")] if model_dir.is_dir() else []
registry_file = root / "models" / "registry" / "registry.json"
if registry_file.is_file():
    model_datas.append((str(registry_file), "models/registry"))
production_dir = root / "models" / "production"
if production_dir.is_dir():
    model_datas.append((str(production_dir), "models/production"))

block_cipher = None

a = Analysis(
    [str(root / "apps" / "desktop" / "main.py")],
    pathex=[str(root / "src")],
    binaries=polars_binaries + duck_binaries + xgb_binaries,
    datas=[
        (str(root / "tests" / "fixtures" / "sample_holdings.json"), "."),
        *polars_datas,
        *duck_datas,
        *xgb_datas,
        *model_datas,
    ],
    hiddenimports=[
        "etf_genome",
        "etf_genome.experiments.registry",
        "pydantic",
        "pydantic_settings",
        "httpx",
        *polars_hidden,
        *duck_hidden,
        *xgb_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tensorflow",
        "torch",
        "torch_geometric",
        "torch_geometric_temporal",
        "torch_sparse",
        "torch_scatter",
        "sklearn",
        "scipy",
        "pandas",
        "matplotlib",
        "dask",
        "pyspark",
        "mlflow",
        "wandb",
        "airflow",
        "optuna",
        "kfp",
        "kfp_server_api",
        "kubernetes",
        "docker",
        "PIL",
        "pillow",
        "mypy",
        "sqlalchemy",
        "alembic",
        "cryptography",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ETFGenome",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=os.environ.get("ETF_GENOME_PYINSTALLER_CONSOLE") == "1",
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ETFGenome",
)
