#!/usr/bin/env python3
"""把 skill-public/SKILL.md 发布到 SkillSafe 注册表。

为什么是「你自己跑」而不是 agent 代跑：SkillSafe 的 API key 按官方文档
「carry full account authority」——全账号权限。这种凭据不应该进入 AI 的上下文，
也不该留在会话记录里。本脚本走设备授权流：你在浏览器点同意，key 只存在于
这个进程的内存里，用完即弃，从不落盘、从不打印。

用法:
    python3 scripts/publish_skill.py                 # 正式发布
    python3 scripts/publish_skill.py --dry-run       # 只做本地校验，不联网

流程: 申请设备授权 → 你在浏览器批准 → 取回 key → 上传 SKILL.md → 平台自动安全扫描
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid

API = "https://deploy.skillsafe.ai"
SKILL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "skill-public", "SKILL.md")


def _post(path: str, payload: dict | None = None, key: str | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method="POST")
    if data:
        req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _get(path: str, key: str | None = None) -> dict:
    req = urllib.request.Request(API + path)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load_skill() -> tuple[bytes, dict]:
    """读 SKILL.md 并解析 frontmatter，顺便做发布前校验。"""
    raw = open(SKILL_PATH, "rb").read()
    text = raw.decode("utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        sys.exit("✗ SKILL.md 缺少 YAML frontmatter")
    try:
        import yaml
        fm = yaml.safe_load(m.group(1))
    except ImportError:
        sys.exit("✗ 需要 pyyaml：pip install pyyaml")

    # 注册表字段上限（见 skillsafe.ai/docs）
    for field, cap in (("description", 2000), ("category", 100), ("tags", 1000)):
        if len(str(fm.get(field, ""))) > cap:
            sys.exit(f"✗ {field} 超过 {cap} 字符上限")
    for field in ("name", "description"):
        if not fm.get(field):
            sys.exit(f"✗ frontmatter 缺少必填字段 {field}")
    return raw, fm


def device_login() -> tuple[str, str]:
    """设备授权流。返回 (api_key, namespace)。key 只在内存里流转。"""
    r = _post("/v1/auth/cli", {"label": f"publish-skill-{uuid.uuid4().hex[:8]}"})
    d = r["data"] if "data" in r else r
    session_id, login_url = d["session_id"], d["login_url"]

    print("\n请在浏览器里批准这次授权：")
    print(f"  {login_url}\n")
    # 文档明确：login_url 必须原样使用，且 shell 里要引号包裹（zsh 下 ? 是通配符）
    try:
        subprocess.run(["open", login_url], check=False)
    except Exception:
        print("  （自动打开失败，请手动复制上面的链接）")

    print("等待批准中… 批准后【不要刷新或重开那个页面】——", end="")
    print("页面自身的状态检查会消耗掉一次性的 key。")
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(3)
        try:
            r = _get(f"/v1/auth/cli/{session_id}")
        except Exception:
            continue
        d = r["data"] if "data" in r else r
        if d.get("status") == "approved":
            print(f"✓ 已授权，账号 @{d['username']}")
            return d["api_key"], d["username"]
        if d.get("status") in ("denied", "expired"):
            sys.exit(f"✗ 授权被拒或已过期：{d.get('status')}")
    sys.exit("✗ 等待授权超时（15 分钟）")


def publish(key: str, namespace: str, raw: bytes, fm: dict) -> None:
    name = fm["name"]
    digest = hashlib.sha256(raw).hexdigest()
    metadata = {
        "version": str(fm.get("metadata", {}).get("version", "1.0")),
        "description": fm["description"].strip(),
        "category": fm.get("category", ""),
        "file_manifest": [{"path": "SKILL.md", "hash": f"sha256:{digest}", "size": len(raw)}],
    }
    for opt in ("tags", "license", "github_repo_url"):
        if fm.get(opt):
            metadata[opt] = fm[opt]

    # 手工拼 multipart，避免为一次上传引入 requests 依赖
    boundary = "----skillsafe" + uuid.uuid4().hex
    parts: list[bytes] = []
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
        f"Content-Type: application/json\r\n\r\n".encode()
        + json.dumps(metadata, ensure_ascii=False).encode() + b"\r\n")
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file_SKILL.md"; '
        f'filename="SKILL.md"\r\nContent-Type: text/markdown\r\n\r\n'.encode()
        + raw + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(f"{API}/v1/skills/@{namespace}/{name}",
                                 data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"✗ 发布失败 HTTP {e.code}：{e.read().decode()[:500]}")

    print(f"\n✓ 已发布：@{namespace}/{name}")
    print(f"  页面   https://skillsafe.ai/skill/@{namespace}/{name}/")
    print(f"  安装   npx skills add https://api.skillsafe.ai/{namespace}/{name}")
    print("\n平台会自动做安全扫描；扫描通过后该 skill 才能公开列出。")
    print("扫描状态见上面的页面链接。")
    if resp.get("data", {}).get("scan"):
        print(f"  本次扫描返回：{json.dumps(resp['data']['scan'], ensure_ascii=False)[:300]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只做本地校验，不联网")
    args = ap.parse_args()

    raw, fm = load_skill()
    print(f"✓ SKILL.md 校验通过：{fm['name']}  {len(raw):,} 字节")
    print(f"  description {len(fm['description'])} 字符 · category {fm.get('category')}"
          f" · license {fm.get('license')}")
    if args.dry_run:
        print("\n--dry-run：到此为止，未联网、未发布。")
        return 0

    key, namespace = device_login()
    try:
        publish(key, namespace, raw, fm)
    finally:
        del key      # 不落盘、不打印，用完即弃
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
