# Repository summary: World Cup prediction analytics module.
"""Model layer: Dixon-Coles double-Poisson score-prediction model.

模型层：双泊松 + Dixon-Coles 修正的比分预测模型。

原理
----
1) 双泊松（Lee 1997）：每队进球数 ~ Poisson(λ)
     log λ_主 = 截距 + 主场优势·(非中立) + 进攻[主] + 失球[客]
     log λ_客 = 截距 +                  进攻[客] + 失球[主]
   用 statsmodels 的 Poisson GLM 拟合，freq_weights 喂入时间衰减权重。
   这是凸优化，收敛稳，几秒出结果。

2) Dixon-Coles 修正（1997）：独立泊松会低估 0-0/1-1 等低比分平局，
   引入相关参数 ρ 修正 (0,0)(0,1)(1,0)(1,1) 四个低分格，单独用 1 维优化估计。

输出：完整比分概率矩阵 -> 最可能比分 / 胜平负概率 / 期望进球。
"""
from __future__ import annotations
import difflib
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom, poisson
import statsmodels.api as sm
import statsmodels.formula.api as smf

import data as datamod
import market

MAX_GOALS = 10  # 比分矩阵截断到 0..10 球，足够覆盖 99.99% 概率

# 模型缓存 schema 版本：给类加/删属性时 +1，get_model 据此自动重建旧 model.pkl，
# 避免"忘了删 pkl"导致旧 pickle 缺属性把全站搞挂（曾发生）。
SCHEMA_VERSION = 4

# 反序列化兜底默认值：旧 pickle 缺哪个属性就补哪个，predict 路径永不再 AttributeError。
_STATE_DEFAULTS = {
    "half_life_days": 730.0, "max_age_years": 16.0, "min_matches": 12,
    "market_k": 25.0, "min_market_weight": 0.0,
    "avail_att": {}, "avail_def": {},  # 关键球员可用性 xG 乘子（上下文层，空=零影响）
    "use_elo": False, "elo_ratings": {}, "elo_coef": 0.0, "comp_weights": None,
    "nb_alpha": 0.0,
    "glm": None, "rho": 0.0, "teams": [], "intercept": 0.0, "home_adv": 0.0,
    "attack": {}, "defence": {}, "attack_raw": {}, "defence_raw": {}, "n_matches": {},
    "schema_version": 0,
}


def _tau(i, j, lam, mu, rho):
    """Dixon-Coles 低分相关修正因子。i=主队进球, j=客队进球。"""
    if i == 0 and j == 0:
        return 1.0 - lam * mu * rho
    if i == 0 and j == 1:
        return 1.0 + lam * rho
    if i == 1 and j == 0:
        return 1.0 + mu * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


