#!/usr/bin/env python3
"""下载/更新国际比赛历史数据（martj42/international_results）。"""
import os
import urllib.request

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
OUT = os.path.join(os.path.dirname(__file__), "data", "results.csv")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
print(f"下载 {URL}")
urllib.request.urlretrieve(URL, OUT)
n = sum(1 for _ in open(OUT, encoding="utf-8")) - 1
print(f"完成 -> {OUT}（{n:,} 场比赛）")
