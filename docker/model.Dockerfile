# Model services intentionally keep weights outside the image. Mount a model
# directory at the path configured by the corresponding environment variable.
# This image is an optional GPU profile and is not built by the default stack.
FROM nvidia/cuda:13.0.2-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-dev \
        build-essential \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY src/backend/pyproject.toml src/backend/README.md src/backend/requirements.txt ./
RUN python3 -m pip install --break-system-packages --upgrade pip setuptools wheel \
    && python3 -m pip install --break-system-packages -e . \
    && python3 -m pip install --break-system-packages \
        torch==2.12.0 torchvision==0.27.0

COPY src/backend/ ./
COPY docker/model-entrypoint.sh /usr/local/bin/model-entrypoint
RUN find scripts -type f -name '*.sh' -exec sed -i 's/\r$//' {} + \
    && sed -i 's/\r$//' /usr/local/bin/model-entrypoint \
    && chmod +x /usr/local/bin/model-entrypoint

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/model-entrypoint"]
