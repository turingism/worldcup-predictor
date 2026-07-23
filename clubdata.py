#!/usr/bin/env python3
"""football-data.co.uk 俱乐部数据装载层（P2 俱乐部模型宇宙的数据底座）。

纯离线旁路：零碰国家队主线（data.py/model.pkl 不动）。下载按赛季缓存到 data/club/，
归一成引擎训练 schema（date/home_team/away_team/home_score/away_score/tournament/neutral），
并保留赔率列（B365H/D/A ≈ 赛前盘，B365CH/CD/CA = 闭盘——该源开闭盘原生齐全，CLV 层免快照）。

用法：
    import clubdata
    df = clubdata.load("E0", seasons=7)          # 英超近 7 季，引擎可直接 fit
    df = clubdata.load("E0", refresh=True)       # 强制重新下载最新赛季（进行中赛季会增量更新）
"""
from __future__ import annotations
import os
import urllib.request

import pandas as pd

LEAGUES = {
    "E0": "English Premier League",
    "SP1": "Spanish La Liga",
    "I1": "Italian Serie A",
    "D1": "German Bundesliga",
    "F1": "French Ligue 1",
    "E1": "English Championship",   # 非 S 级；仅作 E0 的升班马数据补充（bt_club_hl E1 变体）
    "SP2": "Spanish Segunda Division",   # ↓ 四个同 E1：仅作各顶级联赛赛季模拟的升班马 feeder
    "I2": "Italian Serie B",
    "D2": "German 2. Bundesliga",
    "F2": "French Ligue 2",
}
# 赛季模拟的规范 feeder 映射（单场预测不并入——bt_club_hl 准度闸门裁决，见 CLAUDE.md）
FEEDER = {"E0": "E1", "SP1": "SP2", "I1": "I2", "D1": "D2", "F1": "F2"}
URL = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
CLUB_DIR = os.path.join(os.path.dirname(__file__), "data", "club")
ODDS_COLS = ["B365H", "B365D", "B365A", "B365CH", "B365CD", "B365CA"]
_CUR_END = 2026   # 最新完结/进行中赛季的结束年下限（新赛季开始后 +1 即可）
                  # 2026-07-19 回补：25-26 整季（2025-08~2026-05）此前一直缺库——
                  # 「8 月开赛滚入」的是 26-27 赛季，勿再混淆两者。


def season_codes(n: int, end_year: int = _CUR_END) -> list[str]:
    """近 n 季的 football-data 赛季码，旧→新：end_year=2025,n=3 → ['2223','2324','2425']。"""
    return [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(end_year - n, end_year)]


