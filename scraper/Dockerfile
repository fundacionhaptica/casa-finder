# casa-finder — scraper (httpx + BeautifulSoup)
# Decision YAGNI: sin Playwright/Chromium. Los portales SSR (escapadarural) se
# resuelven con httpx + BS4. Si en el futuro un portal requiere JS, se anade
# Playwright en ese momento.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Madrid

WORKDIR /app

# Dependencias minimas
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# Requirements primero (cache eficiente)
COPY scraper/requirements.txt /app/scraper/requirements.txt
RUN pip install --no-cache-dir -r /app/scraper/requirements.txt

# Codigo del scraper (en dev se monta como volumen)
COPY scraper/ /app/scraper/

CMD ["python", "-m", "scraper.run", "--help"]