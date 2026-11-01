# Vercel Container runtime: keeps the torch + Chroma stack intact.
# Vercel builds this image, stores it in VCR, and runs it as a Function.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    PORT=80

WORKDIR /app

# CPU-only torch (~200 MB) instead of the default CUDA wheel (~2 GB).
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Bake the MiniLM weights (into HF_HOME) and the Chroma index into the image,
# so cold starts never download a model or build an index.
RUN python -m src.embed

EXPOSE 80
CMD ["sh", "-c", "uvicorn index:app --host 0.0.0.0 --port ${PORT:-80}"]
