# Graph data model

Schema version: `shock-graph-1`.

## ETF node

```text
node_id = cik:{10-digit CIK}|series:{series_id}
ticker, class_id, name
report_date, available_from, accession
```

The ticker is not the identity.

## Security node

```text
cusip:{CUSIP}
isin:{ISIN}
ticker:{ticker}
name:{normalized name}
```

The first available identifier wins. Placeholder tokens are dropped before that choice. Securities are not merged by fuzzy name.

## Holding edge

```text
etf_node_id, security_node_id
portfolio_weight, market_value, quantity
currency, asset_type, country
report_date, publication_date, available_from
accession, source
```

`publication_date` and `available_from` are the SEC filing date. `report_date` is the portfolio date inside the filing.

## Snapshot

A snapshot is the set of ETF filings that were public on `snapshot_date`, plus the securities those filings name. The manifest fingerprint covers the schema version, universe fingerprint, snapshot date, source accessions, and rounded edge weights. It does not include a machine path.

Parquet files:

```text
nodes.parquet
edges.parquet
etf_projection.parquet
security_crowding.parquet
etf_degree.parquet
manifest.json
```

SQLite continues to store filing provenance. There is no graph database in this phase.

## Temporal shape

Each filing stays attached to its own `available_from`. A later snapshot may select a newer filing. An earlier snapshot cannot see it. That is the structure a later temporal model can stack. Phase 7 trains on one snapshot only.
