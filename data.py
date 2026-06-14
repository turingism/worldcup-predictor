"""Data layer: load historical international match results and build time-weighted training data.

数据层：加载国际比赛历史结果，构建带权重的训练数据。

数据源：martj42/international_results
  https://github.com/martj42/international_results
  字段：date, home_team, away_team, home_score, away_score, tournament, city, country, neutral

世界杯预测的核心要点都在权重里：
  - 时间衰减：越近的比赛越能反映当前实力（半衰期可调）
  - 赛事权重：友谊赛强度低，下调权重
  - 中立场：世界杯多为中立场，主场优势应只给真正的主队
"""
from __future__ import annotations
import json
import os
import datetime as dt
import numpy as np
import pandas as pd

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "results.csv")
SHOOTOUTS_PATH = os.path.join(os.path.dirname(__file__), "data", "shootouts.csv")
LIVE_PATH = os.path.join(os.path.dirname(__file__), "data", "live_results.json")

# 友谊赛强度低，下调权重；正式赛事保持 1.0
FRIENDLY_WEIGHT = 0.5


def comp_tier(tournament: str) -> str:
    """赛事强度分级：friendly / qualification / major(大赛正赛) / other。
    注意 'FIFA World Cup qualification' 含 'world cup' 但应归 qualification，故先判预选。"""
    t = (tournament or "").lower()
    if "friendly" in t:
        return "friendly"
    if "qualifi" in t or "qualifier" in t:
        return "qualification"
    if any(s in t for s in ["world cup", "euro", "copa am", "african cup",
                            "asian cup", "nations league", "confederations",
                            "gold cup", "championship"]):
        return "major"
    return "other"


def _load_live_records() -> list[dict]:
    """读取 live.py 持久化的 ESPN 实时完场记录；无文件/损坏返回空。"""
    try:
        with open(LIVE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        recs = d.get("results", []) if isinstance(d, dict) else []
        return recs if isinstance(recs, list) else []
    except (FileNotFoundError, ValueError, OSError):
        return []


def load_shootouts(path: str = SHOOTOUTS_PATH) -> pd.DataFrame:
    """点球大战结果（date, home_team, away_team, winner），用于淘汰赛平局判胜者。
    文件缺失时返回空表（不影响主流程）。合并 ESPN 实时点球胜者（martj42 滞后期兜底；
    若两边都有同一场，simulate 取最后一行=实时记录，结果一致无碍）。"""
    cols = ["date", "home_team", "away_team", "winner"]
    if not os.path.exists(path):
        s = pd.DataFrame(columns=cols)
    else:
        s = pd.read_csv(path)
    live_rows = [{"date": r["date"], "home_team": r["home"], "away_team": r["away"],
                  "winner": r["winner"]}
                 for r in _load_live_records()
                 if r.get("winner") and r.get("gh") == r.get("ga")]
    if live_rows:
        s = pd.concat([s, pd.DataFrame(live_rows)], ignore_index=True)
    s["date"] = pd.to_datetime(s["date"], errors="coerce")
    return s


def merge_live(df: pd.DataFrame) -> pd.DataFrame:
    """把 ESPN 实时完场赛果合并进 df：
    - 已有同对阵的 NA 赛程行（顺序无关，日期±3天内）→ 原地填比分（保留行内 neutral/场馆）
    - 已有比分的行 → 不动（martj42 先到以它为准）
    - 找不到行（典型：淘汰赛对阵 martj42 还没建行）→ 按 ESPN 场馆信息补行；
      东道主在本国出战时放主位且 neutral=False，与训练层主场优势口径一致。"""
    recs = _load_live_records()
    if not recs:
        return df
    wc = (df["tournament"] == "FIFA World Cup") & (df["date"].dt.year >= 2026)
    appended = []
    for r in recs:
        h, a, gh, ga = r["home"], r["away"], int(r["gh"]), int(r["ga"])
        rd = pd.to_datetime(r.get("date"), errors="coerce")
        near = (df["date"] - rd).abs() <= pd.Timedelta(days=3) if pd.notna(rd) else wc
        fwd = wc & near & (df["home_team"] == h) & (df["away_team"] == a)
        rev = wc & near & (df["home_team"] == a) & (df["away_team"] == h)
        if fwd.any():
            idx = df.index[fwd & df["home_score"].isna()]
            df.loc[idx, "home_score"], df.loc[idx, "away_score"] = float(gh), float(ga)
        elif rev.any():
            idx = df.index[rev & df["home_score"].isna()]
            df.loc[idx, "home_score"], df.loc[idx, "away_score"] = float(ga), float(gh)
        else:
            country = r.get("country", "")
            if country == a:           # 东道主放主位（home 旗标喂给 GLM）
                h, a, gh, ga = a, h, ga, gh
            appended.append({"date": rd, "home_team": h, "away_team": a,
                             "home_score": float(gh), "away_score": float(ga),
                             "tournament": "FIFA World Cup",
                             "city": r.get("city", ""), "country": country,
                             "neutral": country != h})
    if appended:
        df = pd.concat([df, pd.DataFrame(appended)], ignore_index=True)
    return df


def load_raw(path: str = DATA_PATH, live: bool = True) -> pd.DataFrame:
    """读取原始 CSV，解析类型，丢掉未开赛（比分为 NA）的场次。
    live=True 时合并 ESPN 实时完场赛果（data/live_results.json）。"""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"找不到数据文件 {path}\n"
            "请先运行：python3 download_data.py"
        )
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    # 未开赛的场次 home_score/away_score 为 NA —— 正是我们最终要预测的对象
    df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce")
    df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce")
    # neutral 字段在 CSV 里是 "TRUE"/"FALSE" 字符串
    df["neutral"] = df["neutral"].astype(str).str.upper().eq("TRUE")
    if live:
        df = merge_live(df)
    return df


