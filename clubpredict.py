#!/usr/bin/env python3
"""俱乐部单场比分预测 CLI（五大联赛，P2 俱乐部宇宙的 predict.py 对应物）。

纯离线旁路：零碰国家队主线（model.pkl / predict.py 不动）。每联赛独立模型
（half_life=365，2026-07-08 五联赛×3 cutoff 正式裁决），缓存在 data/club/model_<码>.pkl，
数据更新（CSV 变新）自动重训。联赛从两队名自动识别，支持中文队名（teams_zh.CLUB）。

用法示例
--------
  # 单场预测（默认第一支为主队，联赛自动识别；中文英文队名均可）
  python3 clubpredict.py "Arsenal" "Man City"
  python3 clubpredict.py "阿森纳" "曼城"
  python3 clubpredict.py "皇家马德里" "巴塞罗那"

  # 中立场（杯赛决赛口径）
  python3 clubpredict.py "利物浦" "拜仁慕尼黑" --neutral   # ⚠ 跨联赛会被拒——见下

  # 联赛实力榜
  python3 clubpredict.py --ranking E0

  # 强制刷新进行中赛季数据后再预测
  python3 clubpredict.py "Arsenal" "Man City" --refresh

⚠ 跨联赛对阵（欧冠等）本 CLI 暂不支持：欧战锚点校准回测已完成且显著有效
  （docs/backtest.md 第七节），欧冠/跨联赛预测待 E4 接线。本 CLI 保持联赛内
  口径不变，跨联赛对阵仍拒绝。
"""
from __future__ import annotations
import argparse
import difflib
import glob
import os
import pickle
import sys
import tempfile

import clubdata
import teams_zh
from model import SCHEMA_VERSION, DixonColesModel

# S 级联赛（E1 英冠仅作 clubsim feeder，一般单场模型并入已否决——见 CLAUDE.md 2026-07-08）
S5 = ("E0", "SP1", "I1", "D1", "F1")
HL_CLUB = 365.0        # 俱乐部半衰期正式裁决值；国家队的 730 不可照搬
SEASONS = 7

# 升班马路径：E1 降权并入，**只对涉升班马新面孔的 E0 场次启用**（2026-08-03 bt_promoted.py
# 专项裁决，正是 07-08 否决时预留的「后续可研究 E1 降权(w<1)并入」）。5 个赛季初 cutoff ×
# 537 场涉升班马留出：w=0.25 RPS 0.1919，且 w 单调劣化至 1.0=0.1949（与全量并入否决同向）；
# 全部 cutoff 显著优于均匀基线 0.2409；对 B365 闭盘差 +0.018=本项目模型对市场的常态差距。
# 一般场次仍走纯 E0 模型，零改动零风险。E1 行降权通道=comp_weights：
# data.comp_tier("English Championship")=="major"（"championship" 关键词撞车，本意欧锦赛）
# 而 EPL→"other"，恰好可分——脆弱巧合，test_core 有护栏测试锁死；此路仅适用英格兰。
PROMOTED_E1_W = 0.25


def _cache_path(code: str) -> str:
    return os.path.join(clubdata.CLUB_DIR, f"model_{code}.pkl")


def _data_mtime(code: str) -> float:
    """该联赛已缓存 CSV 的最新修改时间；无缓存返回 0。"""
    paths = glob.glob(os.path.join(clubdata.CLUB_DIR, f"{code}_????.csv"))
    return max((os.path.getmtime(p) for p in paths), default=0.0)


