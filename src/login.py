"""登录模块：钉钉扫码登录 + storageState 持久化 + 过期检测。

设计：
- 使用 Playwright 同步 API（确定性代码，非 LLM），保证登录可控可调试。
- 扫码成功后保存 storageState（含 cookie/localStorage）到 runtime/storage_state.json。
- 后续所有自动化模块通过 storage_state 复用登录态，避免重复扫码。
- storageState 约 2 天过期（CAS 会话），提供 --check-login 检测。

用法：
    python -m src.login --login        # 弹出浏览器扫码（首次/过期）
    python -m src.login --check-login  # 检测登录态是否有效
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT

LOGIN_HOST = "passport.starmerx.com"   # CAS 登录域
TARGET_HOST = "op.starmerx.com"        # 业务域


def _storage_path(config: dict) -> Path:
    return ROOT / config["app"]["storage_state"]


def _open_context(p, config: dict, headless: bool, storage: Path | None = None):
    """启动 Chromium 并加载已有 storageState（若有）。"""
    browser = p.chromium.launch(
        headless=headless,
        slow_mo=config["app"].get("slow_mo", 100),
    )
    kw = {
        "viewport": config["app"]["viewport"],
        "locale": "zh-CN",
    }
    if storage and storage.exists():
        kw["storage_state"] = str(storage)
    context = browser.new_context(**kw)
    return browser, context


def is_logged_in(page) -> bool:
    """通过 URL 判断是否已登录（URL 已离开 passport 域即视为已登录）。"""
    try:
        return LOGIN_HOST not in page.url
    except Exception:
        return False


def do_login(config: dict) -> None:
    """执行钉钉扫码登录并保存 storageState。

    入口：直接打开产品池 URL，访问 op.starmerx.com 会自动 302 到
    passport.starmerx.com 做 CAS 钉钉扫码；扫码成功后自动跳回产品池页面。
    通过 URL 离开 passport 域（回到 op 域）判定登录成功。
    """
    qr_timeout = config["login"]["qr_timeout_sec"]
    storage = _storage_path(config)
    entry_url = config["product_pool"]["url"]  # 直接进产品池，触发 CAS 登录

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=False, storage=storage)
        page = context.new_page()
        log("[login] 打开产品池（触发 CAS 扫码登录）...")
        log("[login] ⚠️ 请在弹出浏览器中用钉钉扫码确认登录（超时 %ss）" % qr_timeout)
        page.goto(entry_url, wait_until="domcontentloaded", timeout=60000)
        # 若跳转到 passport，打印登录页地址便于确认
        if LOGIN_HOST in page.url:
            log(f"[login] 已跳转到扫码登录页: {page.url}")

        # 等待扫码完成（URL 离开 passport 域）
        deadline = time.time() + qr_timeout
        logged_in = False
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            if is_logged_in(page):
                logged_in = True
                break

        if not logged_in:
            browser.close()
            raise TimeoutError(f"[login] 扫码超时（{qr_timeout}s），请重试")

        # 等待 SPA 加载完成
        page.wait_for_timeout(3000)
        log(f"[login] 登录成功，当前 URL: {page.url}")

        # 保存 storageState
        storage.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(storage))
        log(f"[login] storageState 已保存到 {storage}")
        browser.close()
        log("[login] 登录完成 ✅")


def check_login(config: dict) -> bool:
    """检查 storageState 是否有效（未过期且仍处于登录态）。"""
    storage = _storage_path(config)
    if not storage.exists():
        log("[check-login] ✗ 未找到 storageState，需要先扫码登录")
        return False

    # 检查过期时间
    age_hours = (time.time() - storage.stat().st_mtime) / 3600
    max_age = config["login"]["storage_state_max_age_hours"]
    if age_hours > max_age:
        log(f"[check-login] ✗ storageState 已过期（{age_hours:.1f}h > {max_age}h），需重新扫码")
        return False

    # 实际访问验证登录态（用登录成功的 #/home 路径，避开 #/ 可能的重定向歧义）
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True, storage=storage)
        page = context.new_page()
        try:
            page.goto(config["app"]["base_url"], wait_until="domcontentloaded", timeout=30000)
            # 给 SPA 留出渲染/跳转时间，再判断 URL 是否停留在 passport 域
            page.wait_for_timeout(4000)
            ok = is_logged_in(page)
        except Exception:
            ok = False
        browser.close()

    log(f"[check-login] {'✓ 已登录' if ok else '✗ 登录态已失效，需重新扫码'}")
    return ok


def main() -> None:
    config = load_config()
    args = sys.argv[1:]
    if "--login" in args or "-l" in args:
        do_login(config)
    elif "--check-login" in args or "-c" in args:
        sys.exit(0 if check_login(config) else 1)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()