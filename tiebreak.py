"""FIFA 2026 World Cup group-stage tiebreak — single shared implementation.

2026 世界杯小组赛同分规则的**唯一共用实现**（向量化蒙特卡洛 / simulate_once /
确定性投影三条路径都必须调这里，防止三套逻辑漂移）。

官方规则（2026 版有重大变化：相互战绩优先于总净胜球）——
小组排名：
  1) 积分
同分球队之间（criteria 递归重算，仅限仍并列的球队）：
  2) 同分球队相互比赛积分
  3) 同分球队相互比赛净胜球
  4) 同分球队相互比赛进球
仍无法区分时：
  5) 全部小组赛净胜球
  6) 全部小组赛进球
  7) 球队纪律分（黄牌-1 / 两黄变红-3 / 直红-4 / 一黄+直红-5，高者优先）
  8) 最新一期 FIFA/Coca-Cola 男足排名（2026-06-11 版；官方明确不抽签）

八个最佳第三名：积分 → 净胜球 → 进球 → 纪律分 → FIFA 排名。

数据降级策略（可审计，绝不静默随机）：
  - 纪律分：本项目不采集牌数据 → 该级标准跳过，audit 记 "discipline_unavailable"。
  - FIFA 排名：data/fifa_rankings_2026_06.json（官方 6-11 版，48 队全覆盖）；
    任一队缺排名时该级跳过，audit 记 "fifa_rank_missing"。
  - 全部可用标准穷尽仍并列：
      * 确定性路径（投影/排序）→ 按队名字典序（确定、可复现），audit 记 "unresolved_deterministic"；
      * 蒙特卡洛抽样路径 → 调用方传 rng 随机打散，audit 记 "unresolved_random"。
    只有在官方标准全部无法判定后才允许走到这里。
"""
from __future__ import annotations
import json
import os

_RANKINGS_PATH = os.path.join(os.path.dirname(__file__), "data",
                              "fifa_rankings_2026_06.json")
_FIFA_RANKS: dict[str, int] | None = None


def fifa_rankings() -> dict[str, int]:
    """官方 2026-06-11 版 FIFA 排名（队名=数据集拼写）。文件缺失返回空 dict（降级）。"""
    global _FIFA_RANKS
    if _FIFA_RANKS is None:
        try:
            with open(_RANKINGS_PATH, encoding="utf-8") as f:
                _FIFA_RANKS = dict(json.load(f)["rankings"])
        except (FileNotFoundError, ValueError, KeyError, OSError):
            _FIFA_RANKS = {}
    return _FIFA_RANKS


def _mini_table(subset, results):
    """subset 内部相互比赛的小表 {team: (pts, gd, gf)}；只统计双方都在 subset 的场次。"""
    sub = set(subset)
    pts = {t: 0 for t in subset}
    gd = {t: 0 for t in subset}
    gf = {t: 0 for t in subset}
    for (h, a), (gh, ga) in results.items():
        if h not in sub or a not in sub:
            continue
        gf[h] += gh; gf[a] += ga
        gd[h] += gh - ga; gd[a] += ga - gh
        if gh > ga:
            pts[h] += 3
        elif gh < ga:
            pts[a] += 3
        else:
            pts[h] += 1; pts[a] += 1
    return {t: (pts[t], gd[t], gf[t]) for t in subset}


def _partition(teams, keyfn):
    """按 keyfn 降序排序并划分等价类。返回 [[同 key 的队…], …]（好→差）。"""
    order = sorted(teams, key=keyfn, reverse=True)
    classes, cur = [], [order[0]]
    for t in order[1:]:
        if keyfn(t) == keyfn(cur[0]):
            cur.append(t)
        else:
            classes.append(cur); cur = [t]
    classes.append(cur)
    return classes


def _final_criteria(subset, overall, discipline, ranks, audit, rng):
    """标准 5-8：总净胜 → 总进球 → 纪律分 → FIFA 排名 → （穷尽后）确定性/随机兜底。"""
    def keyfn(t):
        return (overall[t][1], overall[t][2])          # (总净胜, 总进球)
    out = []
    for cls in _partition(subset, keyfn):
        if len(cls) == 1:
            out += cls
            continue
        # 纪律分（高者优）——无数据时跳过并留痕
        if discipline is not None and all(t in discipline for t in cls):
            sub = []
            for c2 in _partition(cls, lambda t: discipline[t]):
                sub.append(c2)
        else:
            if discipline is None or any(t not in discipline for t in cls):
                audit.append({"stage": "discipline_unavailable", "teams": sorted(cls)})
            sub = [cls]
        for c2 in sub:
            if len(c2) == 1:
                out += c2
                continue
            # FIFA 排名（数值小者优）——任一队缺排名则该级跳过并留痕
            if all(t in ranks for t in c2):
                for c3 in _partition(c2, lambda t: -ranks[t]):
                    if len(c3) == 1:
                        out += c3
                    else:           # 同名次不可能，防御分支
                        out += _exhausted(c3, audit, rng)
            else:
                audit.append({"stage": "fifa_rank_missing",
                              "teams": sorted(set(c2) - set(ranks))})
                out += _exhausted(c2, audit, rng)
    return out


