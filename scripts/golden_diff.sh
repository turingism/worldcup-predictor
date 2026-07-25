#!/bin/bash
# golden_diff.sh — 双宇宙 golden diff 脚本化（QA 基建，2026-07-24）
#
# 背景：progress.md 十余轮验收里「五端点 golden diff」均为手工 curl 流程，
# 本脚本把捕获与对比固化进仓库，任何改动前后跑两次 capture + 一次 diff 即可。
#
# 用法:
#   scripts/golden_diff.sh capture <快照目录> [BASE_URL]
#   scripts/golden_diff.sh diff <目录A> <目录B>
#
# 典型流程（改动行为回归验收）:
#   scripts/golden_diff.sh capture data/golden/before
#   ... 改动 + launchctl kickstart -k gui/501/com.melvin.worldcup-predictor ...
#   scripts/golden_diff.sh capture data/golden/after
#   scripts/golden_diff.sh diff data/golden/before data/golden/after
#
# BASE_URL 默认 http://127.0.0.1:8000（launchd 生产实例）。
# 快照目录放 data/golden/（已入 .gitignore，属本地验收产物）；脚本本身入库。
#
# 覆盖端点（仅确定性端点，同一数据状态下逐字节可比）:
#   wc2026 五端点:  /api/ratings /api/teams /api/verify /api/config /api/champ_ci
#   club  五端点:  /api/club/overview /api/club/predict /api/club/seasonsim
#                  /api/club/market /api/jc_review(GET 模型预览)  各 event=epl2627
#
# 明确排除的端点及原因（勿加回来，逐字节不可比）:
#   /api/bracket / /api/champions   — 蒙特卡洛随机抽样（随机一届/夺冠 MC），非确定输出
#   /api/dashboard / /api/live      — ESPN 实时源，输出随抓取时刻变化
#   /api/market / /api/market_research — 外部盘口快照 + as_of 模型训练，随数据滚动
#   /api/xuanxue/board              — 擂台账本随完赛结算滚动
#   /api/version                    — 含构建/时间类元信息
#
# 已知限制:
#   /api/club/overview 的 upcoming 按「今天+14 天」窗口计算——before/after 两份快照
#   须在同一天、同一数据状态下抓取；跨天 diff 出现 upcoming 差异属预期而非回归。
set -euo pipefail

usage() { sed -n '2,40p' "$0" | grep -E '^# ?' | sed 's/^# \{0,1\}//'; exit 1; }

MODE="${1:-}"

# 端点清单：名字|路径|query（query 内以 & 分隔，值允许中文，capture 时逐段 urlencode）
ENDPOINTS=(
  "wc_ratings|/api/ratings|event=wc2026"
  "wc_teams|/api/teams|event=wc2026"
  "wc_verify|/api/verify|event=wc2026"
  "wc_config|/api/config|event=wc2026"
  "wc_champ_ci|/api/champ_ci|event=wc2026"
  "club_overview|/api/club/overview|event=epl2627"
  "club_predict|/api/club/predict|event=epl2627&home=阿森纳&away=曼城"
  "club_seasonsim|/api/club/seasonsim|event=epl2627"
  "club_market|/api/club/market|event=epl2627"
  "club_jc_review|/api/jc_review|event=epl2627&home=阿森纳&away=曼城"
)

capture() {
  local dir="$1" base="${2:-http://127.0.0.1:8000}"
  mkdir -p "$dir"
  local fail=0
  for spec in "${ENDPOINTS[@]}"; do
    IFS='|' read -r name path query <<< "$spec"
    local args=(-sfG "$base$path")
    IFS='&' read -ra kvs <<< "$query"
    for kv in "${kvs[@]}"; do args+=(--data-urlencode "$kv"); done
    if curl "${args[@]}" -o "$dir/$name.json"; then
      printf '  ok   %-16s %s?%s (%s bytes)\n' "$name" "$path" "$query" \
        "$(wc -c < "$dir/$name.json" | tr -d ' ')"
    else
      printf '  FAIL %-16s %s?%s\n' "$name" "$path" "$query"
      fail=1
    fi
  done
  [ "$fail" -eq 0 ] && echo "capture 完成 → $dir" || { echo "capture 有失败端点"; exit 1; }
}

diff_dirs() {
  local a="$1" b="$2" bad=0
  for spec in "${ENDPOINTS[@]}"; do
    IFS='|' read -r name _ _ <<< "$spec"
    if [ ! -f "$a/$name.json" ] || [ ! -f "$b/$name.json" ]; then
      printf '  MISS %-16s（快照缺文件）\n' "$name"; bad=1; continue
    fi
    if cmp -s "$a/$name.json" "$b/$name.json"; then
      printf '  ==   %-16s 逐字节一致\n' "$name"
    else
      printf '  DIFF %-16s 不一致！\n' "$name"; bad=1
    fi
  done
  if [ "$bad" -eq 0 ]; then echo "golden diff 干净：全部端点逐字节一致"; else
    echo "golden diff 存在差异/缺失（见上）"; exit 1; fi
}

case "$MODE" in
  capture) [ $# -ge 2 ] || usage; capture "$2" "${3:-http://127.0.0.1:8000}" ;;
  diff)    [ $# -eq 3 ] || usage; diff_dirs "$2" "$3" ;;
  *)       usage ;;
esac
