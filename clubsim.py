#!/usr/bin/env python3
"""联赛赛季模拟器（P2 俱乐部宇宙：L1「联赛形态」夺冠概率/积分榜赛道的后端）。

纯离线旁路，零碰国家队主线。与 simulate.TournamentSimulator 的小组赛口径同思路：
  - as_of 之前的已赛场次 = 事实（积分直接入账）；
  - as_of 之后的剩余赛程 = 按 DC 比分分布逐场抽样（每场 N 次向量化）；
  - N 次模拟统计每队 冠军 / 前四 / 降级(末三) 概率与期望积分。
排名规则可插拔（tiebreak 参数，simulate_retro 按联赛自动选）：
  - "gd"（英超/德甲/法甲口径）：积分 > 净胜球 > 进球，向量化排序；
  - "h2h"（西甲/意甲口径）：积分同分组内 先比相互战绩小循环（积分→净胜），再回落总净胜/总进球。

剩余赛程来源：
  - 回溯模式（本文件 main / 回测）：赛季数据帧里 as_of 之后的场次即完整剩余赛程。
  - 实况模式（P2 接线）：football-data.co.uk 另有 fixtures.csv 提供未来赛程，届时接入；
    本模块只吃 (facts_df, remaining_fixtures) 两个入参，来源无关。

用法：
    python3 clubsim.py                 # 24-25 英超两个时点回溯验证（对照真实冠军利物浦）
"""
from __future__ import annotations
import warnings

import numpy as np
import pandas as pd

import clubdata
from model import DixonColesModel

warnings.filterwarnings("ignore")

SIDE = 11   # 与 model.score_matrix 一致（0-10 球）

# 同分规则按联赛：西甲/意甲=相互战绩优先（h2h）；英超/德甲/法甲=净胜球优先（gd）。
# 意甲 22-23 起冠军/降级席位恰好同分改踢附加赛——此处不建模，仍按 h2h 规则排（诚实近似）。
LEAGUE_TIEBREAK = {"SP1": "h2h", "I1": "h2h"}


class SeasonSimulator:
    """单联赛单赛季：facts（已赛）+ remaining（未赛主客对）→ N 次终局模拟。"""

    def __init__(self, model, teams, facts, remaining, sims=5000, seed=42, tiebreak="gd"):
        """teams: 本季 20 队；facts: DataFrame(home_team,away_team,home_score,away_score)；
        remaining: [(home, away), ...]（本季未赛场次）；tiebreak: "gd" 英超口径 / "h2h" 西甲口径。"""
        assert tiebreak in ("gd", "h2h"), tiebreak
        self.m = model
        self.teams = sorted(teams)
        self.idx = {t: k for k, t in enumerate(self.teams)}
        self.facts = facts
        self.remaining = list(remaining)
        self.N = sims
        self.rng = np.random.default_rng(seed)
        self.tiebreak = tiebreak

    def _base_table(self):
        """事实积分/净胜/进球向量（所有模拟共享的起点）。"""
        n = len(self.teams)
        pts = np.zeros(n); gd = np.zeros(n); gf = np.zeros(n)
        for _, r in self.facts.iterrows():
            ih, ia = self.idx[r.home_team], self.idx[r.away_team]
            gh, ga = int(r.home_score), int(r.away_score)
            gf[ih] += gh; gf[ia] += ga
            gd[ih] += gh - ga; gd[ia] += ga - gh
            if gh > ga: pts[ih] += 3
            elif gh < ga: pts[ia] += 3
            else: pts[ih] += 1; pts[ia] += 1
        return pts, gd, gf

    def _base_h2h(self):
        """事实相互战绩矩阵：hp[i,j]=i 从对 j 两回合拿到的积分，hgd 同理净胜。"""
        n = len(self.teams)
        hp = np.zeros((n, n)); hgd = np.zeros((n, n))
        for _, r in self.facts.iterrows():
            ih, ia = self.idx[r.home_team], self.idx[r.away_team]
            gh, ga = int(r.home_score), int(r.away_score)
            hgd[ih, ia] += gh - ga; hgd[ia, ih] += ga - gh
            if gh > ga: hp[ih, ia] += 3
            elif gh < ga: hp[ia, ih] += 3
            else: hp[ih, ia] += 1; hp[ia, ih] += 1
        return hp, hgd

    def _rank_h2h(self, pts, gd, gf, hp, hgd):
        """西甲口径逐模拟排名：同分组内 小循环积分 → 小循环净胜 → 总净胜 → 总进球 → 抖动。"""
        N, n = pts.shape
        jit = self.rng.random((N, n)) * 1e-3
        rank = np.empty((N, n), dtype=np.int64)
        for s in range(N):
            order = sorted(range(n), key=lambda k: (-pts[s, k], jit[s, k]))
            final, i = [], 0
            while i < n:
                j = i + 1
                while j < n and pts[s, order[j]] == pts[s, order[i]]:
                    j += 1
                grp = order[i:j]
                if len(grp) > 1:
                    gs = set(grp)
                    grp = sorted(grp, key=lambda k: (
                        -sum(hp[s, k, o] for o in gs if o != k),
                        -sum(hgd[s, k, o] for o in gs if o != k),
                        -gd[s, k], -gf[s, k], jit[s, k]))
                final.extend(grp); i = j
            rank[s, final] = np.arange(n)
        return rank

    def run(self):
        n, N = len(self.teams), self.N
        h2h = self.tiebreak == "h2h"
        pts0, gd0, gf0 = self._base_table()
        pts = np.tile(pts0, (N, 1)); gd = np.tile(gd0, (N, 1)); gf = np.tile(gf0, (N, 1))
        if h2h:
            hp0, hgd0 = self._base_h2h()
            hp = np.tile(hp0, (N, 1, 1)); hgd = np.tile(hgd0, (N, 1, 1))
        for (h, a) in self.remaining:
            if h not in self.idx or a not in self.idx:
                continue
            *_, M = self.m.score_matrix(h, a, neutral=False)
            draws = self.rng.choice(SIDE * SIDE, size=N, p=M.flatten())
            gh, ga = draws // SIDE, draws % SIDE
            ih, ia = self.idx[h], self.idx[a]
            gf[:, ih] += gh; gf[:, ia] += ga
            gd[:, ih] += gh - ga; gd[:, ia] += ga - gh
            w_h = np.where(gh > ga, 3, np.where(gh == ga, 1, 0))
            w_a = np.where(ga > gh, 3, np.where(gh == ga, 1, 0))
            pts[:, ih] += w_h; pts[:, ia] += w_a
            if h2h:
                hgd[:, ih, ia] += gh - ga; hgd[:, ia, ih] += ga - gh
                hp[:, ih, ia] += w_h; hp[:, ia, ih] += w_a
        if h2h:
            rank = self._rank_h2h(pts, gd, gf, hp, hgd)
        else:
            comp = pts * 1e6 + (gd + 200) * 1e3 + gf + self.rng.random((N, n)) * 1e-3
            order = np.argsort(-comp, axis=1)      # 每行：名次 -> 队序号
            rank = np.empty_like(order)
            rows = np.arange(N)[:, None]
            rank[rows, order] = np.arange(n)        # 队序号 -> 名次(0-based)
        out = []
        for t, k in self.idx.items():
            r = rank[:, k]
            out.append(dict(team=t,
                            title=float((r == 0).mean()),
                            top4=float((r < 4).mean()),
                            bottom3=float((r >= n - 3).mean()),
                            exp_pts=float(pts[:, k].mean()),
                            exp_rank=float(r.mean() + 1)))
        out.sort(key=lambda d: (-d["title"], d["exp_rank"]))
        return out


