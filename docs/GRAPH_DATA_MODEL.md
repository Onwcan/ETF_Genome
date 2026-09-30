# Graph data model

Schema version: `shock-graph-1`.

This document defines persisted ETF-security graph artifacts. [Shock Graph](SHOCK_GRAPH.md) describes their analytical meaning; [Data Model](DATA_MODEL.md) defines canonical holdings.

## ETF node

```text
node_id = cik:{10-digit CIK}|series:{series_id}
ticker, class_id, name
report_date, available_from, accession
```

The ticker is a display label, not the identity.

## Security node

```text
cusip:{CUSIP}
isin:{ISIN}
ticker:{ticker}
name:{normalized name}
```

The first available identifier wins. Placeholder tokens are removed before that choice. Securities are not merged by fuzzy name.

## Holding edge

```text
etf_node_id, security_node_id, security_ticker, security_name
portfolio_weight, market_value, quantity
currency, asset_type, country
report_date, publication_date, available_from
accession, source
```

`publication_date` and `available_from` are the SEC filing date. `report_date` is the portfolio date inside the filing. Signed weights retain negative positions.

Graph edge grouping currently uses a plain Polars sum. If every reported weight for an ETF-security pair is null, the aggregate becomes `0.0`; canonical holdings retain their original nulls, but the grouped edge loses that distinction. Missing-weight counts on a graph therefore describe the aggregated artifact and can understate missing source coverage.

## Snapshot artifacts

A snapshot selects eligible ETF filings that were public by `snapshot_date`, then includes their named securities. Its fingerprint covers the schema version, universe identity and fingerprint, snapshot date, source accessions, and sorted edge identifiers with weights rounded to eight decimal places. Machine paths are excluded from the fingerprint.

The directory contains:

```text
nodes.parquet
edges.parquet
etf_projection.parquet
security_crowding.parquet
manifest.json
```

The persisted build also writes `etf_degree.parquet` when degree results are nonempty. SQLite retains filing provenance; no graph database is required.

## Native export

The Python/native boundary exports:

```text
etf_node_id,security_node_id,security_ticker,portfolio_weight
key,shock
```

These are separate edge and scenario CSV files. The export excludes filing metadata, settings, credentials, and local paths. The native CLI provides validated binary exposure snapshots while retaining CSV input; see the [Native Developer Guide](../native/README.md).

## Temporal boundary

Each filing retains its own `available_from`. Later snapshots may select a newer filing; earlier snapshots cannot see it. Snapshot selection is implemented, while temporal learned models remain [planned research](ROADMAP.md#temporal-shock-graph-research).
