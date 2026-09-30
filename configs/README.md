# Configuration

Runtime configuration is `etf_genome.config.AppSettings`. Defaults live in code. Overrides come from environment variables prefixed with `ETF_GENOME_` or from a local `.env` file. See `.env.example`.

Do not add a second copy of the same settings in a YAML file unless a later phase has a real need. Secrets do not belong in this directory.
