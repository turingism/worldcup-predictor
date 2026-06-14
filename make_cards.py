# -*- coding: utf-8 -*-
"""小红书分享卡片生成器 —— 世界杯比分预测器
3:4 尺寸 / 直角 / 无阴影 / 主次分明 / 重点 highlight。
依赖：Pillow + Noto Sans SC 变体字体。
"""
import os
from PIL import Image, ImageDraw, ImageFont

# ---------- 画布 / 配色 ----------
W, H = 1080, 1440                      # 3:4
FONT = "/tmp/fonts/NotoSansSC.ttf"
OUT = "/home/user/worldcup-predictor/share_cards"
os.makedirs(OUT, exist_ok=True)

BG      = (11, 36, 31)                 # 深球场绿（午夜）
BG2     = (8, 28, 24)                  # 更深
PANEL   = (17, 48, 41)                 # 内容面板
LIME    = (200, 255, 70)              # 电光柠檬（高亮主色）
LIME_D  = (150, 205, 40)
WHITE   = (244, 248, 243)
MUTED   = (150, 178, 167)             # 次要文字（灰绿）
FAINT   = (95, 128, 116)
LOCK    = (96, 165, 250)              # 锁定蓝（真实赛果）
GOLD    = (245, 197, 24)
LINE    = (38, 70, 61)

M = 92                                  # 页边距

# ---------- 字体缓存 ----------
_fc = {}
def font(size, wght=400):
    k = (size, wght)
    if k not in _fc:
        f = ImageFont.truetype(FONT, size)
        f.set_variation_by_axes([wght])
        _fc[k] = f
    return _fc[k]

# ---------- 文本工具 ----------
def is_cjk(ch):
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3000 <= o <= 0x303F) or (0xFF00 <= o <= 0xFFEF)

def tokenize(s):
    """CJK 逐字、拉丁/数字成词，便于按像素换行。"""
    toks, buf = [], ""
    for ch in s:
        if is_cjk(ch) or ch == " ":
            if buf:
                toks.append(buf); buf = ""
            toks.append(ch)
        else:
            buf += ch
    if buf:
        toks.append(buf)
    return toks

def wrap(draw, s, fnt, maxw):
    lines, cur = [], ""
    for tok in tokenize(s):
        trial = cur + tok
        if draw.textlength(trial, font=fnt) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur.rstrip()); cur = tok if tok != " " else ""
    if cur.strip():
        lines.append(cur.rstrip())
    return lines

def text(draw, xy, s, fnt, fill, anchor="la"):
    draw.text(xy, s, font=fnt, fill=fill, anchor=anchor)

def para(draw, x, y, s, fnt, fill, maxw, lh):
    for ln in wrap(draw, s, fnt, maxw):
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += lh
    return y

# ---------- 高亮胶囊（重点 highlight） ----------
def pill(draw, x, y, s, fnt, fg=BG, bg=LIME, padx=26, pady=16):
    w = draw.textlength(s, font=fnt)
    asc, desc = fnt.getmetrics()
    h = asc + desc
    draw.rectangle([x, y, x + w + padx*2, y + h + pady*2], fill=bg)   # 直角
    draw.text((x + padx, y + pady), s, font=fnt, fill=fg)
    return y + h + pady*2

# ---------- 公共骨架 ----------
def base(idx=None, total=9, tag="世界杯比分预测器 · WORLD CUP 2026"):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # 顶部品牌行
    text(d, (M, 78), tag, font(26, 600), MUTED)
    if idx:
        s = f"{idx:02d} / {total:02d}"
        text(d, (W - M, 78), s, font(28, 700), LIME, anchor="ra")
    d.line([(M, 132), (W - M, 132)], fill=LINE, width=2)
    return img, d

def footer(d, s="⚽ 看球之前，先看概率 · 开源 · 不玄学 · 不荐彩"):
    d.line([(M, H-120), (W - M, H-120)], fill=LINE, width=2)
    # 用纯文本（去 emoji，画一个小球点代替）
    cx, cy = M+10, H-78
    d.ellipse([cx-9, cy-9, cx+9, cy+9], outline=LIME, width=3)
    text(d, (M+34, H-92), "看球之前，先看概率 · 开源 · 不玄学 · 不荐彩", font(24, 500), FAINT)

# ---------- 图标（直线几何，柠檬色） ----------
def icon_badge(d, cx, cy, r=86):
    d.rectangle([cx-r, cy-r, cx+r, cy+r], outline=LIME, width=4)
    return cx, cy