def season_slice(df, season_start, season_end):
    """从多季合并帧切出一季。"""
    a, b = pd.Timestamp(season_start), pd.Timestamp(season_end)
    return df[(df.date >= a) & (df.date <= b)]


def remaining_pairs(facts, teams=None):
    """整季剩余赛程推导（实况模式用）：双循环全 (主,客) 组合 − 已赛组合。

    football-data fixtures.csv 只有未来一轮，拿不到整季剩余——但双循环联赛的剩余
    赛程是确定集合，无需外部源；改期/延期场次天然包含（对阵没踢过就在集合里）。
    teams 默认从 facts 推（赛季初期若有队还没出场，务必显式传本季完整名单）。"""
    teams = sorted(teams or set(facts.home_team) | set(facts.away_team))
    played = set(zip(facts.home_team, facts.away_team))
    return [(h, a) for h in teams for a in teams if h != a and (h, a) not in played]


def simulate_retro(code, season_start, season_end, as_of, hl=365.0, sims=5000, seasons=7,
                   feeder=None, tiebreak=None):
    """回溯模拟：as_of 前=事实（模型也只用 as_of 前数据训练，防泄漏），后=抽样。

    feeder：次级联赛码（如英超传 "E1"）。赛季模拟必须覆盖升班马（跳过整队 38 场会扭曲全表），
    故训练帧并入次级联赛供其评级——与单场预测「纯 E0 更准」(bt_club_hl E1 变体)不冲突：
    单场展示用纯顶级模型 + 数据不足标注；赛季模拟用合训保覆盖，是分场景取舍（已记入 PLAN §3）。"""
    df = clubdata.load(code, seasons=seasons)
    train = df if not feeder else (
        pd.concat([df, clubdata.load(feeder, seasons=seasons)], ignore_index=True)
        .sort_values("date").reset_index(drop=True))
    m = DixonColesModel(half_life_days=hl).fit(train, verbose=False, as_of=pd.Timestamp(as_of))
    season = season_slice(df, season_start, season_end)
    teams = set(season.home_team) | set(season.away_team)
    cut = pd.Timestamp(as_of)
    facts = season[season.date < cut]
    remaining = [(r.home_team, r.away_team) for _, r in season[season.date >= cut].iterrows()]
    sim = SeasonSimulator(m, teams, facts, remaining, sims=sims,
                          tiebreak=tiebreak or LEAGUE_TIEBREAK.get(code, "gd"))
    return sim.run(), len(facts), len(remaining)


