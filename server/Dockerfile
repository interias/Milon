# Milon Backend — FastAPI + SQLModel (SQLite), APScheduler, Pandas/Pillow.
# Schlankes Single-Stage-Image auf python:3.12-slim (alle Deps als Wheels → kein Build-Toolchain nötig).
FROM python:3.12-slim

# Kein .pyc-Schreiben, ungepufferte Logs (docker logs sofort sichtbar)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/server

# Zuerst nur die Dependency-Deklaration kopieren → Docker-Layer-Cache greift,
# solange sich pyproject.toml nicht ändert.
COPY pyproject.toml ./
# Dependencies aus pyproject installieren (ohne das eigene Paket editable zu bauen).
RUN pip install \
      "fastapi>=0.138,<0.140" \
      "uvicorn[standard]>=0.49" \
      "sqlmodel>=0.0.38" \
      "pandas>=3.0" \
      "python-multipart>=0.0.18" \
      "pydantic-settings>=2.5" \
      "openai>=2.43" \
      "tzdata>=2025.1" \
      "apscheduler>=3.10" \
      "pytz>=2024.1" \
      "pillow>=10.0" \
      "mcp>=1.2" \
      "gdown>=5.1"

# App-Code (ändert sich häufig → nach dem Deps-Layer)
COPY app ./app

# ROOT (config.py: parents[2]) = /app  →  DATA_DIR = /app/data (per Volume gemountet)
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