def ic_ball(d, cx, cy):
    icon_badge(d, cx, cy)
    d.ellipse([cx-46, cy-46, cx+46, cy+46], outline=LIME, width=5)
    # 中心五边形
    import math
    pts = [(cx + 22*math.sin(math.radians(a)), cy - 22*math.cos(math.radians(a))) for a in range(0,360,72)]
    d.polygon(pts, outline=LIME, width=4)
    for p in pts:
        d.line([(cx,cy) if False else p, (cx + 1.9*(p[0]-cx), cy + 1.9*(p[1]-cy))], fill=LIME, width=4)

def ic_matrix(d, cx, cy):
    icon_badge(d, cx, cy)
    n, s, g = 4, 24, 6
    tot = n*s + (n-1)*g
    x0, y0 = cx - tot//2, cy - tot//2
    fill_map = {(0,0),(1,1),(2,2),(0,1),(1,0),(1,2)}
    for r in range(n):
        for c in range(n):
            x, y = x0 + c*(s+g), y0 + r*(s+g)
            if (r,c) in fill_map:
                d.rectangle([x,y,x+s,y+s], fill=LIME)
            else:
                d.rectangle([x,y,x+s,y+s], outline=LIME_D, width=2)

def ic_trophy(d, cx, cy):
    icon_badge(d, cx, cy)
    d.rectangle([cx-26, cy-44, cx+26, cy-8], outline=LIME, width=5)
    d.arc([cx-50, cy-44, cx-18, cy+4], 90, 270, fill=LIME, width=5)
    d.arc([cx+18, cy-44, cx+50, cy+4], 270, 90, fill=LIME, width=5)
    d.line([(cx, cy-8),(cx, cy+18)], fill=LIME, width=5)
    d.rectangle([cx-22, cy+18, cx+22, cy+30], fill=LIME)
    d.rectangle([cx-34, cy+34, cx+34, cy+46], fill=LIME)

def ic_bolt(d, cx, cy):
    icon_badge(d, cx, cy)
    pts = [(cx+8,cy-48),(cx-26,cy+6),(cx-2,cy+6),(cx-8,cy+48),(cx+26,cy-10),(cx+2,cy-10)]
    d.polygon(pts, fill=LIME)

def ic_bracket(d, cx, cy):
    icon_badge(d, cx, cy)
    col = LIME
    ys = [cy-42, cy-18, cy+18, cy+42]
    for y in ys:
        d.line([(cx-50, y),(cx-22, y)], fill=col, width=4)
    d.line([(cx-22, cy-42),(cx-22, cy-18)], fill=col, width=4)
    d.line([(cx-22, cy+18),(cx-22, cy+42)], fill=col, width=4)
    d.line([(cx-22, cy-30),(cx+6, cy-30)], fill=col, width=4)
    d.line([(cx-22, cy+30),(cx+6, cy+30)], fill=col, width=4)
    d.line([(cx+6, cy-30),(cx+6, cy+30)], fill=col, width=4)
    d.line([(cx+6, cy),(cx+40, cy)], fill=col, width=4)
    d.rectangle([cx+40, cy-8, cx+56, cy+8], fill=LIME)

def ic_dash(d, cx, cy):
    icon_badge(d, cx, cy)
    d.rectangle([cx-48, cy-40, cx-4, cy+4], outline=LIME, width=4)
    d.rectangle([cx+8, cy-40, cx+48, cy-8], fill=LIME)
    d.rectangle([cx+8, cy+4, cx+48, cy+40], outline=LIME, width=4)
    d.rectangle([cx-48, cy+16, cx-4, cy+40], fill=LIME)

def ic_target(d, cx, cy):
    icon_badge(d, cx, cy)
    for rr,wd in [(46,5),(28,5)]:
        d.ellipse([cx-rr,cy-rr,cx+rr,cy+rr], outline=LIME, width=wd)
    d.ellipse([cx-9,cy-9,cx+9,cy+9], fill=LIME)

def ic_scale(d, cx, cy):
    icon_badge(d, cx, cy)
    d.line([(cx, cy-46),(cx, cy+40)], fill=LIME, width=4)
    d.line([(cx-44, cy-30),(cx+44, cy-30)], fill=LIME, width=4)
    for sx in (-44, 44):
        d.line([(cx+sx, cy-30),(cx+sx-16, cy+2)], fill=LIME_D, width=3)
        d.line([(cx+sx, cy-30),(cx+sx+16, cy+2)], fill=LIME_D, width=3)
        d.arc([cx+sx-20, cy-8, cx+sx+20, cy+18], 0, 180, fill=LIME, width=4)
    d.rectangle([cx-22, cy+40, cx+22, cy+50], fill=LIME)