# 系统代理偶发 SSL 断流（Clash 节点抖动），ESPN 层实测直连可达——football-data
# 下载同款策略：先默认（系统代理）再绕过代理直连（与 live._fetch_json 对齐）。
_NOPROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _download(url: str, dest: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last = None
    for opener in (None, _NOPROXY_OPENER):
        try:
            r = opener.open(req, timeout=timeout) if opener else \
                urllib.request.urlopen(req, timeout=timeout)
            with r, open(dest, "wb") as f:
                f.write(r.read())
            return
        except Exception as e:  # noqa
            last = e
    raise RuntimeError(f"下载失败（系统代理+直连均失败）：{last}")


def fetch(code: str, season: str, refresh: bool = False) -> str:
    """下载并缓存一季 CSV，返回本地路径。已缓存且非 refresh 直接复用。"""
    if code not in LEAGUES:
        raise KeyError(f"未知联赛码 {code}（可选：{sorted(LEAGUES)}）")
    os.makedirs(CLUB_DIR, exist_ok=True)
    path = os.path.join(CLUB_DIR, f"{code}_{season}.csv")
    if refresh or not os.path.exists(path):
        tmp = path + ".tmp"
        try:
            _download(URL.format(season=season, code=code), tmp)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            if os.path.exists(path):     # 刷新失败但有缓存：沿用缓存，别把可用数据变不可用
                print(f"[clubdata] {code}_{season} 刷新失败，沿用本地缓存")
            else:
                raise
    return path


def _read_one(path: str, code: str) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8", encoding_errors="replace")
    raw = raw.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    df = pd.DataFrame({
        # football-data 日期为 dd/mm/YY 或 dd/mm/YYYY，dayfirst 统一解析
        "date": pd.to_datetime(raw["Date"], dayfirst=True, format="mixed"),
        "home_team": raw["HomeTeam"].str.strip(),
        "away_team": raw["AwayTeam"].str.strip(),
        "home_score": raw["FTHG"].astype(int),
        "away_score": raw["FTAG"].astype(int),
        "tournament": LEAGUES[code],
        "neutral": False,            # 联赛全部主客场
    })
    for c in ODDS_COLS:              # 赔率列透传（老赛季可能缺闭盘列）；统一 float，
        df[c] = (pd.to_numeric(raw[c], errors="coerce")   # 避免全 NA 对象列触发 concat FutureWarning
                 if c in raw.columns else float("nan"))
    return df


def load(code: str = "E0", seasons: int = 7, refresh: bool = False) -> pd.DataFrame:
    """近 seasons 季合并帧（引擎 schema + 赔率列），按日期升序。refresh 只强刷最新一季。

    跨赛季空窗韧性（D1）：_CUR_END +1 后、新季 CSV 尚未发布（404）或仅表头（空）
    的窗口期，最新一季装载失败降级为告警、只用历史季——历史季失败仍硬报错
    （缓存应在位，坏了必须暴露）。"""
    codes = season_codes(seasons)
    frames = []
    for s in codes:
        try:
            frames.append(_read_one(fetch(code, s, refresh=refresh and s == codes[-1]), code))
        except Exception as e:  # noqa
            if s == codes[-1]:
                print(f"[clubdata] {code}_{s} 装载失败（{type(e).__name__}: {e}）；"
                      f"跨赛季空窗降级，仅用历史 {len(frames)} 季")
                continue
            raise
    if not frames:
        raise RuntimeError(f"{code}: 无任何赛季数据可装载")
    return (pd.concat(frames, ignore_index=True)
            .sort_values("date").reset_index(drop=True))


FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
_FIXTURES_TTL_H = 6.0   # 赛程/盘口每天都会动，缓存超龄自动重拉


def load_fixtures(code: str | None = None, refresh: bool = False) -> pd.DataFrame:
    """未来数天赛程 + B365 赛前盘（全联赛一张表，Div 列区分）。

    ⚠ 数据事实：fixtures.csv 只含**未来一轮左右**（数天），不是整季剩余赛程——
    赛季模拟的整季剩余用 clubsim.remaining_pairs 从已赛对阵推导，此表只喂
    看板「即将开赛」与市场层。休赛期可能为空/残留旧行，消费方自行按日期过滤。"""
    import time as _time
    os.makedirs(CLUB_DIR, exist_ok=True)
    path = os.path.join(CLUB_DIR, "fixtures.csv")
    stale = (not os.path.exists(path)
             or _time.time() - os.path.getmtime(path) > _FIXTURES_TTL_H * 3600)
    if refresh or stale:
        tmp = path + ".tmp"
        try:
            _download(FIXTURES_URL, tmp)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            if os.path.exists(path):     # 刷新失败但有缓存：沿用（与 fetch 同口径）
                print("[clubdata] fixtures 刷新失败，沿用本地缓存")
            else:
                raise
    raw = pd.read_csv(path, encoding="utf-8-sig", encoding_errors="replace")
    raw = raw.dropna(subset=["Div", "HomeTeam", "AwayTeam"])
    raw = raw[raw["Div"] == code] if code else raw[raw["Div"].isin(LEAGUES)]
    t = raw["Time"].fillna("00:00") if "Time" in raw.columns else "00:00"
    df = pd.DataFrame({
        "div": raw["Div"],
        "date": pd.to_datetime(raw["Date"] + " " + t, dayfirst=True, format="mixed"),
        "home_team": raw["HomeTeam"].str.strip(),
        "away_team": raw["AwayTeam"].str.strip(),
    })
    for c in ("B365H", "B365D", "B365A"):   # 赛前盘透传（闭盘列在 fixtures 阶段天然为空，不取）
        df[c] = pd.to_numeric(raw[c], errors="coerce") if c in raw.columns else float("nan")
    return df.sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    for lg in LEAGUES:
        df = load(lg, seasons=3)
        print(f"{lg:<4} {LEAGUES[lg]:<24} {len(df):>5} 场  "
              f"{df.date.min().date()} → {df.date.max().date()}  "
              f"闭盘覆盖 {df['B365CH'].notna().mean():.0%}")
