FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml server.py /app/

RUN pip install --no-cache-dir . \
    && useradd --create-home --shell /usr/sbin/nologin appuser

USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/healthz', timeout=3).read()"

CMD ["python", "/app/server.py"]
