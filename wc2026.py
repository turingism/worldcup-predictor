"""Official 2026 World Cup format: group draw + knockout bracket structure + best-third allocation.

2026 世界杯官方赛制：小组分组 + 淘汰赛括号结构 + 第三名分配。

来源：FIFA 官方 / 维基百科 "2026 FIFA World Cup"。
- 12 组 A–L，每组 4 队（top2 + 8 个最佳第三 → 32 强）
- R32 共 16 场（编号 73–88），槽位按官方定义引用小组名次
- 8 个"第三名槽位"各有 5 个候选小组，按官方规则把出线的 8 个第三匹配进去
- 晋级树固定（R16/QF/SF/决赛）
"""
from __future__ import annotations
import json
import os

# —— 官方分组（队名与数据集一致）——
GROUPS: dict[str, list[str]] = {
    "A": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkey"],
    "E": ["Germany", "Curaçao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

# —— R32 槽位（match -> (slotA, slotB)）——
# ("1",X)=X组第一  ("2",X)=X组第二  ("3",match)=分配到该 match 的第三名
R32_SLOTS: dict[int, tuple] = {
    73: (("2", "A"), ("2", "B")),
    74: (("1", "E"), ("3", 74)),
    75: (("1", "F"), ("2", "C")),
    76: (("1", "C"), ("2", "F")),
    77: (("1", "I"), ("3", 77)),
    78: (("2", "E"), ("2", "I")),
    79: (("1", "A"), ("3", 79)),
    80: (("1", "L"), ("3", 80)),
    81: (("1", "D"), ("3", 81)),
    82: (("1", "G"), ("3", 82)),
    83: (("2", "K"), ("2", "L")),
    84: (("1", "H"), ("2", "J")),
    85: (("1", "B"), ("3", 85)),
    86: (("1", "J"), ("2", "H")),
    87: (("1", "K"), ("3", 87)),
    88: (("2", "D"), ("2", "G")),
}

# —— 第三名槽位的候选小组（官方规则）——
THIRD_SLOTS: dict[int, set] = {
    74: set("ABCDF"),
    77: set("CDFGH"),
    79: set("CEFHI"),
    80: set("EHIJK"),
    81: set("BEFIJ"),
    82: set("AEHIJ"),
    85: set("EFGIJ"),
    87: set("DEIJL"),
}

_THIRD_TABLE = None


def _third_table() -> dict[str, dict[str, str]]:
    """Load the official best-third allocation table.

    The table has one row for every possible set of 8 third-placed teams.  A
    constraint solver can find a valid assignment, but not necessarily FIFA's
    official assignment.
    """
    global _THIRD_TABLE
    if _THIRD_TABLE is None:
        path = os.path.join(os.path.dirname(__file__), "data", "third_place_table_2026.json")
        with open(path, encoding="utf-8") as f:
            _THIRD_TABLE = json.load(f)
    return _THIRD_TABLE

# —— 淘汰赛晋级树：(本场, 上轮A, 上轮B) ——
R16 = [(89, 74, 77), (90, 73, 75), (91, 76, 78), (92, 79, 80),
       (93, 83, 84), (94, 81, 82), (95, 86, 88), (96, 85, 87)]
QF = [(97, 89, 90), (98, 93, 94), (99, 91, 92), (100, 95, 96)]
SF = [(101, 97, 98), (102, 99, 100)]
FINAL = (104, 101, 102)

# —— 各场淘汰赛官方日期（2026）——
KO_DATES = {
    73: "2026-06-28", 74: "2026-06-29", 75: "2026-06-29", 76: "2026-06-29",
    77: "2026-06-30", 78: "2026-06-30", 79: "2026-06-30", 80: "2026-07-01",
    81: "2026-07-01", 82: "2026-07-01", 83: "2026-07-02", 84: "2026-07-02",
    85: "2026-07-02", 86: "2026-07-03", 87: "2026-07-03", 88: "2026-07-03",
    89: "2026-07-04", 90: "2026-07-04", 91: "2026-07-05", 92: "2026-07-05",
    93: "2026-07-06", 94: "2026-07-06", 95: "2026-07-07", 96: "2026-07-07",
    97: "2026-07-09", 98: "2026-07-10", 99: "2026-07-11", 100: "2026-07-11",
    101: "2026-07-14", 102: "2026-07-15", 104: "2026-07-19",
}

R32_ORDER = list(range(73, 89))
ROUND_NAMES = {"R32": "1/16 决赛", "R16": "1/8 决赛", "QF": "八强", "SF": "四强", "Final": "决赛"}


def assign_thirds(qual_letters):
    """把出线的 8 个第三名小组匹配到 8 个第三槽位（满足候选约束）。返回 {match: 小组字母}。"""
    key = "".join(sorted(qual_letters))
    row = _third_table().get(key)
    if row:
        return {int(mn): L for mn, L in row.items()}

    qual = set(qual_letters)
    slots = sorted(THIRD_SLOTS.items(),
                   key=lambda kv: sum(1 for L in qual if L in kv[1]))  # 最受限优先
    assign, used = {}, set()

    def bt(i):
        if i == len(slots):
            return True
        mn, allowed = slots[i]
        # sorted：让回溯选到的合法分配与 PYTHONHASHSEED 无关 → 同种子完全可复现
        for L in sorted(x for x in qual if x in allowed and x not in used):
            used.add(L); assign[mn] = L
            if bt(i + 1):
                return True
            used.discard(L); assign.pop(mn, None)
        return False

    if bt(0):
        return assign
    # 兜底：贪心（极少触发）
    assign, used = {}, set()
    for mn, allowed in slots:
        for L in sorted(qual):
            if L in allowed and L not in used:
                assign[mn] = L; used.add(L); break
    return assign


def resolve_r32(winner, runner, third, qual_third_letters):
    """
    给定各组名次，解析 16 场 R32 实际对阵。
      winner/runner/third: {组字母: 队名}
      qual_third_letters:  出线的 8 个第三名所在组字母
    返回 {match: (teamA, teamB)}
    """
    ta = assign_thirds(qual_third_letters)

    def slot(s):
        kind, ref = s
        if kind == "1":
            return winner[ref]
        if kind == "2":
            return runner[ref]
        return third[ta[ref]]  # ("3", match)

    return {mn: (slot(a), slot(b)) for mn, (a, b) in R32_SLOTS.items()}
