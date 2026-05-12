#!/usr/bin/env bash
set -euo pipefail

# Required env vars: RUN_ID, ORCHESTRATOR_URL, HF_TOKEN, ORCHESTRATOR_API_KEY
ORCHESTRATOR_URL="${ORCHESTRATOR_URL%/}"
API_KEY_HEADER="X-API-Key: ${ORCHESTRATOR_API_KEY:-}"
MODEL_DIR="/opt/models"
ENGINE_PORT=8080
ENGINE_PID=""

fail() {
  curl -sf -X POST "${ORCHESTRATOR_URL}/runs/${RUN_ID}/fail" \
    -H "Content-Type: application/json" \
    -H "$API_KEY_HEADER" \
    -d "$(jq -n --arg msg "$1" '{error_message: $msg}')" || true
  [[ -n "$ENGINE_PID" ]] && kill "$ENGINE_PID" 2>/dev/null || true
  exit 1
}

trap 'fail "unexpected error on line $LINENO"' ERR

# --- 1. Fetch run params ---
RUN_JSON=$(curl -sf "${ORCHESTRATOR_URL}/runs/${RUN_ID}" -H "$API_KEY_HEADER")
MODEL=$(echo "$RUN_JSON" | jq -r '.model')
ENGINE=$(echo "$RUN_JSON" | jq -r '.engine')
SCENARIO=$(echo "$RUN_JSON" | jq -r '.scenario_path')
GGUF_FILE=$(echo "$RUN_JSON" | jq -r '.gguf_file // empty')

# --- 2. Download model ---
mkdir -p "${MODEL_DIR}/${MODEL}"
if [[ -n "$GGUF_FILE" ]]; then
  HF_TOKEN="$HF_TOKEN" huggingface-cli download "$MODEL" "$GGUF_FILE" --local-dir "${MODEL_DIR}/${MODEL}"
else
  HF_TOKEN="$HF_TOKEN" huggingface-cli download "$MODEL" --local-dir "${MODEL_DIR}/${MODEL}"
fi

# --- 3. Start engine ---
if [[ "$ENGINE" == "vllm" ]]; then
  python3 -m vllm.entrypoints.openai.api_server \
    --model "${MODEL_DIR}/${MODEL}" --port "$ENGINE_PORT" &
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
  -d '{"model":"default","prompt":"hello","max_tokens":1}' > /dev/null

# --- 6. Benchmark ---
RESULTS=$(llm-grill run --scenario "$SCENARIO" --output jsonl)

# --- 7. Report success ---
curl -sf -X POST "${ORCHESTRATOR_URL}/runs/${RUN_ID}/complete" \
  -H "Content-Type: application/json" \
  -H "$API_KEY_HEADER" \
  -d "$(jq -n --arg r "$RESULTS" '{results_jsonl: $r}')"

# --- 8. Cleanup ---
kill "$ENGINE_PID" 2>/dev/null || true
rm -rf "${MODEL_DIR:?}/${MODEL}"
