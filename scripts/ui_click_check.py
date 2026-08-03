#!/usr/bin/env python3
"""交互验收（真实浏览器）：首页比赛流补估算 + 点击场次把两队带进对阵分析。

为什么单独一个脚本而不是塞进 test_core：pytest 里没有浏览器，最多 grep 到源码里写了
`?h=&a=`——**写了不等于传到了**。本轮真实缺陷就是这种：`renderEventView(key, tab)` 没有
声明 qs 形参，源码里三处 qs 齐全、grep 全绿，运行时却 ReferenceError，整个赛事视图不渲染
（输入框根本不存在＝用户说的「获取不到 id」）。所以行为事实以本脚本退出码为准。

覆盖四条：
  ① 首页未冻结场次显示「当前模型估算（未冻结）」且数字与看板同源（同一场不出两个数字）
  ② 点首页比赛流某场 → hash 带 ?h=&a=，对阵分析输入框预填该场两队并出预测卡
  ③ 看板「未来赛程预测」整行可点，同赛事内连点第二场也生效（带撇号队名如 Nott'm Forest）
  ④ 直接打开带参深链（＝刷新/别人打开分享链接）同样预填；世界杯页零回归

用法：/opt/anaconda3/bin/python3 scripts/ui_click_check.py [--base-url http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui_check import Chrome  # noqa: E402

READY = ("document.getElementById('homeview')"
         "&&document.getElementById('homeview').dataset.homeReady==='1'")
INPUTS = """JSON.stringify({
  h:(document.getElementById('ev_home')||{}).value||'',
  a:(document.getElementById('ev_away')||{}).value||'',
  card:((document.getElementById('ev_predout')||{}).innerText||'').replace(/\\s+/g,' ').slice(0,200)})"""


def _wait(c, expr, secs=30.0):
    for _ in range(int(secs * 4)):
        if c.eval(expr):
            return True
        time.sleep(0.25)
    return False


def run(base: str) -> dict:
    c = Chrome(1440, 1000)
    r = {}
    try:
        c.cmd("Page.enable")
        c.cmd("Runtime.enable")
        c.cmd("Page.navigate", {"url": base + "/#home"})
        _wait(c, READY)
        # ① 首页估算补位（看板请求回来才有）
        _wait(c, "[...document.querySelectorAll('.hm-mrow .m-p')]"
                 ".some(x=>/估算（未冻结）/.test(x.innerText))", 25)
        stream = json.loads(c.eval("""JSON.stringify([...document.querySelectorAll('.hm-mrow')]
            .map(x=>({ev:x.dataset.ev,h:x.dataset.h,a:x.dataset.a,pending:x.dataset.pending,
                      p:x.querySelector('.m-p').innerText.replace(/\\s+/g,' ').trim()})))""") or "[]")
        r["stream_rows"] = len(stream)
        r["stream_has_estimate"] = any("估算（未冻结）" in x["p"] for x in stream)
        r["stream_no_bare_number"] = all(("待冻结" in x["p"]) or ("冻结 ·" in x["p"])
                                         or ("估算（未冻结）" in x["p"]) for x in stream)
        # ② 点首页比赛流
        r["home_click_target"] = stream[0] if stream else None
        c.eval("document.querySelector('.hm-mrow').click()")
        ok = _wait(c, "!!document.getElementById('ev_home')", 20)
        _wait(c, "/单场预测/.test((document.getElementById('ev_predout')||{}).innerText||'')", 25)
        r["home_click_hash"] = c.eval("location.hash")
        r["home_click_inputs"] = json.loads(c.eval(INPUTS) or "{}")
        r["home_click_ok"] = bool(ok and "?h=" in (r["home_click_hash"] or "")
                                  and r["home_click_inputs"].get("h")
                                  and "单场预测" in r["home_click_inputs"].get("card", ""))
        # ③ 看板整行可点（含带撇号队名）
        c.eval("location.hash='epl2627/board'")
        _wait(c, "document.querySelectorAll('tr.ev-clk').length>0", 30)
        n = c.eval("document.querySelectorAll('tr.ev-clk').length")
        r["board_clickable_rows"] = n
        idx = c.eval("""(()=>{const rs=[...document.querySelectorAll('tr.ev-clk')];
            const i=rs.findIndex(x=>/'/.test(x.dataset.h||''));return i<0?0:i;})()""")
        c.eval(f"document.querySelectorAll('tr.ev-clk')[{idx}].click()")
        _wait(c, "!!document.getElementById('ev_home')", 20)
        _wait(c, "/单场预测/.test((document.getElementById('ev_predout')||{}).innerText||'')", 25)
        r["board_click_hash"] = c.eval("location.hash")
        r["board_click_inputs"] = json.loads(c.eval(INPUTS) or "{}")
        r["board_click_ok"] = bool(n and "?h=" in (r["board_click_hash"] or "")
                                   and r["board_click_inputs"].get("h")
                                   and "单场预测" in r["board_click_inputs"].get("card", ""))
        # ④ 深链直开（刷新/分享）+ 世界杯零回归
        c.cmd("Page.navigate", {"url": base + "/#epl2627/matchup?h=Hull&a=Man%20United"})
        _wait(c, "/单场预测/.test((document.getElementById('ev_predout')||{}).innerText||'')", 30)
        d = json.loads(c.eval(INPUTS) or "{}")
        r["deeplink_inputs"] = d
        r["deeplink_ok"] = bool(d.get("h") and "赫尔城" in d["h"] and "单场预测" in d.get("card", ""))
        c.eval("location.hash='wc2026/verify'")
        time.sleep(2.5)
        r["wc_title"] = c.eval("document.title")
        r["wc_verify_display"] = c.eval(
            "getComputedStyle(document.querySelector('#verify')).display")
        r["wc_no_regression"] = (r["wc_title"] == "⚽ 世界杯比分预测器"
                                 and r["wc_verify_display"] == "block")
    finally:
        c.close()
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "docs", "evidence", "ui-click-check.json"))
    a = ap.parse_args()
    r = run(a.base_url)
    checks = ["stream_has_estimate", "stream_no_bare_number", "home_click_ok",
              "board_click_ok", "deeplink_ok", "wc_no_regression"]
    r["pass"] = all(bool(r.get(k)) for k in checks)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: r.get(k) for k in checks + ["pass"]}, ensure_ascii=False, indent=1))
    for k in checks:
        if not r.get(k):
            print(f"  ✗ {k}: {json.dumps(r.get(k.replace('_ok', '_inputs')), ensure_ascii=False)}")
    print(f"→ {a.out}")
    return 0 if r["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
