FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml

RUN pip install --no-cache-dir .

COPY server.py /app/server.py

CMD ["python", "/app/server.py"]
