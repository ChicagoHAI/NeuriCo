#!/bin/bash
# Build chicagohai/neurico:latest from the latest published image plus the
# local src/ and baseline/ (see docker/Dockerfile.local).
#
#   scripts/build_local_image.sh            # pull the registry image first
#   scripts/build_local_image.sh --no-pull  # reuse the local copy of it
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGISTRY_IMAGE="ghcr.io/chicagohai/neurico:latest"
IMAGE_NAME="chicagohai/neurico:latest"

if [ "${1:-}" != "--no-pull" ]; then
    docker pull "$REGISTRY_IMAGE"
fi
docker build -t "$IMAGE_NAME" --build-arg BASE_IMAGE="$REGISTRY_IMAGE" \
    -f "$PROJECT_ROOT/docker/Dockerfile.local" "$PROJECT_ROOT"
echo "Built $IMAGE_NAME from $REGISTRY_IMAGE + local src/, baseline/ and paper-finder changes"
