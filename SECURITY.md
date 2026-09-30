# Security and private data

ETF Genome reads external filings and market data, stores local research artifacts, and loads model files. The current development branch is the maintained code line; no production security certification or release support policy is implied.

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** option if private vulnerability reporting is enabled. If it is unavailable, open a minimal issue asking for a private reporting channel. Do not put credentials, personal addresses, private data, or exploit payloads in a public issue.

Include the affected revision, environment, expected behavior, and a minimal synthetic reproduction through the agreed private channel. Report only the relevant files and sanitized logs.

## Local configuration

- Keep provider credentials and the SEC contact string in your local environment or ignored `.env` file. `.env.example` contains placeholders only.
- Do not print secrets to terminal output, paste them into screenshots, or attach environment dumps to issues.
- Downloaded filings, market histories, local databases, reports, model artifacts, and packaged builds are local outputs. Review them before any deliberate sharing.
- Load only model artifacts you trust. Serialized Python model files can execute code when loaded.
- Treat provider payloads and artifact metadata as data. They must not become shell commands or executable instructions.

The application has credential redaction in logging, but redaction is not a substitute for reviewing output. Repository ignore rules prevent routine accidental inclusion; they do not remove previously tracked files or secrets from history.

## If a credential is exposed

Revoke or rotate it with the provider first. Remove it from affected files, logs, artifacts, and published history using the host's documented process. Deleting the latest copy alone does not make an exposed credential safe to reuse.
