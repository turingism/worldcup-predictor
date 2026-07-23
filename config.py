"""Single source of truth for national-team production model configuration.

国家队生产模型配置的唯一事实来源。

历史教训：half_life 曾在 simulate.py(240)/backtest.py(547)/data.py(547)/test_core.py(240)
等多个入口各自硬编码，运行不同入口会把共享 model.pkl 覆盖成不同参数版本。
生产统一 half_life=730（修复回测时间泄漏后的样本外最优）；一切国家队生产入口
（CLI / 网页 / 模拟器 / 验证账本 / 回测基线）必须从这里取值，不得再写字面量。

俱乐部宇宙（hl=365）的配置在 clubdata/clubpredict，与本文件无关。
"""

# 国家队生产半衰期（天）。回测最优 ≈2 年；旧值 240 是时间泄漏伪影，勿改回。
NATIONAL_HALF_LIFE = 730.0

# DixonColesModel 其余生产默认参数（与 model.py __init__ 保持一致；改动需过回测）
NATIONAL_MAX_AGE_YEARS = 16.0
NATIONAL_MIN_MATCHES = 12
