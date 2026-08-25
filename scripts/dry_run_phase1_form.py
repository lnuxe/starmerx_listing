"""Phase1 表单填写 dry-run 验证：真实打开 dialog 并填写各字段，但【不点确定加入】。

目的：在避免真实提交（不产生上架计划数据）的前提下，验证 `_fill_plan_form`
的选择器/交互逻辑是否正确 —— 平台/站点/店铺/品牌(select)、产品类目(cascader)、
利润率(input)、加入方式/生成方式/GTIN(select) 是否都能正确填入选定值。

流程：
  1) 打开产品池 → 切美区/多渠道 → 选品类 → 搜索
  2) 勾选首行 → 打开「直接加入上架计划」dialog
  3) 调用 phase1._fill_plan_form 填写（不点确定）
  4) 【验证】读回 dialog 内各字段当前值，与 config 期望值比对
  5) 截图存档 → Escape 关闭 dialog（不点「确定加入」，无任何数据提交）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light, safe_click
from src.phase1 import (SEL_TAB_US_POOL, SEL_TAB_CHANNEL, SEL_SEARCH_BTN,
                        _open_category, _fill_plan_form, SEL_TABLE,
                        _open_plan_dialog_via_row, _verify_pool_category)


def _read_form_values(page, config: dict) -> dict:
    """读回 dialog 内各字段当前显示值（含 select 选中文本、cascader 回填、input 值）。

    返回 dict: {label: {ctrl, value, ok}}。value 为选中文本/输入值，供与期望比对。
    """
    plan = config["plan"]
    expected = {
        "平台": plan["platform"],
        "站点": plan["site"],
        "店铺": plan["store"],
        "品牌": plan["brand"],
        # 语言保持英文默认（不切中文，避免后台禁用 cascader）
        "产品类目": config["category"]["platform_path"][-1],
        "利润率": str(plan["margin_rate"]),
        "加入方式": plan.get("join_mode", "按SKU加入"),
        "生成方式": plan.get("generate_mode", "按SPU维度生成多个上架计划"),
        "GTIN类型": plan.get("gtin", "豁免"),
    }
    # 语言下拉框嵌在产品类目 form-item 内（.category-options .el-select），单独读回
    lang_val = page.evaluate(
        """() => {
            const dlg = [...document.querySelectorAll('.el-dialog')]
                .find(d => d.offsetParent !== null
                    || d.getBoundingClientRect().width > 100);
            if (!dlg) return '';
            const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                const l = fi.querySelector('.el-form-item__label, label');
                return l && (l.innerText || '').trim() === '产品类目';
            });
            const sel = f && f.querySelector('.category-options .el-select');
            if (!sel) return '';
            const w = sel.querySelector('.el-select__selected-item,'
                + '.el-select__selected-value,.el-select__placeholder,.el-select__tags-text');
            const inp = sel.querySelector('input');
            return w ? (w.innerText || '').trim() : (inp ? inp.value : '');
        }"""
    )
    vals = page.evaluate(
        """(labels) => {
            const dlg = [...document.querySelectorAll('.el-dialog')]
                .find(d => d.offsetParent !== null
                    || d.getBoundingClientRect().width > 100);
            if (!dlg) return { note: 'NO_DIALOG' };
            const out = {};
            for (const [label] of Object.entries(labels)) {
                const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                    const l = fi.querySelector('.el-form-item__label, label');
                    return l && (l.innerText || '').trim() === label;
                });
                if (!f) { out[label] = { ctrl: null, value: '' }; continue; }
                const sel = f.querySelector('.el-select');
                const cas = f.querySelector('.el-cascader');
                const inp = f.querySelector('input');
                let ctrl = 'input', value = '';
                // 产品类目行内同时含 cascader 与语言 select，须优先识别 cascader
                if (cas) {
                    ctrl = 'cascader';
                    // 收集 cascader 内所有选中 tag 文本，拼接成路径；兜底 input.value
                    const tags = [...cas.querySelectorAll('.el-cascader__tags-text, '
                        + '.el-cascader__selected-item, .el-cascader__selected-value, '
                        + '.el-tag, .el-cascader__node-label')]
                        .map(n => (n.innerText || '').trim())
                        .filter(Boolean);
                    value = tags.join('/');
                    if (!value) {
                        const pi = cas.querySelector('.el-input__inner');
                        value = pi ? (pi.value || '').trim() : '';
                    }
                } else if (sel) {
                    ctrl = 'select';
                    const w = sel.querySelector('.el-select__selected-item, '
                        + '.el-select__selected-value, .el-select__placeholder, '
                        + '.el-select__tags-text');
                    value = w ? (w.innerText || '').trim() : (inp ? inp.value : '');
                } else if (inp) {
                    ctrl = 'input';
                    value = inp.value;
                }
                out[label] = { ctrl, value };
            }
            return out;
        }""",
        expected,
    )
    # 合并语言读回值（产品类目行内嵌下拉，label 匹配不到独立 form-item）
    if "语言" not in vals or not vals["语言"].get("value"):
        vals["语言"] = {"ctrl": "select", "value": lang_val}
    # 组装比对结果
    result = {"note": vals.get("note"), "fields": {}}
    for label, want in expected.items():
        got = vals.get(label) or {}
        ok = bool(got.get("value")) and want in got.get("value", "")
        result["fields"][label] = {"want": want, "ctrl": got.get("ctrl"),
                                   "value": got.get("value", ""), "ok": ok}
    return result


def main() -> None:
    config = load_config()
    pool = config["product_pool"]

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[dry-run] ✗ 未登录，先 `./run.sh login`")
            browser.close()
            sys.exit(1)

        # 1) 打开产品池 + 切美区/多渠道
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        if not is_logged_in(page):
            log("[dry-run] ✗ 跳转后登录态失效")
            browser.close()
            sys.exit(1)
        safe_click(page, SEL_TAB_US_POOL)
        page.wait_for_timeout(800)
        safe_click(page, SEL_TAB_CHANNEL)
        page.wait_for_timeout(800)

        # 2) 选品类（最多重试 3 次）
        for attempt in range(3):
            try:
                _open_category(page, config["category"]["system_path"])
                break
            except RuntimeError as e:
                log(f"[dry-run] 品类选中失败(第{attempt+1}次): {e}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
                if attempt == 2:
                    raise
        if pool.get("escape_after_select", True):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        safe_click(page, SEL_SEARCH_BTN)
        wait_network_idle_light(page)
        log(f"[dry-run] 已筛选类目: {config['category']['system_path'][-1]}")

        # 校验列表确实加载了目标类目的产品（防筛选未生效时误勾选全量）
        _verify_pool_category(page, config)

        # 等待表格行加载
        try:
            page.wait_for_selector(".vxe-table--body-wrapper tr", timeout=15000)
        except Exception:
            pass
        for _ in range(20):
            page.wait_for_timeout(500)
            if page.locator(SEL_TABLE).first.locator("tr").count() > 0:
                break

        # 3) 勾选首行（冻结左列 checkbox）
        frozen = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
        cb_td = frozen.first.locator("td.col--checkbox").first
        if not cb_td.count():
            cb_td = page.locator(SEL_TABLE).first.locator("tr").first \
                .locator("td.col--checkbox").first
        checked = False
        for _ in range(3):
            cb_td.click(timeout=8000)
            page.wait_for_timeout(400)
            checked = cb_td.evaluate(
                """(td) => td.classList.contains('is--checked')
                    || !!td.querySelector('.is--checked, [aria-checked=true]')"""
            )
            if checked:
                break
            page.wait_for_timeout(600)
        if not checked:
            log("[dry-run] ✗ 首行勾选失败，中止")
            browser.close()
            sys.exit(1)
        log("[dry-run] ✓ 已勾选首行")

        # 4) 打开「直接加入上架计划」dialog（单行：点首行行内「加入上架计划」按钮）
        if not _open_plan_dialog_via_row(page, row_index=0):
            log("[dry-run] ✗ dialog 未弹出（时序问题），可重试运行")
            browser.close()
            sys.exit(1)
        page.wait_for_timeout(2000)
        log("[dry-run] ✓ dialog 已弹出")

        # 5) 填写表单（不点确定）
        log("[dry-run] 开始填写表单...")
        _fill_plan_form(page, config)

        # 6) 验证读回
        page.wait_for_timeout(800)
        result = _read_form_values(page, config)
        if "NO_DIALOG" in str(result.get("note", "")):
            log("[dry-run] ✗ 验证阶段 dialog 消失")
            browser.close()
            sys.exit(1)

        log("[dry-run] === 字段填写验证 ===")
        all_ok = True
        for label, f in result["fields"].items():
            mark = "✓" if f["ok"] else "✗"
            if not f["ok"]:
                all_ok = False
            log(f"[dry-run]   {mark} {label}: 期望 {f['want']!r} | "
                f"实际({f['ctrl']}) {f['value']!r}")
        log(f"[dry-run] === 验证{'全部通过' if all_ok else '存在未命中'} ===")

        # 7) 截图存档
        shot = ROOT / "runtime" / "dry_run_phase1_form.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[dry-run] 截图: {shot}")

        # 8) 关闭 dialog（Escape），不点「确定加入」→ 无数据提交
        page.keyboard.press("Escape")
        page.wait_for_timeout(1500)
        log("[dry-run] 已关闭 dialog（未点「确定加入」，无数据提交）")

        browser.close()
        sys.exit(0 if all_ok else 2)


if __name__ == "__main__":
    main()