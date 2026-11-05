# Execution image for the docker backend. Build it with:
#   docker build -t autograder-sandbox:latest docker/
# It only holds the toolchain. The agent stays on the host and starts one
# short-lived container per compile or run.
FROM debian:12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev libasan8 libubsan1 \
    && rm -rf /var/lib/apt/lists/*
USER 65534:65534
WORKDIR /work
