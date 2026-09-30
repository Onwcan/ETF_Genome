"""Path resolution that stays valid in source checkouts and frozen executables."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller-style frozen executable."""

    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Return the source checkout root, or the executable directory when frozen.

    The search walks upward from this file until it finds ``pyproject.toml``.
    A frozen build has no checkout, so the executable directory is used.
    """

    if is_frozen():
        return Path(sys.executable).resolve().parent

    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd().resolve()


def default_data_dir() -> Path:
    """Choose a writable data directory without hard-coding a drive letter.

    ``ETF_GENOME_DATA_DIR`` wins when it is set. Frozen executables use the
    per-user local application directory. Source checkouts use ``<root>/data``.
    """

    override = os.environ.get("ETF_GENOME_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return (base / "ETFGenome").resolve()
    return (project_root() / "data").resolve()


def sample_holdings_path() -> Path:
    """Locate the deterministic Phase 1 sample holdings file."""

    override = os.environ.get("ETF_GENOME_SAMPLE_HOLDINGS")
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Sample holdings file does not exist: {path}")
        return path

    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass is None:
            raise FileNotFoundError("Frozen build is missing the sample holdings bundle.")
        bundled = Path(meipass) / "sample_holdings.json"
        if not bundled.is_file():
            raise FileNotFoundError(f"Bundled sample holdings file is missing: {bundled}")
        return bundled

    path = project_root() / "tests" / "fixtures" / "sample_holdings.json"
    if not path.is_file():
        raise FileNotFoundError(f"Sample holdings fixture is missing: {path}")
    return path
