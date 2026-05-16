FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ bot/
COPY bot/templates/ bot/templates/
COPY bot/static/ bot/static/

EXPOSE 8000

CMD ["python", "-m", "bot.main"]