def _exhausted(cls, audit, rng):
    """全部可用官方标准穷尽仍并列：确定性字典序（rng=None）或显式随机（MC 抽样）。"""
    if rng is None:
        audit.append({"stage": "unresolved_deterministic", "teams": sorted(cls)})
        return sorted(cls)
    audit.append({"stage": "unresolved_random", "teams": sorted(cls)})
    cls = list(cls)
    rng.shuffle(cls)
    return cls


def _resolve_tied(subset, results, overall, discipline, ranks, audit, rng):
    """对积分并列的 subset 应用标准 2-8。相互战绩可分出部分名次时，
    对仍并列的子集**递归重算**相互战绩（官方规则明确要求）。"""
    if len(subset) == 1:
        return list(subset)
    mini = _mini_table(subset, results)
    classes = _partition(subset, lambda t: mini[t])
    if len(classes) > 1:                     # 相互战绩有区分度 → 子集递归重算
        out = []
        for cls in classes:
            out += _resolve_tied(cls, results, overall, discipline, ranks, audit, rng)
        return out
    # 相互战绩完全无区分度 → 进入总成绩及后续标准
    return _final_criteria(subset, overall, discipline, ranks, audit, rng)


def rank_group(members, overall, results, discipline=None, ranks=None, rng=None):
    """
    小组排名（官方 2026 规则完整实现）。
      members:  参赛队列表
      overall:  {team: (pts, gd, gf)} 全部小组赛总成绩
      results:  {(home, away): (gh, ga)} 组内每场比分（方向按实际主客/赛程即可）
      discipline: {team: 纪律分(高优)} 或 None（降级跳过）
      ranks:    {team: FIFA 排名位次} 或 None（默认读官方 2026-06-11 档）
      rng:      numpy Generator；None=确定性路径（穷尽后字典序），MC 抽样传 rng
    返回 (ordered, audit)：ordered=名次列表（第 1→第 4），audit=降级/兜底留痕列表
    （空 audit = 全程官方标准判定）。
    """
    if ranks is None:
        ranks = fifa_rankings()
    audit: list[dict] = []
    out = []
    for cls in _partition(list(members), lambda t: overall[t][0]):   # 先按积分
        out += _resolve_tied(cls, results, overall, discipline, ranks, audit, rng)
    return out, audit


def rank_thirds(entries, discipline=None, ranks=None, rng=None):
    """八个最佳第三名排序：积分 → 净胜 → 进球 → 纪律分 → FIFA 排名（→ 兜底留痕）。
      entries: [(标识, team, pts, gd, gf), …]（标识通常=组字母）
    返回 (ordered_entries, audit)。"""
    if ranks is None:
        ranks = fifa_rankings()
    audit: list[dict] = []
    ordered = []
    bykey = _partition(list(range(len(entries))),
                       lambda i: (entries[i][2], entries[i][3], entries[i][4]))
    for cls in bykey:
        if len(cls) == 1:
            ordered += cls
            continue
        teams = [entries[i][1] for i in cls]
        if discipline is not None and all(t in discipline for t in teams):
            sub = _partition(cls, lambda i: discipline[entries[i][1]])
        else:
            audit.append({"stage": "discipline_unavailable", "teams": sorted(teams)})
            sub = [cls]
        for c2 in sub:
            if len(c2) == 1:
                ordered += c2
                continue
            t2 = [entries[i][1] for i in c2]
            if all(t in ranks for t in t2):
                for c3 in _partition(c2, lambda i: -ranks[entries[i][1]]):
                    ordered += c3 if len(c3) == 1 else _exhausted_idx(c3, entries, audit, rng)
            else:
                audit.append({"stage": "fifa_rank_missing",
                              "teams": sorted(set(t2) - set(ranks))})
                ordered += _exhausted_idx(c2, entries, audit, rng)
    return [entries[i] for i in ordered], audit


def _exhausted_idx(cls, entries, audit, rng):
    teams = sorted(entries[i][1] for i in cls)
    if rng is None:
        audit.append({"stage": "unresolved_deterministic", "teams": teams})
        return sorted(cls, key=lambda i: entries[i][1])
    audit.append({"stage": "unresolved_random", "teams": teams})
    cls = list(cls)
    rng.shuffle(cls)
    return cls