def get_club_model(code: str, refresh: bool = False, verbose: bool = True) -> DixonColesModel:
    """取该联赛模型：缓存命中（schema/hl 匹配且不老于数据）直接用，否则重训并落盘。"""
    df = clubdata.load(code, seasons=SEASONS, refresh=refresh)
    path = _cache_path(code)
    if not refresh and os.path.exists(path):
        try:
            with open(path, "rb") as f:
                m = pickle.load(f)
            if getattr(m, "schema_version", 0) == SCHEMA_VERSION \
                    and abs(getattr(m, "half_life_days", -1) - HL_CLUB) < 1e-6 \
                    and os.path.getmtime(path) >= _data_mtime(code):
                if verbose:
                    print(f"[cache] {clubdata.LEAGUES[code]} 模型缓存命中（{len(m.teams)} 队）")
                return m
        except Exception as e:  # noqa  损坏的缓存 -> 重建
            if verbose:
                print(f"[cache] 缓存损坏（{e}），重建")
    if verbose:
        print(f"[fit] 训练 {clubdata.LEAGUES[code]} 模型（近 {SEASONS} 季, hl={HL_CLUB:.0f}）…")
    m = DixonColesModel(half_life_days=HL_CLUB).fit(df, verbose=False)
    _atomic_dump(m, path)
    return m


