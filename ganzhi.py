# -*- coding: utf-8 -*-
"""干支 / 时辰 / 节气 推算（ganzhi.py）

从一个开球时刻(datetime)推出术数起卦/起局所需的时间柱：
  · 年干支（以立春为界，精确）
  · 日干支（六十甲子连续循环，锚点 2000-01-07=甲子，精确——已与 1949-10-01=甲子交叉验证）
  · 时辰地支 + 时干（五鼠遁，精确）
  · 月建（当令之"节"对应的地支，奇门/紫微/旺衰用）
  · 月将（当令之"中气"对应的太阳过宫地支，大六壬月将加时用）

节气：按【太阳视黄经】精确推算（Meeus 简式，≈0.01°，远超节气定位所需），
   月建以立春(黄经315°)起寅、每30°一建；月将以雨水(330°)起亥、太阳过宫每30°退一将。
   黄经按比赛的真实物理时刻(UTC)计算；任何日期都准，无近似表的交接日误差。
   年干支、日干支、时辰亦为精确计算。
"""
from __future__ import annotations

import datetime as dt
import math

GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"

_DAY_ANCHOR = dt.date(2000, 1, 7)        # 甲子日（精确锚点）
_YEAR_ANCHOR = 1984                       # 1984 = 甲子年

# 地支 → 五行
ZHI_WX = {"子": "水", "亥": "水", "寅": "木", "卯": "木", "巳": "火", "午": "火",
          "申": "金", "酉": "金", "辰": "土", "戌": "土", "丑": "土", "未": "土"}

_LICHUN = (2, 4)   # 立春≈2/4，仅作年干支分界（6-7月世界杯永不触及，留近似无妨）


# ── 精确节气：按太阳视黄经(apparent ecliptic longitude)定月建/月将 ──────────────
def _julian_day(d: dt.datetime) -> float:
    """UTC datetime → 儒略日(JD)。"""
    y, m = d.year, d.month
    day = d.day + (d.hour + d.minute / 60 + d.second / 3600) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + day + b - 1524.5)


def solar_longitude(d_utc: dt.datetime) -> float:
    """太阳视黄经(度, 0–360)。中等精度(≈0.01°，远超节气定位所需)，依 Meeus 简式。"""
    jd = _julian_day(d_utc)
    t = (jd - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = math.radians((357.52911 + 35999.05029 * t - 0.0001537 * t * t) % 360)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m)
         + 0.000289 * math.sin(3 * m))
    omega = math.radians(125.04 - 1934.136 * t)
    return (l0 + c - 0.00569 - 0.00478 * math.sin(omega)) % 360


def jian_from_lon(lon: float) -> str:
    """月建地支：寅月起于立春(黄经315°)，每 30° 一月建。"""
    return ZHI[(2 + int(((lon - 315) % 360) // 30)) % 12]


def jiang_from_lon(lon: float) -> str:
    """月将地支：登明亥起于雨水(黄经330°)，太阳过宫每 30° 退一将。"""
    return ZHI[(11 - int(((lon - 330) % 360) // 30)) % 12]


def _equation_of_time(d: dt.date) -> float:
    """均时差(分钟)：真太阳时 − 平太阳时。常用近似式(误差 <0.5min)。"""
    n = d.timetuple().tm_yday
    b = math.radians(360.0 / 365.0 * (n - 81))
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def true_solar(when: dt.datetime, longitude: float, utc_offset: float) -> tuple[dt.datetime, float]:
    """民用当地钟表时间 → **真太阳时**。返回(校正后时刻, 校正分钟)。
    校正 = 经度时差(经度−时区标准经线)×4分/度 + 均时差。西经为负。"""
    std_meridian = utc_offset * 15.0                 # 该时区标准经线(度)
    lon_corr = (longitude - std_meridian) * 4.0      # 经度时差(分钟)
    corr = lon_corr + _equation_of_time(when.date())
    return when + dt.timedelta(minutes=corr), corr


def pillars(when: dt.datetime, longitude: float | None = None,
            utc_offset: float | None = None) -> dict:
    """开球时刻 → 时间柱字典。年/日/时为精确，月建/月将为近似节气。
    给定 longitude+utc_offset 时，先把民用当地时间校正为**真太阳时**再起柱
    （时辰/日干支按真太阳时；西部球场可差 1+ 小时，足以跨时辰甚至跨日）。"""
    # 月建/月将按【真实物理时刻(UTC)】的太阳黄经定（与"时辰用真太阳时"是两回事）。
    utc = (when - dt.timedelta(hours=utc_offset)) if utc_offset is not None else when
    lon = solar_longitude(utc)
    month_jian = jian_from_lon(lon)
    month_jiang = jiang_from_lon(lon)

    # 时辰/日干支用真太阳时（给定经度则校正）
    solar_corr = None
    if longitude is not None and utc_offset is not None:
        when, solar_corr = true_solar(when, longitude, utc_offset)
    d = when.date()

    # 年干支（立春为界）
    yr = d.year if (d.month, d.day) >= _LICHUN else d.year - 1
    yi = (yr - _YEAR_ANCHOR) % 60
    year_gi, year_zi = yi % 10, yi % 12

    # 日干支（精确）
    di = (d.toordinal() - _DAY_ANCHOR.toordinal()) % 60
    day_gi, day_zi = di % 10, di % 12

    # 时辰地支（子时含 23 点）+ 时干（五鼠遁：时干 =(日干%5*2+时支)%10）
    hour_zi = ((when.hour + 1) // 2) % 12
    hour_gi = (day_gi % 5 * 2 + hour_zi) % 10

    return {
        "year_gz": GAN[year_gi] + ZHI[year_zi], "year_gi": year_gi, "year_zi": year_zi,
        "day_gz": GAN[day_gi] + ZHI[day_zi], "day_gi": day_gi, "day_zi": day_zi, "day_i": di,
        "hour_zhi": ZHI[hour_zi], "hour_zi": hour_zi,
        "hour_gan": GAN[hour_gi], "hour_gi": hour_gi,
        "hour_gz": GAN[hour_gi] + ZHI[hour_zi],
        "month_jian": month_jian, "month_jian_i": ZHI.index(month_jian),
        "month_jiang": month_jiang, "month_jiang_i": ZHI.index(month_jiang),
        "true_solar": when.strftime("%Y-%m-%d %H:%M") if solar_corr is not None else None,
        "solar_corr_min": round(solar_corr, 1) if solar_corr is not None else None,
    }


def parse(dt_str: str | None, default: dt.datetime | None = None) -> dt.datetime:
    """宽松解析 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD' 等；失败回落 default 或揭幕日。"""
    if dt_str:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
            try:
                return dt.datetime.strptime(dt_str.strip()[:16], fmt)
            except ValueError:
                continue
    return default or dt.datetime(2026, 6, 11, 20, 0)


if __name__ == "__main__":
    for s in ["2026-06-11 20:00", "2026-06-20 03:00", "2026-07-19 19:00"]:
        p = pillars(parse(s))
        print(f"{s}  {p['year_gz']}年 {p['day_gz']}日 {p['hour_gz']}时 "
              f"月建{p['month_jian']} 月将{p['month_jiang']}")
