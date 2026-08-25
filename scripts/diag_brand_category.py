"""诊断：品牌下拉全部选项 + 产品类目 cascader 在无干扰下的选择逻辑。

目的：
  1) 完整 dump 品牌 el-select 下拉的所有选项（含滚动到底），确认是否有「无品牌」。
  2) 独立测试产品类目 cascader：先确保品牌面板收起，再验证逐级点击能否选中
     platform_path = Home Supplies → Festive & Party Supplies → Festive Decorations
     → Wreaths, Garlands & Swags。
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
                        _open_category, SEL_TABLE)


def _dialog(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('.el-dialog')]
            .find(d => d.offsetParent !== null
                || d.getBoundingClientRect().width > 100)"""
    )


def _click_form_ctrl(page, label: str, cls: str) -> bool:
    """点击 dialog 内指定 label 的控件中心（cls ∈ el-select/el-cascader/input）。"""
    r = page.evaluate(
        """(args) => {
            const [label, cls] = args;
            const dlg = [...document.querySelectorAll('.el-dialog')]
                .find(d => d.offsetParent !== null
                    || d.getBoundingClientRect().width > 100);
            if (!dlg) return null;
            const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                const l = fi.querySelector('.el-form-item__label, label');
                return l && (l.innerText || '').trim() === label;
            });
            const c = f && f.querySelector(cls);
            if (!c) return null;
            const r = c.getBoundingClientRect();
            return {x: Math.round(r.x + r.width / 2),
                    y: Math.round(r.y + r.height / 2)};
        }""",
        [label, cls],
    )
    if not r:
        return False
    page.mouse.click(r["x"], r["y"])
    page.wait_for_timeout(900)
    return True


def _dump_visible_selects(page) -> list:
    """dump 所有可见 el-select 下拉的选项文本。"""
    return page.evaluate(
        """() => {
            const panels = [...document.querySelectorAll('.el-select-dropdown')]
                .filter(s => { const r = s.getBoundingClientRect();
                               return r.width > 0 && r.height > 0; });
            return panels.map(p => [...p.querySelectorAll('.el-select-dropdown__item')]
                .map(li => (li.innerText || '').trim().replace(/\\s+/g, ' ')));
        }"""
    )


def _dump_cascader_menus(page) -> list:
    """dump 所有可见 cascader 菜单层的节点文本。"""
    return page.evaluate(
        """() => {
            const menus = [...document.querySelectorAll('.el-cascader-menu')]
                .filter(m => { const r = m.getBoundingClientRect();
                               return r.width > 0 && r.height > 0; });
            return menus.map(m => [...m.querySelectorAll('.el-cascader-node')]
                .map(n => (n.querySelector('.el-cascader-node__label') ||
                    n).innerText.trim().replace(/\\s+/g, ' ')));
        }"""
    )


