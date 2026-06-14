"""In-play 实时胜平负的可证伪性校验。

诚实声明（数据可得性）：martj42/ESPN 只给**终场比分**，没有公开免费的国家队
**分钟级进球时刻**历史数据，因此无法用真实历史比赛做"t 分钟时的预测 vs 真实终场"的
样本外回测。这里做两类**正当的正确性/自洽校验**（非样本外预测精度，明确区分）：

  1) t=0 一致性：in-play 在 0 分钟的胜平负应≈赛前 predict（验证缩放+卷积数学正确）。
  2) 模拟路径自洽：用赛前模型自己生成进球时刻（Poisson 计数 + 均匀时刻），在 t∈{0..90}
     切片取"当时比分"，算 in-play 概率对该模拟路径终场结果的 RPS——应**随 t 单调下降、
     t=90 趋 0**。因数据生成过程就是模型本身，这检验的是 in-play 概率的**内部校准与收敛**
     （卷积是否自洽），不是真实世界的预测优势。

真实样本外验证需要分钟级进球数据——与项目其它"无免费数据源"困境同源，诚实记账。
"""
from __future__ import annotations
import numpy as np

import inplay


def _rps(ph: float, pd: float, pa: float, o: str) -> float:
    oh, od = (o == "H") * 1.0, (o == "D") * 1.0
    return 0.5 * ((ph - oh) ** 2 + (ph + pd - (oh + od)) ** 2)


# 代表性对阵：强弱悬殊 / 势均力敌 / 中等，覆盖不同 λ 量级
FIXTURES = [
    ("Germany", "Curaçao"),       # 强 vs 弱
    ("Netherlands", "Japan"),     # 势均力敌
    ("England", "Croatia"),       # 中强对话
    ("Argentina", "Algeria"),     # 强 vs 中弱
    ("Brazil", "Morocco"),        # 强 vs 中
]
CHECKPOINTS = [0, 15, 30, 45, 60, 75, 90]


def run(n: int = 600, seed: int = 42):
    from predict import get_model
    m = get_model(use_cache=True, half_life=730.0, verbose=False)
    rng = np.random.default_rng(seed)

    # 1) t=0 一致性
    print("== 1) t=0 一致性（in-play@0′ vs 赛前 predict，越小越好）==")
    cons = []
    for home, away in FIXTURES:
        pre = m.predict(home, away, neutral=True)
        ip0 = inplay.win_draw_loss(m, home, away, 0, 0, 0, neutral=True)
        l1 = (abs(ip0["p_home"] - pre["p_home"]) + abs(ip0["p_draw"] - pre["p_draw"])
              + abs(ip0["p_away"] - pre["p_away"]))
        cons.append(l1)
        print(f"  {home:>12} vs {away:<10} L1差={l1:.4f}  "
              f"(赛前 {pre['p_home']:.3f}/{pre['p_draw']:.3f}/{pre['p_away']:.3f} → "
              f"in-play {ip0['p_home']:.3f}/{ip0['p_draw']:.3f}/{ip0['p_away']:.3f})")
    print(f"  平均 L1 差 = {np.mean(cons):.4f}（应 <0.02，截断+无ρ的微小误差）\n")

    # 2) 模拟路径自洽：RPS 随 t 单调下降、t=90→0
    print(f"== 2) 模拟路径 RPS vs 比赛进程（每对 {n} 次模拟，应单调下降、90′趋0）==")
    agg = {t: [] for t in CHECKPOINTS}
    for home, away in FIXTURES:
        _h, _a, lh, la = m.expected_goals(home, away, neutral=True)
        for _ in range(n):
            ngh, nga = rng.poisson(lh), rng.poisson(la)
            th = np.sort(rng.uniform(0, 90, ngh))
            ta = np.sort(rng.uniform(0, 90, nga))
            fo = "H" if ngh > nga else ("D" if ngh == nga else "A")
            for t in CHECKPOINTS:
                gh = int((th < t).sum())
                ga = int((ta < t).sum())
                w = inplay.win_draw_loss(m, home, away, gh, ga, t, neutral=True)
                agg[t].append(_rps(w["p_home"], w["p_draw"], w["p_away"], fo))
    prev, mono = None, True
    for t in CHECKPOINTS:
        r = float(np.mean(agg[t]))
        flag = ""
        if prev is not None and r > prev + 1e-9:
            flag = "  ⚠ 非单调"
            mono = False
        print(f"  t={t:>2}′  平均 RPS = {r:.4f}{flag}")
        prev = r
    r90 = float(np.mean(agg[90]))
    print(f"\n  单调下降: {'✅ 是' if mono else '❌ 否'} · t=90′ RPS={r90:.4f}"
          f"（应≈0，{'✅' if r90 < 0.01 else '❌'}）")
    print("\n  注：这是内部自洽校验（数据生成=模型本身），证明 in-play 卷积随信息增加正确收敛；")
    print("  非真实样本外精度——后者需分钟级进球数据（无免费源）。")


if __name__ == "__main__":
    run()
