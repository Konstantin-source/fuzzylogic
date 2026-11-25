FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 --no-create-home appuser \
    && mkdir /app/data \
    && chown appuser /app/data
COPY app ./app
COPY sample_data ./sample_data
ENV DATA_DIR=/app/data PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
