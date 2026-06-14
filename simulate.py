"""
蒙特卡洛赛事模拟：基于比分矩阵，模拟整届 2026 世界杯，输出每队夺冠概率。

流程
----
1) 从赛程自动推断 12 个小组（并查集：同组的队互相有小组赛对阵）。
2) 小组赛：对每场用模型的比分概率矩阵抽样真实比分 -> 算积分/净胜球/进球。
   排名规则：积分 > 净胜球 > 进球数 >（随机打破剩余平局）。
3) 出线：每组前 2（24 队）+ 成绩最好的 8 个小组第三 = 32 队。
4) 淘汰赛：单场淘汰，平局按 (胜率/(胜率+负率)) 模拟点球。
   对阵采用「按模型实力重新种子」的标准简化括号（强 vs 弱）。
5) 重复 N 次，统计每队进入各轮 / 夺冠的频率。

注：FIFA 官方的 8 个第三名 -> 具体括号位是复杂的固定映射，这里用实力种子简化，
   会让强队路径略平滑；夺冠概率量级可靠，精确括号可作为后续扩展。
"""
from __future__ import annotations
import argparse
from collections import defaultdict

import numpy as np
import pandas as pd

import data as datamod
import wc2026
import schedule
import env
from model import MAX_GOALS, DixonColesModel
from predict import get_model

SIDE = MAX_GOALS + 1  # 比分矩阵边长 (0..MAX_GOALS)


def derive_groups(fx):
    """用并查集从小组赛对阵推断 12 个小组。返回 {组号: [4队]} 与每组的对阵列表。"""
    teams = sorted(set(fx["home_team"]) | set(fx["away_team"]))
    parent = {t: t for t in teams}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, r in fx.iterrows():
        parent[find(r["home_team"])] = find(r["away_team"])

    comp = defaultdict(list)
    for t in teams:
        comp[find(t)].append(t)
    groups = {i: sorted(v) for i, v in enumerate(comp.values())}

    fixtures = defaultdict(list)
    root2gid = {}
    for gid, members in groups.items():
        root2gid[find(members[0])] = gid
    for _, r in fx.iterrows():
        gid = root2gid[find(r["home_team"])]
        fixtures[gid].append((r["home_team"], r["away_team"]))
    return groups, fixtures


