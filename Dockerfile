FROM python:3.12-slim

# System deps for psycopg binary + Java for Flyway
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# Install Flyway (no-JRE bundle — uses system JRE, works on ARM + x86)
ENV FLYWAY_VERSION=10.6.0
RUN curl -fsSL https://repo1.maven.org/maven2/org/flywaydb/flyway-commandline/${FLYWAY_VERSION}/flyway-commandline-${FLYWAY_VERSION}.tar.gz \
    | tar xz -C /opt \
    && ln -s /opt/flyway-${FLYWAY_VERSION}/flyway /usr/local/bin/flyway

# Poetry install
ENV POETRY_VERSION=1.8.0 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml poetry.lock* ./
RUN poetry install --only main --no-root && rm -rf ${POETRY_CACHE_DIR}

# Copy application source
COPY . .

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
