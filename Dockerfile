# narravid — Linux / Docker single-user baseline
# Edge TTS needs outbound HTTPS. System TTS is Windows-only (not available here).
#
# Build:
#   docker build -t narravid .
# Run (bind-mount outputs; expose only behind auth on shared LAN):
#   docker run --rm -p 5000:5000 -v narravid-data:/app/rendered narravid
#
# Optional Chinese font override:
#   -e NARRAVID_FONT=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NARRAVID_DOCKER=1 \
    NARRAVID_HOST=0.0.0.0 \
    NARRAVID_PORT=5000

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY _bundled_ffmpeg.py video_auto.py webui.py ./
COPY examples ./examples
COPY examples-assets ./examples-assets

RUN mkdir -p /app/rendered /app/fonts

EXPOSE 5000

CMD ["python", "webui.py", "--host", "0.0.0.0", "--port", "5000"]
