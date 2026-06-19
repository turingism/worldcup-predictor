# -*- coding: utf-8 -*-
"""足球经理人 功能卡 · Claude 经典配色版
3:4 / 直角 / 无阴影 / 主次分明 / 重点 highlight。
暖奶油底 (#F0EEE6) + 陶土橙 (#CC785C) + 深墨字。
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1440
FONT = "/tmp/fonts/NotoSansSC.ttf"
OUT = "/home/user/worldcup-predictor/share_cards_claude"
os.makedirs(OUT, exist_ok=True)

PAGE  = (240, 238, 230)   # 暖奶油底
INK   = (38, 35, 31)      # 深墨字
CLAY  = (204, 120, 92)    # Claude 陶土橙 #CC785C
CLAY_D= (176, 98, 73)
SUB   = (120, 113, 102)   # 暖灰次要
FAINT = (166, 159, 147)
PANEL = (232, 229, 219)
LINE  = (219, 215, 204)
M = 92

_fc = {}
def font(size, wght=400):
    k = (size, wght)
    if k not in _fc:
        f = ImageFont.truetype(FONT, size); f.set_variation_by_axes([wght]); _fc[k] = f
    return _fc[k]

def is_cjk(ch):
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3000 <= o <= 0x303F) or (0xFF00 <= o <= 0xFFEF)

def tokenize(s):
    toks, buf = [], ""
    for ch in s:
        if is_cjk(ch) or ch == " ":
            if buf: toks.append(buf); buf = ""
            toks.append(ch)
        else:
            buf += ch
    if buf: toks.append(buf)
    return toks

def wrap(draw, s, fnt, maxw):
    lines, cur = [], ""
    for tok in tokenize(s):
        trial = cur + tok
        if draw.textlength(trial, font=fnt) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur.rstrip()); cur = tok if tok != " " else ""
    if cur.strip(): lines.append(cur.rstrip())
    return lines

def text(draw, xy, s, fnt, fill, anchor="la"):
    draw.text(xy, s, font=fnt, fill=fill, anchor=anchor)

def para(draw, x, y, s, fnt, fill, maxw, lh):
    for ln in wrap(draw, s, fnt, maxw):
        draw.text((x, y), ln, font=fnt, fill=fill); y += lh
    return y

def pill(draw, x, y, s, fnt, bg, fg, padx=26, pady=16):
    w = draw.textlength(s, font=fnt); asc, desc = fnt.getmetrics(); h = asc + desc
    draw.rectangle([x, y, x + w + padx*2, y + h + pady*2], fill=bg)
    draw.text((x + padx, y + pady), s, font=fnt, fill=fg)
    return y + h + pady*2

# ---------- 图标：战术板 / 经理夹板 ----------
def ic_manager(d, cx, cy, ac, r=86):
    d.rectangle([cx-r, cy-r, cx+r, cy+r], outline=ac, width=5)
    # 夹板外框
    d.rectangle([cx-44, cy-40, cx+44, cy+52], outline=ac, width=4)
    # 顶部夹子
    d.rectangle([cx-16, cy-52, cx+16, cy-34], fill=ac)
    # 战术：两名球员 + 传球线 + 箭头
    d.line([(cx-26, cy+30),(cx+6, cy-6)], fill=CLAY_D, width=3)
    d.ellipse([cx-32, cy+24, cx-20, cy+36], fill=ac)     # 球员1
    d.ellipse([cx+0, cy-12, cx+12, cy+0], fill=ac)        # 球员2
    # 箭头指向右上
    d.line([(cx+6, cy-6),(cx+30, cy-26)], fill=ac, width=3)
    d.line([(cx+30, cy-26),(cx+20, cy-24)], fill=ac, width=3)
    d.line([(cx+30, cy-26),(cx+28, cy-14)], fill=ac, width=3)

def main():
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    # 顶部品牌行
    text(d, (M, 78), "世界杯比分预测器 · WORLD CUP 2026", font(26, 600), SUB)
    pill(d, W-M-150, 70, "NEW", font(26, 800), CLAY, PAGE, padx=22, pady=10)
    d.rectangle([M, 132, W - M, 138], fill=CLAY)

    # 图标
    ic_manager(d, M+86, 250, CLAY)

    # 标题
    ty = 380
    text(d, (M, ty), "足球经理人", font(80, 900), INK)
    ty += 104
    # 副标
    ty = para(d, M, ty, "一份赛前深度报告：过程数据 → 算法模型 → 结论。",
              font(35, 500), SUB, W-2*M, 50)
    # 高亮
    ty += 24
    ty = pill(d, M, ty, "一场比赛，把全盘口一次看全", font(38, 800), CLAY, PAGE)

    # 要点
    ty += 42
    bullets = [
        "近期状态 / 历史交锋 / 攻防画像，全来自真实战绩",
        "比分矩阵卷出：胜平负 · 大小球 · 亚盘 · 竞彩 · 双方进球 · 半全场",
        "自带置信度评级，叠加伤停、场馆、赔率、名气对标",
        "给不了的（阵容 / 天气 / 裁判）老实标注，不构成投注建议",
    ]
    for b in bullets:
        d.rectangle([M, ty+9, M+18, ty+27], fill=CLAY)
        ny = para(d, M+44, ty, b, font(34, 500), INK, W-2*M-44, 48)
        ty = ny + 20

    # 示例条（随内容自然下排）
    y = ty + 22
    d.rectangle([M, y, W-M, y+150], fill=PANEL)
    text(d, (M+28, y+22), "Argentina  vs  France", font(34, 800), INK)
    text(d, (M+28, y+68), "xG 1.15 - 0.77 · 最可能 1-0 · 置信度：中", font(25, 500), SUB)
    bx = M+28; bw = (W-M-28) - (M+28); by = y+112
    for p, col in [(0.444, CLAY), (0.312, FAINT), (0.245, INK)]:
        w = int(bw*p); d.rectangle([bx, by, bx+w, by+22], fill=col); bx += w
    text(d, (W-M-28, y+68), "主44% 平31% 客25%", font(25, 500), SUB, anchor="ra")

    # 一行注脚（诚实定位）
    cy0 = y + 150 + 26
    d.rectangle([M, cy0+2, M+7, cy0+34], fill=CLAY)
    text(d, (M+26, cy0), "只读装配层，复用 Dixon-Coles 引擎 —— 不碰模型、不碰回测，纯展示。",
         font(27, 500), SUB)

    # 页脚
    d.line([(M, H-120), (W - M, H-120)], fill=LINE, width=2)
    cx, cy = M+10, H-78
    d.ellipse([cx-9, cy-9, cx+9, cy+9], outline=CLAY, width=3)
    text(d, (M+34, H-92), "看球之前，先看概率 · 开源 · 不玄学 · 不荐彩", font(24, 500), FAINT)

    img.save(f"{OUT}/10_manager.png")
    print("saved ->", f"{OUT}/10_manager.png")

if __name__ == "__main__":
    main()
