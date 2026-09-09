FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# The database lives on a volume so deals survive a container rebuild.
RUN mkdir -p /data && useradd --system --uid 10001 guarantor && chown guarantor /data
USER guarantor
ENV DATABASE_PATH=/data/guarantor.db
VOLUME ["/data"]

ENTRYPOINT ["guarantor"]
CMD ["run"]
