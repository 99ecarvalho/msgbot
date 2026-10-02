#!/usr/bin/env bash
# Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
#
# This file is part of MsgBot. It is free software, licensed under the GNU
# Lesser General Public License v3.0 or later. See COPYING.LESSER and
# COPYING for details.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

set -euo pipefail

cd "$(dirname "$0")"

usage() {
    cat <<EOF
Usage: ./run.sh [command] [service...]

Builds and runs the MsgBot stack with docker compose. With no command, does
everything needed to get it running: fetches the submodules, creates .env and
its secrets, builds the images, starts the stack, waits for the web UI, and
prints how to reach it and log in.

Commands:
  up                Prepare, build, and start everything (the default)
  build [service]   Build the images (all, or the services named)
  start [service]   Start the stack without rebuilding
  stop [service]    Stop the containers, keeping them
  restart [service] Restart the containers
  down              Stop and remove the containers (data volumes are kept)
  status            Show the containers and how to reach the web UI
  logs [service]    Follow the logs (all services, or the ones named)
  update            git pull, update the submodules, rebuild, and restart
  info              Print the web UI address and login
  help              Show this help

Services: bot, evolution-api, postgres, transcriber, tts

Examples:
  ./run.sh                 # first run, or bring everything up to date
  ./run.sh logs bot        # follow the bot's logs
  ./run.sh build bot && ./run.sh restart bot

Settings are read from .env (see .env.example and README.md).
EOF
}

log()  { printf '=== %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

compose() { docker compose "$@"; }

# ---- Checks and setup ----

require_docker() {
    command -v docker >/dev/null 2>&1 || die "docker is not installed: https://docs.docker.com/engine/install/"
    docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required (the 'docker compose' command)"
    docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon: is it running, and may this user use it?"
}

check_gpu() {
    if ! docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia; then
        warn "the NVIDIA container runtime was not found; the transcriber needs a GPU."
        warn "Without one, set WHISPER_DEVICE=cpu and a small WHISPER_MODEL in .env, and remove"
        warn "the deploy: block of the transcriber service in docker-compose.yml."
    fi
}

# The transcriber and TTS services are git submodules in external/; fetch them
# if this checkout was cloned without --recurse-submodules.
fetch_submodules() {
    if [[ ! -f external/ai-transcriber/Dockerfile || ! -f external/ai-tts/Dockerfile ]]; then
        log "Fetching submodules"
        git submodule update --init --recursive
    fi
}

env_get() { grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true; }

env_set() {
    if grep -qE "^$1=" .env; then
        sed -i "s|^$1=.*|$1=$2|" .env
    else
        printf '%s=%s\n' "$1" "$2" >> .env
    fi
}

random_secret() {
    openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
}

# Create .env from the example, and fill in the secrets nobody has to choose.
prepare_env() {
    if [[ ! -f .env ]]; then
        cp .env.example .env
        chmod 600 .env
        log "Created .env from .env.example"
    fi

    local value
    value=$(env_get EVOLUTION_API_KEY)
    if [[ -z "$value" || "$value" == "your-chosen-api-key" ]]; then
        env_set EVOLUTION_API_KEY "$(random_secret 32)"
        log "Generated EVOLUTION_API_KEY in .env"
    fi
    if [[ -z "$(env_get WEB_PASSWORD)" ]]; then
        env_set WEB_PASSWORD "$(random_secret 12)"
        log "Generated WEB_PASSWORD in .env"
    fi

    value=$(env_get AZURE_OPENAI_API_KEY)
    if [[ -z "$value" || "$value" == "your-azure-openai-key" ]]; then
        warn "AZURE_OPENAI_API_KEY is not set in .env: everything starts, but LLM steps will fail."
        warn "Fill in the AZURE_OPENAI_* settings and run ./run.sh again."
    fi
}

# ---- Access information ----

web_port() {
    local port
    port=$(compose config --format json bot 2>/dev/null \
        | grep -oE '"published": *"[0-9]+"' | grep -oE '[0-9]+' | head -n1 || true)
    echo "${port:-8088}"
}

wait_for_web() {
    local port=$1 i
    command -v curl >/dev/null 2>&1 || return 0
    log "Waiting for the web UI"
    for i in $(seq 1 60); do
        curl -fsS -o /dev/null "http://localhost:$port/health" 2>/dev/null && return 0
        sleep 2
    done
    warn "the web UI didn't answer within 2 minutes; check ./run.sh logs bot"
}

print_info() {
    local port ip user
    port=$(web_port)
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | grep -oE 'src [0-9.]+' | cut -d' ' -f2 || true)
    [[ -n "$ip" ]] || ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    user=$(env_get WEB_USERNAME)

    echo
    echo "MsgBot web UI"
    echo "  This machine:  http://localhost:$port"
    if [[ -n "$ip" ]]; then
        if grep -qi microsoft /proc/version 2>/dev/null; then
            echo "  WSL address:   http://$ip:$port   (from Windows, use localhost)"
        else
            echo "  Network:       http://$ip:$port"
        fi
    fi
    echo "  Username:      ${user:-admin}"
    echo "  Password:      $(env_get WEB_PASSWORD)"
    echo
    echo "Next: open WhatsApp QR to pair WhatsApp, then whitelist a chat and enable a workflow."
    echo "More commands: ./run.sh help"
}

# ---- Commands ----

cmd_build() {
    fetch_submodules
    log "Building images"
    compose build "$@"
}

cmd_up() {
    check_gpu
    fetch_submodules
    prepare_env
    cmd_build
    log "Starting the stack"
    compose up -d --remove-orphans
    wait_for_web "$(web_port)"
    compose ps
    print_info
}

cmd_update() {
    log "Pulling the latest code"
    git pull --ff-only
    git submodule update --init --recursive
    cmd_up
}

main() {
    local cmd=${1:-up}
    shift || true

    case "$cmd" in
        help|-h|--help) usage; return ;;
    esac

    require_docker
    case "$cmd" in
        up)      cmd_up ;;
        build)   cmd_build "$@" ;;
        start)   [[ -f .env ]] || die ".env not found: run ./run.sh first"
                 compose up -d "$@"; wait_for_web "$(web_port)"; print_info ;;
        stop)    compose stop "$@" ;;
        restart) compose restart "$@" ;;
        down)    compose down ;;
        status)  compose ps; print_info ;;
        logs)    compose logs -f --tail=100 "$@" ;;
        update)  cmd_update ;;
        info)    print_info ;;
        *)       usage >&2; die "unknown command: $cmd" ;;
    esac
}

main "$@"
