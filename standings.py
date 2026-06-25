"""本届世界杯上下文表（只读衍生层）。

提供三块「综合让球判断」需要的事实/状态数据，全部从真实已踢赛果或模型评级推导：
  1) tournament_gd_table —— 全部参赛队本届实际累计净胜球榜（仅已踢小组赛）。
  2) group_table        —— 单组实时积分榜（真实已踢，附剩余场次）。
  3) clinch_status      —— 某队是否已提前出线/锁定头名/已出局（暴力枚举剩余赛果，保守判定）。

铁律：本模块**绝不进训练、不碰 GLM、不写任何账本**。它只读 simulator 的真实赛果与
官方分组，输出展示用上下文。已出线检测对"让球结论"只作动机层的输入（预警/可选降权），
不改变 DC 引擎本身的概率。
"""
from itertools import product

import wc2026


# ───────────────────────── 全队净胜球榜 ─────────────────────────

def _played_group(sim):
    """本届正赛已踢小组赛 {(home,away): (gh,ga)}（顺序即官方赛程主客）。"""
    return dict(sim.actual_results)


def tournament_gd_table(sim):
    """全部 48 强本届实际累计净胜球榜（只统计已踢小组赛）。
    排序：净胜球 > 进球数 > 积分。未出场（0 场）的队不入榜。"""
    parts = [t for g in wc2026.GROUPS.values() for t in g]
    agg = {t: {"gf": 0, "ga": 0, "w": 0, "d": 0, "l": 0, "pld": 0} for t in parts}
    for (h, a), (gh, ga) in _played_group(sim).items():
        if h not in agg or a not in agg:
            continue
        agg[h]["gf"] += gh; agg[h]["ga"] += ga; agg[h]["pld"] += 1
        agg[a]["gf"] += ga; agg[a]["ga"] += gh; agg[a]["pld"] += 1
        if gh > ga:
            agg[h]["w"] += 1; agg[a]["l"] += 1
        elif gh < ga:
            agg[a]["w"] += 1; agg[h]["l"] += 1
        else:
            agg[h]["d"] += 1; agg[a]["d"] += 1
    rows = []
    for t, s in agg.items():
        if s["pld"] == 0:
            continue
        rows.append({"team": t, "pld": s["pld"], "gf": s["gf"], "ga": s["ga"],
                     "gd": s["gf"] - s["ga"], "pts": s["w"] * 3 + s["d"],
                     "w": s["w"], "d": s["d"], "l": s["l"]})
    rows.sort(key=lambda r: (r["gd"], r["gf"], r["pts"]), reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


# ───────────────────────── 单组实时积分榜 ─────────────────────────

def _group_of(sim, team):
    """返回 team 所在组的 (gid, 字母, 成员, 该组全部官方对阵)。找不到返回 None。"""
    for gid, members in sim.groups.items():
        if team in members:
            return gid, sim.group_letter.get(gid), list(members), list(sim.fixtures[gid])
    return None


def _actual_points(members, fixtures, played):
    """只用真实已踢赛果算积分/净胜球/进球；返回 (pts, gd, gf, remaining_fixtures)。"""
    pts = {t: 0 for t in members}
    gd = {t: 0 for t in members}
    gf = {t: 0 for t in members}
    remaining = []
    for (h, a) in fixtures:
        if (h, a) in played:
            gh, ga = played[(h, a)]
        elif (a, h) in played:          # 顺序无关兜底
            ga, gh = played[(a, h)]
        else:
            remaining.append((h, a))
            continue
        gf[h] += gh; gf[a] += ga
        gd[h] += gh - ga; gd[a] += ga - gh
        if gh > ga: pts[h] += 3
        elif gh < ga: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
    return pts, gd, gf, remaining


def group_table(sim, team):
    """team 所在组的**真实**积分榜（仅已踢场次）+ 每队剩余场数。"""
    g = _group_of(sim, team)
    if not g:
        return None
    gid, letter, members, fixtures = g
    played = _played_group(sim)
    pts, gd, gf, remaining = _actual_points(members, fixtures, played)
    rem_cnt = {t: 0 for t in members}
    for (h, a) in remaining:
        rem_cnt[h] += 1; rem_cnt[a] += 1
    order = sorted(members, key=lambda t: (pts[t], gd[t], gf[t], sim.strength.get(t, -9)),
                   reverse=True)
    rows = [{"team": t, "pts": pts[t], "gd": gd[t], "gf": gf[t],
             "remaining": rem_cnt[t], "rank": i + 1} for i, t in enumerate(order)]
    return {"group": letter, "rows": rows, "remaining": len(remaining)}


# ───────────────────────── 已出线 / 出局检测 ─────────────────────────

def clinch_status(sim, team):
    """暴力枚举该组剩余比赛的全部赛果组合，**保守**判定 team 的出线状态。

    返回 {state, label, top1, qualified, remaining, played} ——
      state ∈ {clinched_first, clinched_qualify, alive, eliminated}
    保守口径：积分相等的平局一律按【对 team 最不利】拆（判出线时假设并列被挤到身后、
    判出局时假设并列把 team 压下），因此**绝不会误报"已出线"**——只有真正铁定才标。
    剩余 ≤6 场、3^6=729 组合，毫秒级。"""
    g = _group_of(sim, team)
    if not g:
        return None
    gid, letter, members, fixtures = g
    played = _played_group(sim)
    base_pts, base_gd, base_gf, remaining = _actual_points(members, fixtures, played)
    played_n = len(fixtures) - len(remaining)

    if not remaining:
        # 全组踢完：直接按真实最终排名定（GD/GF 打破平局）
        order = sorted(members, key=lambda t: (base_pts[t], base_gd[t], base_gf[t]),
                       reverse=True)
        idx = order.index(team)
        state = ("clinched_first" if idx == 0 else
                 "clinched_qualify" if idx <= 1 else "eliminated")
        return _clinch_out(state, letter, remaining, played_n, top2=order[:2])

    always_top1 = always_top2 = True
    ever_top2 = False
    for combo in product((0, 1, 2), repeat=len(remaining)):  # 0=主胜 1=平 2=客胜
        pts = dict(base_pts)
        for (h, a), o in zip(remaining, combo):
            if o == 0: pts[h] += 3
            elif o == 2: pts[a] += 3
            else: pts[h] += 1; pts[a] += 1
        my = pts[team]
        # 严格强于 team 的队数（积分更高）；并列者按保守拆分另算
        strictly_above = sum(1 for t in members if t != team and pts[t] > my)
        tied = sum(1 for t in members if t != team and pts[t] == my)
        # 判"是否仍可能进前2"用乐观（并列都排在 team 后）→ rank_best = strictly_above
        # 判"是否铁定进前2"用悲观（并列都排在 team 前）→ rank_worst = strictly_above + tied
        rank_best = strictly_above
        rank_worst = strictly_above + tied
        if rank_worst > 0: always_top1 = False
        if rank_worst > 1: always_top2 = False
        if rank_best <= 1: ever_top2 = True

    if always_top2:
        state = "clinched_first" if always_top1 else "clinched_qualify"
    elif not ever_top2:
        state = "eliminated"
    else:
        state = "alive"
    return _clinch_out(state, letter, remaining, played_n)


_LABELS = {
    "clinched_first": "已锁定小组头名",
    "clinched_qualify": "已提前出线",
    "alive": "出线未定",
    "eliminated": "已无出线可能",
}


def _clinch_out(state, letter, remaining, played_n, top2=None):
    return {
        "state": state,
        "label": _LABELS[state],
        "top1": state == "clinched_first",
        "qualified": state in ("clinched_first", "clinched_qualify"),
        "group": letter,
        "remaining": len(remaining),
        "played": played_n,
        "top2": top2,
    }


if __name__ == "__main__":  # CLI 自测
    import app
    sim = app._sim()
    tab = tournament_gd_table(sim)
    print(f"全队净胜球榜（{len(tab)} 队有出场）前 8：")
    for r in tab[:8]:
        print(f"  #{r['rank']:>2} {r['team']:<22} 踢{r['pld']} 净{r['gd']:+d} 进{r['gf']} {r['pts']}分")
    for tm in ("Morocco", "Brazil", "Argentina"):
        gt = group_table(sim, tm)
        cs = clinch_status(sim, tm)
        print(f"\n{tm}: {cs['label']}（{cs['group']}组 已踢{cs['played']}/剩{cs['remaining']}）")
        for row in gt["rows"]:
            print(f"  {row['rank']}. {row['team']:<22} {row['pts']}分 净{row['gd']:+d} 剩{row['remaining']}")
