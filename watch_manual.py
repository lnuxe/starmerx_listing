"""旁观记录：有头模式打开利润测算抽屉，你手动操作，脚本轮询记录字段状态变化轨迹。

用法：
  .venv/bin/python watch_manual.py

脚本会：
  1. 打开上架计划页 → 打开首行利润测算抽屉（有头浏览器，你能看到同一窗口）
  2. 每 1 秒轮询读取：公司利润率、个人利润率、活动营销费、弹窗标题、申请理由框、按钮
  3. 检测到状态变化即记录一条轨迹（时间戳 + 字段快照 + 自动截图）
  4. 运行时长默认 300 秒（5 分钟），你可在此期间手动操作
  5. 结束后把轨迹 JSON + 截图归纳到 runtime/手动操作轨迹/

截图目录：runtime/手动操作轨迹/
轨迹文件：runtime/手动操作轨迹/trace.jsonl
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _open_profit_drawer

WATCH_SEC = int(sys.argv[1]) if len(sys.argv) > 1 else 300
TRACE_DIR = ROOT / "runtime" / "手动操作轨迹"
TRACE_DIR.mkdir(parents=True, exist_ok=True)
TRACE_FILE = TRACE_DIR / "trace.jsonl"

_SNAP_JS = """() => {
    const roots = [...document.querySelectorAll(
        '.el-drawer:not([style*="display: none"]), .el-dialog:not([style*="display: none"])')]
        .filter(r => r.offsetParent !== null || r.getBoundingClientRect().width > 0);
    const root = roots.find(r => (r.innerText||'').includes('保存算价')) || roots[0];
    if (!root) return { note: 'no drawer' };

    const out = {};

    // 公司利润率 / 个人利润率 / 活动营销费
    const tdMargin = root.querySelector('td[colid="col_58"]');
    const tdFee = root.querySelector('td[colid="col_69"]');
    if (tdMargin) {
        const inp = tdMargin.querySelector('input');
        if (inp) { inp.id = '__margin2__'; out.margin = inp.value; }
        const text = tdMargin.innerText;
        const m = text.match(/个人:\\s*[\\d.]+\\s+([\\d.]+)%/);
        out.personal_pct = m ? m[1] : null;
        out.margin_cell_text = text;
    }
    if (tdFee) {
        const inp = tdFee.querySelector('input');
        if (inp) { inp.id = '__mkt_fee__'; out.mkt_fee = inp.value; }
    }

    // 弹窗（价格校验异常等）
    const dialogs = [...document.querySelectorAll(
        '.el-dialog:not([style*="display: none"]), .el-message-box')]
        .filter(d => d.offsetParent !== null || d.getBoundingClientRect().width > 0);
    if (dialogs.length) {
        const d = dialogs[dialogs.length - 1];
        const title = d.querySelector('.el-dialog__title, .el-message-box__title');
        const textarea = d.querySelector('textarea');
        const buttons = [...d.querySelectorAll('button')].map(b => (b.innerText||'').trim()).filter(Boolean);
        out.dialog = {
            title: title ? title.innerText.trim() : '',
            has_textarea: !!textarea,
            textarea_value: textarea ? textarea.value : null,
            buttons,
        };
    }

    // toast 提示
    const toasts = [...document.querySelectorAll('.el-message, .el-notification')]
        .filter(t => t.offsetParent !== null || t.getBoundingClientRect().width > 0)
        .map(t => (t.innerText||'').trim()).filter(Boolean);
    if (toasts.length) out.toasts = toasts;

    return out;
}"""


def _key(s: dict) -> str:
    """生成快照的特征键，用于判断是否发生变化。"""
    return json.dumps({k: s.get(k) for k in
                       ("margin", "personal_pct", "mkt_fee", "dialog", "toasts")},
                      ensure_ascii=False, sort_keys=True)


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(
            p, config, headless=False,   # 有头：你能看到并操作同一窗口
            storage=ROOT / config["app"]["storage_state"],
        )
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录"); browser.close(); sys.exit(1)

        _open_plan_page(page, config)
        page.wait_for_timeout(2000)
        try:
            page.locator(".vxe-table--body-wrapper tr").first.wait_for(
                state="attached", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        ok = _open_profit_drawer(page, row_idx=0)
        log(f"打开利润抽屉: {ok}")
        page.wait_for_timeout(2000)

        # 打开后先记录初始快照
        prev_key = None
        step = 0
        shot_idx = 0
        f = open(TRACE_FILE, "a", encoding="utf-8")

        def record(s: dict, changed: bool, note: str = ""):
            nonlocal step, shot_idx
            entry = {
                "ts": datetime.now().strftime("%H:%M:%S"),
                "step": step,
                "changed": changed,
                "note": note,
                "snap": s,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            if changed:
                shot_idx += 1
                png = TRACE_DIR / f"step{step:03d}.png"
                page.screenshot(path=str(png), full_page=True)
                log(f"[轨迹] step{step} 变化: {note} | {json.dumps({k: s.get(k) for k in ('margin','personal_pct','mkt_fee','dialog','toasts') if k in s}, ensure_ascii=False)} → 截图 {png.name}")
            step += 1

        log(f"=== 开始旁观，时长 {WATCH_SEC}s。请在同一浏览器窗口手动操作 ===")
        log("提示：我会每秒轮询，检测到字段/弹窗变化即记录轨迹+截图")

        t0 = time.time()
        while time.time() - t0 < WATCH_SEC:
            s = page.evaluate(_SNAP_JS)
            k = _key(s)
            if k != prev_key:
                note = "首次快照" if prev_key is None else "状态变化"
                record(s, changed=(prev_key is not None), note=note)
                prev_key = k
            time.sleep(1)

        record(page.evaluate(_SNAP_JS), changed=False, note="结束快照")
        f.close()
        log(f"=== 旁观结束。轨迹已保存到 {TRACE_FILE}，截图 {shot_idx} 张 ===")
        browser.close()


if __name__ == "__main__":
    main()