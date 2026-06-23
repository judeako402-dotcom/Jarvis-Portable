FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential portaudio19-dev libsndfile1 \
    tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

ENV JARVIS_WEB_HOST=0.0.0.0
ENV JARVIS_WEB_PORT=5000

CMD ["python", "main.py", "--headless"]
