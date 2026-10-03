FROM python:3.12.10-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libseccomp2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/nas-filetools
COPY pyproject.toml requirements.lock.txt ./
COPY src ./src
COPY scripts/prepare_models.py ./prepare_models.py
RUN python -m venv .venv \
    && .venv/bin/python -m pip install --no-cache-dir -c requirements.lock.txt '.[engines]' \
    && groupadd -g 10001 filetools && useradd -u 10001 -g filetools -M filetools
USER 10001:10001
ENTRYPOINT ["/opt/nas-filetools/.venv/bin/nas-filetools"]
CMD ["serve", "--root", "/var/lib/nas-filetools", "--config", "/etc/nas-filetools/config.json"]
