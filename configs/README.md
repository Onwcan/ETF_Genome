# Configuration

Runtime configuration is `etf_genome.config.AppSettings`. Defaults live in code. Overrides come from environment variables prefixed with `ETF_GENOME_` or from a local `.env` file. See the credential-free [environment template](../.env.example).

The checked-in files configure specific research inputs rather than duplicate runtime settings:

- [Risk experiment configuration](experiments/qqq_risk_baseline.toml) defines studies and tuning controls.
- [ETF universe](graph/etf_universe.toml) defines the requested graph fund set.
- [Example shock scenario](graph/example_shock.json) supplies direct security shocks.

Keep credentials and contact strings in local environment settings. Configuration responsibilities and artifact boundaries are described in the [system architecture](../docs/ARCHITECTURE.md).
