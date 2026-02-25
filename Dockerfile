FROM python:3.11-slim
WORKDIR /app
COPY app/ /app/
COPY pmn_sources.example.yaml /app/
COPY prompt_template.default.txt /app/
RUN apt-get update && apt-get install -y poppler-utils && \
    pip install feedparser requests beautifulsoup4 PyMuPDF openai pyyaml
ENV DATA_DIR=/data
ENV PMN_CONFIG_PATH=/app/pmn_sources.example.yaml
ENV DB_PATH=/data/utah_pmn.db
ENV PROMPT_TEMPLATE_PATH=/app/prompt_template.default.txt
CMD ["python", "agenda_downloader.py"]
