# -*- coding: utf-8 -*-
"""玄学占卜比分引擎（xuanxue.py）— 七法「忠实排盘」版

7 套传统术数各自实现为一个**确定性**的"比分占卜器"：
给定（主队、客队、开球时刻）→ 每个体系按其**真实排盘/起卦/起局/断卦逻辑**
吐出一个比分 + 胜负 + 一个伪"信心%"。

【起局驱动】起卦/起局**由开球时刻经 ganzhi 真正驱动**（年/日/时干支精确，
月建/月将按精确太阳黄经）。队名只进"取用 / 角色分配 / 辅助"层
（主客归属、区分同一时刻的不同对阵），不污染排盘本体。

【七法忠实度（2026-06-21 · 七 agent 深挖重写）】
  · 梅花易数：时间起卦三步(年月日%8上卦/+时%8下卦/总和%6动爻) + 体用(动爻定) + 互卦 + 变卦 + 卦气旺衰。
  · 射覆    ：梅花路线占时起卦，由卦五行生成数 × 卦气旺衰 × 动爻"射"出进球数(覆物之数)。
  · 周易    ：以数起卦得本卦 → 动爻 → 变卦；综合卦义吉凶 + 动爻爻位中正 + 体用生克 + 本卦→变卦升降。
  · 六爻    ：京房八宫定世应 + 纳甲配五行六亲 + 六兽 + 月建日辰旺衰生克 + 旬空月破冲合，世(主)/应(客)取用。
  · 奇门    ：定阴阳遁/三元/局数 → 地盘三奇六仪 → 天盘九星/八门/八神 → 值符值使 → 主(日干)/客(时干)落宫断格局旺衰。
  · 大六壬  ：月将加占时排天地盘 → 起四课 → 九宗门发三传 → 昼夜贵人布十二天将 → 日干(主)/日支(客)取用断课体。
  · 紫微    ：节气月+时辰定命宫(五虎遁定干) → 纳音起五行局 → 安紫微/紫微系/天府系十四主星 → 庙旺利陷 + 生年四化落宫，命(主)/迁(客)取用。

⚠️ 时区：开球时刻应传**球场当地时间**；给定经度+时区偏移则先校真太阳时再起局（最正统）。
⚠️ 术数无任何科学/统计依据，本模块是文化/趣味实验，禁用于赌博或任何现实决策。
   优化目标是【对传统术数排盘的忠实度】，而非预测命中率（命中率优化=灌真实先验=违背诚实定位）。
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

import ganzhi
from ganzhi import GAN, ZHI, ZHI_WX  # noqa: F401

# ── 八卦基础表 ───────────────────────────────────────────────────────────────
GUA = {1: "乾", 2: "兑", 3: "离", 4: "震", 5: "巽", 6: "坎", 7: "艮", 8: "坤"}
GUA_WX = {"乾": "金", "兑": "金", "离": "火", "震": "木",
          "巽": "木", "坎": "水", "艮": "土", "坤": "土"}
WX_SHENG = {"金": "水", "水": "木", "木": "火", "火": "土", "土": "金"}
WX_KE = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}
WX_NUM = {"水": (1, 6), "火": (2, 7), "木": (3, 8), "金": (4, 9), "土": (5, 10)}

# 十干四化（仅取在 14 主星内的；文昌/左辅等不在14主星者略）→ 紫微用
_SIHUA_RAW = {  # 干: (化禄, 化权, 化科, 化忌)
    "甲": ("廉贞", "破军", "武曲", "太阳"), "乙": ("天机", "天梁", "紫微", "太阴"),
    "丙": ("天同", "天机", "", "廉贞"), "丁": ("太阴", "天同", "天机", "巨门"),
    "戊": ("贪狼", "太阴", "", "天机"), "己": ("武曲", "贪狼", "天梁", ""),
    "庚": ("太阳", "武曲", "太阴", "天同"), "辛": ("巨门", "太阳", "", ""),
    "壬": ("天梁", "紫微", "", "武曲"), "癸": ("破军", "巨门", "太阴", "贪狼"),
}


def _sihua_map(gan: str) -> dict:
    lu, quan, ke, ji = _SIHUA_RAW.get(gan, ("", "", "", ""))
    m = {}
    for s, d in ((lu, 2), (quan, 1), (ke, 1), (ji, -2)):
        if s:
            m[s] = d
    return m


# ── 共享工具 ─────────────────────────────────────────────────────────────────
@lru_cache(maxsize=4096)
def _num(s: str) -> int:
    """队名 → 稳定正整数（用于取用层：主客归属 + 同时段不同对阵的区分）。缓存加速历史回测。"""
    return int(hashlib.sha1(s.strip().encode("utf-8")).hexdigest()[:8], 16)


def _gua(n: int) -> int:
    r = n % 8
    return r if r else 8


def _tiyong(ti_wx: str, yong_wx: str):
    """体用生克（体=主队，用=客队）→ (关系文字, winner, 体-用 强度差)。"""
    if ti_wx == yong_wx:
        return "比和（势均力敌）", "draw", 0
    if WX_SHENG[yong_wx] == ti_wx:
        return f"用生体（{yong_wx}生{ti_wx}·主得助）", "home", 3
    if WX_KE.get(ti_wx) == yong_wx:
        return f"体克用（{ti_wx}克{yong_wx}·主制客）", "home", 2
    if WX_SHENG[ti_wx] == yong_wx:
        return f"体生用（{ti_wx}生{yong_wx}·主耗泄）", "away", -2
    return f"用克体（{yong_wx}克{ti_wx}·客制主）", "away", -3


def _goals(n: int) -> int:
    table = [0, 1, 0, 2, 1, 0, 2, 1, 3, 0, 1, 2, 0, 1, 4, 2]
    return table[n % len(table)]


def _settle(h: int, a: int, winner: str):
    h, a = min(h, 5), min(a, 5)
    if winner == "home" and h <= a:
        h = a + 1
    elif winner == "away" and a <= h:
        a = h + 1
    elif winner == "draw" and h != a:
        a = h = min(h, a)
    return min(h, 6), min(a, 6)


def _conf(base: int, gap: int) -> int:
    return max(38, min(82, base + abs(gap) * 6))


def _sign_winner(x) -> str:
    return "home" if x > 0 else ("away" if x < 0 else "draw")


# ══════════════════════════════════════════════════════════════════════════════
# ===================  梅花易数 专用模块（_MH_* / _mh_*）  =====================
# ══════════════════════════════════════════════════════════════════════════════
# 八卦先天数 → 三爻二进制（自下而上 爻1,爻2,爻3；1=阳,0=阴）。
_MH_BITS = {"乾": (1, 1, 1), "兑": (1, 1, 0), "离": (1, 0, 1), "震": (1, 0, 0),
            "巽": (0, 1, 1), "坎": (0, 1, 0), "艮": (0, 0, 1), "坤": (0, 0, 0)}
_MH_BITS_INV = {v: k for k, v in _MH_BITS.items()}
# 卦气旺衰：木旺春/火旺夏/金旺秋/水旺冬/土旺四季月（以月建地支判）
_MH_WANG = {"木": {"寅", "卯"}, "火": {"巳", "午"}, "金": {"申", "酉"},
            "水": {"亥", "子"}, "土": {"辰", "戌", "丑", "未"}}
_MH_XIANG = {"火": {"寅", "卯"}, "土": {"巳", "午"}, "金": {"辰", "戌", "丑", "未"},
             "水": {"申", "酉"}, "木": {"亥", "子"}}


def _MH_norm8(x):
    return ((x - 1) % 8) + 1


def _MH_norm6(x):
    return ((x - 1) % 6) + 1


def _MH_bits_name(bits):
    return _MH_BITS_INV[tuple(bits)]


def _MH_hu(y):
    """互卦：下互=2,3,4 爻，上互=3,4,5 爻（y 自下而上 index 0..5）。返回(上,下)。"""
    return _MH_bits_name((y[2], y[3], y[4])), _MH_bits_name((y[1], y[2], y[3]))


def _MH_bian(y, moving):
    """变卦：动爻阴阳互换，其余不动。返回(上,下)。"""
    yy = y[:]
    yy[moving - 1] ^= 1
    return _MH_bits_name(tuple(yy[3:6])), _MH_bits_name(tuple(yy[0:3]))


def _MH_rel_to_ti(ti_wx, other_wx):
    """他卦对体卦生克：+1 生体、-1 克体、0 无涉。"""
    if WX_SHENG[other_wx] == ti_wx:
        return 1
    if WX_KE.get(other_wx) == ti_wx:
        return -1
    return 0


def _MH_wangshuai(ti_wx, jian):
    """体卦旺衰（以月建判卦气）→ (调节值, 文字)。旺+2 相+1 休0 囚/死-1。"""
    if jian in _MH_WANG.get(ti_wx, set()):
        return 2, "旺"
    if jian in _MH_XIANG.get(ti_wx, set()):
        return 1, "相"
    jian_wx = ZHI_WX[jian]
    if WX_KE.get(ti_wx) == jian_wx:
        return -1, "囚"
    if WX_SHENG[ti_wx] == jian_wx:
        return 0, "休"
    if WX_KE.get(jian_wx) == ti_wx:
        return -1, "死"
    return 0, "平"


def _MH_tiyong_rel(ti_wx, yong_wx):
    """体用生克五判 → (关系文字, base 分, 倾向)。体宜旺宜得生。"""
    if ti_wx == yong_wx:
        return "比和", 0, "draw"
    if WX_SHENG[yong_wx] == ti_wx:
        return f"用生体({yong_wx}生{ti_wx})", 3, "home"
    if WX_KE.get(ti_wx) == yong_wx:
        return f"体克用({ti_wx}克{yong_wx})", 1, "home"
    if WX_SHENG[ti_wx] == yong_wx:
        return f"体生用({ti_wx}泄于{yong_wx})", -1, "away"
    return f"用克体({yong_wx}克{ti_wx})", -2, "away"


def m_meihua(nh, na, P):
    """梅花易数（正统时间起卦法，三步起卦 + 互卦/变卦/旺衰断卦）。
    起卦【纯由开球时刻干支驱动】：上卦=(年支数+月数+日数)%8、下卦=+时支数%8、
    动爻=+时支数%6（皆0取满）。队名【仅取用层】定主/客占体之归属，不入起卦数。
    本卦→互卦(2345爻)→变卦(动爻变)；动爻所在之卦为用、不动之卦为体。
    断卦=体用生克(纲)+互卦对体生克(过程)+变卦对体生克(结果)+体卦旺衰(卦气)。"""
    # 1. 时间数（年支/月建/日支/时支，0→满）
    yr = P["year_zi"] + 1
    mo = ganzhi.ZHI.index(P["month_jian"]) + 1
    dy = P["day_zi"] + 1
    hr = P["hour_zi"] + 1
    upper_n = _MH_norm8(yr + mo + dy)
    lower_n = _MH_norm8(yr + mo + dy + hr)
    moving = _MH_norm6(yr + mo + dy + hr)
    upper, lower = GUA[upper_n], GUA[lower_n]
    y = list(_MH_BITS[lower]) + list(_MH_BITS[upper])   # 六爻自下而上

    # 2. 体用（动爻所在之卦为用，另一为体）
    if moving in (1, 2, 3):
        yong_gua, ti_gua, ti_pos = lower, upper, "上"
        yong_gua_n, ti_gua_n = lower_n, upper_n
    else:
        yong_gua, ti_gua, ti_pos = upper, lower, "下"
        yong_gua_n, ti_gua_n = upper_n, lower_n

    # 3. 主客归属（取用层）：队名 hash 奇偶确定性决定哪边占体（体宜得位）
    home_is_ti = ((nh ^ na) & 1) == 0
    ti_wx, yong_wx = GUA_WX[ti_gua], GUA_WX[yong_gua]

    # 4. 体用生克（总纲）
    rel, base, _ = _MH_tiyong_rel(ti_wx, yong_wx)

    # 5. 互卦/变卦对体生克 + 体卦旺衰
    hu_u, hu_l = _MH_hu(y)
    bi_u, bi_l = _MH_bian(y, moving)
    hu_adj = _MH_rel_to_ti(ti_wx, GUA_WX[hu_u]) + _MH_rel_to_ti(ti_wx, GUA_WX[hu_l])
    bian_other = bi_u if ti_pos == "上" else bi_l       # 变卦中体所在位
    bian_adj = _MH_rel_to_ti(ti_wx, GUA_WX[bian_other])
    ws_adj, ws_txt = _MH_wangshuai(ti_wx, P["month_jian"])

    # 6. 体势（>0 体强）→ 映射主客
    ti_total = base + hu_adj + bian_adj + ws_adj
    margin = ti_total if home_is_ti else -ti_total
    winner = "home" if margin >= 2 else ("away" if margin <= -2 else "draw")

    # 7. 比分（卦先天数 + 强弱偏置；与胜负自洽）
    ti_goals = ti_gua_n % 4 + (1 if moving % 2 else 0) + max(ti_total // 2, 0)
    yong_goals = yong_gua_n % 4 + max(-ti_total // 2, 0)
    hg, ag = (ti_goals, yong_goals) if home_is_ti else (yong_goals, ti_goals)
    h, a = _settle(hg, ag, winner)

    side = "主" if home_is_ti else "客"
    detail = (f"时间起卦 上卦{upper}/下卦{lower}·动爻{moving} → 本卦{upper}{lower}"
              f"｜互卦{hu_u}{hu_l}·变卦{bi_u}{bi_l}"
              f"｜体卦{ti_gua}({ti_wx},{ws_txt})={side}队/用卦{yong_gua}({yong_wx})·{rel}"
              f"｜体势{ti_total:+d}（{P['year_gz']}年{P['month_jian']}月{P['day_gz']}日{P['hour_zhi']}时）")
    return {"key": "meihua", "name": "梅花易数", "icon": "🌸", "score": [h, a],
            "winner": winner, "confidence": _conf(50, margin),
            "detail": detail}


# ══════════════════════════════════════════════════════════════════════════════
# ===========================  射覆 专用模块（_sf_*）  =========================
# ══════════════════════════════════════════════════════════════════════════════
def _sf_wangshuai(gua_wx, yue_wx):
    """卦气旺衰：本卦五行相对月令五行 → (档位, 修正值 +2旺/+1相/0休/-1囚/-2死)。"""
    if gua_wx == yue_wx:
        return "旺", 2                       # 同气当令
    if WX_SHENG[yue_wx] == gua_wx:
        return "相", 1                       # 月令生我=受生而相
    if WX_SHENG[gua_wx] == yue_wx:
        return "休", 0                       # 我生月令=泄出而休
    if WX_KE[gua_wx] == yue_wx:
        return "囚", -1                      # 我克月令=耗力
    return "死", -2                          # 月令克我=受制


def _sf_shoot(gua_wx, ws, yao):
    """由五行生成数射数目：旺衰把取数重心从生数(失令)移向成数(得令)，
    动爻在重心 ±1 内做确定性落点，折算 0..5 进球。"""
    sheng, cheng = WX_NUM[gua_wx]            # 生数(小)、成数(大)
    pos = (ws + 2) / 4.0                      # 失令→0(取生数) 得令→1(取成数)
    center = sheng + (cheng - sheng) * pos    # 取数重心
    adj = ((yao - 1) % 3) - 1                # 动爻段内微调 -1/0/+1
    return max(0, (int(round(center)) + adj) % 6)


def _sf_tiyong(ti_wx, yong_wx):
    """体用生克(体=主卦, 用=客卦) → (关系, winner, gap)。"""
    if ti_wx == yong_wx:
        return "比和(势均)", "draw", 0
    if WX_SHENG[yong_wx] == ti_wx:
        return f"用生体({yong_wx}生{ti_wx}·主得生)", "home", 3
    if WX_KE.get(ti_wx) == yong_wx:
        return f"体克用({ti_wx}克{yong_wx}·主制客)", "home", 2
    if WX_SHENG[ti_wx] == yong_wx:
        return f"体生用({ti_wx}生{yong_wx}·主泄气)", "away", -2
    return f"用克体({yong_wx}克{ti_wx}·客制主)", "away", -3


def m_shefu(nh, na, P):
    """射覆(梅花易数路线)：占时(开球干支)真正起卦得体用→据卦五行生成数 ×
    卦气旺衰 × 体用生克，直"射"两队进球数(覆物之数)与谁胜(覆物之势)。

    占时起卦：上卦=(年支+月支+日支)数%8(客·外)，下卦=上卦数+时支数%8(主·内)，
    动爻=(上下卦数+时支)%6。主取下卦(内/本体)为体、客取上卦(外/所测)为用；
    队名仅作 %8 微扰区分同一开球时刻的不同对阵(不改卦气、不灌实力先验)。"""
    yz, mz, dz, hz = P["year_zi"], P["month_jian_i"], P["day_zi"], P["hour_zi"]
    up_n = (yz + 1) + (mz + 1) + (dz + 1)
    dn_n = up_n + (hz + 1)
    g_up = _gua(up_n + (na % 8))             # 上卦(客·外)
    g_dn = _gua(dn_n + (nh % 8))             # 下卦(主·内)
    yao = (g_up + g_dn + hz) % 6 or 6

    gua_up, gua_dn = GUA[g_up], GUA[g_dn]
    wx_dn, wx_up = GUA_WX[gua_dn], GUA_WX[gua_up]   # 主=下卦, 客=上卦
    yue_wx = ZHI_WX[P["month_jian"]]

    ws_h_t, ws_h = _sf_wangshuai(wx_dn, yue_wx)
    ws_a_t, ws_a = _sf_wangshuai(wx_up, yue_wx)

    h = _sf_shoot(wx_dn, ws_h, yao)
    a = _sf_shoot(wx_up, ws_a, yao)

    rel, winner, gap = _sf_tiyong(wx_dn, wx_up)
    ws_gap = ws_h - ws_a
    if winner == "draw" and ws_gap != 0:                 # 比和则旺衰分高下
        winner = "home" if ws_gap > 0 else "away"
        rel += f"·旺衰分高下({ws_h_t}vs{ws_a_t})"

    h, a = _settle(h, a, winner)
    ch = WX_NUM[wx_dn][1]
    ca = WX_NUM[wx_up][1]
    detail = (f"{P['hour_zhi']}时占时起卦·上卦{gua_up}(客{wx_up})/下卦{gua_dn}(主{wx_dn})"
              f"·动爻{yao}｜主{wx_dn}成数{ch}·{ws_h_t}令→射{h}球"
              f"｜客{wx_up}成数{ca}·{ws_a_t}令→射{a}球｜{rel}")
    return {"key": "shefu", "name": "射覆", "icon": "🎯", "score": [h, a],
            "winner": winner, "confidence": _conf(44, gap + ws_gap), "detail": detail}


# ══════════════════════════════════════════════════════════════════════════════
# ===================  周易·六十四卦 专用模块（_YJ_* / _yj_*）  ================
# ══════════════════════════════════════════════════════════════════════════════
# 经卦三爻二进制(下→中→上, 阳=1)：拼六爻 / 求变卦 / 互综错卦
_YJ_BIN = {"乾": "111", "兑": "110", "离": "101", "震": "100",
           "巽": "011", "坎": "010", "艮": "001", "坤": "000"}
_YJ_BIN_INV = {v: k for k, v in _YJ_BIN.items()}

# (上卦, 下卦) → (通行本序号, 卦名)。
_YJ_HEX = {
    ("乾", "乾"): (1, "乾"), ("坤", "坤"): (2, "坤"), ("坎", "震"): (3, "屯"),
    ("艮", "坎"): (4, "蒙"), ("坎", "乾"): (5, "需"), ("乾", "坎"): (6, "讼"),
    ("坤", "坎"): (7, "师"), ("坎", "坤"): (8, "比"), ("巽", "乾"): (9, "小畜"),
    ("乾", "兑"): (10, "履"), ("坤", "乾"): (11, "泰"), ("乾", "坤"): (12, "否"),
    ("乾", "离"): (13, "同人"), ("离", "乾"): (14, "大有"), ("坤", "艮"): (15, "谦"),
    ("震", "坤"): (16, "豫"), ("兑", "震"): (17, "随"), ("艮", "巽"): (18, "蛊"),
    ("坤", "兑"): (19, "临"), ("巽", "坤"): (20, "观"), ("离", "震"): (21, "噬嗑"),
    ("艮", "离"): (22, "贲"), ("艮", "坤"): (23, "剥"), ("坤", "震"): (24, "复"),
    ("乾", "震"): (25, "无妄"), ("艮", "乾"): (26, "大畜"), ("艮", "震"): (27, "颐"),
    ("兑", "巽"): (28, "大过"), ("坎", "坎"): (29, "坎"), ("离", "离"): (30, "离"),
    ("兑", "艮"): (31, "咸"), ("震", "巽"): (32, "恒"), ("乾", "艮"): (33, "遯"),
    ("震", "乾"): (34, "大壮"), ("离", "坤"): (35, "晋"), ("坤", "离"): (36, "明夷"),
    ("巽", "离"): (37, "家人"), ("离", "兑"): (38, "睽"), ("坎", "艮"): (39, "蹇"),
    ("震", "坎"): (40, "解"), ("艮", "兑"): (41, "损"), ("巽", "震"): (42, "益"),
    ("兑", "乾"): (43, "夬"), ("乾", "巽"): (44, "姤"), ("兑", "坤"): (45, "萃"),
    ("坤", "巽"): (46, "升"), ("兑", "坎"): (47, "困"), ("坎", "巽"): (48, "井"),
    ("兑", "离"): (49, "革"), ("离", "巽"): (50, "鼎"), ("震", "震"): (51, "震"),
    ("艮", "艮"): (52, "艮"), ("巽", "艮"): (53, "渐"), ("震", "兑"): (54, "归妹"),
    ("震", "离"): (55, "丰"), ("离", "艮"): (56, "旅"), ("巽", "巽"): (57, "巽"),
    ("兑", "兑"): (58, "兑"), ("巽", "坎"): (59, "涣"), ("坎", "兑"): (60, "节"),
    ("巽", "兑"): (61, "中孚"), ("震", "艮"): (62, "小过"), ("坎", "离"): (63, "既济"),
    ("离", "坎"): (64, "未济"),
}

# 64 卦卦义吉凶 auspice(-2 大凶 … +2 大吉)
_YJ_AUSPICE = {
    "乾": 2, "坤": 0, "屯": -1, "蒙": 0, "需": 1, "讼": -2, "师": 1, "比": 1,
    "小畜": 0, "履": 1, "泰": 2, "否": -2, "同人": 1, "大有": 2, "谦": 2, "豫": 1,
    "随": 1, "蛊": 0, "临": 2, "观": 0, "噬嗑": 1, "贲": 0, "剥": -2, "复": 1,
    "无妄": 0, "大畜": 2, "颐": 0, "大过": -1, "坎": -2, "离": 1,
    "咸": 2, "恒": 1, "遯": -1, "大壮": 1, "晋": 2, "明夷": -1, "家人": 1, "睽": -1,
    "蹇": -2, "解": 1, "损": 0, "益": 2, "夬": 1, "姤": -1, "萃": 1, "升": 2,
    "困": -2, "井": 0, "革": 1, "鼎": 2, "震": 0, "艮": 0, "渐": 1, "归妹": -1,
    "丰": 1, "旅": -1, "巽": 0, "兑": 1, "涣": 0, "节": 0, "中孚": 1, "小过": -1,
    "既济": 0, "未济": 0,
}

# "相持/缠斗"之卦：胜负胶着，提高平局倾向
_YJ_DRAW = {"既济", "未济", "坎", "节", "恒", "蒙", "讼"}


def _yj_yao_luck(line_is_yang: bool, pos: int) -> int:
    """动爻吉凶按【爻位法理】程序化生成：得中/中正/当位/上穷。
    pos:1..6 自下而上；line_is_yang:该爻是否阳爻。返回 -2..+2。"""
    luck = 0
    if pos in (2, 5):                       # 得中
        luck += 1
        if (pos == 5 and line_is_yang) or (pos == 2 and not line_is_yang):
            luck += 1                       # 中正(五阳/二阴)
    odd = pos % 2 == 1
    luck += 1 if line_is_yang == odd else -1   # 当位/失位
    if pos == 6:                            # 上爻"亢/穷"
        luck -= 1
    return max(-2, min(2, luck))


def m_yijing(nh, na, P):
    """周易·六十四卦：以数起卦(时间起卦法)+卦义/爻辞/体用综合断卦。
    上卦数=(年支+月建+日序)%8、下卦数=(上卦和+时支)%8、动爻=总和%6；
    主=下卦(内/主场)、客=上卦(外)，队名仅进取用层。本卦→动爻→变卦，
    综合【本卦卦义 + 动爻爻位吉凶 + 体用五行生克 + 本卦→变卦升降】判胜负。"""
    yz, mj, di, hz = P["year_zi"], P["month_jian_i"], P["day_i"], P["hour_zi"]
    up_sum = yz + mj + di + na           # 上卦取数(客入取用)
    lo_sum = up_sum + hz + nh            # 下卦取数(主入取用)
    g_up, g_lo = up_sum % 8 or 8, lo_sum % 8 or 8
    upper, lower = GUA[g_up], GUA[g_lo]
    moving = (up_sum + lo_sum) % 6 or 6  # 动爻位 1..6
    hexid, hexname = _YJ_HEX[(upper, lower)]

    # 本卦六爻(下→上) & 变卦
    bits = [int(b) for b in (_YJ_BIN[lower] + _YJ_BIN[upper])]
    line_yang = bits[moving - 1] == 1
    bits2 = bits[:]; bits2[moving - 1] ^= 1
    lo2 = _YJ_BIN_INV["".join(map(str, bits2[:3]))]
    up2 = _YJ_BIN_INV["".join(map(str, bits2[3:]))]
    bid, bname = _YJ_HEX[(up2, lo2)]

    # 体用：动爻所在卦为"用"，不动者为"体"；主=下卦
    move_in_lower = moving <= 3
    ti_wx = GUA_WX[upper] if move_in_lower else GUA_WX[lower]
    yong_wx = GUA_WX[lower] if move_in_lower else GUA_WX[upper]
    ti_is_home = not move_in_lower
    if ti_wx == yong_wx:
        ty_score, ty_txt = 0, "比和"
    elif WX_SHENG[yong_wx] == ti_wx:
        ty_score, ty_txt = 2, f"用生体({yong_wx}生{ti_wx})"
    elif WX_KE.get(ti_wx) == yong_wx:
        ty_score, ty_txt = 1, f"体克用({ti_wx}克{yong_wx})"
    elif WX_SHENG[ti_wx] == yong_wx:
        ty_score, ty_txt = -2, f"体生用({ti_wx}生{yong_wx}泄)"
    else:
        ty_score, ty_txt = -3, f"用克体({yong_wx}克{ti_wx})"
    ty_home = ty_score if ti_is_home else -ty_score

    # 卦义吉凶 + 本卦→变卦升降(利主动方=主)
    aus, aus2 = _YJ_AUSPICE[hexname], _YJ_AUSPICE[bname]
    trend = aus2 - aus
    gua_home = aus + (1 if trend > 0 else (-1 if trend < 0 else 0))

    # 动爻爻位吉凶(利动爻所在一方)
    yao_luck = _yj_yao_luck(line_yang, moving)
    yao_home = yao_luck if move_in_lower else -yao_luck

    total = ty_home + gua_home + yao_home
    if hexname in _YJ_DRAW and abs(total) <= 1:
        total = 0
    winner = _sign_winner(total)

    # 比分：八卦五行成数 + 动爻所在卦关键进球 + 君位决定性球
    base_h = WX_NUM[GUA_WX[lower]][di % 2]
    base_a = WX_NUM[GUA_WX[upper]][hz % 2]
    h, a = base_h % 4, base_a % 4
    if move_in_lower:
        h += 1
    else:
        a += 1
    if moving == 5:
        if winner == "home":
            h += 1
        elif winner == "away":
            a += 1
    h, a = _settle(h, a, winner)

    yname = ("九" if line_yang else "六") + "初二三四五上"[moving - 1]
    detail = (f"{P['year_gz']}年{P['day_gz']}日{P['hour_zhi']}时起卦→"
              f"本卦【{hexname}】(上{upper}客/下{lower}主) {yname}动→变【{bname}】｜"
              f"{ty_txt}({'体=主' if ti_is_home else '体=客'})·"
              f"卦义{aus:+d}→{aus2:+d}·爻位{yao_luck:+d}")
    return {"key": "yijing", "name": "周易·六十四卦", "icon": "☯",
            "score": [h, a], "winner": winner, "confidence": _conf(48, total),
            "detail": detail}


# ══════════════════════════════════════════════════════════════════════════════
# ====================  六爻纳甲 专用模块（_LY_* / _ly_*）  ====================
# ══════════════════════════════════════════════════════════════════════════════
_LY_PALACE_WX = {"乾": "金", "坎": "水", "艮": "土", "震": "木",
                 "巽": "木", "离": "火", "坤": "土", "兑": "金"}
_LY_TRIGRAM_LINES = {  # 八卦三爻阴阳(初→上, 1阳0阴)
    "乾": (1, 1, 1), "兑": (1, 1, 0), "离": (1, 0, 1), "震": (1, 0, 0),
    "巽": (0, 1, 1), "坎": (0, 1, 0), "艮": (0, 0, 1), "坤": (0, 0, 0),
}
_LY_TRIGRAM_INNER = {  # 纳支·内卦三爻(初中上)，纳甲口诀(阳顺阴逆)
    "乾": ("子", "寅", "辰"), "坎": ("寅", "辰", "午"), "艮": ("辰", "午", "申"),
    "震": ("子", "寅", "辰"), "巽": ("丑", "亥", "酉"), "离": ("卯", "丑", "亥"),
    "坤": ("未", "巳", "卯"), "兑": ("巳", "卯", "丑"),
}
_LY_TRIGRAM_OUTER = {  # 纳支·外卦三爻(四五上)
    "乾": ("午", "申", "戌"), "坎": ("申", "戌", "子"), "艮": ("戌", "子", "寅"),
    "震": ("午", "申", "戌"), "巽": ("未", "巳", "卯"), "离": ("酉", "未", "巳"),
    "坤": ("丑", "亥", "酉"), "兑": ("亥", "酉", "未"),
}
_LY_LINES_TO_TRIGRAM = {v: k for k, v in _LY_TRIGRAM_LINES.items()}
_LY_WORLD_RESP = {"本宫": (6, 3), "一世": (1, 4), "二世": (2, 5), "三世": (3, 6),
                  "四世": (4, 1), "五世": (5, 2), "游魂": (4, 1), "归魂": (3, 6)}
_LY_SHEN = ["青龙", "朱雀", "勾陈", "螣蛇", "白虎", "玄武"]
_LY_SHEN_START = {0: 0, 1: 0, 2: 1, 3: 1, 4: 2, 5: 3, 6: 4, 7: 4, 8: 5, 9: 5}  # 日干→初爻六神
_LY_LIUHE = {(0, 1), (2, 11), (3, 10), (4, 9), (5, 8), (6, 7)}
_LY_LIUCHONG = {(0, 6), (1, 7), (2, 8), (3, 9), (4, 10), (5, 11)}


def _ly_build_palaces():
    """京房八宫：每宫由本宫卦按变爻规律生成八卦(本宫→五世→游魂→归魂)。"""
    order = ["本宫", "一世", "二世", "三世", "四世", "五世", "游魂", "归魂"]
    palaces = {}
    for pure in _LY_TRIGRAM_LINES:
        lines = list(_LY_TRIGRAM_LINES[pure]) * 2
        seq = [lines[:]]
        cur = lines[:]
        for i in range(5):                      # 一~五世：依次变初二三四五爻
            cur = cur[:]; cur[i] ^= 1; seq.append(cur[:])
        gh = seq[5][:]; gh[3] ^= 1; seq.append(gh)         # 游魂：四爻回变
        gui = gh[:]
        for i in range(3):
            gui[i] ^= 1                          # 归魂：内卦三爻全变回
        seq.append(gui)
        palaces[pure] = seq
    return palaces, order


_LY_PALACE_SEQ, _LY_RANK_ORDER = _ly_build_palaces()


def _ly_xunkong(day_gi, day_zi):
    """日柱(干index,支index) → 该旬两空亡地支index。"""
    head = (day_zi - day_gi) % 12
    return {(head + 10) % 12, (head + 11) % 12}


def _ly_pair_in(a, b, table):
    return (min(a, b), max(a, b)) in {(min(x, y), max(x, y)) for x, y in table}


def _ly_wang(yao_wx, yue_wx):
    """旺相休囚死(以月令)。"""
    if yao_wx == yue_wx:
        return 2.0
    if WX_SHENG[yue_wx] == yao_wx:
        return 1.4
    if WX_SHENG[yao_wx] == yue_wx:
        return 0.6
    if WX_KE[yao_wx] == yue_wx:
        return 0.3
    return 0.1


def _ly_liuqin(yao_wx, palace_wx):
    if yao_wx == palace_wx:
        return "兄弟"
    if WX_SHENG[palace_wx] == yao_wx:
        return "子孙"
    if WX_KE[palace_wx] == yao_wx:
        return "妻财"
    if WX_SHENG[yao_wx] == palace_wx:
        return "父母"
    return "官鬼"


def m_liuyao(nh, na, P):
    """六爻纳甲（忠实版）：开球干支起本卦 → 京房八宫定世应 → 纳甲配六亲 →
    起六兽 → 月建/日辰定旺衰生克 → 取世应用神(世=主/应=客, 子孙福神/官鬼对手) →
    旬空月破冲合修正 → 断主客强弱。确定性，不读赛果，不灌实力先验。"""
    g_low = (nh + P["day_zi"]) % 8 or 8
    g_up = (na + P["day_zi"]) % 8 or 8
    moving = (g_low + g_up + P["hour_zi"]) % 6 or 6
    lower, upper = GUA[g_low], GUA[g_up]
    lines = list(_LY_TRIGRAM_LINES[lower]) + list(_LY_TRIGRAM_LINES[upper])

    pure_low = _LY_LINES_TO_TRIGRAM[tuple(lines[0:3])]
    pure_up = _LY_LINES_TO_TRIGRAM[tuple(lines[3:6])]
    palace = rank = None
    for pl in _LY_PALACE_SEQ:
        for ri, hexa in enumerate(_LY_PALACE_SEQ[pl]):
            if hexa == lines:
                palace, rank = pl, _LY_RANK_ORDER[ri]; break
        if palace:
            break
    palace_wx = _LY_PALACE_WX[palace]
    w_pos, y_pos = _LY_WORLD_RESP[rank]

    branches = list(_LY_TRIGRAM_INNER[pure_low]) + list(_LY_TRIGRAM_OUTER[pure_up])
    shen_start = _LY_SHEN_START[P["day_gi"]]
    yao = []
    for i in range(6):
        zhi = branches[i]; wx = ZHI_WX[zhi]
        yao.append({"pos": i + 1, "zhi": zhi, "zi": ZHI.index(zhi), "wx": wx,
                    "qin": _ly_liuqin(wx, palace_wx),
                    "shen": _LY_SHEN[(shen_start + i) % 6],
                    "moving": (i + 1) == moving})

    yue_wx = ZHI_WX[P["month_jian"]]
    yue_zi = ZHI.index(P["month_jian"])
    day_zi = P["day_zi"]
    day_wx = ZHI_WX[ZHI[day_zi]]
    kong = _ly_xunkong(P["day_gi"], day_zi)

    def strength(y):
        wx, zi = y["wx"], y["zi"]
        s = _ly_wang(wx, yue_wx); notes = []
        if WX_SHENG[yue_wx] == wx:
            s += 0.4; notes.append("月生")
        elif WX_KE[yue_wx] == wx:
            s -= 0.4; notes.append("月克")
        if _ly_pair_in(zi, yue_zi, _LY_LIUCHONG):
            s -= 0.8; notes.append("月破")
        if day_wx == wx:
            s += 0.5; notes.append("日临")
        elif WX_SHENG[day_wx] == wx:
            s += 0.5; notes.append("日生")
        elif WX_KE[day_wx] == wx:
            s -= 0.6; notes.append("日克")
        if _ly_pair_in(zi, day_zi, _LY_LIUHE):
            s += 0.2; notes.append("日合")
        day_chong = _ly_pair_in(zi, day_zi, _LY_LIUCHONG)
        if day_chong:
            notes.append("日冲")
        if zi in kong:
            if day_chong:
                s += 0.3; notes.append("冲空填实")
            else:
                s -= 0.7; notes.append("旬空")
        elif day_chong and not y["moving"]:
            s += 0.3; notes.append("暗动")
        if y["moving"]:
            s += 0.4; notes.append("动")
        y["notes"] = notes
        return s

    for y in yao:
        y["s"] = strength(y)
    shi, ying = yao[w_pos - 1], yao[y_pos - 1]

    sun = [y for y in yao if y["qin"] == "子孙"]
    gui = [y for y in yao if y["qin"] == "官鬼"]
    sun_s = max((y["s"] for y in sun), default=0.0)
    gui_s = max((y["s"] for y in gui), default=0.0)

    rel_adj = 0.0; sw, yw = shi["wx"], ying["wx"]
    if sw == yw:
        rel_txt = "世应比和(势均)"
    elif WX_SHENG[yw] == sw:
        rel_adj += 0.6; rel_txt = f"应生世({yw}生{sw}·主得助)"
    elif WX_KE.get(sw) == yw:
        rel_adj += 0.5; rel_txt = f"世克应({sw}克{yw}·主制客)"
    elif WX_SHENG[sw] == yw:
        rel_adj -= 0.5; rel_txt = f"世生应({sw}生{yw}·主泄气)"
    else:
        rel_adj -= 0.6; rel_txt = f"应克世({yw}克{sw}·客占优)"

    sy_chong = _ly_pair_in(shi["zi"], ying["zi"], _LY_LIUCHONG)
    sy_he = _ly_pair_in(shi["zi"], ying["zi"], _LY_LIUHE)

    D = (shi["s"] - ying["s"]) + rel_adj + 0.3 * (sun_s - gui_s)
    TH = 0.6
    winner = "home" if D > TH else ("away" if D < -TH else "draw")

    def lam(y):
        return max(0.0, min(5.0, y["s"] * 1.15))
    lh, la = lam(shi), lam(ying)
    n_moving = sum(1 for y in yao if y["moving"])
    move_bump = 0.4 if n_moving >= 2 else (0.0 if n_moving == 1 else -0.3)
    lh += move_bump; la += move_bump

    def shen_bump(y):
        return {"白虎": 0.5, "青龙": 0.2, "朱雀": 0.1, "玄武": -0.3,
                "螣蛇": -0.1, "勾陈": -0.2}.get(y["shen"], 0.0)
    lh += shen_bump(shi); la += shen_bump(ying)
    if shi["zi"] in kong and not _ly_pair_in(shi["zi"], day_zi, _LY_LIUCHONG):
        lh -= 1.0
    if ying["zi"] in kong and not _ly_pair_in(ying["zi"], day_zi, _LY_LIUCHONG):
        la -= 1.0
    if sy_chong:
        lh += 0.4; la += 0.4
    elif sy_he:
        lh -= 0.4; la -= 0.4

    h = max(0, min(5, round(lh))); a = max(0, min(5, round(la)))
    h, a = _settle(h, a, winner)
    if winner == "draw" and sy_he:
        h = a = min(h, a)
    conf = _conf(46, int(round(D * 4)))

    kong_txt = "/".join(ZHI[k] for k in sorted(kong))
    ssun = "无" if not sun else sun[0]["zhi"] + sun[0]["wx"]
    sgui = "无" if not gui else gui[0]["zhi"] + gui[0]["wx"]
    detail = (
        f"{palace}宫{rank}·{P['day_gz']}日(旬空{kong_txt})·月建{P['month_jian']}({yue_wx})｜"
        f"世{shi['shen']}{shi['qin']}{shi['zhi']}{shi['wx']}(主"
        f"{'·'.join(shi['notes']) if shi['notes'] else ''})"
        f"/应{ying['shen']}{ying['qin']}{ying['zhi']}{ying['wx']}(客"
        f"{'·'.join(ying['notes']) if ying['notes'] else ''})｜"
        f"{rel_txt}·子孙{ssun}·官鬼{sgui}"
        f"{'·世应六冲(激烈)' if sy_chong else ('·世应六合(胶着)' if sy_he else '')}"
        f"·动爻{n_moving} → {'主旺' if D > TH else '客旺' if D < -TH else '势均'}(D={D:+.2f})")
    return {"key": "liuyao", "name": "六爻纳甲", "icon": "🪙", "score": [h, a],
            "winner": winner, "confidence": conf, "detail": detail}


# ══════════════════════════════════════════════════════════════════════════════
# ===================  奇门遁甲 专用模块（_QM_* / _qm_*）  =====================
# ══════════════════════════════════════════════════════════════════════════════
_QM_PALACE_WX = {1: "水", 2: "土", 3: "木", 4: "木", 5: "土",
                 6: "金", 7: "金", 8: "土", 9: "火"}
_QM_RING = [1, 8, 3, 4, 9, 2, 7, 6]            # 转盘环；中5寄坤2
_QM_STAR_HOME = {1: "天蓬", 8: "天任", 3: "天冲", 4: "天辅",
                 9: "天英", 2: "天芮", 7: "天柱", 6: "天心", 5: "天禽"}
_QM_STAR_LUCK = {"天蓬": -1, "天任": 1, "天冲": 0.5, "天辅": 1, "天英": -0.5,
                 "天芮": -2, "天柱": -1, "天心": 2, "天禽": 1}
_QM_GATE_HOME = {1: "休门", 8: "生门", 3: "伤门", 4: "杜门",
                 9: "景门", 2: "死门", 7: "惊门", 6: "开门"}
_QM_GATE_ORDER = ["休门", "生门", "伤门", "杜门", "景门", "死门", "惊门", "开门"]
_QM_GATE_WX = {"休门": "水", "生门": "土", "伤门": "木", "杜门": "木",
               "景门": "火", "死门": "土", "惊门": "金", "开门": "金"}
_QM_GATE_LUCK = {"休门": 1, "生门": 2, "伤门": -1, "杜门": 0,
                 "景门": 0.5, "死门": -2, "惊门": -1, "开门": 2}
_QM_SPIRIT_ORDER = ["值符", "螣蛇", "太阴", "六合", "白虎", "玄武", "九地", "九天"]
_QM_SPIRIT_LUCK = {"值符": 2, "螣蛇": -1, "太阴": 1, "六合": 1,
                   "白虎": -1, "玄武": -1, "九地": 0.5, "九天": 1}
_QM_FILL = ["戊", "己", "庚", "辛", "壬", "癸", "丁", "丙", "乙"]
_QM_DUNYI = {"甲子": "戊", "甲戌": "己", "甲申": "庚",
             "甲午": "辛", "甲辰": "壬", "甲寅": "癸"}
_QM_JU_YANG = {
    "冬至": [1, 7, 4], "小寒": [2, 8, 5], "大寒": [3, 9, 6],
    "立春": [8, 5, 2], "雨水": [9, 6, 3], "惊蛰": [1, 7, 4],
    "春分": [3, 9, 6], "清明": [4, 1, 7], "谷雨": [5, 2, 8],
    "立夏": [4, 1, 7], "小满": [5, 2, 8], "芒种": [6, 3, 9],
}
_QM_JU_YIN = {
    "夏至": [9, 3, 6], "小暑": [8, 2, 5], "大暑": [7, 1, 4],
    "立秋": [2, 5, 8], "处暑": [1, 4, 7], "白露": [9, 3, 6],
    "秋分": [7, 1, 4], "寒露": [6, 9, 3], "霜降": [5, 8, 2],
    "立冬": [6, 9, 3], "小雪": [5, 8, 2], "大雪": [4, 7, 1],
}
# 月建地支 → (主节气, 阴阳遁)。自包含近似：每"建"月含两节气，取主节气。
_QM_JIAN_JIE = {
    "子": ("冬至", "阳遁"), "丑": ("大寒", "阳遁"), "寅": ("立春", "阳遁"),
    "卯": ("惊蛰", "阳遁"), "辰": ("清明", "阳遁"), "巳": ("立夏", "阳遁"),
    "午": ("芒种", "阳遁"), "未": ("小暑", "阴遁"), "申": ("立秋", "阴遁"),
    "酉": ("白露", "阴遁"), "戌": ("寒露", "阴遁"), "亥": ("立冬", "阴遁"),
}
_QM_YUAN = {"子": 0, "午": 0, "卯": 0, "酉": 0,    # 上元
            "寅": 1, "申": 1, "巳": 1, "亥": 1,    # 中元
            "辰": 2, "戌": 2, "丑": 2, "未": 2}    # 下元
_QM_SEASON = {"寅": "木", "卯": "木", "巳": "火", "午": "火",
              "申": "金", "酉": "金", "亥": "水", "子": "水",
              "辰": "土", "戌": "土", "丑": "土", "未": "土"}
_QM_STATE = {"旺": 1.0, "相": 0.7, "休": 0.4, "囚": 0.2, "死": 0.0}
_QM_MU = {"乙": 2, "丙": 6, "戊": 6, "丁": 8, "己": 8, "壬": 4, "辛": 8, "庚": 8, "癸": 2}
_QM_WBYS = {"甲": "庚午", "乙": "辛巳", "丙": "壬辰", "丁": "癸卯", "戊": "甲寅",
            "己": "乙丑", "庚": "丙子", "辛": "丁酉", "壬": "戊午", "癸": "己未"}


def _qm_state(sym_wx, dominant):
    if sym_wx == dominant:
        return "旺"
    if WX_SHENG[dominant] == sym_wx:
        return "相"
    if WX_SHENG[sym_wx] == dominant:
        return "休"
    if WX_KE[sym_wx] == dominant:
        return "囚"
    return "死"


def _qm_xunshou(gz):
    """干支 → 所属旬的旬首(六甲)。"""
    gi = GAN.index(gz[0]); zi = ZHI.index(gz[1])
    return "甲" + ZHI[(zi - gi) % 12]


def _qm_dipan(dun, ju):
    """排地盘 {宫:干}：阳遁 ju 宫顺布、阴遁逆布，中5之干寄坤2(取宫时处理)。"""
    dipan = {}; step = 1 if dun == "阳遁" else -1; pal = ju
    for gan in _QM_FILL:
        dipan[pal] = gan
        pal = (pal - 1 + step) % 9 + 1
    return dipan


def _qm_ring_walk(start_pal, n, forward):
    pos = _QM_RING.index(2 if start_pal == 5 else start_pal)
    return _QM_RING[(pos + (n if forward else -n)) % 8]


def m_qimen(nh, na, P):
    """奇门遁甲（忠实排盘版）：开球时刻定阴阳遁与局数 → 排地盘三奇六仪 → 定值符值使 →
    排天盘九星/八门/八神 → 主用神=日干落宫、客用神=时干落宫 → 按门星神吉凶+旺衰+格局判强弱。
    队名仅作取用层微扰（区分同一开球时刻的不同对阵；不改变排盘本身）。"""
    # 1. 阴阳遁 / 节气 / 三元 → 局数
    jie, dun = _QM_JIAN_JIE[P["month_jian"]]
    yuan = _QM_YUAN[ZHI[P["day_zi"]]]
    ju = (_QM_JU_YANG if dun == "阳遁" else _QM_JU_YIN)[jie][yuan]
    forward = (dun == "阳遁")

    # 2. 地盘三奇六仪
    dipan = _qm_dipan(dun, ju)
    gan2pal = {g: p for p, g in dipan.items()}

    # 3. 值符星 / 值使门（由时柱旬首遁仪定）
    yi = _QM_DUNYI[_qm_xunshou(P["hour_gz"])]
    fu_pal = gan2pal[yi]
    fu_eff = 2 if fu_pal == 5 else fu_pal       # 中5无门寄坤2(值符星天禽寄2宫死门)
    fu_star = _QM_STAR_HOME[fu_pal]
    shi_gate = _QM_GATE_HOME[fu_eff]

    hour_gan = P["hour_gan"]
    eff_hour_gan = yi if hour_gan == "甲" else hour_gan
    hour_pal = gan2pal[eff_hour_gan]            # 时干落宫 = 值符飞临宫

    # 4. 天盘九星（值符飞到时干宫，余星沿环跟飞，天盘干随星飞）
    fu_idx = _QM_RING.index(2 if fu_pal == 5 else fu_pal)
    hr_idx = _QM_RING.index(2 if hour_pal == 5 else hour_pal)
    shift = (hr_idx - fu_idx) % 8
    tianpan_star, tianpan_gan = {}, {}
    for k in range(8):
        src = _QM_RING[k]; dst = _QM_RING[(k + shift) % 8]
        tianpan_star[dst] = _QM_STAR_HOME[src]; tianpan_gan[dst] = dipan[src]
    tianpan_star[5] = "天禽"; tianpan_gan[5] = dipan[5]

    # 5. 八门（值使门按时辰差走宫定位，其余恒顺布）
    head_zi = ZHI.index(_qm_xunshou(P["hour_gz"])[1])
    steps = (P["hour_zi"] - head_zi) % 12
    shi_gate_pal = _qm_ring_walk(fu_pal, steps, forward)
    gates = {}
    g_start = _QM_RING.index(2 if shi_gate_pal == 5 else shi_gate_pal)
    order_from = _QM_GATE_ORDER.index(shi_gate)
    for k in range(8):
        gates[_QM_RING[(g_start + k) % 8]] = _QM_GATE_ORDER[(order_from + k) % 8]

    # 6. 八神（值符同时干宫，阳顺阴逆）
    spirits = {}
    s_start = _QM_RING.index(2 if hour_pal == 5 else hour_pal)
    for k in range(8):
        spirits[_QM_RING[(s_start + (k if forward else -k)) % 8]] = _QM_SPIRIT_ORDER[k]

    def cell(pal):
        rp = 2 if pal == 5 else pal
        return {"pal": pal, "wx": _QM_PALACE_WX[rp],
                "tg": tianpan_gan.get(rp, dipan[rp]), "dg": dipan[rp],
                "star": tianpan_star.get(rp, _QM_STAR_HOME[rp]),
                "gate": gates.get(rp, _QM_GATE_HOME[rp]),
                "spirit": spirits.get(rp, "值符")}

    # 7. 主客用神落宫（主=日干、客=时干）
    day_gan = P["day_gz"][0]
    eff_day_gan = _QM_DUNYI[_qm_xunshou(P["day_gz"])] if day_gan == "甲" else day_gan
    h_pal = gan2pal[eff_day_gan]
    a_pal = hour_pal
    if h_pal == a_pal:                          # 同宫→队名微扰区分同时段对阵（取用层）
        a_pal = _qm_ring_walk(a_pal, 1 + (na % 2), forward)
    tie_bias = 1 if (nh % 2) >= (na % 2) else -1

    dominant = _QM_SEASON[P["month_jian"]]

    def score_palace(c, used_gan):
        s = (_QM_GATE_LUCK[c["gate"]] * 0.30 + _QM_STAR_LUCK[c["star"]] * 0.25
             + _QM_SPIRIT_LUCK[c["spirit"]] * 0.20)
        st = _qm_state(c["wx"], dominant)
        s += _QM_STATE[st] * 0.5 - 0.25         # 旺衰居中化到 ±
        ge = []
        if c["tg"] == "戊" and c["dg"] == "丙": s += 2.0; ge.append("青龙返首")
        if c["tg"] == "丙" and c["dg"] == "戊": s += 2.0; ge.append("飞鸟跌穴")
        gu = {"乙": ("己", "辛"), "丙": ("戊", "庚"), "丁": ("壬", "癸")}
        if c["tg"] in gu and c["dg"] in gu[c["tg"]]: s += 1.5; ge.append("三奇得使")
        if _QM_MU.get(used_gan) == c["pal"]: s -= 1.5; ge.append("入墓")
        if WX_KE.get(_QM_GATE_WX[c["gate"]]) == c["wx"]: s -= 1.0; ge.append("门迫")
        if c["tg"] == c["dg"]: s -= 1.0; ge.append("伏吟")
        return s, st, ge

    ch, ca = cell(h_pal), cell(a_pal)
    sh, sth, geh = score_palace(ch, eff_day_gan)
    sa, sta, gea = score_palace(ca, eff_hour_gan)
    wbys = False
    if _QM_WBYS.get(day_gan) == P["hour_gz"]:
        sh -= 2.0; wbys = True

    gap = sh - sa
    if abs(gap) < 0.12:
        winner = "draw"
    elif abs(gap) < 0.35:
        winner = _sign_winner(gap if abs(gap) > 1e-9 else tie_bias)
    else:
        winner = _sign_winner(gap)

    atk = {"伤门", "生门", "景门"}
    base_h = h_pal + (3 if ch["gate"] in atk else 0) + int(round(sh))
    base_a = a_pal + (3 if ca["gate"] in atk else 0) + int(round(sa))
    h, a = _settle(_goals(base_h), _goals(base_a), winner)

    allge = []
    if geh: allge.append("主" + "/".join(geh))
    if gea: allge.append("客" + "/".join(gea))
    if wbys: allge.append("主五不遇时")
    gestr = ("·格局" + " ".join(allge)) if allge else ""

    detail = (f"{dun}{ju}局·{jie}{['上', '中', '下'][yuan]}元·值符{fu_star}值使{shi_gate}"
              f"｜主用神日干{day_gan}落{h_pal}宫({ch['gate']}/{ch['star']}/{ch['spirit']}·{sth})"
              f"／客用神时干{hour_gan}落{a_pal}宫({ca['gate']}/{ca['star']}/{ca['spirit']}·{sta}){gestr}")

    return {"key": "qimen", "name": "奇门遁甲", "icon": "🧭", "score": [h, a],
            "winner": winner, "confidence": _conf(50, int(round(gap * 2))),
            "detail": detail}


# ══════════════════════════════════════════════════════════════════════════════
# ====================  大六壬 专用模块（_LR_* / _lr_*）  ======================
# ══════════════════════════════════════════════════════════════════════════════
_LR_JIGONG = {"甲": "寅", "乙": "辰", "丙": "巳", "戊": "巳", "丁": "未", "己": "未",
              "庚": "申", "辛": "戌", "壬": "亥", "癸": "丑"}                 # 干寄宫
_LR_ZHI_GAN = {"子": "癸", "丑": "己", "寅": "甲", "卯": "乙", "辰": "戊", "巳": "丙",
               "午": "丁", "未": "己", "申": "庚", "酉": "辛", "戌": "戊", "亥": "壬"}  # 支本气干(涉害用)
_LR_GAN_WX = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
              "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
_LR_GAN_YANG = {"甲": 1, "丙": 1, "戊": 1, "庚": 1, "壬": 1,
                "乙": 0, "丁": 0, "己": 0, "辛": 0, "癸": 0}
_LR_GUIREN = {"甲": ("丑", "未"), "戊": ("丑", "未"), "庚": ("丑", "未"),   # 日干→(昼贵,夜贵)
              "乙": ("子", "申"), "己": ("子", "申"), "丙": ("亥", "酉"), "丁": ("亥", "酉"),
              "壬": ("卯", "巳"), "癸": ("卯", "巳"), "辛": ("午", "寅")}
_LR_GENERALS = ["贵人", "腾蛇", "朱雀", "六合", "勾陈", "青龙",
                "天空", "白虎", "太常", "玄武", "太阴", "天后"]            # 顺布序
_LR_GEN_LUCK = {"贵人": 2, "腾蛇": -2, "朱雀": 0, "六合": 1, "勾陈": -1, "青龙": 2,
                "天空": -1, "白虎": -2, "太常": 1, "玄武": -1, "太阴": 1, "天后": 1}
_LR_DAY_ZHI = set("卯辰巳午未申")                                          # 昼贵分界
_LR_XUNKONG = {0: ("戌", "亥"), 10: ("申", "酉"), 20: ("午", "未"),
               30: ("辰", "巳"), 40: ("寅", "卯"), 50: ("子", "丑")}       # 六甲旬空
_LR_MENG = set("寅申巳亥")
_LR_ZHONG = set("子午卯酉")
_LR_SANHE = {"申": "子", "子": "辰", "辰": "申", "亥": "卯", "卯": "未", "未": "亥",
             "寅": "午", "午": "戌", "戌": "寅", "巳": "酉", "酉": "丑", "丑": "巳"}
_LR_GANHE = {"甲": "己", "己": "甲", "乙": "庚", "庚": "乙", "丙": "辛", "辛": "丙",
             "丁": "壬", "壬": "丁", "戊": "癸", "癸": "戊"}


def _lr_zidx(z): return ZHI.index(z)
def _lr_ke(wx_a, wx_b): return WX_KE.get(wx_a) == wx_b


def _lr_build_plate(jiang_i, hour_zi):
    """月将加占时排天地盘。heaven[g]=盖在地盘第 g 支上的天盘支。"""
    off = (jiang_i - hour_zi) % 12
    return [ZHI[(g + off) % 12] for g in range(12)], off


def _lr_shang(z, heaven): return heaven[_lr_zidx(z)]     # 取 z 之上神(天盘)


def _lr_find_ke(lessons):
    """四课找克→[(上神,下神,'zei'下克上/'ke'上克下)]。"""
    res = []
    for low, up in lessons:
        if _lr_ke(ZHI_WX[low], ZHI_WX[up]): res.append((up, low, "zei"))
        if _lr_ke(ZHI_WX[up], ZHI_WX[low]): res.append((up, low, "ke"))
    return res


def _lr_develop(chu, heaven):
    """贼克类三传递推：中=初之上神，末=中之上神。"""
    zhong = _lr_shang(chu, heaven)
    return [chu, zhong, _lr_shang(zhong, heaven)]


def _lr_shehai_depth(cand, heaven):
    """涉害深浅：候选上神回归地盘本位，沿途被(支克+寄宫干克)次数。"""
    pos = next(g for g in range(12) if heaven[g] == cand)
    home, cnt, g = _lr_zidx(cand), 0, pos
    while g != home:
        tu = ZHI[g]
        if _lr_ke(ZHI_WX[tu], ZHI_WX[cand]): cnt += 1
        if _lr_ke(_LR_GAN_WX[_LR_ZHI_GAN[tu]], ZHI_WX[cand]): cnt += 1
        g = (g - 1) % 12
    return cnt


def _lr_pick_bi(cands, rgan):
    """比用：取与日干同阴阳的唯一上神；多于一→None(转涉害)。"""
    yang = _LR_GAN_YANG[rgan]
    bi = [c for c in cands if (_lr_zidx(c) % 2 == 0) == (yang == 1)]
    return bi[0] if len(bi) == 1 else None


def _lr_resolve_ke(kes, rgan):
    zei = [k for k in kes if k[2] == "zei"]
    cands = list(dict.fromkeys(k[0] for k in (zei if zei else kes)))
    if len(cands) == 1: return cands[0]
    return _lr_pick_bi(cands, rgan) or cands[0]


def _lr_three_chuan(lessons, heaven, off, rgan, rzhi, jigong):
    """发三传（九宗门）→(三传, 课体名)。"""
    yang = _LR_GAN_YANG[rgan]
    if off == 0:                                            # 伏吟
        kes = _lr_find_ke(lessons)
        if kes: return _lr_develop(_lr_resolve_ke(kes, rgan), heaven), "伏吟·贼克"
        chu = jigong if yang else _lr_shang(rzhi, heaven)
        def xing(z):
            X = {"子": "卯", "卯": "子", "寅": "巳", "巳": "申", "申": "寅",
                 "丑": "戌", "戌": "未", "未": "丑"}
            y = X.get(z, z)
            return y if y != z else ZHI[(_lr_zidx(z) + 6) % 12]   # 自刑取冲
        zhong = xing(chu)
        return [chu, zhong, xing(zhong)], ("伏吟·自任" if yang else "伏吟·自信")
    if off == 6:                                            # 返吟
        kes = _lr_find_ke(lessons)
        if kes: return _lr_develop(_lr_resolve_ke(kes, rgan), heaven), "返吟·无依"
        chu = ZHI[(_lr_zidx(rzhi) + 6) % 12]
        return [chu, _lr_shang(rzhi, heaven), _lr_shang(jigong, heaven)], "返吟·井栏"
    if jigong == rzhi:                                      # 八专
        gs = _lr_shang(jigong, heaven)
        chu = ZHI[(_lr_zidx(gs) + 2) % 12] if yang else ZHI[(_lr_zidx(_lr_shang(rzhi, heaven)) - 2) % 12]
        return [chu, gs, gs], "八专"
    kes = _lr_find_ke(lessons)
    if len(kes) == 1:                                       # 贼克
        return _lr_develop(kes[0][0], heaven), ("元首" if kes[0][2] == "ke" else "重审")
    if len(kes) >= 2:
        zei = [k for k in kes if k[2] == "zei"]
        grp = zei if zei else kes
        cands = list(dict.fromkeys(k[0] for k in grp))
        if len(cands) == 1:
            return _lr_develop(cands[0], heaven), ("重审" if zei else "元首")
        bi = _lr_pick_bi(cands, rgan)                       # 比用
        if bi is not None: return _lr_develop(bi, heaven), "知一(比用)"
        depths = [(c, _lr_shehai_depth(c, heaven)) for c in cands]   # 涉害
        mx = max(d for _, d in depths)
        deep = [c for c, d in depths if d == mx]
        if len(deep) == 1: return _lr_develop(deep[0], heaven), "涉害"
        meng = [c for c in deep if c in _LR_MENG]
        if meng: return _lr_develop(meng[0], heaven), "涉害·见机(临孟)"
        zhong = [c for c in deep if c in _LR_ZHONG]
        if zhong: return _lr_develop(zhong[0], heaven), "涉害·察微(临仲)"
        return _lr_develop(deep[0], heaven), "涉害"
    ups, rwx = [up for _, up in lessons], _LR_GAN_WX[rgan]  # 遥克
    hao = [u for u in ups if _lr_ke(ZHI_WX[u], rwx)]
    if hao:
        return _lr_develop(hao[0] if len(hao) == 1 else (_lr_pick_bi(hao, rgan) or hao[0]), heaven), "遥克·蒿矢"
    dan = [u for u in ups if _lr_ke(rwx, ZHI_WX[u])]
    if dan:
        return _lr_develop(dan[0] if len(dan) == 1 else (_lr_pick_bi(dan, rgan) or dan[0]), heaven), "遥克·弹射"
    if len(set(low for low, _ in lessons)) == 4:            # 昴星(四课俱全)
        if yang:
            return [_lr_shang("酉", heaven), _lr_shang(rzhi, heaven), _lr_shang(jigong, heaven)], "昴星·虎视"
        return [ZHI[heaven.index("酉")], _lr_shang(jigong, heaven), _lr_shang(rzhi, heaven)], "昴星·冬蛇掩目"
    chu = _lr_shang(_LR_JIGONG[_LR_GANHE[rgan]], heaven) if yang else _LR_SANHE.get(rzhi, rzhi)  # 别责
    gs = _lr_shang(jigong, heaven)
    return [chu, gs, gs], "别责·芜淫"


def _lr_place_generals(rgan, hour_zi, heaven):
    """昼夜贵人→顺逆布十二天将。返回 dict 地盘支→天将。"""
    zhou = ZHI[hour_zi] in _LR_DAY_ZHI
    guiren = _LR_GUIREN[rgan][0 if zhou else 1]
    gui_g = heaven.index(guiren)
    shun = guiren in set("亥子丑寅卯辰")
    res = {}
    for i in range(12):
        g = (gui_g + i) % 12 if shun else (gui_g - i) % 12
        res[ZHI[g]] = _LR_GENERALS[i]
    return res, guiren, zhou, shun


def _lr_wang(wx, jiang_zhi):
    """旺相休囚死（以月将所在五行近似月令）。"""
    yue = ZHI_WX[jiang_zhi]
    if wx == yue: return 2
    if WX_SHENG[yue] == wx: return 1
    if WX_SHENG[wx] == yue: return 0
    if WX_KE.get(wx) == yue: return -1
    return -2


def m_daliuren(nh, na, P):
    """大六壬：月将加占时排天地盘 → 起四课 → 九宗门发三传 → 昼夜贵人布十二天将
    → 日干(主)/日支(客)取用，凭三传天将生克旺衰空亡断主客气势。"""
    rgan, rzhi = P["day_gz"][0], P["day_gz"][1]    # 日干=主、日支=客
    jigong = _LR_JIGONG[rgan]
    salt = (nh ^ na) % 12                          # 队名只作返吟同分歧微扰(取用层,不进盘核心)
    heaven, off = _lr_build_plate(P["month_jiang_i"], P["hour_zi"])
    k1 = _lr_shang(jigong, heaven); k2 = _lr_shang(k1, heaven)
    k3 = _lr_shang(rzhi, heaven);   k4 = _lr_shang(k3, heaven)
    lessons = [(jigong, k1), (k1, k2), (rzhi, k3), (k3, k4)]    # 一~四课
    chuan, keti = _lr_three_chuan(lessons, heaven, off, rgan, rzhi, jigong)
    gens, guiren, zhou, shun = _lr_place_generals(rgan, P["hour_zi"], heaven)
    kong = set(_LR_XUNKONG.get((P["day_i"] // 10) * 10, ()))    # 旬空

    home_wx, away_wx, score = _LR_GAN_WX[rgan], ZHI_WX[rzhi], 0
    if _lr_ke(home_wx, away_wx): score += 3                     # (1)主客直接生克
    elif _lr_ke(away_wx, home_wx): score -= 3
    elif WX_SHENG[away_wx] == home_wx: score += 2
    elif WX_SHENG[home_wx] == away_wx: score -= 1
    for z, w in zip(chuan, [2, 1, 3]):                         # (2)三传(开局/中段/终局)+天将
        wx, gen = ZHI_WX[z], gens.get(z, "贵人")
        favh = _lr_ke(wx, away_wx) or WX_SHENG[wx] == home_wx
        fava = _lr_ke(wx, home_wx) or WX_SHENG[wx] == away_wx
        if favh: score += w + _LR_GEN_LUCK[gen]
        if fava: score -= w + _LR_GEN_LUCK[gen]
    score += _lr_wang(home_wx, P["month_jiang"])              # (3)旺衰
    score -= _lr_wang(away_wx, P["month_jiang"])
    if jigong in kong: score -= 2                             # (4)旬空
    if rzhi in kong: score += 2
    if "伏吟" in keti: score = int(score * 0.7)               # (5)课体
    elif "返吟" in keti: score += (1 if salt % 2 else -1)
    winner = _sign_winner(score)

    ci, cm = _lr_zidx(chuan[0]), _lr_zidx(chuan[2])           # 比分:初/末传序+气势
    base_h = (ci + cm + (3 if winner == "home" else 0)) % 6
    base_a = (_lr_zidx(chuan[1]) + cm + (3 if winner == "away" else 0)) % 6
    wxs = [ZHI_WX[z] for z in chuan]
    if WX_SHENG.get(wxs[0]) == wxs[1] and WX_SHENG.get(wxs[1]) == wxs[2]:   # 连茹增球
        base_h += 1; base_a += 1
    if (WX_KE.get(wxs[0]) == wxs[1] and WX_KE.get(wxs[1]) == wxs[2]) or "伏吟" in keti:  # 递克/伏吟闷局
        base_h = max(0, base_h - 1); base_a = max(0, base_a - 1)
    h, a = _settle(base_h, base_a, winner)

    chuan_str = "→".join(chuan)
    gen_str = "·".join(f"{z}乘{gens.get(z, '?')}" for z in chuan)
    kong_str = f"·{'/'.join(sorted(kong))}空" if kong else ""
    main_state = "旺" if _lr_wang(home_wx, P["month_jiang"]) >= 1 else "衰"
    detail = (f"{P['day_gz']}日·月将{P['month_jiang']}加{P['hour_zhi']}时·课体【{keti}】"
              f"·三传{chuan_str}({gen_str})·{'昼' if zhou else '夜'}贵{guiren}"
              f"{'顺' if shun else '逆'}布·日干{rgan}({home_wx}){main_state}/日支{rzhi}({away_wx})"
              f"{kong_str}（气势{score:+d}）")
    return {"key": "daliuren", "name": "大六壬", "icon": "🔯", "score": [h, a],
            "winner": winner, "confidence": _conf(46, score), "detail": detail}


# ══════════════════════════════════════════════════════════════════════════════
# ====================  紫微斗数 专用模块（_ZW_* / _zw_*）  ====================
# ══════════════════════════════════════════════════════════════════════════════
# 五虎遁：年干索引 → 寅宫天干索引（甲己起丙2/乙庚起戊4/丙辛起庚6/丁壬起壬8/戊癸起甲0）
_ZW_YIN_STEM = {0: 2, 5: 2, 1: 4, 6: 4, 2: 6, 7: 6, 3: 8, 8: 8, 4: 0, 9: 0}
# 六十甲子纳音五行（30 组，甲子序每组两甲子）→ 起五行局。
_ZW_NAYIN30 = ["金", "火", "木", "土", "金", "火", "水", "土", "金", "木",
               "水", "土", "火", "木", "水", "金", "火", "木", "土", "金",
               "火", "水", "土", "金", "木", "水", "土", "火", "木", "水"]
_ZW_WX_BUREAU = {"水": 2, "木": 3, "金": 4, "土": 5, "火": 6}
_ZW_BUREAU_NAME = {2: "水二局", 3: "木三局", 4: "金四局", 5: "土五局", 6: "火六局"}
_ZW_BNAME = {5: "庙", 4: "旺", 3: "得地", 2: "平", 1: "不得地", 0: "陷"}
# 庙旺利陷：14 主星 × 12 地支(子0..亥11)，庙5/旺4/得地3/平2/不得地1/陷0（通行《全书》精简口径）
_ZW_BRIGHT = {
    "紫微": [2, 4, 5, 4, 3, 4, 5, 4, 3, 4, 3, 2], "天机": [2, 1, 4, 5, 2, 3, 2, 1, 4, 5, 2, 3],
    "太阳": [0, 1, 3, 4, 5, 5, 5, 4, 3, 1, 0, 0], "武曲": [4, 5, 2, 3, 5, 1, 4, 5, 2, 3, 5, 1],
    "天同": [4, 1, 3, 2, 1, 5, 1, 2, 3, 1, 1, 4], "廉贞": [3, 2, 5, 1, 3, 0, 3, 2, 5, 1, 3, 0],
    "天府": [4, 5, 5, 3, 5, 4, 4, 5, 5, 3, 5, 4], "太阴": [5, 5, 1, 0, 0, 0, 0, 1, 3, 4, 4, 5],
    "贪狼": [4, 5, 2, 3, 5, 1, 4, 5, 2, 3, 5, 1], "巨门": [4, 2, 4, 5, 1, 3, 4, 2, 4, 5, 1, 3],
    "天相": [4, 5, 4, 3, 2, 4, 4, 5, 4, 3, 2, 4], "天梁": [4, 4, 5, 4, 4, 1, 4, 4, 2, 1, 4, 1],
    "七杀": [4, 3, 5, 3, 4, 3, 4, 3, 5, 3, 4, 3], "破军": [5, 4, 2, 3, 4, 1, 5, 4, 2, 3, 4, 1],
}


def _zw_bright(star: str, zhi: int) -> int:
    return _ZW_BRIGHT.get(star, [2] * 12)[zhi]


def _zw_bureau(gan_i: int, zhi_i: int) -> int:
    """命宫(天干索引,地支索引) → 纳音五行局数 N∈{2,3,4,5,6}。"""
    for k in range(60):
        if k % 10 == gan_i and k % 12 == zhi_i:
            return _ZW_WX_BUREAU[_ZW_NAYIN30[k // 2]]
    return 5  # 理论不可达


def _zw_ziwei_pos(day: int, N: int) -> int:
    """安紫微星：农历日 day(1..30)+五行局 N →紫微地支索引。商进余退法。"""
    q = (day + N - 1) // N        # 向上取整商
    c = q * N - day               # 补数
    base = (2 + (q - 1)) % 12     # 寅起，顺行 q 步
    return (base + c) % 12 if c % 2 == 0 else (base - c) % 12


def _zw_chart(year_gan_i: int, month: int, hour_zi: int, day: int):
    """完整排盘 → (命宫,身宫,五行局N,{宫地支:[主星]},{主星:宫地支})。
    month=农历月数(1..12,以节气月近似)；day=农历日(1..30,以干支日序近似)；hour_zi=时辰(子0)。"""
    month_palace = (2 + (month - 1)) % 12          # 寅起正月顺数
    ming = (month_palace - hour_zi) % 12            # 命宫(起子时逆数生时)
    shen = (month_palace + hour_zi) % 12            # 身宫(顺数生时)
    ming_stem = (_ZW_YIN_STEM[year_gan_i] + (ming - 2)) % 10   # 五虎遁定命宫干
    N = _zw_bureau(ming_stem, ming)                 # 起五行局
    zw = _zw_ziwei_pos(day, N)                      # 安紫微
    fu = (4 - zw) % 12                              # 天府=(4-紫微)%12
    stars = {}
    for s, off in (("紫微", 0), ("天机", -1), ("太阳", -3), ("武曲", -4), ("天同", -5), ("廉贞", -8)):
        stars[s] = (zw + off) % 12                  # 紫微系(逆行)
    for s, off in (("天府", 0), ("太阴", 1), ("贪狼", 2), ("巨门", 3),
                   ("天相", 4), ("天梁", 5), ("七杀", 6), ("破军", 10)):
        stars[s] = (fu + off) % 12                  # 天府系(顺行)
    by_palace = {}
    for s, z in stars.items():
        by_palace.setdefault(z, []).append(s)
    return ming, shen, N, by_palace, stars


def m_ziwei(nh, na, P):
    """紫微斗数（真实排盘）：以开球时刻为「比赛诞生时刻」起盘——
    节气月+时辰定命宫/身宫 → 五虎遁定命宫干 → 命宫干支纳音起五行局 →
    局+生日安紫微 → 紫微系(逆)/天府系(顺)排十四主星入十二宫 →
    命宫(主)/迁移宫(对宫,客)主星庙旺利陷 + 生年四化落宫 → 断主客强弱。
    ⚠️无农历库：以【节气月支近似农历月】+【干支日序近似农历日】，故为近似排盘(已标注)。
    队名(nh/na)仅进【取用层】：势均时微破均势 + 区分同开球时刻的不同对阵。"""
    month = ((P["month_jian_i"] - 2) % 12) + 1      # 节气月支→农历月数(寅=正月)，近似
    day = (P["day_i"] % 30) + 1                      # 干支日序→农历日，近似
    ming, shen, N, by_palace, stars = _zw_chart(P["year_gi"], month, P["hour_zi"], day)
    qian = (ming + 6) % 12                           # 迁移宫(命宫对宫)=客
    sihua = _sihua_map(P["year_gz"][0])              # 生年四化(主星→吉凶权)
    raw = _SIHUA_RAW.get(P["year_gz"][0], ("", "", "", ""))

    def sihua_tag(s):
        return ("化禄" if s == raw[0] else "化权" if s == raw[1]
                else "化科" if s == raw[2] else "化忌" if s == raw[3] else "")

    def palace_score(z):
        host = by_palace.get(z, []); borrow = False
        if not host:                                 # 空宫借对宫(力弱)
            host = by_palace.get((z + 6) % 12, []); borrow = True
        sc = sum(_zw_bright(s, z) + sihua.get(s, 0) * 2 for s in host)
        if borrow:
            sc = sc * 0.7 - 1
        return sc, host, borrow

    sc_h, sh_h, _ = palace_score(ming)
    sc_a, sh_a, _ = palace_score(qian)
    gap = sc_h - sc_a
    # 势均(|gap|<1)时以取用层(队名)微破均势，区分同时刻不同对阵
    winner = _sign_winner(gap if abs(gap) >= 1 else ((nh % 7) - (na % 7)))

    def goal_seed(z, sd):
        host = by_palace.get(z, []) or by_palace.get((z + 6) % 12, [])
        kpl = sum(1 for s in host if s in ("七杀", "破军", "贪狼"))   # 杀破狼主攻击→高比分倾向
        return sum(_zw_bright(s, z) for s in host) + kpl + sd
    h, a = _settle(_goals(goal_seed(ming, P["day_i"] + nh)),
                   _goals(goal_seed(qian, P["hour_zi"] + na)), winner)

    def brief(z):
        host = by_palace.get(z, []); bw = ""
        if not host:
            host = by_palace.get((z + 6) % 12, []); bw = "借"
        if not host:
            return "空宫"
        return bw + "·".join(f"{s}{_ZW_BNAME[_zw_bright(s, z)]}{sihua_tag(s)}" for s in host[:2])
    mw = "主旺" if winner == "home" else ("客旺" if winner == "away" else "势均")
    detail = (f"{P['year_gz']}年·{_ZW_BUREAU_NAME[N]}·命宫{ZHI[ming]}({brief(ming)})/"
              f"迁移{ZHI[qian]}({brief(qian)}) → {mw}")
    return {"key": "ziwei", "name": "紫微斗数", "icon": "✨", "score": [h, a],
            "winner": winner, "confidence": _conf(48, int(gap // 2)),
            "detail": detail}


# ══════════════════════════════════════════════════════════════════════════════
METHODS = [m_meihua, m_shefu, m_yijing, m_liuyao, m_qimen, m_daliuren, m_ziwei]


def divine(home: str, away: str, dt: str | None = None,
           longitude: float | None = None, utc_offset: float | None = None) -> dict:
    """对一场比赛运行全部 7 套术数 + 玄学共识。确定性、可复现。
    dt：开球时刻字符串（传**球场当地钟表时间** 'YYYY-MM-DD HH:MM'）。
    longitude+utc_offset：给定则把当地时间校正为**真太阳时**再起卦（最正统）。"""
    when = ganzhi.parse(dt)
    P = ganzhi.pillars(when, longitude=longitude, utc_offset=utc_offset)
    nh, na = _num(home), _num(away)
    results = [fn(nh, na, P) for fn in METHODS]

    votes = {"home": 0, "draw": 0, "away": 0}
    for r in results:
        votes[r["winner"]] += 1
    cons_winner = max(votes, key=votes.get)
    score_tally: dict[tuple, int] = {}
    for r in results:
        if r["winner"] == cons_winner:
            t = tuple(r["score"])
            score_tally[t] = score_tally.get(t, 0) + 1
    cons_score = max(score_tally, key=lambda k: (score_tally[k], -sum(k)))

    return {
        "home": home, "away": away,
        "datetime": when.strftime("%Y-%m-%d %H:%M"),
        "pillars": {"year": P["year_gz"], "day": P["day_gz"], "hour": P["hour_gz"],
                    "month_jian": P["month_jian"], "month_jiang": P["month_jiang"],
                    "true_solar": P["true_solar"], "solar_corr_min": P["solar_corr_min"]},
        "methods": results,
        "consensus": {"winner": cons_winner, "votes": votes,
                      "score": list(cons_score), "agree": score_tally[cons_score],
                      "n": len(results)},
        "disclaimer": "术数预测无科学依据，仅为文化/趣味实验，禁用于赌博或任何现实决策。",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(divine("Argentina", "France", "2026-07-19 19:00"),
                     ensure_ascii=False, indent=2))
