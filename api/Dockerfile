# casa-finder — API (FastAPI)
#
# Reusa scraper/models.py y scraper/store.py (toda la logica SQL y de
# validacion vive ahi) copiando solo esos dos archivos + __init__.py, sin
# arrastrar las deps del scraper (httpx/bs4/lxml) que la API no necesita.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    TZ=Europe/Madrid

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# Requirements primero (cache eficiente)
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Solo lo que hace falta del scraper (modelos + persistencia), no los portales
COPY scraper/__init__.py scraper/models.py scraper/store.py /app/scraper/

# Codigo de la API
COPY api/ /app/api/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]