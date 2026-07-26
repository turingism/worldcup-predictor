#!/usr/bin/env python3
"""静态导出：把 READONLY 冻结快照下的全部 GET 响应预渲染成 JSON 文件，供 GitHub Pages 托管。

为什么可行：冻结快照下每个读接口的响应都是数据的确定函数，没有随机、没有实时。
把重计算（回溯验证 3GB、市场评估 1GB、262s 预热）全留在构建期，线上只发文件。

产物结构：
    dist/index.html               前端（由 app 渲染后落盘，STATIC_MODE 已注入）
    dist/api/ab/<16位哈希>.json   每个接口响应一个文件

**刻意不做 manifest**：本项目导出约 3 万个接口组合，映射表约 3MB，而访客首次取数就得先
把它整个下载下来——代价不可接受。改用确定性哈希：文件名 = FNV-1a 64 位(规范化查询串)，
前端同式算出路径直接取，零索引、零预载；没预生成就自然 404，由既有错误分支渲染。

两个口径必须与前端 shim 逐字节一致，任一改动都要同步改，否则全站取数落空：
    ① canon()：路径 + '?' + 参数按 key 排序、值取**解码后**原文、以 & 连接
    ② fnv1a64()：同一初值/质数/64 位掩码，输出 16 位小写十六进制
前两位做子目录分片，避免单目录几万文件。

用法（务必不带 READONLY，否则 champions/insights 会被写接口守卫挡成 403）：
    python3 export_static.py [--out dist] [--skip-heavy]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from urllib.parse import parse_qsl, urlparse

os.environ.pop("READONLY", None)          # 导出器要真实数据，不能被只读守卫挡

import app as appmod                       # noqa: E402  模块级会训练/载入模型

# 关掉市场让球盘的后台抓取。它每遇到一个新对阵就起一个线程去抓 ESPN（两次请求），
# 导出时按无序对阵去重仍有 1128 组——而这函数**本次调用只返回已有缓存**，
# 抓回来的数据进不了当次响应，等于纯白跑网络。更要命的是它让输出不确定：
# 某个对阵的 JSON 里有没有市场数据，取决于后台线程与导出循环谁先跑完。
# 冻结快照必须可复现，故直接置空——线上本就不显示市场对标（无实时盘口来源）。
appmod._market_handicap_one = lambda *a, **k: None


# ---------------------------------------------------------------- 规范化

def canon(url: str) -> str:
    """URL → 规范化查询串。与前端 shim 的 canon() 必须完全同口径。"""
    u = urlparse(url)
    if not u.query:
        return u.path
    items = sorted(parse_qsl(u.query, keep_blank_values=True))
    return u.path + "?" + "&".join(f"{k}={v}" for k, v in items)


_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_MASK64 = 0xFFFFFFFFFFFFFFFF


def fnv1a64(s: str) -> str:
    """FNV-1a 64 位。选它是因为几行就能在 Python 与 JS 里写出逐位相同的实现
    （JS 侧用 BigInt）；3 万条目下碰撞概率约 2.7e-11，可忽略。"""
    h = _FNV_OFFSET
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * _FNV_PRIME) & _MASK64
    return f"{h:016x}"


def path_for(url: str) -> str:
    d = fnv1a64(canon(url))
    return f"api/{d[:2]}/{d}.json"


class Exporter:
    def __init__(self, out: str):
        self.out = out
        os.makedirs(os.path.join(out, "api"), exist_ok=True)
        self.client = appmod.app.test_client()
        self.seen: set[str] = set()
        self.n = 0
        self.bytes = 0
        self.skipped: list[tuple[str, str]] = []

    def get(self, url: str, *, method: str = "GET", body: dict | None = None) -> bool:
        key = canon(url)
        if key in self.seen:
            return True
        try:
            if method == "POST":
                r = self.client.post(url, json=body or {})
            else:
                r = self.client.get(url)
        except Exception as e:                       # noqa  单个接口炸掉不能中断整次导出
            self.skipped.append((key, f"异常 {type(e).__name__}: {e}"))
            return False
        if r.status_code != 200:
            # 4xx 也照实落盘：前端本来就有「该场暂无盘口」这类空态分支，落盘才能忠实还原
            if r.status_code in (400, 404):
                pass
            else:
                self.skipped.append((key, f"HTTP {r.status_code}"))
                return False
        rel = path_for(url)
        dst = os.path.join(self.out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(r.data)
        self.n += 1
        self.bytes += len(r.data)
        self.seen.add(key)
        return True

    def json_of(self, url: str):
        r = self.client.get(url)
        return json.loads(r.get_data(as_text=True)) if r.status_code == 200 else None

    def finish(self):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--skip-heavy", action="store_true",
                    help="跳过 manager（占体积八成），用于快速冒烟")
    args = ap.parse_args()

    t0 = time.time()
    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    ex = Exporter(args.out)

    # ---------------------------------------------------------- ① 单例接口
    singles = ["/api/events", "/api/home", "/api/teams", "/api/config", "/api/version",
               "/api/dashboard", "/api/ratings", "/api/fixtures", "/api/availability",
               "/api/environment", "/api/handicap_ledger", "/api/lineup_ledger",
               "/api/xuanxue/board", "/api/champ_ci", "/api/verify", "/api/bracket",
               "/api/market?demo=1", "/api/market_research"]
    for u in singles:
        ex.get(u)
    print(f"[export] ① 单例接口 {len(singles)} 个 → 已写 {ex.n}", flush=True)

    # POST 且带 overrides 的两个：只导出「无假设赛果」的默认态（静态站无法提交假设）。
    # sims 取 #sims 下拉的全部档位（2000/5000/10000），漏一档那档就查不到表。
    for n in (2000, 5000, 10000):
        ex.get(f"/api/champions?sims={n}", method="POST", body={"overrides": []})
    ex.get("/api/insights?sims=3000", method="POST", body={"overrides": []})

    # ---------------------------------------------------------- ② 赛事与俱乐部面板
    import events as evmod
    club_keys = [k for k, v in evmod.EVENTS.items()
                 if str(v.get("universe", "")).startswith("club_")]
    intl_keys = [k for k, v in evmod.EVENTS.items()
                 if str(v.get("universe", "")) == "intl"]

    before = ex.n
    for k in club_keys:
        for kind in ("overview", "seasonsim", "market"):
            ex.get(f"/api/club/{kind}?event={k}")
    print(f"[export] ② 俱乐部面板 {len(club_keys)}赛事×3 → 新增 {ex.n - before}", flush=True)

    # ---------------------------------------------------------- ③ 国家队对阵
    teams = ex.json_of("/api/teams") or []
    before = ex.n
    for k in intl_keys:
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                for nt in (0, 1):
                    ex.get(f"/api/predict?event={k}&home={h}&away={a}&neutral={nt}")
    print(f"[export] ③ 国家队单场 {len(teams)}队×{len(intl_keys)}赛事×2 → 新增 {ex.n - before}", flush=True)

    before = ex.n
    for h in teams:
        for a in teams:
            if h != a:
                ex.get(f"/api/explainer?home={h}&away={a}")
    print(f"[export] ④ 读盘卡 → 新增 {ex.n - before}", flush=True)

    if not args.skip_heavy:
        before = ex.n
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                for nt in (0, 1):
                    ex.get(f"/api/manager?home={h}&away={a}&neutral={nt}")
        print(f"[export] ⑤ 对阵分析报告 → 新增 {ex.n - before}", flush=True)
    else:
        print("[export] ⑤ 对阵分析报告 —— 按 --skip-heavy 跳过", flush=True)

    # ---------------------------------------------------------- ⑥ 俱乐部对阵
    before = ex.n
    for k in club_keys:
        ov = ex.json_of(f"/api/club/overview?event={k}") or {}
        names: list[str] = []
        for row in ov.get("ranking") or []:
            # team=football-data 拼写（Ath Madrid），disp=中文；输入框是自由文本，两套都要覆盖
            for f in ("team", "disp"):
                v = row.get(f)
                if v and v not in names:
                    names.append(v)
        for h in names:
            for a in names:
                if h == a:
                    continue
                for nt in (0, 1):
                    ex.get(f"/api/club/predict?event={k}&home={h}&away={a}&neutral={nt}&detail=1")
    print(f"[export] ⑥ 俱乐部单场 → 新增 {ex.n - before}", flush=True)

    # ---------------------------------------------------------- ⑦ 前端
    # 用 app 自己渲染，保证服务端注入的 event_keys/alias/default 与动态版完全一致
    # （boot 脚本依赖它们，且前端刻意零赛事 key 字面量）。再把 STATIC_MODE 翻成 true。
    html = ex.client.get("/").get_data(as_text=True)
    flag = "var STATIC_MODE = false;"
    if flag not in html:
        print("[export] ✗ index.html 里找不到 STATIC_MODE 开关，shim 未生效", file=sys.stderr)
        return 1
    html = html.replace(flag, "var STATIC_MODE = true;", 1)
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    # Pages 不做 Jekyll 处理（否则下划线开头的目录会被吞）
    open(os.path.join(args.out, ".nojekyll"), "w").close()
    print(f"[export] ⑦ index.html {len(html)/1000:.0f} KB（STATIC_MODE 已注入）", flush=True)

    ex.finish()

    # ---------------------------------------------------------- 汇总
    dt = time.time() - t0
    print()
    print(f"[export] 完成：{ex.n:,d} 个文件 / {ex.bytes/1e6:.1f} MB / 耗时 {dt/60:.1f} 分钟")
    if ex.skipped:
        print(f"[export] 跳过 {len(ex.skipped)} 个（前 10 条）：")
        for k, why in ex.skipped[:10]:
            print(f"    {why:16s} {k}")
    # GitHub Pages 硬限制：站点 1GB。超了必须裁导出范围，不能静默发布
    if ex.bytes > 900e6:
        print(f"[export] ✗ 体积 {ex.bytes/1e6:.0f}MB 逼近 GitHub Pages 的 1GB 上限", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
