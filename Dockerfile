FROM python:3.14.0-slim
WORKDIR /app
COPY requirements-lock.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-deps --no-build-isolation . && useradd --uid 10001 --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "reliability_intelligence.serving.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
