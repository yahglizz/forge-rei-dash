# FORGE REI OS — OPTIONAL Docker image.
#
# You do NOT need this. The live box runs via systemd and that is the
# recommended path (see DEPLOY_DIGITALOCEAN.md). Use Docker only if you want to
# standardize everything on containers.
#
# The app reads secrets from a SIBLING dir (../marcus-wholesale-agent/config/ghl.env)
# and writes state to ./marcus_state and the vault. Those are provided as VOLUMES
# in docker-compose.yml — they are intentionally NOT baked into the image.

FROM python:3.12-slim

# Only dependency is `requests` (used by the wholesale classifier).
RUN pip install --no-cache-dir requests

# Match the on-box layout so connector.py's HERE.parent lookups resolve:
#   /opt/forge/forge-rei/        <- this app
#   /opt/forge/marcus-wholesale-agent/config/ghl.env  <- secrets (volume)
#   /opt/forge/vault/            <- brain (volume)
WORKDIR /opt/forge/forge-rei

# Copy only the app code. Secrets/state/keys are excluded via .dockerignore.
COPY . /opt/forge/forge-rei/

ENV FORGE_HOST=0.0.0.0 \
    FORGE_PORT=7799 \
    FORGE_VAULT=/opt/forge/vault \
    FORGE_MARCUS=1 \
    FORGE_QUIET_HOURS=1 \
    FORGE_TZ=America/New_York \
    TZ=America/New_York

EXPOSE 7799

# Lightweight liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:7799/api/health',timeout=4)" || exit 1

CMD ["python3", "connector.py"]
