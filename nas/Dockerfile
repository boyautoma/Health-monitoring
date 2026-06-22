FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir garminconnect==0.2.38 garth

COPY entrypoint.sh /entrypoint.sh

# Lancé via bash (le script est monté en volume, pas besoin du bit +x)
ENTRYPOINT ["bash", "/entrypoint.sh"]