def main() -> None:
    config = load_config()
    pool = config["product_pool"]

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag] ✗ 未登录")
            browser.close()
            sys.exit(1)

        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        safe_click(page, SEL_TAB_US_POOL)
        page.wait_for_timeout(800)
        safe_click(page, SEL_TAB_CHANNEL)
        page.wait_for_timeout(800)
        for attempt in range(3):
            try:
                _open_category(page, config["category"]["system_path"])
                break
            except RuntimeError as e:
                log(f"[diag] 品类选中失败(第{attempt+1}次): {e}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        if pool.get("escape_after_select", True):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        safe_click(page, SEL_SEARCH_BTN)
        wait_network_idle_light(page)
        try:
            page.wait_for_selector(".vxe-table--body-wrapper tr", timeout=15000)
        except Exception:
            pass
        for _ in range(20):
            page.wait_for_timeout(500)
            if page.locator(SEL_TABLE).first.locator("tr").count() > 0:
                break

        # 勾选首行
        frozen = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
        cb_td = frozen.first.locator("td.col--checkbox").first
        if not cb_td.count():
            cb_td = page.locator(SEL_TABLE).first.locator("tr").first \
                .locator("td.col--checkbox").first
        for _ in range(3):
            cb_td.click(timeout=8000)
            page.wait_for_timeout(400)
            if cb_td.evaluate(
                """(td) => td.classList.contains('is--checked')
                    || !!td.querySelector('.is--checked, [aria-checked=true]')"""
            ):
                break
            page.wait_for_timeout(600)

        # 打开 dialog
        trig = page.locator("button.el-dropdown-selfdefine").first
        trig.click(timeout=8000)
        page.wait_for_timeout(800)
        li = page.evaluate(
            """() => {
                const it = [...document.querySelectorAll('.el-dropdown-menu__item')]
                    .find(x => (x.innerText || '').trim() === '直接加入上架计划');
                if (!it) return null;
                const r = it.getBoundingClientRect();
                return {x: Math.round(r.x + r.width / 2),
                        y: Math.round(r.y + r.height / 2)};
            }"""
        )
        page.mouse.click(li["x"], li["y"])
        for _ in range(20):
            page.wait_for_timeout(1000)
            if _dialog(page):
                break
        page.wait_for_timeout(2000)
        log("[diag] dialog 已弹出")

        # ── ① 品牌下拉全量 dump ──
        log("[diag] ── ① 品牌下拉全量选项 ──")
        _click_form_ctrl(page, "品牌", ".el-select")
        page.wait_for_timeout(600)
        # 滚动到底收集全部选项
        all_items = page.evaluate(
            """() => {
                const panels = [...document.querySelectorAll('.el-select-dropdown')]
                    .filter(s => { const r = s.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; });
                if (!panels.length) return 'NO_PANEL';
                const panel = panels[0];
                const scrollEl = panel.querySelector('.el-select-dropdown__wrap')
                    || panel;
                const out = [];
                let last = -1;
                for (let i = 0; i < 50; i++) {
                    const items = [...panel.querySelectorAll('.el-select-dropdown__item')]
                        .map(li => (li.innerText || '').trim().replace(/\\s+/g, ' '));
                    out.push(...items);
                    const sh = scrollEl.scrollTop;
                    scrollEl.scrollTop = sh + 500;
                    if (scrollEl.scrollTop === sh) break;
                }
                return [...new Set(out)];
            }"""
        )
        log(f"[diag] 品牌全部选项({len(all_items) if isinstance(all_items, list) else '?'}): "
            f"{all_items}")
        # 是否有「无品牌」
        if isinstance(all_items, list):
            hit = [x for x in all_items if "无品牌" in x or x.strip() == ""]
            log(f"[diag] 「无品牌」命中: {hit if hit else '❌ 下拉中无「无品牌」'}")
        # 收起品牌面板：点击 dialog 标题（安全，不关 dialog）
        page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null
                        || d.getBoundingClientRect().width > 100);
                const hd = dlg && dlg.querySelector('.el-dialog__header,.el-dialog__title');
                if (hd) { const r = hd.getBoundingClientRect();
                    window.__clx = r.x + Math.min(r.width / 2, 120);
                    window.__cly = r.y + r.height / 2; }
            }"""
        )
        try:
            page.mouse.click(page.evaluate("window.__clx"), page.evaluate("window.__cly"))
        except Exception:
            pass
        page.wait_for_timeout(500)
        log(f"[diag] 品牌面板收起后可见下拉: {_dump_visible_selects(page)}")

        # ── ② 产品类目 cascader：dump 第1级菜单节点精确 innerText ──
        log("[diag] ── ② 产品类目 cascader 菜单结构 ──")
        _click_form_ctrl(page, "产品类目", ".el-cascader")
        page.wait_for_timeout(1200)
        detail = page.evaluate(
            """() => {
                const menus = [...document.querySelectorAll('.el-cascader-menu')]
                    .filter(m => { const r = m.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; });
                const nodes = menus.length ? [...menus[0].querySelectorAll('.el-cascader-node')]
                    .map(n => {
                        const lbl = n.querySelector('.el-cascader-node__label') || n;
                        return { text: lbl.innerText, len: lbl.innerText.length };
                    }) : [];
                const hasSearch = [...document.querySelectorAll(
                    '.el-cascader__dropdown, .el-cascader-panel')]
                    .filter(s => { const r = s.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; })
                    .some(d => !!d.querySelector('.el-cascader__search-input'));
                const allMenus = menus.map(m => [...m.querySelectorAll('.el-cascader-node')]
                    .map(n => (n.querySelector('.el-cascader-node__label') || n)
                        .innerText.trim().replace(/\\s+/g, ' ')));
                return { nodes, hasSearch, allMenus, menusCount: menus.length };
            }"""
        )
        log(f"[diag] cascader 菜单数: {detail.get('menusCount')} | 有搜索框: {detail.get('hasSearch')}")
        log(f"[diag] 各菜单层: {detail.get('allMenus')}")
        for n in detail.get("nodes", []):
            log(f"[diag]   节点 text={n['text']!r} len={n['len']}")

        # 若支持搜索，尝试搜索式选中叶子
        if detail.get("hasSearch"):
            leaf = config["category"]["platform_path"][-1]
            log(f"[diag] 搜索式选中叶子「{leaf}」")
            try:
                page.locator(".el-cascader__dropdown .el-cascader__search-input, "
                              ".el-cascader-panel .el-cascader__search-input").first \
                    .click(timeout=5000)
                page.wait_for_timeout(400)
                page.keyboard.type(leaf)
                page.wait_for_timeout(1500)
                sug = page.evaluate(
                    """(leaf) => {
                        const out = [];
                        document.querySelectorAll('.el-cascader__suggestion-item').forEach(e => {
                            const r = e.getBoundingClientRect();
                            if (e.offsetParent === null || r.width === 0) return;
                            const t = (e.innerText || '').trim().replace(/\\s+/g, ' ');
                            if (t.includes(leaf) && t.length <= 80)
                                out.push({t, x: Math.round(r.x + r.width / 2),
                                          y: Math.round(r.y + r.height / 2)});
                        });
                        out.sort((a, b) => a.t.length - b.t.length);
                        return out[0] || null;
                    }""",
                    leaf,
                )
                if sug:
                    log(f"[diag] 搜索式命中: {sug['t']!r}")
                    page.mouse.click(sug["x"], sug["y"])
                    page.wait_for_timeout(800)
                else:
                    sugs = page.evaluate(
                        """() => [...document.querySelectorAll('.el-cascader__suggestion-item')]
                            .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' '))"""
                    )
                    log(f"[diag] ✗ 搜索式无建议项, 当前suggestion: {sugs}")
            except Exception as e:
                log(f"[diag] 搜索式失败: {e}")
        else:
            log("[diag] ✗ cascader 无搜索框，需逐级点击")

        # 读回产品类目最终值
        val = page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null
                        || d.getBoundingClientRect().width > 100);
                const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                    const l = fi.querySelector('.el-form-item__label, label');
                    return l && (l.innerText || '').trim() === '产品类目';
                });
                const w = f && (f.querySelector('.el-cascader__tags-text')
                    || f.querySelector('.el-cascader__selected-item')
                    || f.querySelector('.el-input__inner'));
                return w ? (w.innerText || w.value || '').trim() : '';
            }"""
        )
        log(f"[diag] 产品类目最终值: {val!r}")

        shot = ROOT / "runtime" / "diag_brand_category.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[diag] 截图: {shot}")

        browser.close()


if __name__ == "__main__":
    main()