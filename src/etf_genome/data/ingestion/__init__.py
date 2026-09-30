"""Ingestion workflows.

Phase 1 does not schedule ingestion. Later Airflow jobs can write raw files
into the configured raw directory and call the normalization functions in
``etf_genome.data.normalization``.
"""
