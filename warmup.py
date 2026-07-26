"""构建期预热：把冷启动的重计算烤进镜像，线上首屏才能秒开。

在 Docker build 阶段运行（此时容器有网络）。做三件事：
  ① import app —— 触发国家队 Dixon-Coles 模型训练，落 model.pkl（实测 ~33s）
  ② GET /api/dashboard —— 回溯验证约 30 个 as_of 模型，落 data/predictions.json
     （实测冷 71.7s / 热 0.02s，峰值内存 3GB；不预热则线上首个访客必然超时）
  ③ 逐个 club event GET /api/club/overview —— 从 football-data.co.uk 拉数据并训练
     per-league 模型（实测每个约 37s）

失败一律软处理：任一预热项挂掉都不能让 build 失败，app 运行时会自愈（只是那次请求慢）。
"""
import os
import time
import traceback

os.environ.setdefault("READONLY", "1")

t_all = time.time()


def step(label, fn):
    t = time.time()
    try:
        fn()
        print(f"[warmup] ✓ {label}  {time.time() - t:.1f}s", flush=True)
    except Exception:
        print(f"[warmup] ✗ {label}  {time.time() - t:.1f}s —— 跳过，运行时自愈", flush=True)
        traceback.print_exc()


print("[warmup] ① 训练国家队模型 …", flush=True)
t = time.time()
import app  # noqa: E402  —— 模块级 MODEL = get_model(...) 在此触发训练
print(f"[warmup] ✓ 模型就绪：{len(app.MODEL.teams)} 支球队  {time.time() - t:.1f}s", flush=True)

client = app.app.test_client()


def _get(path):
    r = client.get(path)
    if r.status_code != 200:
        raise RuntimeError(f"{path} -> HTTP {r.status_code}")


print("[warmup] ② 预热世界杯看板（回溯验证账本）…", flush=True)
step("/api/dashboard", lambda: _get("/api/dashboard"))

print("[warmup] ③ 预热各俱乐部联赛模型 …", flush=True)
try:
    import events
    club_keys = [k for k, v in events.EVENTS.items()
                 if str(v.get("universe", "")).startswith("club_")]
except Exception:
    club_keys = ["epl2627"]
    print("[warmup] 读取 events.EVENTS 失败，退回仅预热英超", flush=True)

for key in club_keys:
    step(f"/api/club/overview?event={key}", lambda k=key: _get(f"/api/club/overview?event={k}"))

print(f"[warmup] 全部完成，总耗时 {time.time() - t_all:.1f}s", flush=True)
