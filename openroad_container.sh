#!/usr/bin/env bash
set -euo pipefail
podman --root /data/taiyuzhou/containers/storage --runroot /data/taiyuzhou/containers/runroot --events-backend=file --cgroup-manager=cgroupfs run --rm --network=none --userns=host --device /dev/fuse \
  -v /data/taiyuzhou:/data/taiyuzhou \
  -e HOME=/data/taiyuzhou/containers/home \
  -e XDG_CONFIG_HOME=/data/taiyuzhou/containers/home/.config \
  -e XDG_DATA_HOME=/data/taiyuzhou/containers/home/.local/share \
  -e XDG_RUNTIME_DIR=/data/taiyuzhou/containers/runtime_openlayout \
  docker.io/openroad/orfs:latest \
  /OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad "$@"
