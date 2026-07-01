FROM python:3.11-slim

WORKDIR /app

COPY requirements-m3l2.txt .
RUN pip install --no-cache-dir -r requirements-m3l2.txt

COPY . .

CMD ["uvicorn", "m3l2.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
