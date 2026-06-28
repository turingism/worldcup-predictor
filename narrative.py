"""比赛解读文案层（只读展示）：把模型概率翻成「狂热但理性」的球迷语言。

合规铁律（个人/教育项目，**非投注建议**）：
  ① **违规词守卫** `_clean`：禁"稳赚/必中/包赢/必胜/锁定/上车/跟单"等担保或诱导下注词——
     生成器本就不产出，再加一道运行时守卫（违反即抛），并有单测遍历对阵断言永不命中。
  ② 每条文案**附"非投注建议、理性观赛"**尾注。
  ③ 只陈述**模型概率与事实**，不导购彩票、不给"出票/买入"建议、不暗示稳赢。

纯函数、无网络、无随机：同输入恒定输出，可安全缓存。
"""

# 球队昵称（仅常见强队；未收录的回退为纯国名，不影响功能）
NICK = {
    "阿根廷": "潘帕斯雄鹰", "巴西": "桑巴军团", "法国": "高卢雄鸡", "英格兰": "三狮军团",
    "西班牙": "斗牛士军团", "德国": "日耳曼战车", "葡萄牙": "五星葡萄牙", "荷兰": "橙衣军团",
    "意大利": "蓝衣军团", "比利时": "欧洲红魔", "克罗地亚": "格子军团", "乌拉圭": "天蓝军团",
    "墨西哥": "三色军团", "美国": "星条旗", "哥伦比亚": "咖啡军团", "塞内加尔": "特兰加雄狮",
    "摩洛哥": "非洲雄狮", "日本": "蓝武士", "韩国": "太极虎", "澳大利亚": "袋鼠军团",
    "瑞士": "红十字军", "丹麦": "丹麦童话", "挪威": "维京海盗", "加拿大": "枫叶军团",
    "加纳": "黑色之星", "尼日利亚": "非洲雄鹰", "喀麦隆": "非洲雄狮", "厄瓜多尔": "三色军团",
}

# 违规/担保/诱导下注词（守卫黑名单）。注意：不收"投注建议/下注建议"——它们是合规尾注
# "非投注建议"的子串，会误伤；担保/诱导语义已由下列更强的词覆盖。
_BANNED = ["稳赚", "必中", "包赢", "稳赢", "必胜", "包中", "百分百", "100%", "锁定胜局",
           "锁定胜利", "推荐下注", "跟单上车", "买它", "稳了", "无脑买", "闭眼买", "梭哈",
           "全压", "出票建议", "一键买入", "推荐购彩"]


def _clean(s: str) -> str:
    for w in _BANNED:
        if w in s:
            raise ValueError(f"解读文案含违规词「{w}」：{s}")
    return s


def _plain(disp: str) -> str:
    """去掉国旗 emoji，取中文/英文名。disp 形如「🇧🇷 巴西」→「巴西」。"""
    return disp.split(" ")[-1] if " " in disp else disp


def _with_nick(disp: str) -> str:
    """「🇧🇷 巴西」→「巴西（桑巴军团）」；无昵称则原样返回。"""
    nm = _plain(disp)
    nk = NICK.get(nm)
    return f"{disp}（{nk}）" if nk else disp


def _level(p: float) -> str:
    if p >= 0.65:
        return "大热"
    if p >= 0.50:
        return "占优"
    if p >= 0.38:
        return "略处下风"
    return "需爆冷"


TAIL = "📌 仅为模型概率推演，非投注建议，理性观赛、量力而行。"


def match_narrative(home_disp: str, away_disp: str, p_home: float, p_draw: float,
                    p_away: float, handicap: dict | None = None,
                    exp_total: float | None = None, compact: bool = False) -> str:
    """生成单场解读（一句话球迷语言 + 让球倾向 + 进球氛围 + 合规尾注）。

    compact=True：看板逐行速览用——省去每行重复的免责尾注（由调用方在解读区
    **统一展示一次** TAIL），但 `_clean` 违规词守卫照常逐行执行，红线不破。"""
    fav_home = p_home >= p_away
    fav_disp, dog_disp = (home_disp, away_disp) if fav_home else (away_disp, home_disp)
    fav_p = p_home if fav_home else p_away
    lv = _level(fav_p)

    if abs(p_home - p_away) < 0.08 and p_draw >= 0.24:
        head = (f"{_with_nick(home_disp)} 对阵 {_with_nick(away_disp)} 势均力敌，"
                f"模型胜率几乎五五开（{home_disp.split(' ')[-1]} {round(p_home*100)}% / "
                f"平 {round(p_draw*100)}% / {away_disp.split(' ')[-1]} {round(p_away*100)}%），平局风险高。")
    elif lv == "大热":
        head = (f"{_with_nick(fav_disp)} 实力明显占优，模型主导胜率约 {round(fav_p*100)}%（大热门），"
                f"{_plain(dog_disp)} 想全身而退不易——但足球场上冷门从不缺席。")
    elif lv == "占优":
        head = (f"{_with_nick(fav_disp)} 略胜一筹，模型给约 {round(fav_p*100)}% 胜率，"
                f"{_plain(dog_disp)} 仍有一搏之力，平局也在剧本里。")
    else:
        head = (f"{_with_nick(fav_disp)} 与 {_plain(dog_disp)} 谁都没拉开身位，"
                f"模型对头号选项也只给约 {round(fav_p*100)}%，是道难题。")

    # 让球倾向（接本场动态竞彩让球线，合规：只陈述概率倾向，不诱导）
    hc = ""
    if handicap:
        if handicap.get("csl_is_handicap"):
            n, vd = handicap.get("csl_line"), handicap.get("jc_verdict")
            fav_nm = _plain(fav_disp)
            hc = (f"竞彩让球本场约为 {fav_nm} 让 {n} 球，模型倾向「{vd}」"
                  f"（让球后强弱差被拉近，参考为主）。")
        else:
            hc = "双方接近，本场竞彩多为平手盘，按常规胜平负看即可。"

    goals = ""
    if exp_total is not None:
        tag = "进球大战可期" if exp_total >= 2.8 else ("闷战概率不低" if exp_total <= 2.0 else "进球数中规中矩")
        goals = f"预计总进球约 {exp_total:.1f} 球，{tag}。"

    parts = (head, hc, goals) if compact else (head, hc, goals, TAIL)
    return _clean(" ".join(x for x in parts if x))


if __name__ == "__main__":   # CLI 自测 + 合规自检
    import numpy as np
    import predict
    m = predict.get_model(True, 730, verbose=False)
    import teams_zh
    for h, a in [("Morocco", "Haiti"), ("Germany", "Ecuador"), ("Argentina", "France"),
                 ("Brazil", "Scotland"), ("Norway", "France")]:
        r = m.predict(h, a, neutral=True)
        M = r["matrix"]
        tot = float(sum((i + j) * M[i, j] for i in range(M.shape[0]) for j in range(M.shape[1])))
        import manager
        _, _, _, _, M2 = m.score_matrix(h, a, neutral=True)
        mp = manager._margin_pmf(M2)
        fav_home = r["p_home"] >= r["p_away"]
        csl = manager.csl_handicap(mp, fav_home)
        hc = {"csl_is_handicap": csl["is_handicap"], "csl_line": csl["line"], "jc_verdict": csl["verdict"]}
        s = match_narrative(teams_zh.disp(h), teams_zh.disp(a),
                            r["p_home"], r["p_draw"], r["p_away"], hc, tot)
        print(f"\n{h} vs {a}:\n  {s}")
    print("\n[narrative] 违规词守卫自检通过：以上文案均不含黑名单词。")
