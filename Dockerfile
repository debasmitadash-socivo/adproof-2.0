# AdProof FastAPI backend — runs on Railway / Render / Fly / any container host.
# Frontend (web/) is NOT in this image — it deploys separately to Vercel.

FROM python:3.11-slim

# System deps for Pillow + scipy
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libjpeg-dev zlib1g-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer — rebuilds only when requirements change)
COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir -r api/requirements.txt

# Copy source (everything except what's in .dockerignore)
COPY . .

# Railway/Render inject PORT; default to 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Health check uses the existing /api/healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen(f'http://localhost:{__import__(\"os\").environ.get(\"PORT\",\"8000\")}/api/healthz').read()" || exit 1

# Workers=1 for v1 (single-process). Bump to 2-4 once we're on a paid Railway plan.
# --app-dir tells uvicorn where `main.py` lives without needing `cd` first
# (avoids Railway's "executable `cd` not found" error when running CMD bare).
CMD ["sh", "-c", "uvicorn main:app --app-dir api --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