def _atomic_dump(obj, path: str) -> None:
    """pkl 原子写：同目录 mkstemp + os.replace（对齐国家队 save_model_cache 模式）。
    直接 open(path,'wb') 在跨进程并发（CLI 与 app 同时重训）下会产生撕裂文件。"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                               suffix=".pkl.tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(obj, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def promoted_newcomers() -> set[str]:
    """当季 E0 赛程（ESPN 缓存）里、近 7 季 E0 帧没有、但 E1 帧有的队=升班马新面孔。

    只读缓存不联网（clubfixtures.load_cached）；无赛程缓存返回空集=路径自动关闭。
    有近 7 季 E0 历史的升班马（如降而复升）不算新面孔——标准模型本就有其参数，
    且专项回测显示合训对这类队同样成立，但按最小改动原则只对「池外队」开新路径。"""
    try:
        import clubfixtures
        fx = clubfixtures.load_cached("E0")
    except Exception:
        return set()
    if fx is None or not len(fx):
        return set()
    fixture_teams = set(fx.home_team) | set(fx.away_team)
    e0 = clubdata.load("E0", seasons=SEASONS)
    e1 = clubdata.load("E1", seasons=SEASONS)
    return (fixture_teams - set(e0.home_team) - set(e0.away_team)) \
        & (set(e1.home_team) | set(e1.away_team))


def resolve_promoted(name: str, promoted: set[str]):
    """升班马新面孔解析（E0 常规池外、E1 拼写）。命中返回 football-data 队名，否则 None。"""
    if not promoted:
        return None
    cand = teams_zh.to_en(name)
    if cand in promoted:
        return cand
    if name in promoted:
        return name
    low = {t.lower(): t for t in promoted}
    hit = low.get(name.strip().lower())
    if hit:
        return hit
    subs = [t for t in promoted if name.lower() in t.lower()]
    return subs[0] if len(subs) == 1 else None


def get_promoted_model(refresh: bool = False, verbose: bool = True) -> DixonColesModel:
    """E0+E1（英冠降权 PROMOTED_E1_W）合训模型，仅供涉升班马场次。

    缓存纪律同 get_club_model：schema/hl/权重精确匹配 + 不老于 E0、E1 任一 CSV。"""
    import pandas as pd

    e0 = clubdata.load("E0", seasons=SEASONS, refresh=refresh)
    e1 = clubdata.load("E1", seasons=SEASONS, refresh=refresh)
    path = _cache_path("E0promo")
    newest = max(_data_mtime("E0"), _data_mtime("E1"))
    if not refresh and os.path.exists(path):
        try:
            with open(path, "rb") as f:
                m = pickle.load(f)
            if getattr(m, "schema_version", 0) == SCHEMA_VERSION \
                    and abs(getattr(m, "half_life_days", -1) - HL_CLUB) < 1e-6 \
                    and (getattr(m, "comp_weights", None) or {}).get("major") == PROMOTED_E1_W \
                    and os.path.getmtime(path) >= newest:
                if verbose:
                    print(f"[cache] 升班马合训模型缓存命中（{len(m.teams)} 队）")
                return m
        except Exception as e:  # noqa
            if verbose:
                print(f"[cache] 缓存损坏（{e}），重建")
    if verbose:
        print(f"[fit] 训练 E0+E1 升班马合训模型（英冠权重 {PROMOTED_E1_W}, hl={HL_CLUB:.0f}）…")
    m = DixonColesModel(half_life_days=HL_CLUB,
                        comp_weights={"major": PROMOTED_E1_W, "other": 1.0}).fit(
        pd.concat([e0, e1], ignore_index=True), verbose=False)
    _atomic_dump(m, path)
    return m


def _league_teams(codes=S5) -> dict[str, set[str]]:
    """各联赛近 7 季出现过的全部队名（与训练窗口一致）。"""
    out = {}
    for c in codes:
        df = clubdata.load(c, seasons=SEASONS)
        out[c] = set(df.home_team) | set(df.away_team)
    return out


def resolve(name: str, pool: dict[str, set[str]]):
    """输入（中文/显示串/英文，大小写/子串宽容）→ (football-data 队名, 所在联赛码)。

    找不到返回 (None, 近似建议列表)。
    """
    allnames = {t for s in pool.values() for t in s}
    cand = teams_zh.to_en(name)
    if cand not in allnames:
        cand = None
    if cand is None and name in allnames:
        cand = name
    if cand is None:                                   # 大小写宽容
        low = {t.lower(): t for t in allnames}
        cand = low.get(name.strip().lower())
    if cand is None:                                   # 唯一子串（Forest → Nott'm Forest）
        subs = [t for t in allnames if name.lower() in t.lower()]
        if len(subs) == 1:
            cand = subs[0]
    if cand is None:
        zh_labels = {teams_zh.disp(t): t for t in allnames}
        sugg = difflib.get_close_matches(name, list(allnames) + list(zh_labels), n=3, cutoff=0.4)
        return None, [zh_labels.get(s, s) for s in sugg]
    code = next(c for c, s in pool.items() if cand in s)
    return (cand, code), None


def net_ranking(m: DixonColesModel, top: int = 20) -> list[tuple[str, float]]:
    """俱乐部净实力榜：attack - defence 直算（与 power_ranking 同式）。

    不用 m.power_ranking——其身价过滤是国家队口径（剔非 FIFA 噪声队），俱乐部
    无身价记录会整池滤空（2026-07-19 实测暗坑）。CLI 与 /api/club/overview 同源取此。
    """
    rows = sorted(((t, float(m.attack[t] - m.defence[t])) for t in m.teams),
                  key=lambda x: -x[1])
    return rows[:top]


def bar(p: float, width: int = 24) -> str:
    n = int(round(p * width))
    return "█" * n + "·" * (width - n)


def print_club_prediction(m: DixonColesModel, code: str, home: str, away: str, neutral: bool):
    r = m.predict(home, away, neutral=neutral)
    M = r["matrix"]
    import numpy as np
    tot = np.add.outer(np.arange(M.shape[0]), np.arange(M.shape[1]))
    p_over25 = float(M[tot >= 3].sum())
    p_btts = float(M[1:, 1:].sum())
    dh, da = teams_zh.disp(r["home"]), teams_zh.disp(r["away"])
    venue = "中立场" if neutral else f"{dh} 主场"
    print()
    print(f"  ⚽ {dh}  vs  {da}   （{clubdata.LEAGUES[code]} · {venue}）")
    print("  " + "─" * 46)
    print(f"  期望进球 (xG):   {dh} {r['xg_home']:.2f}  -  {r['xg_away']:.2f} {da}")
    print()
    print("  赛果概率")
    print(f"    {dh:<16} 胜  {r['p_home']*100:5.1f}%  {bar(r['p_home'])}")
    print(f"    {'平局':<15} {'':<1} {r['p_draw']*100:5.1f}%  {bar(r['p_draw'])}")
    print(f"    {da:<16} 胜  {r['p_away']*100:5.1f}%  {bar(r['p_away'])}")
    print()
    print(f"  大小球 2.5:  大 {p_over25*100:.1f}% / 小 {(1-p_over25)*100:.1f}%    "
          f"双方进球 (BTTS): {p_btts*100:.1f}%")
    print()
    print("  最可能比分 (Top 7)")
    for (i, j), p in r["top_scores"]:
        print(f"    {i}-{j}   {p*100:5.1f}%   {bar(p)}")
    ms = r["top_scores"][0]
    print()
    print(f"  ➜ 最可能比分: {dh} {ms[0][0]}-{ms[0][1]} {da}  ({ms[1]*100:.1f}%)")
    print()


def print_ranking(code: str, top: int = 20):
    m = get_club_model(code)
    print(f"\n  🏆 {clubdata.LEAGUES[code]} 模型净实力榜 Top {top}（近 {SEASONS} 季加权，联赛内相对值，跨联赛不可比）")
    print("  " + "─" * 44)
    for i, (t, s) in enumerate(net_ranking(m, top), 1):
        print(f"   {i:>2}. {teams_zh.disp(t):<26} {s:+.3f}")
    print()


def main():
    ap = argparse.ArgumentParser(
        description="俱乐部单场比分预测（五大联赛 · 双泊松 + Dixon-Coles）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("home", nargs="?", help="主队（中文/英文均可）")
    ap.add_argument("away", nargs="?", help="客队")
    ap.add_argument("--neutral", action="store_true", help="中立场（默认第一支为主队）")
    ap.add_argument("--league", choices=S5, help="指定联赛码（默认从队名自动识别）")
    ap.add_argument("--refresh", action="store_true", help="强制刷新进行中赛季数据并重训")
    ap.add_argument("--ranking", metavar="CODE", choices=S5, help="输出该联赛实力榜")
    args = ap.parse_args()

    if args.ranking:
        print_ranking(args.ranking)
        return
    if not (args.home and args.away):
        ap.print_help()
        return

    pool = _league_teams((args.league,) if args.league else S5)
    promoted = promoted_newcomers()
    sides, use_promoted = [], False
    for raw in (args.home, args.away):
        hit, sugg = resolve(raw, pool)
        if hit is None:
            promo = resolve_promoted(raw, promoted)
            if promo is not None:
                hit, use_promoted = (promo, "E0"), True
        if hit is None:
            print(f"\n  ✗ 未识别球队「{raw}」" + (f"，你是想找：{' / '.join(sugg)}？" if sugg else ""))
            print(f"    （范围=五大联赛近 {SEASONS} 季 + 当季升班马；欧冠等跨联赛对阵暂不支持）\n")
            sys.exit(1)
        sides.append(hit)
    (h, ch), (a, ca) = sides
    if ch != ca:
        print(f"\n  ✗ 跨联赛对阵：{teams_zh.disp(h)}（{clubdata.LEAGUES[ch]}） vs "
              f"{teams_zh.disp(a)}（{clubdata.LEAGUES[ca]}）")
        print("    欧战锚点校准回测已完成（docs/backtest.md 第七节），欧冠/跨联赛预测待 E4 接线；"
              "本 CLI 保持联赛内口径，跨联赛对阵仍拒绝。\n")
        sys.exit(1)

    if use_promoted and ch == "E0":
        m = get_promoted_model(refresh=args.refresh)
        df = clubdata.load("E0", seasons=SEASONS)
        print(f"  [data] {clubdata.LEAGUES['E0']} 近 {SEASONS} 季 {len(df)} 场 + 英冠样本"
              f"（降权 {PROMOTED_E1_W}），截至 {df['date'].max().date()}")
        print(f"  [口径] 升班马路径：该队近 7 季无英超样本，按英冠战绩降权评级"
              f"（2026-08-03 专项回测采纳，涉升班马场次留出 RPS 0.192 vs 均匀 0.241）")
        print_club_prediction(m, "E0", h, a, args.neutral)
        return

    m = get_club_model(ch, refresh=args.refresh)
    df = clubdata.load(ch, seasons=SEASONS)
    print(f"  [data] {clubdata.LEAGUES[ch]} 近 {SEASONS} 季 {len(df)} 场，截至 {df['date'].max().date()}")
    print_club_prediction(m, ch, h, a, args.neutral)


if __name__ == "__main__":
    main()
