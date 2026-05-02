FROM python:3.13-slim

WORKDIR /app

# System deps required to build some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Persistent storage for SQLite DB
RUN mkdir -p data
VOLUME ["/app/data"]

EXPOSE 8000

# Use exec form to get proper signal handling
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