def played(df: pd.DataFrame) -> pd.DataFrame:
    """只保留已开赛、且日期有效的场次（用于训练）。"""
    m = df["home_score"].notna() & df["away_score"].notna() & df["date"].notna()
    return df.loc[m].copy()


def upcoming(df: pd.DataFrame, tournament: str | None = "FIFA World Cup") -> pd.DataFrame:
    """未开赛的赛程（比分为 NA），可按赛事过滤。用于批量预测真实赛程。"""
    m = df["home_score"].isna() & df["date"].notna()
    out = df.loc[m].copy()
    if tournament:
        out = out[out["tournament"].str.contains(tournament, case=False, na=False)]
    return out.sort_values("date")


def build_training_frame(
    df: pd.DataFrame,
    half_life_days: float = 547.0,   # ~1.5 年；近期比赛权重更高
    max_age_years: float = 16.0,     # 太老的比赛直接丢弃（限制规模 + 阵容已大换血）
    min_matches: int = 12,           # 样本太少的球队拟合不稳，剔除
    as_of: dt.date | None = None,
    elo_map: dict | None = None,     # {df_index:(home_elo,away_elo)} 时加 elo_diff 外生特征列
    comp_weights: dict | None = None,  # {tier:权重} 分级赛事权重；None 时沿用 友谊0.5/其余1.0
) -> pd.DataFrame:
    """
    把每场比赛拆成两行（主队视角 / 客队视角），构建长表用于 Poisson GLM。

    返回列：
      goals    —— 该视角进球数（被预测变量）
      attack   —— 进攻方（这队的进攻强度）
      defence  —— 防守方（这队的失球倾向）
      home     —— 是否享有主场优势（中立场两边都为 0）
      weight   —— 时间衰减 × 赛事强度
    """
    pl = played(df)
    if as_of is None:
        as_of = pl["date"].max().date()
    as_of_ts = pd.Timestamp(as_of)

    # 年龄过滤；as_of 之后的比赛必须剔除（负年龄=未来数据，回测时会泄漏且权重>1）
    age_days = (as_of_ts - pl["date"]).dt.days.astype(float)
    pl = pl.loc[(age_days >= 0) & (age_days <= max_age_years * 365.25)].copy()
    age_days = (as_of_ts - pl["date"]).dt.days.astype(float)

    # 权重：时间衰减（半衰期）× 赛事强度
    time_w = 0.5 ** (age_days / half_life_days)
    if comp_weights is None:
        is_friendly = pl["tournament"].str.contains("Friendly", case=False, na=False)
        comp_w = np.where(is_friendly, FRIENDLY_WEIGHT, 1.0)
    else:  # 分级赛事权重
        comp_w = pl["tournament"].map(
            lambda t: comp_weights.get(comp_tier(t), 1.0)).to_numpy()
    pl["weight"] = time_w.to_numpy() * comp_w

    # 主场优势只给真正的主队：中立场 -> home=0
    home_flag = (~pl["neutral"]).astype(int)

    home_rows = pd.DataFrame({
        "goals": pl["home_score"].astype(int).to_numpy(),
        "attack": pl["home_team"].to_numpy(),
        "defence": pl["away_team"].to_numpy(),
        "home": home_flag.to_numpy(),
        "weight": pl["weight"].to_numpy(),
    })
    away_rows = pd.DataFrame({
        "goals": pl["away_score"].astype(int).to_numpy(),
        "attack": pl["away_team"].to_numpy(),
        "defence": pl["home_team"].to_numpy(),
        "home": 0,  # 客队（或中立）无主场优势
        "weight": pl["weight"].to_numpy(),
    })
    if elo_map is not None:
        # 进攻方视角的 Elo 差（/100 缩放便于系数收敛）；客队视角取相反数
        he = np.array([elo_map.get(i, (1500.0, 1500.0))[0] for i in pl.index])
        ae = np.array([elo_map.get(i, (1500.0, 1500.0))[1] for i in pl.index])
        home_rows["elo_diff"] = (he - ae) / 100.0
        away_rows["elo_diff"] = (ae - he) / 100.0
    long = pd.concat([home_rows, away_rows], ignore_index=True)

    # 剔除样本过少的球队（按出现总场次）
    counts = pd.concat([pl["home_team"], pl["away_team"]]).value_counts()
    valid_teams = set(counts[counts >= min_matches].index)
    long = long[long["attack"].isin(valid_teams) & long["defence"].isin(valid_teams)]
    long = long.reset_index(drop=True)

    # 把球队列设为同一套 category，保证 attack/defence 参考类别一致
    teams = sorted(valid_teams)
    long["attack"] = pd.Categorical(long["attack"], categories=teams)
    long["defence"] = pd.Categorical(long["defence"], categories=teams)
    return long


if __name__ == "__main__":
    df = load_raw()
    print(f"原始场次: {len(df):,}")
    print(f"已开赛:   {len(played(df)):,}")
    long = build_training_frame(df)
    print(f"训练长表: {len(long):,} 行, {long['attack'].cat.categories.size} 支球队")
    print(f"权重范围: {long['weight'].min():.4f} ~ {long['weight'].max():.4f}")
