"""勘察：有头模式枚举叶子 + 逐叶测数据量。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light
from src.phase1 import (
    SEL_TAB_US_POOL, SEL_TAB_CHANNEL, SEL_SEARCH_BTN, SEL_TABLE,
)

CAT_L2 = "圣诞花环、花带装饰和垂花饰"


def cat_target(page):
    """返回品类级联容器中心坐标。"""
    return page.evaluate(
        """() => {
            const cands = [];
            document.querySelectorAll('.el-cascader').forEach((c, i) => {
                const inp = c.querySelector('.el-input__inner');
                const ph = (inp && inp.placeholder) || '';
                if (!ph.includes('品类')) return;
                const r = c.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                cands.push({x: r.x + r.width/2, y: r.y + r.height/2, w: r.width,
                            disabled: c.classList.contains('is-disabled')});
            });
            cands.sort((a,b)=>(a.disabled-b.disabled)||(b.w-a.w));
            return cands[0] || null;
        }"""
    )


def click_node(page, text):
    """点击包含 text 的可见级联节点（用 Playwright locator，与 phase1 一致）。"""
    from src.phase1 import SEL_CATEGORY_NODE
    loc = page.locator(SEL_CATEGORY_NODE).filter(has_text=text).filter(visible=True).first
    try:
        loc.click(timeout=8000)
        return True
    except Exception as e:
        log(f"click_node「{text}」: {e}")
        return False


def read_cat(page):
    """读取品类输入框当前值。"""
    return page.evaluate(
        """() => { const c = document.querySelector('.el-cascader .el-input__inner'); return c ? c.value : null; }"""
    )


def dump_leaves(page):
    """返回当前第三级面板下的叶子节点文本（★ 前缀标记叶子）。"""
    return page.evaluate(
        """() => {
            const ns = document.querySelectorAll('.el-cascader-node');
            const arr = [...ns].filter(n => n.offsetParent !== null);
            return arr.map(n => {
                const has_arrow = !!n.querySelector('.el-cascader-node__postfix, .el-icon-arrow-right, .el-cascader-node__prefix');
                const txt = (n.innerText||'').trim().split('\\n')[0];
                return (has_arrow ? '' : '★') + txt;
            }).filter(Boolean).slice(0, 80);
        }"""
    )


def open_pool(page, config):
    pool = config["product_pool"]
    page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
    wait_network_idle_light(page)
    page.click(SEL_TAB_US_POOL)
    page.wait_for_timeout(1200)
    try:
        page.click(SEL_TAB_CHANNEL, timeout=5000)
    except Exception as e:
        log(f"点「多渠道」失败(可能已默认选中): {str(e)[:80]}")
    page.wait_for_timeout(1200)


def expand_to_l2(page):
    """展开级联到第三级父节点「圣诞花环、花带装饰和垂花饰」。"""
    t = cat_target(page)
    if not t:
        log("✗ 无品类容器")
        return False
    page.mouse.click(t["x"], t["y"])
    page.wait_for_timeout(1800)
    log(f"展开后可见级联节点: {dump_leaves(page)}")
    for txt in ["家居、厨具、家装", "节日饰品", CAT_L2]:
        if not click_node(page, txt):
            log(f"✗ 点击「{txt}」失败")
            return False
        page.wait_for_timeout(1200)
    return True


def count_rows(page) -> int:
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    page.click(SEL_SEARCH_BTN)
    page.wait_for_timeout(4000)
    table = page.locator(SEL_TABLE).first
    return table.locator("tr").count()


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录")
            browser.close()
            sys.exit(1)
        open_pool(page, config)

        if not expand_to_l2(page):
            browser.close()
            sys.exit(1)
        leaves = dump_leaves(page)
        leaf_names = [l.lstrip("★") for l in leaves]
        log(f"=== 第三级「{CAT_L2}」下叶子节点({len(leaf_names)}) ===")
        for l in leaves:
            log(l)

        # 对每个叶子：新开页面 → 展开到第三级 → 点叶子 → 读回填 → 搜索 → 数行
        for name in leaf_names:
            if name in ("圣诞花环、花带装饰和垂花饰", "家居、厨具、家装", "节日饰品"):
                continue
            browser.close()
            browser, context = _open_context(p, config, headless=True,
                                             storage=ROOT / config["app"]["storage_state"])
            page = context.new_page()
            open_pool(page, config)
            if not expand_to_l2(page):
                browser.close()
                continue
            if not click_node(page, name):
                log(f"✗ 点叶子「{name}」失败")
                browser.close()
                continue
            page.wait_for_timeout(1000)
            val = read_cat(page)
            n = count_rows(page)
            log(f">>> 叶子「{name}」: 回填={val!r} 搜索后行数={n}")

        browser.close()
        log("完成")


if __name__ == "__main__":
    main()