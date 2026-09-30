# Scala

No Scala sources are included in Phase 1. Polars handles the current holdings tables. If a later ingestion or graph-edge aggregation job is large enough that the JVM stack is justified, it belongs in this directory and must write Parquet (or another runtime format) that the Windows application can read without a Scala installation.
