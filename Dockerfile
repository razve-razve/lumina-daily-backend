FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies for pyswisseph C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Download Swiss Ephemeris data files (covers 1800–2400 CE)
RUN mkdir -p /app/ephe \
    && wget -q -P /app/ephe \
        https://www.astro.com/ftp/swisseph/ephe/seas_18.se1 \
        https://www.astro.com/ftp/swisseph/ephe/semo_18.se1 \
        https://www.astro.com/ftp/swisseph/ephe/sepl_18.se1

# ── Final image ───────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/ephe /app/ephe
COPY ./app ./app
COPY ./migrations ./migrations
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
