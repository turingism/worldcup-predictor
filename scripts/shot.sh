#!/bin/bash
# shot.sh — headless 截图（**必须用它，不要手敲 Chrome 命令**）
#
# 为什么存在：手敲的 `Google Chrome --headless=new --screenshot ...` 若不带 --user-data-dir，
# 会直接占用**用户的真实 Chrome 配置目录**。此时该实例持有 profile 的 singleton 锁，
# 用户点击 Chrome 图标只会把请求转交给这个无窗口的 headless 实例——表现就是「Chrome 打不开」。
# 2026-07-25 已真实发生过一次。本脚本固定给独立临时 profile，并在退出时清理。
#
# 用法:
#   scripts/shot.sh <输出png> <宽,高> <缩放> <url> [额外参数...]
# 例:
#   scripts/shot.sh docs/evidence/home.png 1440,1700 1 'http://127.0.0.1:8000/#home'
#   scripts/shot.sh /tmp/m.png 390,1500 2 'http://127.0.0.1:8000/#home'
#
# 已知坑（沿用 CLAUDE.md 档案）：headless 的 innerWidth 有 ~500px 地板，≤430px 的手机断点
# 截不出来；`--force-device-scale-factor=2` 只放大像素、不改 CSS 视口。
set -euo pipefail

OUT="${1:?用法: shot.sh <out.png> <w,h> <scale> <url>}"
SIZE="${2:?}"
SCALE="${3:-1}"
URL="${4:?}"
shift 4 || true

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$(mktemp -d -t chrome-shot)"
trap 'rm -rf "$PROFILE"' EXIT

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"

"$CHROME" --headless=new --no-proxy-server --disable-gpu --no-first-run \
  --user-data-dir="$PROFILE" \
  --screenshot="$OUT" --window-size="$SIZE" \
  --force-device-scale-factor="$SCALE" --virtual-time-budget=15000 \
  "$@" "$URL" >/dev/null 2>&1 &
PID=$!

# macOS 无 timeout 命令：自建看门狗（60s）
for _ in $(seq 1 60); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 1
done
kill -9 "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true

[ -s "$OUT" ] || { echo "截图失败：$OUT 未生成" >&2; exit 1; }
printf '%s (%s bytes)\n' "$OUT" "$(wc -c < "$OUT" | tr -d ' ')"