def ic_chart(d, cx, cy):
    icon_badge(d, cx, cy)
    d.line([(cx-46, cy+44),(cx-46, cy-46)], fill=LIME_D, width=3)
    d.line([(cx-46, cy+44),(cx+48, cy+44)], fill=LIME_D, width=3)
    bars = [(-34,18),(-10,40),(14,28),(38,58)]
    for bx,bh in bars:
        d.rectangle([cx+bx-9, cy+44-bh, cx+bx+9, cy+44], fill=LIME)

# ========================================================
#  封面卡
# ========================================================
def cover():
    img = Image.new("RGB", (W, H), BG2)
    d = ImageDraw.Draw(img)
    # 顶部柠檬粗条
    d.rectangle([0, 0, W, 14], fill=LIME)
    text(d, (M, 110), "OPEN SOURCE · 实时概率引擎", font(28, 700), LIME)
    text(d, (M, 158), "WORLD CUP 2026", font(26, 600), MUTED)

    # 大标题
    y = 250
    text(d, (M, y), "世界杯", font(150, 900), WHITE)
    text(d, (M, y+158), "比分预测器", font(150, 900), WHITE)
    # 副标
    y2 = y + 350
    para(d, M, y2, "一台你能亲手拨动的 2026 世界杯概率机器。",
         font(40, 500), MUTED, W-2*M, 56)
    para(d, M, y2+70, "真实数据驱动 · 样本外校准 · 实时随赛况更新。",
         font(40, 500), MUTED, W-2*M, 56)

    # 功能清单（2 列网格）
    feats = [
        "单场比分预测", "夺冠概率＋可信区间",
        "In-play 实时胜平负", "本届实时晋级树",
        "赛事看板", "预测验证",
        "市场对标 CLV", "回测可证伪",
    ]
    gx0, gy0 = M, 940
    cw = (W - 2*M - 30) // 2
    rh = 92
    for i, f in enumerate(feats):
        r, c = divmod(i, 2)
        x = gx0 + c*(cw+30)
        yy = gy0 + r*rh
        d.rectangle([x, yy, x+cw, yy+rh-18], fill=PANEL)
        d.rectangle([x, yy, x+7, yy+rh-18], fill=LIME)   # 左侧柠檬条
        text(d, (x+28, yy+(rh-18)//2), f, font(33, 600), WHITE, anchor="lm")

    # 底部条
    d.rectangle([0, H-86, W, H-72], fill=LIME)
    text(d, (M, H-54), "Dixon-Coles 双泊松 · 1872–2026 真实国际赛 · 蒙特卡洛模拟",
         font(25, 500), MUTED)
    img.save(f"{OUT}/01_cover.png")
    print("saved 01_cover")

# ========================================================
#  内容卡通用渲染
# ========================================================
def content(idx, icon_fn, title, subtitle, highlight, bullets, note=None, extra=None):
    img, d = base(idx)
    # 图标
    icx, icy = M+86, 248
    icon_fn(d, icx, icy)
    # 标题
    ty = 380
    for ln in wrap(d, title, font(72, 900), W-2*M):
        text(d, (M, ty), ln, font(72, 900), WHITE)
        ty += 92
    # 副标
    ty += 6
    ty = para(d, M, ty, subtitle, font(36, 500), MUTED, W-2*M, 52)
    # 高亮胶囊
    ty += 30
    ty = pill(d, M, ty, highlight, font(38, 800))
    # 要点
    ty += 56
    for b in bullets:
        # 柠檬方块项目符
        d.rectangle([M, ty+10, M+18, ty+28], fill=LIME)
        ny = para(d, M+44, ty, b, font(37, 500), WHITE, W-2*M-44, 52)
        ty = ny + 26
    # 示例 / 数据条
    if extra:
        extra(d, ty)
    # 备注（次要）
    if note:
        ny = H-210
        d.rectangle([M, ny, M+7, ny+70], fill=FAINT)
        para(d, M+26, ny-4, note, font(28, 500), MUTED, W-2*M-26, 40)
    footer(d)
    img.save(f"{OUT}/{idx:02d}_card.png")
    print(f"saved {idx:02d}")

# ---- 02 示例：胜平负小条 ----
def ex_predict(d, y):
    y = max(y, 1030)
    d.rectangle([M, y, W-M, y+150], fill=PANEL)
    text(d, (M+28, y+24), "Argentina  1-0  France", font(34, 700), WHITE)
    text(d, (M+28, y+72), "最可能比分 16.9%", font(26, 500), LIME)
    # 胜平负堆叠
    bx, bw = M+28, W-M-28 - (M+28)
    by = y+112
    segs = [(0.454, LIME), (0.309, MUTED), (0.237, LOCK)]
    cx = bx
    for p, col in segs:
        w = int(bw*p)
        d.rectangle([cx, by, cx+w, by+22], fill=col)
        cx += w
    text(d, (W-M-28, y+72), "胜45% 平31% 负24%", font(26, 500), MUTED, anchor="ra")

def main():
    cover()

    content(2, ic_matrix,
        "单场比分预测",
        "输入两支球队 → 最可能比分、胜平负、期望进球 xG。",
        "一整张 11×11 比分概率矩阵",
        ["不是一句「谁赢」，而是给你整张概率分布",
         "Top7 最可能比分 + 概率热力图，一屏看全",
         "中立场 / 东道主主场优势，自动分得清"],
        extra=ex_predict)

    content(3, ic_trophy,
        "夺冠概率 · 90% 可信区间",
        "蒙特卡洛整届模拟 → 48 强每队夺冠/进决赛/四强/出线概率。",
        "5000 次模拟仅 1–2 秒",
        ["贝叶斯分层后验驱动的 90% 可信区间",
         "晋级漏斗：出线 → 八强 → 四强 → 决赛 → 夺冠",
         "录入新赛果后，区间后台自动重算"],
        note="区间宽且重叠＝夺冠次序本就高度不确定。我们不假装确定。")

    content(4, ic_bolt,
        "In-play 实时胜平负",
        "比赛进行中，胜平负随每一个进球和分钟实时跳动。",
        "赛前一锤子 → 实时概率引擎",
        ["赛前 λ 按剩余时间缩放 + 当前比分泊松卷积",
         "给出「从现状到终场」的主胜 / 平 / 客胜",
         "只读引擎严格隔离，绝不污染赛前预测"],
        note="差异化护城河：别人赛前算一次就完事，我们让概率随赛况漂移。")

    content(5, ic_bracket,
        "本届实时晋级树",
        "2026 官方赛制：12 组 + 官方括号 + 最佳第三名分配。",
        "全程可编辑 · 实时重算",
        ["真实赛果蓝色锁定，其余按模型预测投影",
         "改任意比分 / 假设淘汰赛 → 括号 + 夺冠率实时重算",
         "北京 / 当地时间切换，录入自动存盘不丢"])

    content(6, ic_dash,
        "赛事看板（首屏）",
        "正在比赛 / 即将开赛 / 已结束，三态聚合一屏掌握全局。",
        "三态聚合 · 一屏看全",
        ["即将开赛按比赛日分组，带预测比分 + 三向概率",
         "每场一键「看预测」，弹出完整概率矩阵",
         "秒级拉 ESPN 完场，有新赛果模型自动重训"])

    content(7, ic_target,
        "预测验证 · 拿数字逼自己诚实",
        "逐场核对赛果 / 比分命中，谁也别想事后改口。",
        "赛前预测开球前冻结存证",
        ["账本不可事后篡改，开球后条目只读",
         "按置信度分桶命中率 + 冷门归因",
         "样本外回测 ECE = 1.06%（行业基准 8–10%）"],
        note="我们用数字逼自己说真话——吹得对不对，逐场一目了然。")

    content(8, ic_scale,
        "市场对标 · CLV 诚实层",
        "模型 vs 博彩闭盘线 + 闭盘线价值(CLV)可证伪检验。",
        "无显著正 CLV → 不显示任何注码",
        ["理性博彩护栏 + 严格门槛 gating",
         "做诚实检验，不做下注诱导",
         "概率 ≠ 确定，本项目不构成任何投注建议"],
        note="绝不出现「稳赢 / 必中 / 内幕」——拿数字逼自己说真话。")

    content(9, ic_chart,
        "为什么它不一样",
        "我们替你试过了所有花哨方案，留下来的每一项都有回测背书。",
        "回测否决的，绝不硬塞给你",
        ["身价先验 / Elo / 赛事分级 / 负二项 / 后校准 → 全部更差，默认关",
         "学术级模型：Maher(1982) → Dixon-Coles(1997) 一脉相承",
         "每个数字都能被回测证伪，随真实赛果自动更新"],
        note="免责声明：本项目仅供统计建模与编程学习，不构成任何投注 / 投资建议。")

if __name__ == "__main__":
    main()
    print("ALL DONE ->", OUT)
