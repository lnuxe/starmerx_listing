"""勘察 el-cascader 品类选择器 DOM 结构。

用法: .venv/bin/python -m scripts.probe_cascader
目的：确认 el-cascader 的真实层级，找到展开面板、选项节点、搜索框的可点击定位方式，
从而修复 phase1 中品类选择被内部 search-input 拦截的问题。
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light

SEL_TAB_US_POOL = "text=美区产品池"
SEL_CATEGORY = "input[placeholder*='品类']"


def _dump_cascader(page, label: str) -> None:
    """dump 页面中 el-cascader 相关元素的 DOM 结构。"""
    try:
        html = page.evaluate(
            """() => {
                const out = [];
                const containers = document.querySelectorAll('.el-cascader');
                containers.forEach((c, i) => {
                    const r = c.getBoundingClientRect();
                    const inner = c.querySelector('.el-input__inner');
                    out.push(
                        `[cascader#${i}] cls="${(c.className||'').slice(0,60)}"`
                        + ` rect=(${Math.round(r.x)},${Math.round(r.y)},${Math.round(r.width)},${Math.round(r.height)})`
                        + ` innerValue="${inner ? inner.value : ''}"`
                    );
                    // 其下的 input
                    c.querySelectorAll('input').forEach((inp, j) => {
                        out.push(`    input#${j} cls="${(inp.className||'').slice(0,50)}" placeholder="${inp.placeholder||''}" value="${inp.value||''}"`);
                    });
                });
                return out.join('\\n') || '(无 .el-cascader 容器)';
            }"""
        )
        log(f"[probe] {label}:\n{html}")
    except Exception as e:
        log(f"[probe] dump 失败 {label}: {e}")


def _click_category_open(page) -> None:
    """点击品类选择器（可见的 el-cascader 容器）展开面板。"""
    # 用 JS 定位：所有 .el-cascader 中，可见且其 input placeholder 含"品类"的容器中心
    info = page.evaluate(
        """() => {
            const cands = [];
            document.querySelectorAll('.el-cascader').forEach((c, i) => {
                const inp = c.querySelector('.el-input__inner');
                const ph = (inp && inp.placeholder) || '';
                if (!ph.includes('品类')) return;
                const r = c.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;   // 隐藏
                const disabled = c.classList.contains('is-disabled');
                cands.push({i, x: r.x + r.width/2, y: r.y + r.height/2, disabled,
                            w: r.width, ph});
            });
            return cands;
        }"""
    )
    log(f"[probe] 品类 cascader 候选: {info}")
    if not isinstance(info, list) or not info:
        log("[probe] ✗ 未找到可见品类 cascader")
        return False
    # 优先选非 disabled 且尺寸合理的
    info.sort(key=lambda c: (c["disabled"], -c["w"]))
    t = info[0]
    page.mouse.click(t["x"], t["y"])
    log(f"[probe] 已鼠标点击品类 cascader#({t['i']}) 中心 ({round(t['x'])},{round(t['y'])})")
    page.wait_for_timeout(1500)
    return True


def _dump_dropdown_panel(page) -> None:
    """dump 展开后的下拉面板选项结构。"""
    try:
        html = page.evaluate(
            """() => {
                const out = [];
                // 遍历所有 el-popper / el-popover，找出可见的面板
                const pops = document.querySelectorAll('.el-popper, .el-popover, .el-cascader__dropdown, .el-cascader-panel');
                pops.forEach((pop, i) => {
                    const r = pop.getBoundingClientRect();
                    const vis = pop.offsetParent !== null;
                    if (!vis || (r.width === 0 && r.height === 0)) return;
                    const hasNodes = pop.querySelectorAll('.el-cascader-node, .el-cascader-menu__item').length;
                    out.push(`[面板#${i}] cls="${(pop.className||'').slice(0,60)}" rect=(${Math.round(r.x)},${Math.round(r.y)},${Math.round(r.width)},${Math.round(r.height)}) 级联节点=${hasNodes}`);
                });
                if (!out.length) out.push('(无可见面板)');
                // 可见级联节点
                const nodes = document.querySelectorAll('.el-cascader-node');
                let cnt = 0;
                nodes.forEach((nd, i) => {
                    const r = nd.getBoundingClientRect();
                    if (r.width === 0 && r.height === 0) return;
                    const txt = (nd.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
                    if (!txt) return;
                    cnt++;
                    const leaf = nd.className.includes('is-leaf') || !nd.querySelector('.el-cascader-node__postfix, .el-icon--right');
                    out.push(`  node#${i} ${leaf ? '[末级]' : '[有子级]'} "${txt}"`);
                });
                if (cnt) out.push(`  (共 ${cnt} 个可见节点)`);
                return out.join('\\n');
            }"""
        )
        log(f"[probe] 下拉面板:\n{html}")
    except Exception as e:
        log(f"[probe] 面板 dump 失败: {e}")


def _click_cascader_node(page, text: str) -> bool:
    """点击级联面板中指定文本的节点（可见的 .el-cascader-node）。"""
    # 找到文本匹配且可见的节点
    sel = f".el-cascader-node:has-text('{text}')"
    loc = page.locator(sel).filter(visible=True).first
    if not loc.count():
        log(f"[probe] ✗ 未找到可见节点「{text}」")
        return False
    try:
        loc.click(timeout=5000)
        log(f"[probe] ✓ 点击节点「{text}」")
        page.wait_for_timeout(800)
        return True
    except Exception as e:
        log(f"[probe] ✗ 点击节点「{text}」失败: {str(e)[:60]}")
        return False


def _dump_current_level(page, label: str) -> None:
    """dump 当前展开层级的所有可见节点文本。"""
    try:
        txts = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-cascader-node').forEach((nd) => {
                    const r = nd.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    const t = (nd.innerText || '').trim().replace(/\\s+/g, ' ');
                    if (t) out.push(t.slice(0, 40));
                });
                return out;
            }"""
        )
        log(f"[probe] {label} 层级节点: {txts}")
    except Exception as e:
        log(f"[probe] {label} dump 失败: {e}")


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        url = config["product_pool"]["url"]
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(2500)
        log(f"[probe] URL: {page.url}")
        if not is_logged_in(page):
            log("[probe] ✗ 未登录")
            browser.close()
            return

        us_tab = page.locator(SEL_TAB_US_POOL).first
        if us_tab.count():
            us_tab.click(timeout=8000)
            page.wait_for_timeout(2500)
            log("[probe] 已点击美区产品池标签")

        ok = _click_category_open(page)
        if not ok:
            browser.close()
            return

        # 逐级选择品类路径
        path = config["category"]["system_path"]  # 家居、厨具、家装 → 节日饰品 → 圣诞花环、花带装饰和垂花饰 → 圣诞花带装饰
        for idx, node_text in enumerate(path):
            _dump_current_level(page, f"第{idx+1}级")
            if not _click_cascader_node(page, node_text):
                log(f"[probe] ✗ 第{idx+1}级「{node_text}」选择失败，中止")
                break
            _dump_current_level(page, f"第{idx+1}级点击后")

        # 关闭下拉并截图
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        shot = ROOT / "runtime" / "probe_cascader_path.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[probe] 截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()