FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -r -f /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web ./web

RUN useradd --create-home --uid 1000 appuser
USER appuser

# панель слушает все интерфейсы контейнера: к ней ходит Caddy по имени сервиса, порт наружу не публикуется
ENV WEB_HOST=0.0.0.0

CMD ["python", "-m", "web.app"]
