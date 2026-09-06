FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BMA_BRIEFING_APP_ROOT=/app \
    BMA_BRIEFING_DB_PATH=/data/db/bma-briefing.db \
    BMA_BRIEFING_EXPORT_ROOT=/data/exports

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get update && apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --system --create-home --uid 10001 briefing
COPY . .
ARG BMA_BRIEFING_BUILD_VERSION=development
ENV BMA_BRIEFING_BUILD_VERSION=${BMA_BRIEFING_BUILD_VERSION}
COPY deploy/entrypoint.sh /usr/local/bin/bma-briefing-entrypoint
RUN chmod 755 /usr/local/bin/bma-briefing-entrypoint && \
    mkdir -p /data/db /data/exports && chown -R briefing:briefing /data

EXPOSE 8790
ENTRYPOINT ["bma-briefing-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8790", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
