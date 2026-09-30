"""Check Git publication candidates without printing sensitive matching values.

Default: inspect tracked and nonignored untracked files. --staged: inspect the
actual Git index, including forced additions. This is a local guard, not proof
that arbitrary personal information or every possible secret has been removed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PRIVATE_DIRECTORIES = {
    "data",
    "models",
    "reports",
    "artifacts",
    "cachedir",
    "cache",
    "mlruns",
    "mlartifacts",
    "wandb",
    "local-private",
    "private-notes",
    ".codex",
    ".cursor",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
PRIVATE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".sqlite",
    ".db",
    ".duckdb",
    ".parquet",
    ".log",
    ".pyc",
    ".exe",
    ".dll",
    ".pyd",
    ".so",
    ".dylib",
    ".o",
    ".obj",
}
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    (
        "GitHub token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    ),
    ("cloud access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "service token",
        re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
    ),
    (
        "credential assignment",
        re.compile(
            r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|secret)"
            r"[\"']?\s*[:=]\s*[\"']([A-Za-z0-9_+/.-]{20,})[\"']"
        ),
    ),
    (
        "environment credential",
        re.compile(
            r"(?im)^[A-Z_]*(?:API_KEY|ACCESS_TOKEN|CLIENT_SECRET|PASSWORD)"
            r"\s*=\s*([A-Za-z0-9_+/.-]{20,})\s*$"
        ),
    ),
    (
        "personal Windows path",
        re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!<|Public\b|example\b)[^\\/\s\"'<>]+"),
    ),
    ("personal Linux path", re.compile(r"/home/(?!<|example\b|user\b)[A-Za-z0-9_.-]+/")),
)
MAX_FILE_BYTES = 2_000_000


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    reason: str


def scan_file(path: str, content: bytes) -> list[Finding]:
    """Return locations/reasons only. Findings never contain matching values."""
    normalized = PurePosixPath(path.replace("\\", "/"))
    parts = {part.lower() for part in normalized.parts[:-1]}
    root_directory = normalized.parts[0].lower()
    name = normalized.name.lower()
    if (
        (root_directory in PRIVATE_DIRECTORIES and name != ".gitkeep")
        or bool(parts & {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
        or any(part.startswith((".venv", "venv")) for part in parts)
        or any(
            part in {"build", "dist"} or part.startswith(("build-", "cmake-build-"))
            for part in parts
        )
        or (name.startswith(".env") and name != ".env.example")
        or name.startswith(("credentials", "secrets"))
        or normalized.suffix.lower() in PRIVATE_SUFFIXES
        or ".sqlite-" in name
        or ".duckdb." in name
        or name
        in {"cursor_etf_genome_project_overview.md", "yap\u0131\u015ft\u0131r\u0131lan metin.txt"}
    ):
        return [Finding(path, 0, "private/generated artifact")]
    if len(content) > MAX_FILE_BYTES:
        return [Finding(path, 0, "file exceeds public-source size limit; review required")]
    try:
        source = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [Finding(path, 0, "non-UTF-8 file; review required")]
    if "\x00" in source:
        return [Finding(path, 0, "binary file; review required")]
    findings: list[Finding] = []
    for line_number, line in enumerate(source.splitlines(), 1):
        for reason, pattern in PATTERNS:
            match = pattern.search(line)
            synthetic_test = (
                match is not None
                and reason in {"credential assignment", "environment credential"}
                and root_directory == "tests"
                and match.group(1).startswith("synthetic-")
            )
            if match and not synthetic_test:
                findings.append(Finding(path, line_number, reason))
        for match in EMAIL.finditer(line):
            domain = match.group(1).lower()
            if domain not in {"example.com", "example.net", "example.org"} and not domain.endswith(
                ".invalid"
            ):
                findings.append(Finding(path, line_number, "non-placeholder email address"))
    return findings


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def publication_findings(root: Path, *, staged: bool = False) -> tuple[int, list[Finding]]:
    findings: list[Finding] = []
    if staged:
        records = _git(root, "ls-files", "--stage", "-z").split(b"\x00")
        count = 0
        for record in filter(None, records):
            metadata, encoded_path = record.split(b"\t", 1)
            mode, object_id, stage = metadata.decode("ascii").split()
            path = encoded_path.decode("utf-8")
            count += 1
            if mode != "100644" and mode != "100755":
                findings.append(Finding(path, 0, "symlink/submodule needs explicit review"))
                continue
            if stage != "0":
                findings.append(Finding(path, 0, "unresolved Git index conflict"))
                continue
            findings.extend(scan_file(path, _git(root, "cat-file", "blob", object_id)))
        return count, findings
    paths = set(
        _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\x00")
    )
    paths.discard(b"")
    for encoded_path in sorted(paths):
        path = encoded_path.decode("utf-8")
        source = root / path
        if source.is_symlink():
            findings.append(Finding(path, 0, "symlink needs explicit review"))
        elif source.is_file():
            findings.extend(scan_file(path, source.read_bytes()))
    return len(paths), findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Read actual indexed contents")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        count, findings = publication_findings(root, staged=args.staged)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        # Do not print subprocess stderr or file contents; those can contain PII.
        parser.exit(2, f"Publication scan could not complete ({type(exc).__name__}).\n")
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.reason}")
    if findings:
        print(f"Publication check failed: {len(findings)} findings in {count} candidate files.")
        return 1
    print(f"Publication check passed: {count} candidate files; no detected findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