class TournamentSimulator:
    def __init__(self, model: DixonColesModel, df, sims=5000, seed=42):
        self.m = model
        self.N = sims
        self.rng = np.random.default_rng(seed)
        # 小组与小组赛程用官方静态数据（wc2026.GROUPS + schedule.GROUP）构建。
        # 旧实现从「未开赛(NA比分)行」并查集推断（derive_groups），开赛后比分逐场填入、
        # NA 行消失，小组推断会逐场退化（一组踢完整组消失）——必须与数据推进解耦。
        # 排序后构建保证跨进程确定性（可复现性铁律）；赛程按开球时间排序与旧 date 序一致。
        letters = sorted(wc2026.GROUPS)
        self.groups = {gid: sorted(wc2026.GROUPS[L]) for gid, L in enumerate(letters)}
        self.group_letter = {gid: L for gid, L in enumerate(letters)}
        self.gid_by_letter = {L: gid for gid, L in self.group_letter.items()}
        team_gid = {t: gid for gid, mem in self.groups.items() for t in mem}
        self.fixtures = defaultdict(list)
        for (h, a), _bj in sorted(schedule.GROUP.items(), key=lambda kv: (kv[1], kv[0])):
            self.fixtures[team_gid[h]].append((h, a))
        # 过滤掉模型里没有的队（样本不足）
        self.all_teams = sorted({t for g in self.groups.values() for t in g})
        missing = [t for t in self.all_teams if t not in self.m.attack]
        if missing:
            print(f"[warn] {len(missing)} 队不在模型中，将用联赛平均近似: {missing}")
        # 静态实力（用于淘汰赛种子）
        self.strength = {t: self.m.attack.get(t, 0.0) - self.m.defence.get(t, 0.0)
                         for t in self.all_teams}
        self._pmf_cache = {}     # 小组赛对阵 -> 比分概率分布(扁平)
        self._adv_cache = {}     # 淘汰赛对阵 -> A 晋级概率
        # 小组赛对阵 -> 比赛日（场馆当地日，对齐数据集口径；用于标注兜底）
        self.fixture_date = {}
        for ps in self.fixtures.values():
            for (h, a) in ps:
                gv = schedule.group_venue(h, a) or {}
                src = gv.get("local") or schedule.GROUP.get((h, a), "")
                self.fixture_date[(h, a)] = src[:10]
        # 已踢的真实世界杯赛果（随赛程推进自动生效，支撑"按比赛情况动态更新"）
        # 仅正赛（精确匹配，排除 "FIFA World Cup qualification" 预选赛），且为本届赛程对阵。
        # 数据行主客顺序可能与官方赛程相反 -> frozenset 顺序无关匹配，反序时翻转比分。
        # 日期须在小组赛阶段内：淘汰赛可能重演小组对阵（R16 起），不能凭对阵误判成小组赛。
        self.actual_results = {}
        canon = {frozenset(p): p for ps in self.fixtures.values() for p in ps}
        group_end = pd.Timestamp("2026-06-28")
        wp = datamod.played(df)
        wp = wp[wp["tournament"] == "FIFA World Cup"]
        for _, r in wp.iterrows():
            if getattr(r["date"], "year", 0) >= 2026 and r["date"] < group_end:
                cp = canon.get(frozenset((r["home_team"], r["away_team"])))
                if cp:  # 只认本届小组赛赛程里的对阵
                    gh, ga = int(r["home_score"]), int(r["away_score"])
                    if cp != (r["home_team"], r["away_team"]):
                        gh, ga = ga, gh
                    self.actual_results[cp] = (gh, ga)
        # 已踢的真实淘汰赛赛果：本届 WC 正赛、两队都是参赛队、但不是小组赛场次。
        # 顺序无关地按 frozenset 存；平局的点球胜者查 shootouts.csv。
        self.actual_ko = {}     # frozenset({a,b}) -> ({team: goals}, winner_en)
        teams48 = set(self.all_teams)
        sh = datamod.load_shootouts()
        sh = sh[sh["date"].dt.year >= 2026] if len(sh) else sh
        for _, r in wp.iterrows():
            if getattr(r["date"], "year", 0) < 2026:
                continue
            h, a = r["home_team"], r["away_team"]
            if (h not in teams48 or a not in teams48
                    or (frozenset((h, a)) in canon and r["date"] < group_end)):
                continue
            gh, ga = int(r["home_score"]), int(r["away_score"])
            if gh > ga:
                w = h
            elif ga > gh:
                w = a
            else:                # 平局 -> 点球，查 shootouts（两队任意顺序），查不到给主位兜底
                hit = sh[((sh["home_team"] == h) & (sh["away_team"] == a)) |
                         ((sh["home_team"] == a) & (sh["away_team"] == h))]
                w = hit.iloc[-1]["winner"] if len(hit) else h
            self.actual_ko[frozenset((h, a))] = ({h: gh, a: ga}, w)

        # 东道主主场优势：预计算每场小组赛的主场方 + 每个淘汰赛场次城市所属东道主国
        self.group_host = {}
        self.group_city = {}
        for ps in self.fixtures.values():
            for (h, a) in ps:
                self.group_host[(h, a)] = schedule.group_match_host(h, a)
                gv = schedule.group_venue(h, a)
                self.group_city[(h, a)] = gv.get("city") if gv else None
        self.ko_country = {mn: schedule.ko_city_country(mn) for mn in schedule.KO}
        self.ko_city = {mn: (schedule.ko_venue(mn) or {}).get("city") for mn in schedule.KO}
        # 环境上下文层开关（海拔/高温），默认开；可用性层不在此开关内
        self.use_env = True

    # ---------- 概率来源（host=a/b 时给该东道主主场优势，None 为中立）----------
    def _env(self, a, b, city):
        """该场环境乘子 (mult_a, mult_b)；use_env=False 或无城市时 (1,1)。"""
        if not self.use_env or not city:
            return None
        ma, mb = env.match_mult(a, b, city)
        return (ma, mb) if (ma != 1.0 or mb != 1.0) else None

    def _pmf(self, a, b, host=None, city=None):
        """a 视角的比分分布（扁平，行=a 进球）。"""
        key = (a, b, host, city)
        if key not in self._pmf_cache:
            em = self._env(a, b, city)              # (mult_a, mult_b)
            if host == a:
                _, _, _, _, M = self.m.score_matrix(a, b, neutral=False, env_mult=em)
            elif host == b:                          # b 为主 → score_matrix(b,a)，乘子需调序
                emb = (em[1], em[0]) if em else None
                _, _, _, _, Mb = self.m.score_matrix(b, a, neutral=False, env_mult=emb)
                M = Mb.T                             # 转置回 a 视角
            else:
                _, _, _, _, M = self.m.score_matrix(a, b, neutral=True, env_mult=em)
            self._pmf_cache[key] = M.ravel()
        return self._pmf_cache[key]

    def _match_full(self, a, b, host=None, city=None):
        """a 视角 (p_a胜, p_平, p_b胜, xg_a, xg_b)，含东道主主场 + 环境。"""
        em = self._env(a, b, city)
        if host == a:
            r = self.m.predict(a, b, neutral=False, env_mult=em)
            return r["p_home"], r["p_draw"], r["p_away"], r["xg_home"], r["xg_away"]
        if host == b:
            emb = (em[1], em[0]) if em else None
            r = self.m.predict(b, a, neutral=False, env_mult=emb)
            return r["p_away"], r["p_draw"], r["p_home"], r["xg_away"], r["xg_home"]
        r = self.m.predict(a, b, neutral=True, env_mult=em)
        return r["p_home"], r["p_draw"], r["p_away"], r["xg_home"], r["xg_away"]

    def _wdl(self, a, b, host=None, city=None):
        """a 视角 (p_a胜, p_平, p_b胜)，含东道主主场 + 环境。"""
        pa, pd, pb, _, _ = self._match_full(a, b, host, city)
        return pa, pd, pb

    def _padv(self, a, b, host=None, city=None):
        """A 在淘汰赛中晋级的概率（平局按相对胜率模拟点球）。"""
        key = (a, b, host, city)
        if key not in self._adv_cache:
            ph, pd, pa = self._wdl(a, b, host, city)
            pen = ph / (ph + pa) if (ph + pa) > 0 else 0.5  # 点球大战近似
            self._adv_cache[key] = ph + pd * pen
        return self._adv_cache[key]

    def _ko_host(self, mn, a, b):
        """淘汰赛该场次城市所属东道主若正好是对阵两队之一，返回其队名（占主场）。"""
        c = self.ko_country.get(mn)
        return a if a == c else (b if b == c else None)

    # ---------- 小组赛（按组向量化 N 次） ----------
    def _simulate_groups(self, known=None):
        N = self.N
        known = known or {}
        # 输出：winners/runners (N, 12)；thirds 及其成绩用于挑最佳 8
        winners = np.empty((N, len(self.groups)), dtype=object)
        runners = np.empty((N, len(self.groups)), dtype=object)
        thirds = np.empty((N, len(self.groups)), dtype=object)
        third_score = np.zeros((N, len(self.groups)))

        for gid, members in self.groups.items():
            idx = {t: k for k, t in enumerate(members)}
            pts = np.zeros((N, 4)); gf = np.zeros((N, 4)); ga = np.zeros((N, 4))
            for (h, a) in self.fixtures[gid]:
                if (h, a) in known:  # 已知/假设赛果：全部 N 次固定，不抽样
                    kh, ka = known[(h, a)]
                    gh = np.full(N, kh); gaa = np.full(N, ka)
                else:
                    pmf = self._pmf(h, a, self.group_host.get((h, a)), self.group_city.get((h, a)))
                    draws = self.rng.choice(SIDE * SIDE, size=N, p=pmf)
                    gh, gaa = draws // SIDE, draws % SIDE
                ih, ia = idx[h], idx[a]
                gf[:, ih] += gh; ga[:, ih] += gaa
                gf[:, ia] += gaa; ga[:, ia] += gh
                pts[:, ih] += np.where(gh > gaa, 3, np.where(gh == gaa, 1, 0))
                pts[:, ia] += np.where(gaa > gh, 3, np.where(gh == gaa, 1, 0))
            gd = gf - ga
            jitter = self.rng.random((N, 4)) * 1e-6
            comp = pts * 1e6 + (gd + 100) * 1e3 + gf + jitter
            order = np.argsort(-comp, axis=1)  # 每行：名次->队序号
            members_arr = np.array(members, dtype=object)
            winners[:, gid] = members_arr[order[:, 0]]
            runners[:, gid] = members_arr[order[:, 1]]
            third_idx = order[:, 2]
            thirds[:, gid] = members_arr[third_idx]
            r = np.arange(N)
            third_score[:, gid] = (pts[r, third_idx] * 1e6
                                   + (gd[r, third_idx] + 100) * 1e3
                                   + gf[r, third_idx])
        # 每次模拟取成绩最好的 8 个小组第三
        best_thirds_idx = np.argsort(-third_score, axis=1)[:, :8]
        return winners, runners, thirds, best_thirds_idx

    # ---------- 淘汰赛（逐次模拟） ----------
    def run(self, known=None, ko_known=None):
        # 条件化在已知赛果（真实自动 + 用户假设）上，使夺冠概率随赛况动态更新
        cond = dict(self.actual_results)
        if known:
            cond.update(known)
        ko_known = ko_known or {}
        winners, runners, thirds, best3 = self._simulate_groups(cond)
        teams = self.all_teams
        stat = {t: dict(ko=0, qf=0, sf=0, final=0, champ=0) for t in teams}

        gl = self.group_letter
        for s in range(self.N):
            win = {gl[g]: winners[s, g] for g in self.groups}
            run = {gl[g]: runners[s, g] for g in self.groups}
            thr = {gl[g]: thirds[s, g] for g in self.groups}
            qual_letters = [gl[g] for g in best3[s]]
            for t in list(win.values()) + list(run.values()) + [thirds[s, g] for g in best3[s]]:
                stat[t]["ko"] += 1
            # 按 2026 官方括号打淘汰赛
            results, _, champ = self._play_bracket(win, run, thr, qual_letters, self.rng,
                                                   ko_known=ko_known)
            for (mn, _, _) in wc2026.R16:  # R16 胜者 = 进八强(8)
                stat[results[mn]]["qf"] += 1
            for (mn, _, _) in wc2026.QF:   # QF 胜者 = 进四强(4)
                stat[results[mn]]["sf"] += 1
            for (mn, _, _) in wc2026.SF:   # SF 胜者 = 进决赛(2)
                stat[results[mn]]["final"] += 1
            stat[champ]["champ"] += 1

        rows = []
        for t in teams:
            d = stat[t]; n = self.N
            rows.append((t, d["champ"]/n, d["final"]/n, d["sf"]/n, d["qf"]/n, d["ko"]/n))
        rows.sort(key=lambda x: x[1], reverse=True)
        return rows

    # ---------- 单届完整模拟（用于晋级树状图） ----------
    @staticmethod
    def _seed_order(n):
        """标准单淘汰种子排位：保证 1、2 号种子只能在决赛相遇。"""
        seeds = [1]
        while len(seeds) < n:
            length = len(seeds) * 2
            seeds = [x for s in seeds for x in (s, length + 1 - s)]
        return seeds

    def _match_score(self, a, b, rng, host=None, city=None):
        idx = int(rng.choice(SIDE * SIDE, p=self._pmf(a, b, host, city)))
        return idx // SIDE, idx % SIDE

    def _pen(self, a, b, host=None, city=None):
        """点球大战 A 取胜概率（按相对常规胜率近似）。"""
        ph, _, pa = self._wdl(a, b, host, city)
        return ph / (ph + pa) if (ph + pa) > 0 else 0.5

    def _play_bracket(self, winner, runner, third, qual_letters, rng, record=False, ko_known=None):
        """
        按 2026 官方括号打完淘汰赛。
          winner/runner/third: {组字母: 队名}；qual_letters: 出线的 8 个第三所在组
          ko_known: {(a,b): (ga,gb,winner)} 已知/假设淘汰赛结果（这两队相遇时套用）
          record=True 时返回每场比分明细（用于树状图），否则只决胜负（冠军模拟，更快）
        返回 (results{match:winner}, rounds_detail, champion)
        """
        ko_known = ko_known or {}
        r32 = wc2026.resolve_r32(winner, runner, third, qual_letters)
        results, rounds_detail = {}, []

        def play(a, b, mn):
            if (a, b) in ko_known:        # 这两队相遇且结果已知 -> 套用
                ka, kb, w = ko_known[(a, b)]
                return w, {"a": a, "b": b, "ga": ka, "gb": kb, "winner": w, "pens": ka == kb}
            if (b, a) in ko_known:        # 顺序相反
                kb, ka, w = ko_known[(b, a)]
                return w, {"a": a, "b": b, "ga": ka, "gb": kb, "winner": w, "pens": ka == kb}
            host = self._ko_host(mn, a, b)    # 该场次城市若是东道主本国 -> 其占主场
            city = self.ko_city.get(mn)
            if record:
                gh, ga = self._match_score(a, b, rng, host, city)
                if gh > ga:
                    return a, {"a": a, "b": b, "ga": gh, "gb": ga, "winner": a, "pens": False}
                if gh < ga:
                    return b, {"a": a, "b": b, "ga": gh, "gb": ga, "winner": b, "pens": False}
                w = a if rng.random() < self._pen(a, b, host, city) else b
                return w, {"a": a, "b": b, "ga": gh, "gb": ga, "winner": w, "pens": True}
            return (a if rng.random() < self._padv(a, b, host, city) else b), None

        det = []
        for mn in wc2026.R32_ORDER:
            a, b = r32[mn]
            results[mn], d = play(a, b, mn)
            det.append(d)
        rounds_detail.append(("R32", det))
        for name, rnd in [("R16", wc2026.R16), ("QF", wc2026.QF),
                          ("SF", wc2026.SF), ("Final", [wc2026.FINAL])]:
            det = []
            for (mn, fa, fb) in rnd:
                a, b = results[fa], results[fb]
                results[mn], d = play(a, b, mn)
                det.append(d)
            rounds_detail.append((name, det))
        return results, rounds_detail, results[wc2026.FINAL[0]]

    def simulate_once(self, seed=None):
        """模拟完整一届（2026 官方括号）：返回小组排名 + 各轮对阵(带比分) + 冠军。"""
        rng = np.random.default_rng(seed)
        groups_out = []
        win_L, run_L, third_L = {}, {}, {}
        thirds_meta = []  # (letter, team, pts, gd, gf) 用于挑最佳 8 个第三

        for gid, members in self.groups.items():
            L = self.group_letter.get(gid)
            idx = {t: k for k, t in enumerate(members)}
            pts = [0]*4; gf = [0]*4; ga = [0]*4; ms = []
            for (h, a) in self.fixtures[gid]:
                gh, gaa = self._match_score(h, a, rng, self.group_host.get((h, a)),
                                            self.group_city.get((h, a)))
                ih, ia = idx[h], idx[a]
                gf[ih] += gh; ga[ih] += gaa; gf[ia] += gaa; ga[ia] += gh
                if gh > gaa: pts[ih] += 3
                elif gh < gaa: pts[ia] += 3
                else: pts[ih] += 1; pts[ia] += 1
                ms.append({"home": h, "away": a, "gh": int(gh), "ga": int(gaa)})
            order = sorted(range(4), key=lambda k: (pts[k], gf[k]-ga[k], gf[k], rng.random()),
                           reverse=True)
            standings = [{"team": members[k], "pts": pts[k], "gd": gf[k]-ga[k],
                          "gf": gf[k], "rank": pos+1} for pos, k in enumerate(order)]
            groups_out.append({"group": L, "standings": standings, "matches": ms})
            win_L[L] = members[order[0]]; run_L[L] = members[order[1]]
            k3 = order[2]; third_L[L] = members[k3]
            thirds_meta.append((L, members[k3], pts[k3], gf[k3]-ga[k3], gf[k3]))

        groups_out.sort(key=lambda g: g["group"])
        best = sorted(thirds_meta, key=lambda d: (d[2], d[3], d[4], rng.random()), reverse=True)[:8]
        qual_letters = [d[0] for d in best]

        _, rounds_detail, champion = self._play_bracket(
            win_L, run_L, third_L, qual_letters, rng, record=True)
        rounds = [{"name": name, "matches": ms} for name, ms in rounds_detail]
        return {"groups": groups_out, "rounds": rounds, "champion": champion}

    # ---------- 确定性"最可能"投影（动态更新预测核心） ----------
    def _modal_score(self, a, b, host=None, city=None):
        M = self._pmf(a, b, host, city).reshape(SIDE, SIDE)
        i, j = np.unravel_index(int(M.argmax()), M.shape)
        return int(i), int(j)

    def _project_match(self, a, b, ko_known=None, mn=None):
        if ko_known and (a, b) in ko_known:   # 用户假设/录入优先
            ka, kb, w = ko_known[(a, b)]
            return w, {"a": a, "b": b, "ga": ka, "gb": kb, "winner": w,
                       "pens": ka == kb, "set": True}
        ak = getattr(self, "actual_ko", None)  # 自动套入真实淘汰赛赛果（顺序无关）
        if ak:
            sc_w = ak.get(frozenset((a, b)))
            if sc_w:
                sc, w = sc_w
                ka, kb = sc[a], sc[b]
                return w, {"a": a, "b": b, "ga": ka, "gb": kb, "winner": w,
                           "pens": ka == kb, "set": True, "real": True}
        host = self._ko_host(mn, a, b) if mn is not None else None
        city = self.ko_city.get(mn) if mn is not None else None
        gh, gaa = self._modal_score(a, b, host, city)
        pa_, _, pb_ = self._wdl(a, b, host, city)
        if gh != gaa:
            w, pens = (a if gh > gaa else b), False
        else:
            w, pens = (a if pa_ >= pb_ else b), True  # 平 -> 点球给热门
        return w, {"a": a, "b": b, "ga": gh, "gb": gaa, "winner": w, "pens": pens,
                   "pa": round(pa_, 3), "pb": round(pb_, 3)}

    def project(self, known=None, ko_known=None, today=None):
        """
        确定性投影：真实赛果(自动) + 用户假设(known) + 模型预测(其余) -> 官方括号最可能走势。
        known:    {(home,away): (gh,ga)} 覆盖某场小组赛。
        ko_known: {(teamA,teamB): (ga,gb,winner)} 覆盖某场淘汰赛（按当前对阵的两队）。
        today:    "YYYY-MM-DD"，用于判定 已结束/进行中/未开赛。
        返回 {groups(含可编辑赛果+期望积分排名+日期状态), rounds(官方括号+日期状态), champion}
        """
        res = dict(self.actual_results)
        if known:
            res.update(known)
        ko_known = ko_known or {}
        today = today or "1970-01-01"

        def play_state(key, date):
            if key in self.actual_results:
                return "finished"          # 真实已结束
            if date and date < today:
                return "finished"
            if date and date == today:
                return "live"              # 当天=进行中
            return "upcoming"

        groups_out = []
        win_L, run_L, third_L, thirds_meta = {}, {}, {}, []
        for gid, members in self.groups.items():
            L = self.group_letter.get(gid)
            ep = {t: 0.0 for t in members}    # 期望积分
            eg = {t: 0.0 for t in members}    # 期望净胜球
            ms = []
            for (h, a) in self.fixtures[gid]:
                key = (h, a)
                if key in res:
                    gh, ga = res[key]
                    status = "played" if key in self.actual_results else "set"
                    if gh > ga: ep[h] += 3
                    elif gh < ga: ep[a] += 3
                    else: ep[h] += 1; ep[a] += 1
                    eg[h] += gh - ga; eg[a] += ga - gh
                else:
                    hostg = self.group_host.get((h, a))
                    cityg = self.group_city.get((h, a))
                    gh, ga = self._modal_score(h, a, hostg, cityg)
                    status = "pred"
                    ph, pdr, pa, xh, xa = self._match_full(h, a, hostg, cityg)
                    ep[h] += 3 * ph + pdr
                    ep[a] += 3 * pa + pdr
                    eg[h] += xh - xa
                    eg[a] += xa - xh
                kt = schedule.GROUP.get((h, a), "")
                date, time = (kt[:10], kt[11:]) if kt else (self.fixture_date.get((h, a), ""), "")
                ven = schedule.group_venue(h, a) or {}
                lc = ven.get("local", "")
                ms.append({"home": h, "away": a, "gh": int(gh), "ga": int(ga),
                           "status": status, "date": date, "time": time, "drawn": True,
                           "city": ven.get("city", ""),
                           "date_local": lc[:10], "time_local": lc[11:],
                           "play": play_state((h, a), date), "hypo": status == "set"})
            order = sorted(members, key=lambda t: (ep[t], eg[t], self.strength.get(t, -9)),
                           reverse=True)
            standings = [{"team": t, "pts": round(ep[t], 1), "gd": round(eg[t], 1),
                          "rank": i + 1} for i, t in enumerate(order)]
            groups_out.append({"group": L, "standings": standings, "matches": ms})
            win_L[L], run_L[L], third_L[L] = order[0], order[1], order[2]
            thirds_meta.append((L, ep[order[2]], eg[order[2]]))

        groups_out.sort(key=lambda g: g["group"])
        best = sorted(thirds_meta, key=lambda d: (d[1], d[2]), reverse=True)[:8]
        qual_letters = [d[0] for d in best]

        # 各组是否已"定档"（6 场都有结果，名次确定）→ 决定淘汰赛是否已抽签
        gdet = {}
        for gid, members in self.groups.items():
            L = self.group_letter.get(gid)
            gdet[L] = all(p in res for p in self.fixtures[gid])
        all_det = all(gdet.values())

        def r32_drawn(mn):
            def side(s):
                k, ref = s
                return all_det if k == "3" else gdet.get(ref, False)
            sa, sb = wc2026.R32_SLOTS[mn]
            return side(sa) and side(sb)

        def annotate(d, mn, drawn):
            kt = schedule.KO.get(mn, "")
            date, time = (kt[:10], kt[11:]) if kt else (wc2026.KO_DATES.get(mn, ""), "")
            ven = schedule.ko_venue(mn) or {}
            lc = ven.get("local", "")
            decided = d.get("set", False)        # 已录入结果（真实/假设）
            real = d.get("real", False)          # 真实赛果（自动套入），非用户试算
            d["mn"] = mn; d["date"] = date; d["time"] = time; d["drawn"] = drawn
            d["city"] = ven.get("city", ""); d["date_local"] = lc[:10]; d["time_local"] = lc[11:]
            d["hypo"] = decided and not real     # 仅用户试算才标"试算"，真实赛果标"已结束"
            if not drawn:
                d["play"] = "tbd"                # 未抽签
            elif decided:
                d["play"] = "finished"
            elif date and date < today: d["play"] = "finished"
            elif date and date == today: d["play"] = "live"
            else: d["play"] = "upcoming"
            return d

        r32 = wc2026.resolve_r32(win_L, run_L, third_L, qual_letters)
        results, rounds, decided = {}, [], {}
        det = []
        for mn in wc2026.R32_ORDER:
            a, b = r32[mn]
            results[mn], d = self._project_match(a, b, ko_known, mn)
            dr = r32_drawn(mn)
            decided[mn] = dr and d.get("set", False)
            det.append(annotate(d, mn, dr))
        rounds.append({"name": "R32", "matches": det})
        for name, rnd in [("R16", wc2026.R16), ("QF", wc2026.QF),
                          ("SF", wc2026.SF), ("Final", [wc2026.FINAL])]:
            det = []
            for (mn, fa, fb) in rnd:
                a, b = results[fa], results[fb]
                results[mn], d = self._project_match(a, b, ko_known, mn)
                dr = decided.get(fa, False) and decided.get(fb, False)  # 双方上轮都已决出
                decided[mn] = dr and d.get("set", False)
                det.append(annotate(d, mn, dr))
            rounds.append({"name": name, "matches": det})
        return {"groups": groups_out, "rounds": rounds,
                "champion": results[wc2026.FINAL[0]],
                "qualified_thirds": qual_letters}


