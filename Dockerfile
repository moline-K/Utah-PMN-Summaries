FROM python:3.11-slim
WORKDIR /app
COPY app/ /app/
COPY cities.yaml /app/
RUN apt-get update && apt-get install -y poppler-utils && \
    pip install feedparser requests beautifulsoup4 PyMuPDF openai pyyaml
ENV DATA_DIR=/data
CMD ["python", "agenda_downloader.py"]
