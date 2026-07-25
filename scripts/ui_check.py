#!/usr/bin/env python3
"""真实浏览器布局验收（P0-H）：headless Chrome + CDP 实测，产出 docs/evidence/home-ui-check.json。

为什么单独一个脚本而不是塞进 test_core：pytest 里没有浏览器，最多只能 grep 到 CSS 写了
flex-wrap:nowrap——而 CSS 写了不等于渲染不溢出（外层容器 min-width、长英文串都能推翻它）。
一个叫 has_no_page_overflow 的 pytest 在页面真溢出时仍然绿，比没有这个测试更糟。
所以 pytest 只保留静态护栏（规则没被删除），**布局事实以本脚本的退出码与 JSON 为准**。

用法：
  /opt/anaconda3/bin/python3 scripts/ui_check.py --base-url http://127.0.0.1:8000 \
      --out docs/evidence/home-ui-check.json
  /opt/anaconda3/bin/python3 scripts/ui_check.py --path '#epl2627/board'   # 详情页同样可测

任一检查为 false → 退出码 1（不允许"生成 JSON 后永远 exit 0"）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import websocket   # websocket-client（anaconda 自带）

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
VIEWPORTS = [(390, 844), (430, 932), (768, 1024), (1440, 900)]
# 本机 CDP 必须绕开系统代理：urllib 默认吃 http_proxy 环境变量，会把 127.0.0.1 也送进代理，
# 表现为「CDP 未就绪」这种误导性失败（本机 Chrome 其实早就起来了）。
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 页面内实测：所有断言都读真实渲染盒模型（getBoundingClientRect / scrollWidth），不读 CSS 声明。
PROBE = r"""
(() => {
  const out = {}, de = document.documentElement;
  out.page_no_overflow = de.scrollWidth <= de.clientWidth + 1;
  const vis = x => x.offsetParent !== null || x === document.body;
  // Tab 单行只在移动端要求（≤760px 起横滚）；桌面宽屏折行是既有设计，不作缺陷。
  const tabs = [...document.querySelectorAll('.tabs .tab')].filter(vis);
  out.tabs_single_row = window.innerWidth > 760 || tabs.length === 0 ||
    new Set(tabs.map(x => Math.round(x.getBoundingClientRect().top))).size === 1;
  // 截断=缺陷；nowrap 本身不是——「14天后」「赛程待发布」这类原子标签本就该不换行。
  // 所以：所有文本节点都查是否被截断；只有**成句文案**额外禁止 nowrap（它们必须能折行）。
  const texts = [...document.querySelectorAll(
      '#homeview .hm-meta, #homeview .hm-fresh div, #homeview .hm-run > div, #eventview .muted')]
    .filter(x => vis(x) && x.textContent.trim());
  const prose = texts.filter(x => !x.matches('.r-days, .r-state, .m-ko, .hm-unit')
                                  && x.textContent.trim().length > 12);
  out.intro_not_clipped = texts.every(el => el.scrollWidth <= el.clientWidth + 1)
    && prose.every(el => getComputedStyle(el).whiteSpace !== 'nowrap');
  out.text_nodes_checked = texts.length;
  out.prose_nodes_checked = prose.length;
  // 越界判定要排除**横滚容器内部**的元素：横滚条（赛事切换器/Tab 条/宽表）里的项本就该伸出去，
  // 它们由容器自己滚动，不会撑大页面。真正的缺陷是「不在任何横滚容器里却越界」。
  const inScroller = el => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement)
      if (/auto|scroll/.test(getComputedStyle(p).overflowX)) return true;
    return false;
  };
  const past = [...document.querySelectorAll('#homeview *, #eventview *, .tabs, .evbar')]
    .filter(x => vis(x) && !inScroller(x) && x.getBoundingClientRect().right > window.innerWidth + 1);
  out.no_element_past_viewport = past.length === 0;
  out.past_viewport_sample = past.slice(0, 3).map(x => (x.tagName + '.' + x.className).slice(0, 60));
  const hs = [...document.querySelectorAll('.hscroll')].filter(vis);
  out.hscroll_contained = hs.every(x => x.getBoundingClientRect().right <= window.innerWidth + 1);
  out.hscroll_checked = hs.length;
  const cards = document.querySelectorAll('#homeview .hm-card').length;
  const evs = document.querySelectorAll('#evbar .ev').length;
  out.all_events_discoverable = cards >= 7 || evs >= 8;   // 首页七张卡 / 详情页侧栏总览+七赛事
  const on = document.querySelector('.tabs .tab.on');
  out.active_tab_visible = !on || (on.getBoundingClientRect().left >= -1 &&
    on.getBoundingClientRect().right <= window.innerWidth + 1);
  out.home_ready = !!(document.querySelector('#homeview') || {}).dataset?.homeReady ||
                   !document.querySelector('#homeview[style*="block"]');
  return out;
})()
"""

BOOL_CHECKS = ("page_no_overflow", "tabs_single_row", "intro_not_clipped",
               "no_element_past_viewport", "hscroll_contained",
               "all_events_discoverable", "active_tab_visible")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Chrome:
    """一个视口一个实例：避免 CDP 改窗口尺寸后的重排竞态污染断言。"""

    def __init__(self, w: int, h: int):
        self.port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="uicheck-")
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--no-proxy-server", "--disable-gpu", "--no-first-run",
             f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
             f"--window-size={w},{h}", "--force-device-scale-factor=1", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws, self._id = None, 0
        for _ in range(80):
            try:
                with _DIRECT.open(f"http://127.0.0.1:{self.port}/json", timeout=5) as r:
                    pages = [t for t in json.loads(r.read()) if t.get("type") == "page"]
                if pages:
                    # suppress_origin 必需：websocket-client 默认发 Origin 头，
                    # Chrome DevTools 对带 Origin 的 WS 升级一律 403（防跨站调试）。
                    self.ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"],
                                                          timeout=30, suppress_origin=True)
                    return
            except Exception:  # noqa  DevTools 尚未监听
                pass
            time.sleep(0.25)
        raise RuntimeError("CDP 未就绪")

    def cmd(self, method: str, params: dict | None = None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def eval(self, expr: str):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                          "awaitPromise": True})
        return r.get("result", {}).get("value")

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        finally:
            self.proc.kill()
            shutil.rmtree(self.profile, ignore_errors=True)


def check(url: str, w: int, h: int, ready_sel: str) -> dict:
    c = Chrome(w, h)
    try:
        c.cmd("Page.enable")
        c.cmd("Page.navigate", {"url": url})
        ok = False
        for _ in range(80):                      # 等渲染完成标记 + 字体就绪
            time.sleep(0.25)
            try:
                if c.eval(f"!!document.querySelector('{ready_sel}')"):
                    c.eval("document.fonts && document.fonts.ready")
                    time.sleep(0.4)
                    ok = True
                    break
            except Exception:  # noqa  导航中 context 重建
                pass
        if not ok:
            return {"width": w, "height": h, "error": f"未等到就绪标记 {ready_sel}", "checks": {}}
        return {"width": w, "height": h, "checks": c.eval(PROBE)}
    finally:
        c.close()


STATE_JS = r"""(() => {
  const tb = document.querySelector('.tabs'), v = document.querySelector('#verify'),
        h = document.querySelector('header h1');
  return {title: document.title, h1: h ? h.textContent.trim() : null,
          tabs: tb ? getComputedStyle(tb).display : null,
          verify: v ? getComputedStyle(v).display : null,
          boot: document.documentElement.className, hash: location.hash};
})()"""


def boot_checks(base_url: str) -> dict:
    """启动期验收（修「刷新时世界杯页面闪一下」）：三项都是 pytest 断不了的浏览器事实。

    ① 真首帧：把 /api/events 与 /api/home 全部堵死（最坏情况：永不返回），
       首页与联赛深链的首帧都不得出现世界杯页头/Tab/看板；世界杯深链必须原样保留。
       注意不能用「关掉 JS」来验——关了 JS，boot 脚本本身也不执行，验的是个空气。
    ② 路由生命周期：#home → #wc2026/bracket → #home → #wc2026/verify，
       抓 boot 类没清理导致世界杯 Tab 被永久压住这类问题。
    """
    out = {"first_frame": [], "lifecycle": []}
    for path, label, expect_wc in (("", "home", False), ("#epl2627/board", "event", False),
                                   ("#wc2026/bracket", "wc", True)):
        c = Chrome(1440, 900)
        try:
            c.cmd("Network.enable")
            c.cmd("Network.setBlockedURLs", {"urls": ["*/api/events*", "*/api/home*"]})
            c.cmd("Page.enable")
            c.cmd("Page.navigate", {"url": f"{base_url}/{path}"})
            time.sleep(2.0)
            s = c.eval(STATE_JS)
            wc_chrome = ("世界杯" in (s.get("h1") or "")) or s.get("tabs") == "flex" \
                or s.get("verify") == "block"
            s.update(label=label, expect_wc=expect_wc, ok=(wc_chrome == expect_wc))
            out["first_frame"].append(s)
        finally:
            c.close()

    c = Chrome(1440, 900)
    try:
        c.cmd("Page.enable")
        c.cmd("Page.navigate", {"url": base_url + "/"})
        for _ in range(80):
            time.sleep(0.25)
            if c.eval("!!document.querySelector('#homeview[data-home-ready]')"):
                break
        steps = [("#home", False), ("wc2026/bracket", True), ("home", False),
                 ("wc2026/verify", True)]
        for i, (h, want_tabs) in enumerate(steps):
            if i:
                c.eval(f"location.hash={h!r}")
                time.sleep(3.0)
            s = c.eval(STATE_JS)
            s.update(step=h, want_tabs=want_tabs,
                     ok=((s["tabs"] == "flex") == want_tabs) and s["boot"].find("boot-") < 0)
            out["lifecycle"].append(s)
    finally:
        c.close()
    out["ok"] = all(x["ok"] for x in out["first_frame"] + out["lifecycle"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--boot", action="store_true", help="只跑启动期验收（首帧 + 路由生命周期）")
    ap.add_argument("--path", default="#home", help="要验收的 hash 路由")
    ap.add_argument("--ready", default=None, help="就绪标记选择器（默认按 path 推断）")
    ap.add_argument("--out", default="docs/evidence/home-ui-check.json")
    a = ap.parse_args()
    if a.boot:
        out = boot_checks(a.base_url)
        for x in out["first_frame"]:
            print(f"  首帧 {x['label']:6} {'OK' if x['ok'] else 'FAIL'}  h1={x['h1']} tabs={x['tabs']}")
        for x in out["lifecycle"]:
            print(f"  路由 {x['step']:16} {'OK' if x['ok'] else 'FAIL'}  tabs={x['tabs']} boot={x['boot']!r}")
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(("通过" if out["ok"] else "存在失败") + f" → {a.out}")
        return 0 if out["ok"] else 1

    ready = a.ready or ("#homeview[data-home-ready]" if a.path in ("#home", "")
                        else "#eventview, #verify")
    url = f"{a.base_url}/{a.path}"

    vps, ok = [], True
    for w, h in VIEWPORTS:
        r = check(url, w, h, ready)
        bad = [k for k in BOOL_CHECKS if r.get("checks", {}).get(k) is False]
        if r.get("error") or bad:
            ok = False
            r["failed"] = bad or [r.get("error")]
        vps.append(r)
        print(f"  {w}x{h}: {'OK' if not (r.get('error') or bad) else 'FAIL ' + str(bad or r.get('error'))}")

    out = {"ok": ok, "url": url, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "viewports": vps}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(("通过" if ok else "存在失败") + f" → {a.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
