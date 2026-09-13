FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY src/backend/pyproject.toml src/backend/README.md src/backend/requirements.txt ./
# Installing CPU PyTorch first prevents transitive dependencies in the
# remote-LLM image from pulling CUDA runtime wheels. ASR uses the Xfyun
# WebAPI, so no WhisperX package or local ASR model is included in this image.
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.7.1 torchvision==0.22.1 \
    && python -m pip install -e .

COPY src/backend/ ./
COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint
COPY docker/backend-worker-entrypoint.sh /usr/local/bin/backend-worker-entrypoint
RUN find scripts -type f -name '*.sh' -exec sed -i 's/\r$//' {} + \
    && sed -i 's/\r$//' /usr/local/bin/backend-entrypoint /usr/local/bin/backend-worker-entrypoint \
    && chmod +x /usr/local/bin/backend-entrypoint /usr/local/bin/backend-worker-entrypoint \
    && mkdir -p online_sessions online_tasks runtime logs

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/backend-entrypoint"]
