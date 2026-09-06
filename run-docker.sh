#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .env ]]; then
    echo "Missing .env. Run: cp .env.example .env"
    exit 1
fi

if [[ -z "${DISPLAY:-}" ]]; then
    echo "DISPLAY is not set. Start this command from your Ubuntu desktop session."
    exit 1
fi

if [[ ! -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/pulse/native" ]]; then
    echo "PulseAudio/PipeWire-Pulse socket was not found."
    exit 1
fi

export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"
export AUDIO_GID="$(getent group audio | cut -d: -f3)"
export AUDIO_GID="${AUDIO_GID:-$HOST_GID}"

mkdir -p memory config runtime
xhost +SI:localuser:"$(id -un)" >/dev/null

exec docker compose up --build
