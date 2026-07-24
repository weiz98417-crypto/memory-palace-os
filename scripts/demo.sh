#!/bin/bash
# Memory Palace OS · Demo Script
# Usage: ./scripts/demo.sh [scene1|scene2|scene3|scene4|scene5|all]
# Requires: DEMO_MODE=true server running on localhost:8000

BASE="http://localhost:8000"
SCENE="${1:-all}"

send() {
  local scene="$1" msg="$2"
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  $scene"
  echo "  Input: $msg"
  echo "═══════════════════════════════════════════════════════════"
  local resp=$(curl -s -X POST "$BASE/demo/send" \
    -H "Content-Type: application/json" \
    -d "{\"content\":\"$msg\",\"from_user\":\"demo\"}")
  echo "  Sent: $resp"
  local tid=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('trace_id',''))" 2>/dev/null)
  if [ -z "$tid" ]; then
    # Try python (Windows)
    tid=$(echo "$resp" | python -c "import sys,json; print(json.load(sys.stdin).get('trace_id',''))" 2>/dev/null)
  fi
  [ -z "$tid" ] && { echo "  ERROR: Failed to get trace_id"; return; }

  echo "  Polling result..."
  for i in $(seq 1 15); do
    sleep 1
    local result=$(curl -s "$BASE/demo/result/$tid")
    local code=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code','1'))" 2>/dev/null)
    [ -z "$code" ] && code=$(echo "$result" | python -c "import sys,json; print(json.load(sys.stdin).get('code','1'))" 2>/dev/null)
    if [ "$code" = "0" ]; then
      local reply=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reply_text',''))" 2>/dev/null)
      [ -z "$reply" ] && reply=$(echo "$result" | python -c "import sys,json; print(json.load(sys.stdin).get('reply_text',''))" 2>/dev/null)
      local route=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('route',''))" 2>/dev/null)
      [ -z "$route" ] && route=$(echo "$result" | python -c "import sys,json; print(json.load(sys.stdin).get('route',''))" 2>/dev/null)
      echo "  ─────────────────────────────────────────────────────"
      echo "  Route: $route"
      echo "  Reply:"
      echo "    $reply"
      echo "  ─────────────────────────────────────────────────────"
      return
    fi
  done
  echo "  Timeout - pipeline may still be processing"
}

# ── Scene 1: 紧急事件 → Commander ──────────────────────────────────────────
scene1() {
  send "🎬 Scene 1: 紧急事件 → ContextTrigger + Commander" \
    "景区西门有游客受伤了，需要紧急处理"
}

# ── Scene 2: 日常咨询 → Persona ────────────────────────────────────────────
scene2() {
  send "🎬 Scene 2: 日常咨询 → Router + Persona" \
    "景区附近有什么好吃的餐厅推荐吗"
}

# ── Scene 3: 任务分解 → Todo + TaskGraph ───────────────────────────────────
scene3() {
  send "🎬 Scene 3: 任务分解 → Todo + TaskGraph" \
    "景区节假日前需要做安全检查和人员排班计划"
}

# ── Scene 4: 经验萃取 → PersonaExtract ─────────────────────────────────────
scene4() {
  send "🎬 Scene 4: 老员工经验萃取 → PersonaExtract" \
    "我在这里工作了15年，主要负责园区安全巡检和游客疏导，每天早班第一件事是检查所有消防设备"
}

# ── Scene 5: 知识检索 → MemoryOps ──────────────────────────────────────────
scene5() {
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  🎬 Scene 5: 知识库检索 → MemoryOps"
  echo "═══════════════════════════════════════════════════════════"
  echo ""
  echo "  Querying knowledge base..."
  curl -s "$BASE/v1/knowledge/query?question=景区安全应急预案&top_k=3&threshold=0.3" | python3 -m json.tool 2>/dev/null || curl -s "$BASE/v1/knowledge/query?question=景区安全应急预案&top_k=3&threshold=0.3" | python -m json.tool 2>/dev/null
}

# ── Main ────────────────────────────────────────────────────────────────────
case "$SCENE" in
  scene1)  scene1 ;;
  scene2)  scene2 ;;
  scene3)  scene3 ;;
  scene4)  scene4 ;;
  scene5)  scene5 ;;
  all|*)
    scene1; sleep 2
    scene2; sleep 2
    scene3; sleep 2
    scene4; sleep 2
    scene5
    ;;
esac

echo ""
echo "═══ Demo complete ═══"
