#!/usr/bin/env bash
set -euo pipefail

# Required env vars: RUN_ID, ORCHESTRATOR_URL, HF_TOKEN, ORCHESTRATOR_API_KEY,
#                    MODEL, ENGINE, SCENARIO, GGUF_FILE (optional, may be empty)
ORCHESTRATOR_URL="${ORCHESTRATOR_URL%/}"
API_KEY_HEADER="X-API-Key: ${ORCHESTRATOR_API_KEY:-}"
GGUF_FILE="${GGUF_FILE:-}"
MODEL_DIR="/opt/models"
ENGINE_PORT=8080
ENGINE_PID=""
LOG_FILE="/var/log/llmgrill-runner.log"
LOGS_UPLOADED=0

# Mirror stdout/stderr to a file (also kept in journald via the systemd unit).
: > "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

upload_logs() {
  [[ "$LOGS_UPLOADED" == "1" ]] && return 0
  local size body tmp=""
  size=$(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)
  if [ "$size" -le 5242880 ]; then
    body="$LOG_FILE"
  else
    tmp=$(mktemp)
    head -c 2621440 "$LOG_FILE" > "$tmp"
    printf '\n[... truncated middle %s bytes ...]\n' "$((size - 5242880))" >> "$tmp"
    tail -c 2621440 "$LOG_FILE" >> "$tmp"
    body="$tmp"
  fi
  curl -sf -X POST "${ORCHESTRATOR_URL}/runs/${RUN_ID}/logs" \
    -H "$API_KEY_HEADER" -H "Content-Type: text/plain" \
    --data-binary "@$body" || true
  [[ -z "$tmp" ]] || rm -f "$tmp"
  LOGS_UPLOADED=1
  return 0
}

fail() {
  upload_logs
  curl -sf -X POST "${ORCHESTRATOR_URL}/runs/${RUN_ID}/fail" \
    -H "Content-Type: application/json" \
    -H "$API_KEY_HEADER" \
    -d "$(jq -n --arg msg "$1" '{error_message: $msg}')" || true
  [[ -n "$ENGINE_PID" ]] && kill "$ENGINE_PID" 2>/dev/null || true
  exit 1
}

trap 'fail "unexpected error on line $LINENO"' ERR

# Run params are injected via cloud-init into /etc/llmgrill/env (MODEL, ENGINE,
# SCENARIO, GGUF_FILE). No round-trip to the orchestrator is needed at startup.

# --- 1. Download model ---
mkdir -p "${MODEL_DIR}/${MODEL}"
if [[ -n "$GGUF_FILE" ]]; then
  HF_TOKEN="$HF_TOKEN" hf download "$MODEL" "$GGUF_FILE" --local-dir "${MODEL_DIR}/${MODEL}"
else
  HF_TOKEN="$HF_TOKEN" hf download "$MODEL" --local-dir "${MODEL_DIR}/${MODEL}"
fi

# --- 3. Start engine ---
if [[ "$ENGINE" == "vllm" ]]; then
  python3 -m vllm.entrypoints.openai.api_server \
    --model "${MODEL_DIR}/${MODEL}" \
    --served-model-name "$MODEL" \
    --port "$ENGINE_PORT" &
  ENGINE_PID=$!
elif [[ "$ENGINE" == "llamacpp" ]]; then
  if [[ -n "$GGUF_FILE" ]]; then
    GGUF="${MODEL_DIR}/${MODEL}/${GGUF_FILE}"
  else
    GGUF=$(ls "${MODEL_DIR}/${MODEL}"/*.gguf | head -1)
  fi
  llama-server --model "$GGUF" --port "$ENGINE_PORT" --ctx-size 4096 &
  ENGINE_PID=$!
else
  fail "unknown engine: $ENGINE"
fi

# --- 4. Healthcheck ---
DEADLINE=$(( $(date +%s) + 300 ))
until curl -sf "http://localhost:${ENGINE_PORT}/health" > /dev/null; do
  [[ $(date +%s) -ge $DEADLINE ]] && fail "engine did not become healthy within 300s"
  sleep 5
done

# --- 5. Warmup ---
curl -sf -X POST "http://localhost:${ENGINE_PORT}/v1/completions" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg m "$MODEL" '{model:$m,prompt:"hello",max_tokens:1}')" > /dev/null

# --- 6. Benchmark ---
RESULTS_FILE=/tmp/llmgrill-results.jsonl
llm-grill run "$SCENARIO" --output "$RESULTS_FILE"

# --- 7. Report success ---
upload_logs
COMPLETE_PAYLOAD=/tmp/llmgrill-complete.json
jq -n --rawfile r "$RESULTS_FILE" '{results_jsonl: $r}' > "$COMPLETE_PAYLOAD"
curl -sf -X POST "${ORCHESTRATOR_URL}/runs/${RUN_ID}/complete" \
  -H "Content-Type: application/json" \
  -H "$API_KEY_HEADER" \
  --data-binary "@$COMPLETE_PAYLOAD"

# --- 8. Cleanup ---
kill "$ENGINE_PID" 2>/dev/null || true
rm -rf "${MODEL_DIR:?}/${MODEL}"
