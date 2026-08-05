#!/usr/bin/env bash

set -u

BASE_URL="${BASE_URL:-http://localhost:3010}"
LITELLM_URL="${LITELLM_URL:-http://localhost:4000}"
SERVER_WHISPER_URL="${SERVER_WHISPER_URL:-http://localhost:3004}"

PASSED=0
FAILED=0

green() {
    printf '\033[0;32m%s\033[0m\n' "$1"
}

red() {
    printf '\033[0;31m%s\033[0m\n' "$1"
}

yellow() {
    printf '\033[0;33m%s\033[0m\n' "$1"
}

check_http() {
    local name="$1"
    local url="$2"
    local expected="${3:-200}"

    local status

    status=$(curl \
        --silent \
        --output /tmp/homelab-smoke-body \
        --write-out '%{http_code}' \
        --connect-timeout 5 \
        --max-time 15 \
        "$url" 2>/dev/null || true)

    if [ "$status" = "$expected" ]; then
        green "PASS  $name ($status)"
        PASSED=$((PASSED + 1))
        return 0
    fi

    red "FAIL  $name (expected $expected, got ${status:-no response})"

    if [ -s /tmp/homelab-smoke-body ]; then
        head -c 500 /tmp/homelab-smoke-body
        echo
    fi

    FAILED=$((FAILED + 1))
    return 1
}

check_json_value() {
    local name="$1"
    local url="$2"
    local jq_filter="$3"
    local expected="$4"

    local response
    local value

    response=$(curl \
        --silent \
        --show-error \
        --connect-timeout 5 \
        --max-time 15 \
        "$url" 2>/dev/null || true)

    if [ -z "$response" ]; then
        red "FAIL  $name (no response)"
        FAILED=$((FAILED + 1))
        return 1
    fi

    value=$(printf '%s' "$response" | jq -r "$jq_filter" 2>/dev/null || true)

    if [ "$value" = "$expected" ]; then
        green "PASS  $name ($value)"
        PASSED=$((PASSED + 1))
        return 0
    fi

    red "FAIL  $name (expected $expected, got ${value:-null})"
    FAILED=$((FAILED + 1))
    return 1
}

echo
echo "========================================"
echo " Homelab Core Smoke Test"
echo "========================================"
echo

check_http "Homelab Core root" "$BASE_URL/"
check_http "Health API" "$BASE_URL/health"
check_http "Dashboard API" "$BASE_URL/dashboard"
check_http "System API" "$BASE_URL/system"
check_http "Models API" "$BASE_URL/models"
check_http "Resources API" "$BASE_URL/resources/mac"
check_http "Task Queue API" "$BASE_URL/tasks"
check_http "Task statistics" "$BASE_URL/tasks/stats"
check_http "OpenAPI documentation" "$BASE_URL/docs"

echo
echo "Backend checks"
echo "--------------"

check_json_value \
    "Core status" \
    "$BASE_URL/health" \
    '.status' \
    'ok'

check_json_value \
    "SQLite schema" \
    "$BASE_URL/health" \
    '.schema_version' \
    '1'

check_json_value \
    "Server Whisper" \
    "$BASE_URL/health" \
    '.server_whisper' \
    'true'

check_json_value \
    "LiteLLM" \
    "$BASE_URL/health" \
    '.litellm' \
    'true'

check_http \
    "Server Whisper direct API" \
    "$SERVER_WHISPER_URL/v1/models"

echo
echo "Optional Mac checks"
echo "-------------------"

MAC_ONLINE=$(curl -s "$BASE_URL/dashboard" | jq -r '.mac.online // false')

if [ "$MAC_ONLINE" = "true" ]; then
    green "PASS  Mac Agent online"
    PASSED=$((PASSED + 1))

    LM_STUDIO=$(curl -s "$BASE_URL/dashboard" | jq -r '.llm.lm_studio // false')

    if [ "$LM_STUDIO" = "true" ]; then
        green "PASS  LM Studio online"
        PASSED=$((PASSED + 1))
    else
        yellow "INFO  LM Studio offline — queued LLM tasks will wait"
    fi

    MAC_WHISPER=$(curl -s "$BASE_URL/dashboard" | jq -r '.whisper.mac_running // false')

    if [ "$MAC_WHISPER" = "true" ]; then
        green "PASS  Mac Whisper running"
        PASSED=$((PASSED + 1))
    else
        yellow "INFO  Mac Whisper sleeping — this is normal"
    fi
else
    yellow "INFO  Mac Agent offline — Fujitsu Whisper fallback remains available"
fi

echo
echo "Container checks"
echo "----------------"

for container in \
    ai-gateway \
    litellm \
    whisper \
    open-webui \
    n8n \
    qdrant \
    homepage
do
    if docker inspect \
        --format '{{.State.Running}}' \
        "$container" 2>/dev/null | grep -q '^true$'
    then
        green "PASS  container $container running"
        PASSED=$((PASSED + 1))
    else
        red "FAIL  container $container not running"
        FAILED=$((FAILED + 1))
    fi
done

echo
echo "========================================"
echo " Passed: $PASSED"
echo " Failed: $FAILED"
echo "========================================"

rm -f /tmp/homelab-smoke-body

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi

exit 0