def main():
    ap = argparse.ArgumentParser(description="2026 世界杯夺冠概率蒙特卡洛模拟")
    ap.add_argument("--sims", type=int, default=5000, help="模拟次数（默认 5000）")
    ap.add_argument("--top", type=int, default=24, help="显示前 N 名")
    ap.add_argument("--no-cache", action="store_true", help="强制重新训练模型")
    ap.add_argument("--no-injuries", action="store_true",
                    help="忽略 availability.json 关键球员缺阵调整（默认计入）")
    args = ap.parse_args()

    m = get_model(not args.no_cache, half_life=240.0)
    if not args.no_injuries:
        n = m.set_availability()
        if n:
            print(f"[avail] 计入 {n} 队关键球员缺阵调整（--no-injuries 可关）")
    df = datamod.load_raw()
    print(f"[sim] 运行 {args.sims} 次蒙特卡洛 ...")
    rows = TournamentSimulator(m, df, sims=args.sims).run()

    print(f"\n  🏆 2026 世界杯夺冠概率（{args.sims} 次模拟）")
    print("  " + "─" * 64)
    print(f"  {'#':>2} {'球队':<22}{'夺冠':>7}{'进决赛':>8}{'四强':>7}{'八强':>7}{'出线':>7}")
    print("  " + "─" * 64)
    for i, (t, ch, fi, sf, qf, ko) in enumerate(rows[:args.top], 1):
        print(f"  {i:>2} {t:<22}{ch*100:6.1f}%{fi*100:7.1f}%{sf*100:6.1f}%{qf*100:6.1f}%{ko*100:6.1f}%")
    print()


if __name__ == "__main__":
    main()
