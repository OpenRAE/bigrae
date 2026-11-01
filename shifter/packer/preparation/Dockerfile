# Build from repository root. Private adapters derive from this runtime and copy
# their contained contexts into /app/preparation/contexts before digest approval.
# base image: python3.14-trixie-slim
FROM ghcr.io/astral-sh/uv@sha256:637619278855a77885a94312efa7decd8479ca6cec5f959e134cbab96582821e AS builder
WORKDIR /build
COPY shifter/packer/pyproject.toml shifter/packer/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --output-file requirements.txt && \
    uv venv --python /usr/local/bin/python /opt/venv && \
    uv pip install --python /opt/venv/bin/python --no-config --require-hashes --only-binary :all: -r requirements.txt

# base image: python:3.14-slim-trixie
FROM python@sha256:cd89c30eda26ee911a4611b18680086e0ea42e6f5f8cbe653d07fa7958c9cec8
# CI sets the source URL from the running repository (ADR-069).
# A local build leaves the label empty.
ARG SOURCE_REPOSITORY_URL=""
LABEL maintainer="Shifter maintainers" \
      org.opencontainers.image.title="shifter-artifact-preparation" \
      org.opencontainers.image.description="Contained artifact preparation and independent verification" \
      org.opencontainers.image.source="${SOURCE_REPOSITORY_URL}" \
      org.opencontainers.image.licenses="MIT"
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY shifter/shifter_adapter_sdk ./shifter_adapter_sdk
COPY shifter/shifter_platform/shared/__init__.py shifter/shifter_platform/shared/enums.py \
     shifter/shifter_platform/shared/exceptions.py \
     shifter/shifter_platform/shared/operation_envelope.py shifter/shifter_platform/shared/artifact_preparation.py \
     shifter/shifter_platform/shared/preparation_grant.py ./shared/
COPY shifter/shifter_platform/shared/raes/__init__.py shifter/shifter_platform/shared/raes/preparation_contract.py \
     shifter/shifter_platform/shared/raes/preparation_inputs.py \
     shifter/shifter_platform/shared/raes/json_ingress.py ./shared/raes/
COPY shifter/packer/preparation ./preparation
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["/opt/venv/bin/python", "-m", "preparation.worker_client"]