class DixonColesModel:
    def __init__(self, half_life_days=730.0, max_age_years=16.0, min_matches=12,
                 market_k=25.0, use_elo=False, comp_weights=None, nb_alpha=0.0):
        self.schema_version = SCHEMA_VERSION
        self.nb_alpha = nb_alpha          # 进球分布过离散参数(NB2: var=μ+α·μ²)；0=Poisson(默认)
        self.half_life_days = half_life_days
        self.max_age_years = max_age_years
        self.min_matches = min_matches
        self.comp_weights = comp_weights  # 分级赛事权重 {tier:w}；None 时友谊0.5/其余1.0
        self.use_elo = use_elo            # 是否把 Elo 差作为外生特征加进 GLM（实验性，默认关）
        self.elo_ratings: dict[str, float] = {}
        self.elo_coef = 0.0
        self.market_k = market_k          # 身价收缩强度：球队比赛数 = K 时为 50/50 混合
        # 回测显示身价收缩不改善 RPS（国家队样本本就够大），故默认关闭(0)；
        # 身价数值仍在 UI 展示。设 >0 可启用（略升命中率但略降概率校准）。
        self.min_market_weight = 0.0
        self.glm = None
        self.rho = 0.0
        self.teams: list[str] = []
        self.intercept = 0.0
        self.home_adv = 0.0
        self.attack: dict[str, float] = {}
        self.defence: dict[str, float] = {}
        self.attack_raw: dict[str, float] = {}   # 收缩前的纯数据评级（留档）
        self.defence_raw: dict[str, float] = {}
        self.n_matches: dict[str, int] = {}
        # 关键球员可用性『上下文层』乘子（默认空=零影响，引擎与纯 DC 数值一致）。
        # avail_att[t]<1 削该队进攻 λ；avail_def[t]>1 抬对手对该队进球 λ。
        self.avail_att: dict[str, float] = {}
        self.avail_def: dict[str, float] = {}

    def set_availability(self, avail=None):
        """从 availability.json（或传入 dict）装载关键球员缺阵 xG 乘子。返回受影响队数。
        这是运行期调用的补充层，不进 model.pkl 缓存、不影响 backtest。"""
        import adjust
        mods = adjust.team_modifiers(avail if isinstance(avail, dict) else None)
        self.avail_att = {t: m["att"] for t, m in mods.items()}
        self.avail_def = {t: m["def_pen"] for t, m in mods.items()}
        return len(mods)

    # ---------- 训练 ----------
    def fit(self, df: pd.DataFrame, verbose=True, as_of=None):
        elo_map = None
        if self.use_elo:
            import elo as elomod
            elo_map, self.elo_ratings = elomod.prematch_ratings(df, as_of=as_of)
        long = datamod.build_training_frame(
            df,
            half_life_days=self.half_life_days,
            max_age_years=self.max_age_years,
            min_matches=self.min_matches,
            as_of=as_of,
            elo_map=elo_map,
            comp_weights=self.comp_weights,
        )
        self.teams = list(long["attack"].cat.categories)
        if verbose:
            print(f"[fit] {len(long):,} 行训练数据, {len(self.teams)} 支球队 ... 拟合 Poisson GLM"
                  + ("（含 Elo 外生特征）" if self.use_elo else ""))

        # Poisson GLM（带频率权重）；use_elo 时加 elo_diff 项
        formula = ("goals ~ home + elo_diff + C(attack) + C(defence)"
                   if self.use_elo else "goals ~ home + C(attack) + C(defence)")
        self.glm = smf.glm(
            formula=formula,
            data=long,
            family=sm.families.Poisson(),
            freq_weights=long["weight"].to_numpy(),
        ).fit()

        # 解析系数 -> attack / defence / 主场 / 截距
        params = self.glm.params
        self.intercept = float(params.get("Intercept", 0.0))
        self.home_adv = float(params.get("home", 0.0))
        self.elo_coef = float(params.get("elo_diff", 0.0)) if self.use_elo else 0.0
        ref = self.teams[0]  # 被 statsmodels 丢弃的参考类别，系数视为 0
        self.attack = {ref: 0.0}
        self.defence = {ref: 0.0}
        for t in self.teams[1:]:
            self.attack[t] = float(params.get(f"C(attack)[T.{t}]", 0.0))
            self.defence[t] = float(params.get(f"C(defence)[T.{t}]", 0.0))

        # 每队比赛数（用于身价收缩权重）
        self.n_matches = long[long["home"] >= 0]["attack"].value_counts().to_dict()
        # 快照纯 GLM 评级（身价收缩前），便于以不同参数廉价复算
        self.attack_raw = dict(self.attack)
        self.defence_raw = dict(self.defence)

        # 估计 Dixon-Coles 的 rho
        self._fit_rho(long, verbose=verbose)

        # 用身价做先验（默认关闭：min_market_weight=0）
        if self.min_market_weight > 0 and market.has_data():
            self._apply_market_prior(verbose=verbose)
        return self

    def reshrink(self, market_k=None, min_market_weight=None, verbose=False):
        """用新的身价收缩参数复算评级（无需重训 GLM）。回测扫参用。"""
        if market_k is not None:
            self.market_k = market_k
        if min_market_weight is not None:
            self.min_market_weight = min_market_weight
        self.attack = dict(self.attack_raw)
        self.defence = dict(self.defence_raw)
        if self.min_market_weight > 0 and market.has_data():
            self._apply_market_prior(verbose=verbose)
        return self

    def _apply_market_prior(self, verbose=True):
        """
        把攻防评级向「身价隐含评级」收缩：
          1) 在样本充足的球队上，拟合 attack~log(身价)、defence~log(身价) 的线性关系
          2) 对每队按 w=n/(n+K) 混合：数据多 -> 信自己，数据少 -> 信身价
        """
        # 始终基于纯 GLM 评级(raw)计算，保证可重复复算
        fit_t = [t for t in self.teams
                 if market.value(t) and self.n_matches.get(t, 0) >= 40]
        if len(fit_t) < 20:
            if verbose:
                print("[market] 可用于回归的球队太少，跳过身价先验")
            return
        lv = np.array([market.log_value(t) for t in fit_t])
        atk = np.array([self.attack_raw[t] for t in fit_t])
        dfc = np.array([self.defence_raw[t] for t in fit_t])
        ka, ba = np.polyfit(lv, atk, 1)   # attack  ≈ ka*log(val)+ba
        kd, bd = np.polyfit(lv, dfc, 1)   # defence ≈ kd*log(val)+bd

        K, wmin = self.market_k, self.min_market_weight
        shrunk = 0
        for t in self.teams:
            lvt = market.log_value(t)
            if lvt is None:
                continue
            n = self.n_matches.get(t, 0)
            # 身价权重：样本越少越大，但每队至少 wmin（反映当前阵容）
            w_mkt = max(1 - n / (n + K), wmin)
            self.attack[t] = (1 - w_mkt) * self.attack_raw[t] + w_mkt * (ka * lvt + ba)
            self.defence[t] = (1 - w_mkt) * self.defence_raw[t] + w_mkt * (kd * lvt + bd)
            shrunk += 1
        if verbose:
            print(f"[market] 身价先验已应用：{shrunk} 队收缩，"
                  f"attack 斜率={ka:+.3f}/log€, defence 斜率={kd:+.3f}/log€")
        return self

    def _fit_rho(self, long, verbose=True):
        """固定 GLM 系数，1 维优化 rho（只有低分格依赖它）。"""
        n = len(long) // 2
        home = long.iloc[:n]
        # 还原每场主/客 lambda 与真实比分
        lam = np.exp(self.glm.predict(long))
        lam_h = lam.iloc[:n].to_numpy()
        lam_a = lam.iloc[n:].to_numpy()
        hs = home["goals"].to_numpy()
        as_ = long.iloc[n:]["goals"].to_numpy()
        w = home["weight"].to_numpy()

        low = (hs <= 1) & (as_ <= 1)  # 只有这些场次的 tau != 1
        hi, lhi, lai, ahi, whi = hs[low], lam_h[low], lam_a[low], as_[low], w[low]

        def neg_ll(rho):
            tau = np.ones_like(lhi)
            m00 = (hi == 0) & (ahi == 0); tau[m00] = 1 - lhi[m00]*lai[m00]*rho
            m01 = (hi == 0) & (ahi == 1); tau[m01] = 1 + lhi[m01]*rho
            m10 = (hi == 1) & (ahi == 0); tau[m10] = 1 + lai[m10]*rho
            m11 = (hi == 1) & (ahi == 1); tau[m11] = 1 - rho
            tau = np.clip(tau, 1e-9, None)
            return -np.sum(whi * np.log(tau))

        res = minimize_scalar(neg_ll, bounds=(-0.2, 0.2), method="bounded")
        self.rho = float(res.x)
        if verbose:
            print(f"[fit] 完成。主场优势 exp={np.exp(self.home_adv):.3f}, rho={self.rho:+.3f}")

    # ---------- 缓存：只存预测需要的轻量系数，丢掉笨重的 GLM 对象 ----------
    def __getstate__(self):
        s = self.__dict__.copy()
        s["glm"] = None  # GLM 结果对象含完整设计矩阵(数百 MB)，预测用不到
        # 上下文层不进缓存：model.pkl 永远是纯引擎，可用性每次启动从 json 现装
        s["avail_att"] = {}; s["avail_def"] = {}
        return s

    def __setstate__(self, state):
        # 先铺默认值再覆盖：旧 pickle 缺新属性也不会崩（曾因缺 use_elo 全站 500）
        merged = {k: (dict(v) if isinstance(v, dict) else v)
                  for k, v in _STATE_DEFAULTS.items()}
        merged.update(state)
        self.__dict__.update(merged)

    # ---------- 球队名解析 ----------
    def resolve(self, name: str) -> str:
        if name in self.attack:
            return name
        # 中文 / 国旗显示串 -> 英文
        try:
            import teams_zh
            en = teams_zh.to_en(name)
            if en and en in self.attack:
                return en
        except Exception:
            pass
        # 不区分大小写精确匹配
        for t in self.teams:
            if t.lower() == name.lower():
                return t
        # 模糊匹配
        cand = difflib.get_close_matches(name, self.teams, n=3, cutoff=0.6)
        if cand:
            raise KeyError(f"未找到球队 '{name}'。你是不是指: {', '.join(cand)} ?")
        raise KeyError(f"未找到球队 '{name}'（不在训练集中，可能样本过少或拼写不同）。")

    # ---------- 预测 ----------
    def expected_goals(self, home: str, away: str, neutral: bool = True, env_mult=None,
                       avail_override=None):
        # log λ_主 = 截距 + 主场优势 + 进攻[主] + 失球[客]
        # defence 系数为负 = 防守好（对手进球少）
        h = self.resolve(home); a = self.resolve(away)
        ha = 0.0 if neutral else self.home_adv
        # Elo 外生特征项（默认关；elo_coef=0 时无影响）。__setstate__ 已保证属性存在。
        ed = 0.0
        if self.use_elo and self.elo_coef:
            ed = (self.elo_ratings.get(h, 1500.0) - self.elo_ratings.get(a, 1500.0)) / 100.0
        lam_h = np.exp(self.intercept + ha + self.attack[h] + self.defence[a] + self.elo_coef * ed)
        lam_a = np.exp(self.intercept + self.attack[a] + self.defence[h] + self.elo_coef * (-ed))
        # 可用性上下文层：自家进攻乘子 × 对手失球(def_pen)乘子。空 dict 时全 1.0 零影响。
        # avail_override（per-match，如实时首发）优先：非 None 时**只用它**、不叠加全局静态种子；
        #   传 {} 即强制纯 DC 基线（零可用性）。None 时沿用全局 set_availability（现有行为）。
        if avail_override is not None:
            aa = {t: v[0] for t, v in avail_override.items()}
            ad = {t: v[1] for t, v in avail_override.items()}
            lam_h *= aa.get(h, 1.0) * ad.get(a, 1.0)
            lam_a *= aa.get(a, 1.0) * ad.get(h, 1.0)
        elif self.avail_att or self.avail_def:
            lam_h *= self.avail_att.get(h, 1.0) * self.avail_def.get(a, 1.0)
            lam_a *= self.avail_att.get(a, 1.0) * self.avail_def.get(h, 1.0)
        # 环境上下文层：env_mult=(mult_主, mult_客)，海拔/高温对各自进攻 λ 的乘子（None=无）。
        if env_mult is not None:
            lam_h *= env_mult[0]
            lam_a *= env_mult[1]
        return h, a, lam_h, lam_a

    def _goal_pmf(self, lam):
        """单队进球分布：nb_alpha>0 用负二项(更宽尾，匹配过离散)，否则 Poisson。"""
        ks = np.arange(MAX_GOALS + 1)
        a = getattr(self, "nb_alpha", 0.0)
        if a > 0:                       # NB2 -> scipy (n=1/α, p=n/(n+μ))；α→0 即 Poisson
            n = 1.0 / a
            return nbinom.pmf(ks, n, n / (n + lam))
        return poisson.pmf(ks, lam)

    def score_matrix(self, home: str, away: str, neutral: bool = True, env_mult=None,
                     avail_override=None):
        h, a, lam_h, lam_a = self.expected_goals(home, away, neutral, env_mult, avail_override)
        ph = self._goal_pmf(lam_h)
        pa = self._goal_pmf(lam_a)
        M = np.outer(ph, pa)
        # Dixon-Coles 修正四个低分格
        for i in (0, 1):
            for j in (0, 1):
                M[i, j] *= _tau(i, j, lam_h, lam_a, self.rho)
        np.clip(M, 0.0, None, out=M)   # DC τ 修正在极端 λ 下可能产生微负格 → 截零（标准做法）。
        # 真实拟合 ρ 下四格恒非负，此截零对正常预测/回测是恒等操作；仅护住参数扰动等异常输入。
        M /= M.sum()  # 截断 + 修正后重新归一化
        return h, a, lam_h, lam_a, M

    def predict(self, home: str, away: str, neutral: bool = True, env_mult=None,
                avail_override=None):
        h, a, lam_h, lam_a, M = self.score_matrix(home, away, neutral, env_mult, avail_override)
        p_home = np.tril(M, -1).sum()   # 主队进球 > 客队
        p_draw = np.trace(M)
        p_away = np.triu(M, 1).sum()
        # 最可能比分 top
        idx = np.dstack(np.unravel_index(np.argsort(M.ravel())[::-1], M.shape))[0]
        top = [((int(i), int(j)), float(M[i, j])) for i, j in idx[:7]]
        return {
            "home": h, "away": a, "neutral": neutral,
            "xg_home": lam_h, "xg_away": lam_a,
            "p_home": float(p_home), "p_draw": float(p_draw), "p_away": float(p_away),
            "top_scores": top,
            "matrix": M,
        }

    # ---------- 实力榜（健全性检查 / 彩蛋） ----------
    def power_ranking(self, top=20):
        # 净实力 = 进攻强 - 失球少（defence 系数越负越好，故相减）
        # 仅排有身价记录的正式国家队，剔除非 FIFA / 罕赛噪声队（如 Basque Country）
        pool = [t for t in self.teams if market.value(t)] if market.has_data() else self.teams
        rows = [(t, self.attack[t] - self.defence[t]) for t in pool]
        rows.sort(key=lambda x: x[1], reverse=True)
        return rows[:top]
