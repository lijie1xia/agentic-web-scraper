FROM python:3.11-slim

WORKDIR /app

COPY spaces/job_demo/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir "mcp>=1.3.0,<2"

COPY scraper_framework /app/scraper_framework
COPY data /app/data
COPY spaces/job_demo/app.py /app/app.py
COPY spaces/job_demo/README.md /app/README.md

ENV CRAWL_MODEL=deepseek
ENV GRADIO_SERVER_NAME=0.0.0.0
ENV PYTHONUNBUFFERED=1

EXPOSE 7860

CMD ["python", "app.py"]
