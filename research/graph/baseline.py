"""Pure-PyTorch bipartite link reconstruction.

The desktop package does not import this module. PyTorch is imported only when
training runs, inside the isolated graph environment.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def train_baseline(
    edges: list[tuple[str, str, float]],
    *,
    seed: int = 42,
    dimension: int = 16,
    epochs: int = 25,
    graph_fingerprint: str,
    universe_fingerprint: str,
    snapshot_date: str,
    output_dir: Path,
) -> dict[str, object]:
    import torch
    from torch import nn

    torch.manual_seed(seed)
    device = _device(torch)
    etf_ids, security_ids, positives = _index_edges(edges)
    split = _split_pairs(positives, seed)
    model = _DotProduct(len(etf_ids), len(security_ids), dimension).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.05)
    loss_fn = nn.BCEWithLogitsLoss()
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    history: list[float] = []
    for _epoch in range(epochs):
        batch = _batch(split["train"], positives, len(security_ids), generator, torch)
        optimizer.zero_grad()
        score = model(_tensor(torch, batch, 0, device), _tensor(torch, batch, 1, device))
        target = torch.tensor([item[2] for item in batch], dtype=torch.float32, device=device)
        loss = loss_fn(score, target)
        loss.backward()
        optimizer.step()
        history.append(float(loss.detach().cpu()))
    metrics = {
        "validation": _evaluate(
            model, split["validation"], positives, len(security_ids), seed + 1, torch, device
        ),
        "test": _evaluate(
            model, split["test"], positives, len(security_ids), seed + 2, torch, device
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model.pt"
    torch.save(
        {
            "state": model.state_dict(),
            "etf_ids": etf_ids,
            "security_ids": security_ids,
            "dimension": dimension,
        },
        model_path,
    )
    loaded = _DotProduct(len(etf_ids), len(security_ids), dimension).to(device)
    payload = torch.load(model_path, map_location=device, weights_only=True)
    loaded.load_state_dict(payload["state"])
    _same_forward(model, loaded, torch, device)
    etf_vectors = model.etf.weight.detach().cpu().tolist()
    security_vectors = model.security.weight.detach().cpu().tolist()
    _write_embeddings(output_dir, etf_ids, etf_vectors, "etf_embeddings.parquet")
    _write_embeddings(output_dir, security_ids, security_vectors, "security_embeddings.parquet")
    metadata = {
        "model_type": "pure_pytorch_bipartite_dot",
        "task": "holdings link reconstruction",
        "pytorch_version": torch.__version__,
        "pyg_version": None,
        "graph_fingerprint": graph_fingerprint,
        "universe_fingerprint": universe_fingerprint,
        "snapshot_date": snapshot_date,
        "etf_count": len(etf_ids),
        "security_count": len(security_ids),
        "edge_count": len(positives),
        "embedding_dimension": dimension,
        "random_seed": seed,
        "epochs": epochs,
        "device": str(device),
        "negative_sampling": (
            "one uniform security that is absent from that ETF positive set, per positive edge"
        ),
        "split": "deterministic hash of the etf-security pair into train, validation, and test",
        "metrics": metrics,
        "final_train_loss": history[-1] if history else None,
        "model_path": str(model_path),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (output_dir / "node_schema.json").write_text(
        json.dumps({"etf_ids": etf_ids, "security_ids": security_ids}, indent=2),
        encoding="utf-8",
    )
    return metadata


def embedding_neighbors(
    embeddings_path: Path,
    query_id: str,
    *,
    limit: int = 5,
) -> list[tuple[str, float]]:
    import polars as pl

    frame = pl.read_parquet(embeddings_path)
    rows = {str(row["node_id"]): list(row["vector"]) for row in frame.iter_rows(named=True)}
    query = rows.get(query_id)
    if query is None:
        return []
    scored = [
        (_cosine(query, vector), node_id)
        for node_id, vector in rows.items()
        if node_id != query_id
    ]
    scored.sort(reverse=True)
    return [(node_id, score) for score, node_id in scored[:limit]]


def _device(torch: object) -> object:
    cuda = torch.cuda  # type: ignore[attr-defined]
    if not bool(cuda.is_available()):
        return torch.device("cpu")  # type: ignore[attr-defined]
    try:
        probe = torch.zeros(1, device="cuda")  # type: ignore[attr-defined]
        _ = probe + 1
        return torch.device("cuda")  # type: ignore[attr-defined]
    except Exception:
        return torch.device("cpu")  # type: ignore[attr-defined]


def _index_edges(
    edges: list[tuple[str, str, float]],
) -> tuple[list[str], list[str], set[tuple[int, int]]]:
    etf_ids = sorted({item[0] for item in edges})
    security_ids = sorted({item[1] for item in edges})
    etf_index = {item: index for index, item in enumerate(etf_ids)}
    security_index = {item: index for index, item in enumerate(security_ids)}
    positives = {(etf_index[item[0]], security_index[item[1]]) for item in edges}
    return etf_ids, security_ids, positives


def _split_pairs(positives: set[tuple[int, int]], seed: int) -> dict[str, list[tuple[int, int]]]:
    buckets: dict[str, list[tuple[int, int]]] = {"train": [], "validation": [], "test": []}
    for pair in sorted(positives):
        digest = hashlib.sha256(f"{seed}:{pair[0]}:{pair[1]}".encode()).hexdigest()
        slot = int(digest[:2], 16) % 10
        if slot < 7:
            buckets["train"].append(pair)
        elif slot < 9:
            buckets["validation"].append(pair)
        else:
            buckets["test"].append(pair)
    return buckets


def _batch(
    pairs: list[tuple[int, int]],
    positives: set[tuple[int, int]],
    security_count: int,
    generator: object,
    torch: object,
) -> list[tuple[int, int, float]]:
    rows: list[tuple[int, int, float]] = []
    for etf_id, security_id in pairs:
        rows.append((etf_id, security_id, 1.0))
        negative = _negative(etf_id, positives, security_count, generator, torch)
        rows.append((etf_id, negative, 0.0))
    return rows


def _negative(
    etf_id: int,
    positives: set[tuple[int, int]],
    security_count: int,
    generator: object,
    torch: object,
) -> int:
    for _ in range(100):
        draw = int(torch.randint(0, security_count, (1,), generator=generator).item())  # type: ignore[attr-defined]
        if (etf_id, draw) not in positives:
            return draw
    return 0


def _evaluate(
    model: object,
    pairs: list[tuple[int, int]],
    positives: set[tuple[int, int]],
    security_count: int,
    seed: int,
    torch: object,
    device: object,
) -> dict[str, float | int]:
    if not pairs:
        return {"roc_auc": float("nan"), "pr_auc": float("nan"), "positive_edges": 0}
    generator = torch.Generator(device="cpu")  # type: ignore[attr-defined]
    generator.manual_seed(seed)
    batch = _batch(pairs, positives, security_count, generator, torch)
    with torch.no_grad():  # type: ignore[attr-defined]
        scores = model(_tensor(torch, batch, 0, device), _tensor(torch, batch, 1, device))  # type: ignore[operator]
    probabilities = torch.sigmoid(scores).detach().cpu().tolist()  # type: ignore[attr-defined]
    labels = [item[2] for item in batch]
    return {
        "roc_auc": _roc_auc(labels, probabilities),
        "pr_auc": _pr_auc(labels, probabilities),
        "positive_edges": len(pairs),
    }


def _tensor(torch: object, batch: list[tuple[int, int, float]], column: int, device: object) -> object:
    return torch.tensor([item[column] for item in batch], device=device)  # type: ignore[attr-defined]


def _roc_auc(labels: list[float], scores: list[float]) -> float:
    paired = sorted(zip(scores, labels, strict=True), reverse=True)
    positives = sum(label for _score, label in paired)
    negatives = len(paired) - positives
    if positives == 0 or negatives == 0:
        return float("nan")
    rank_sum = 0.0
    for index, (_score, label) in enumerate(paired, start=1):
        if label:
            rank_sum += index
    return float((rank_sum - positives * (positives + 1) / 2) / (positives * negatives))


def _pr_auc(labels: list[float], scores: list[float]) -> float:
    paired = sorted(zip(scores, labels, strict=True), reverse=True)
    hit = 0.0
    total = sum(labels)
    if total == 0:
        return float("nan")
    area = 0.0
    previous_recall = 0.0
    for index, (_score, label) in enumerate(paired, start=1):
        hit += label
        precision = hit / index
        recall = hit / total
        area += (recall - previous_recall) * precision
        previous_recall = recall
    return float(area)


def _write_embeddings(
    directory: Path,
    ids: list[str],
    vectors: list[list[float]],
    name: str,
) -> None:
    import polars as pl

    pl.DataFrame({"node_id": ids, "vector": vectors}).write_parquet(directory / name)


def _same_forward(first: object, second: object, torch: object, device: object) -> None:
    probe_etf = torch.tensor([0], device=device)  # type: ignore[attr-defined]
    probe_security = torch.tensor([0], device=device)  # type: ignore[attr-defined]
    with torch.no_grad():  # type: ignore[attr-defined]
        left = first(probe_etf, probe_security)  # type: ignore[operator]
        right = second(probe_etf, probe_security)  # type: ignore[operator]
    if not bool(torch.allclose(left, right)):  # type: ignore[attr-defined]
        raise RuntimeError("Reloaded graph baseline does not match the trained forward pass.")


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class _DotProduct:  # defined after torch import inside train; replaced at runtime
    def __init__(self, n_etf: int, n_security: int, dimension: int) -> None:
        import torch
        from torch import nn

        class Model(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.etf = nn.Embedding(n_etf, dimension)
                self.security = nn.Embedding(n_security, dimension)

            def forward(self, etf_index: torch.Tensor, security_index: torch.Tensor) -> torch.Tensor:
                return (self.etf(etf_index) * self.security(security_index)).sum(dim=-1)

        self._model = Model()

    def to(self, device: object) -> _DotProduct:
        self._model = self._model.to(device)
        return self

    def parameters(self) -> object:
        return self._model.parameters()

    def state_dict(self) -> object:
        return self._model.state_dict()

    def load_state_dict(self, state: object) -> None:
        self._model.load_state_dict(state)

    def __call__(self, etf_index: object, security_index: object) -> object:
        return self._model(etf_index, security_index)

    @property
    def etf(self) -> object:
        return self._model.etf

    @property
    def security(self) -> object:
        return self._model.security
