FROM python:3.12.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN groupadd --gid 10001 traceq && useradd --uid 10001 --gid traceq --create-home traceq
COPY . /app
RUN pip install --upgrade pip && pip install .
RUN chown -R traceq:traceq /app
USER traceq
