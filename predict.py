#!/usr/bin/env python3
"""Score-prediction CLI (single match / power ranking / batch fixtures).

世界杯比分预测 CLI

用法示例
--------
  # 单场预测（默认中立场，符合世界杯）
  python3 predict.py "Argentina" "France"

  # 指定第一支为真正主队（带主场优势，如东道主）
  python3 predict.py "United States" "Mexico" --home

  # 看实力榜（健全性检查）
  python3 predict.py --ranking

  # 预测真实的 2026 世界杯赛程
  python3 predict.py --fixtures

  # 缓存模型，避免每次重训（首次生成，后续秒开）
  python3 predict.py "Brazil" "Spain" --cache
"""
from __future__ import annotations
import argparse
import os
import pickle
import sys

import numpy as np

import data as datamod
from model import SCHEMA_VERSION, DixonColesModel

CACHE_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")


def get_model(use_cache: bool, half_life: float, verbose=True) -> DixonColesModel:
    if use_cache and os.path.exists(CACHE_PATH):
        m = None
        try:
            with open(CACHE_PATH, "rb") as f:
                m = pickle.load(f)
        except Exception as e:  # noqa  损坏的缓存 -> 重建
            if verbose:
                print(f"[cache] 缓存损坏（{e}），重建")
        # 仅当 schema 版本与 half_life 都匹配才用缓存，否则重建（杜绝"忘删 pkl"事故）
        if m is not None and getattr(m, "schema_version", 0) == SCHEMA_VERSION \
                and abs(getattr(m, "half_life_days", -1) - half_life) < 1e-6:
            if verbose:
                print(f"[cache] 已加载缓存模型（{len(m.teams)} 支球队）")
            return m
        if verbose and m is not None:
            print("[cache] 缓存 schema/half_life 不匹配，重建模型 …")
    df = datamod.load_raw()
    m = DixonColesModel(half_life_days=half_life).fit(df, verbose=verbose)
    if use_cache:
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(m, f)
        if verbose:
            print(f"[cache] 模型已缓存到 {CACHE_PATH}")
    return m


def bar(p: float, width: int = 24) -> str:
    n = int(round(p * width))
    return "█" * n + "·" * (width - n)


def print_prediction(m: DixonColesModel, home: str, away: str, neutral: bool):
    r = m.predict(home, away, neutral)
    venue = "中立场" if neutral else f"{r['home']} 主场"
    print()
    print(f"  ⚽ {r['home']}  vs  {r['away']}   ({venue})")
    print("  " + "─" * 46)
    print(f"  期望进球 (xG):   {r['home']} {r['xg_home']:.2f}  -  {r['xg_away']:.2f} {r['away']}")
    print()
    print("  赛果概率")
    print(f"    {r['home'][:14]:<14} 胜  {r['p_home']*100:5.1f}%  {bar(r['p_home'])}")
    print(f"    {'平局':<13} {'':<1} {r['p_draw']*100:5.1f}%  {bar(r['p_draw'])}")
    print(f"    {r['away'][:14]:<14} 胜  {r['p_away']*100:5.1f}%  {bar(r['p_away'])}")
    print()
    print("  最可能比分 (Top 7)")
    for (i, j), p in r["top_scores"]:
        print(f"    {i}-{j}   {p*100:5.1f}%   {bar(p)}")
    ms = r["top_scores"][0]
    print()
    print(f"  ➜ 最可能比分: {r['home']} {ms[0][0]}-{ms[0][1]} {r['away']}  ({ms[1]*100:.1f}%)")
    print()


def print_ranking(m: DixonColesModel, top=20):
    print(f"\n  🏆 模型净实力榜 Top {top}（进攻强 - 失球少，相对值）")
    print("  " + "─" * 40)
    for i, (t, s) in enumerate(m.power_ranking(top), 1):
        print(f"   {i:>2}. {t:<24} {s:+.3f}")
    print()


def print_fixtures(m: DixonColesModel):
    df = datamod.load_raw()
    fx = datamod.upcoming(df, tournament="FIFA World Cup")
    if fx.empty:
        print("数据中暂无未开赛的世界杯赛程。")
        return
    print(f"\n  📅 2026 世界杯赛程预测（共 {len(fx)} 场，中立场）")
    print("  " + "─" * 60)
    skipped = 0
    for _, row in fx.iterrows():
        h, a = row["home_team"], row["away_team"]
        try:
            r = m.predict(h, a, neutral=True)
        except KeyError:
            skipped += 1
            continue
        (si, sj), sp = r["top_scores"][0]
        date = str(row["date"].date())
        print(f"   {date}  {h:>16} {si}-{sj} {a:<16}  "
              f"(W{r['p_home']*100:3.0f}/D{r['p_draw']*100:3.0f}/L{r['p_away']*100:3.0f})")
    if skipped:
        print(f"\n   （{skipped} 场因球队样本不足跳过）")
    print()


def main():
    ap = argparse.ArgumentParser(
        description="世界杯比分预测（双泊松 + Dixon-Coles）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("home", nargs="?", help="主队 / 第一支球队")
    ap.add_argument("away", nargs="?", help="客队 / 第二支球队")
    ap.add_argument("--home", dest="real_home", action="store_true",
                    help="第一支球队享有主场优势（默认中立场）")
    ap.add_argument("--ranking", action="store_true", help="打印模型实力榜")
    ap.add_argument("--fixtures", action="store_true", help="预测 2026 世界杯全部赛程")
    ap.add_argument("--cache", action="store_true", help="使用/生成模型缓存")
    ap.add_argument("--half-life", type=float, default=730.0,
                    help="时间衰减半衰期（天），默认 730（修复回测时间泄漏后的最优≈2年）")
    args = ap.parse_args()

    m = get_model(args.cache, args.half_life)

    if args.ranking:
        print_ranking(m)
        return
    if args.fixtures:
        print_fixtures(m)
        return
    if not args.home or not args.away:
        ap.error("请提供两支球队，例如：python3 predict.py \"Argentina\" \"France\"\n"
                 "或使用 --ranking / --fixtures")
    try:
        print_prediction(m, args.home, args.away, neutral=not args.real_home)
    except KeyError as e:
        print(f"\n  ✗ {e}\n  提示：用英文队名（数据源为英文），可先跑 --ranking 看可用队名。")
        sys.exit(1)


if __name__ == "__main__":
    main()
