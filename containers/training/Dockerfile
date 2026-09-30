FROM python:3.12-slim-bookworm

WORKDIR /opt/etf-genome

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs

RUN pip install --no-cache-dir -e ".[ml,training,research]"

ENV ETF_GENOME_DATA_DIR=/data

# This image is for Kubeflow training components. It does not contain PySide6
# or the Windows packaging tools, and it does not promote models.
CMD ["python", "-c", "import etf_genome, xgboost, optuna; print('training image ready')"]