def standings(season_df):
    """一季积分榜（积分>净胜>进球，联赛通用近似）：
    返回按名次排序的行 [{team,played,w,d,l,gf,ga,gd,pts}]。"""
    rows: dict[str, dict] = {}
    for _, r in season_df.iterrows():
        for t in (r.home_team, r.away_team):
            rows.setdefault(t, dict(team=t, played=0, w=0, d=0, l=0, gf=0, ga=0))
        h, a = rows[r.home_team], rows[r.away_team]
        hs, as_ = int(r.home_score), int(r.away_score)
        h["played"] += 1; a["played"] += 1
        h["gf"] += hs; h["ga"] += as_
        a["gf"] += as_; a["ga"] += hs
        if hs > as_: h["w"] += 1; a["l"] += 1
        elif hs < as_: h["l"] += 1; a["w"] += 1
        else: h["d"] += 1; a["d"] += 1
    out = list(rows.values())
    for r in out:
        r["gd"] = r["gf"] - r["ga"]; r["pts"] = 3 * r["w"] + r["d"]
    out.sort(key=lambda r: (r["pts"], r["gd"], r["gf"]), reverse=True)
    return out


def final_table(season_df):
    """一季终表（积分>净胜>进球，联赛通用近似）：返回按名次排序的队名列表。"""
    return [r["team"] for r in standings(season_df)]


def simulate_preseason(code, promoted, hl=365.0, sims=5000, seasons=7,
                       feeder=None, tiebreak=None):
    """季前模拟（实况模式第一形态）：新赛季 0 场已赛，整季 = remaining_pairs 双循环合成。

    promoted：新赛季升班马名单（football-data 拼写）——附加赛胜者无法从联赛终表推导，
    必须显式传入；降级队 = 上季终表末 len(promoted) 位（英超口径准确；德甲/法甲 16 名
    附加赛保级不建模，诚实近似，同意甲同分附加赛注释）。
    feeder：升班马上季在次级联赛，评级必须并入 feeder 帧（同 simulate_retro 的分场景裁决）。
    返回 (rows, teams)——rows 同 SeasonSimulator.run()。"""
    df = clubdata.load(code, seasons=seasons)
    last_end = df.date.max()
    season = df[df.date >= last_end - pd.Timedelta(days=330)]   # 最近一个完整赛季
    table = final_table(season)
    stay = [t for t in table[:len(table) - len(promoted)]]
    teams = set(stay) | set(promoted)
    assert len(teams) == len(table), f"名单数不守恒：{len(teams)} vs {len(table)}"
    train = df if not feeder else (
        pd.concat([df, clubdata.load(feeder, seasons=seasons)], ignore_index=True)
        .sort_values("date").reset_index(drop=True))
    m = DixonColesModel(half_life_days=hl).fit(train, verbose=False)
    facts = df[df.date > last_end]                              # 空帧（列结构完整）
    remaining = remaining_pairs(facts, teams=teams)
    sim = SeasonSimulator(m, teams, facts, remaining, sims=sims,
                          tiebreak=tiebreak or LEAGUE_TIEBREAK.get(code, "gd"))
    return sim.run(), sorted(teams)


def main():
    for as_of, label in [("2024-08-01", "赛季前"), ("2025-01-01", "半程")]:
        rows, nf, nr = simulate_retro("E0", "2024-08-01", "2025-06-01", as_of, sims=5000,
                                      feeder="E1")
        print(f"\n—— 英超 24-25 · {label}（as_of={as_of}，事实 {nf} 场 + 模拟 {nr} 场）——")
        print(f"{'队':<16}{'冠军':>7}{'前四':>7}{'降级':>7}{'期望分':>8}{'期望名次':>8}")
        for d in rows[:6]:
            print(f"{d['team']:<16}{d['title']:>6.1%}{d['top4']:>7.1%}{d['bottom3']:>7.1%}"
                  f"{d['exp_pts']:>8.1f}{d['exp_rank']:>8.1f}")
        print("  …")
        for d in rows[-3:]:
            print(f"{d['team']:<16}{d['title']:>6.1%}{d['top4']:>7.1%}{d['bottom3']:>7.1%}"
                  f"{d['exp_pts']:>8.1f}{d['exp_rank']:>8.1f}")
    print("\n真实终局对照：利物浦冠军(84分)、阿森纳/曼城/切尔西前四；南安普顿/伊普斯维奇/莱斯特降级。")


if __name__ == "__main__":
    main()
