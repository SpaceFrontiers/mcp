#!/bin/bash
cd "$(dirname "$0")"
docker buildx build --push --platform=linux/amd64 \
  -t pashapodolsky/spacefrontiers-mcp:latest .
