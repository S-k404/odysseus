# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] - 2026-11-09

### Fixed
- **Docker vs. Native Instance Lock Resolution**:
  - `src/instance_lock.py`: Added `_docker_container_alive()` check using `docker inspect`. When the native macOS server checks a claim held by a Docker container, it now verifies whether the container is actually running on the host. If the container is stopped/exited, the claim is released immediately rather than blocking startup until the 35-second heartbeat expires.
  - Resolved `port ?` in lock descriptions by establishing default port fallbacks: `7000` for Docker containers and `7860` for native servers when `APP_PORT` is unset or null.
  - Increased `STOPPING_WAIT_SECONDS` from 30 s to 40 s so waiting for a stopping server does not time out right before `STALE_AFTER_SECONDS` (35 s) elapses.
- **Docker Compose Port Variables**:
  - Added `- APP_PORT=${APP_PORT:-7000}` and `- APP_BIND=${APP_BIND:-0.0.0.0}` to the `odysseus` service in `docker-compose.yml`, `docker-compose.gpu-nvidia.yml`, and `docker-compose.gpu-amd.yml` so containers correctly advertise their port in instance lock files.
- **macOS Startup Friction (`start-macos.sh`)**:
  - Added a pre-launch check that detects if a Docker `odysseus` container is actively running and automatically stops it gracefully before launching the native server, leaving supporting containers (`chromadb`, `speaches`, `searxng`, `ntfy`) active.

### Added
- **Native macOS App "Stop Docker & Retry" / "Retry" Button**:
  - `swift/OdysseusApp.swift`: Added an interactive retry button to the startup splash screen. If the backend fails to start due to a conflicting Docker container or server, the UI displays a **"Stop Docker & Retry"** button that stops the conflicting Docker container and restarts the backend with a single click.
- **Unit Tests**:
  - `tests/test_instance_lock.py`: Added test coverage for default port resolution, formatted port descriptions, and immediate takeover from dead/stopped Docker containers.

### Changed
- Rebuilt and installed `/Applications/Odysseus.app` with the updated Swift desktop binary.
- Verified native server startup on `http://127.0.0.1:7860` with supporting Docker services remaining online.
