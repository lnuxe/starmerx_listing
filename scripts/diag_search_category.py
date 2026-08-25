"""诊断脚本 v5：验证 el-cascader 品类选择器「输入品类名+回车」搜索式选中。

核心假设（用户指出）：品类选择器支持 filterable 搜索，向 el-cascader__search-input
输入叶子名 + 回车，可直接过滤并选中叶子，比逐级点击级联节点更稳定。

本脚本：
  1. 打开美区产品池
  2. 若品类 disabled，尝试先解锁（开发负责人）
  3. 展开品类选择器，找 el-cascader__search-input
  4. 输入「圣诞节花环」+ 回车，检查是否回填选中
  5. 截图供人工确认

全程只读，不修改数据。
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light

LEAF = "圣诞节花环"


def _find_vis_cascader(page):
    """返回可见且 placeholder 含「品类」的 el-cascader 容器信息。"""
    return page.evaluate(
        """() => {
            const cands = [];
            document.querySelectorAll('.el-cascader').forEach((c) => {
                const inp = c.querySelector('.el-input__inner');
                const ph = (inp && inp.placeholder) || '';
                const r = c.getBoundingClientRect();
                if (!ph.includes('品类')) return;
                if (c.offsetParent === null || r.width === 0) return;
                const disabled = c.classList.contains('is-disabled')
                    || (c.querySelector('.el-input') || {}).classList?.contains('is-disabled');
                cands.push({
                    x: Math.round(r.x + r.width / 2),
                    y: Math.round(r.y + r.height / 2),
                    disabled: !!disabled,
                    val: (inp && inp.value) || ''
                });
            });
            cands.sort((a, b) => (a.disabled - b.disabled) || (a.y - b.y));
            return cands[0] || null;
        }"""
    )


def _cat_value(page):
    """读品类选择器展示值（优先 input value，其次 tags 文本）。"""
    return page.evaluate(
        """() => {
            const cands = [];
            document.querySelectorAll('.el-cascader').forEach((c) => {
                const inp = c.querySelector('.el-input__inner');
                const ph = (inp && inp.placeholder) || '';
                const r = c.getBoundingClientRect();
                if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) {
                    let v = (inp && inp.value) || '';
                    // 若 value 为空，读 tags 标签文本
                    if (!v) {
                        const tags = [...c.querySelectorAll('.el-cascader__tags .el-tag, .el-cascader__tags span, .el-cascader__tags')]
                            .map(t => (t.innerText||'').trim()).filter(Boolean);
                        if (tags.length) v = tags.join(' | ');
                    }
                    cands.push(v || (inp && inp.value) || '');
                }
            });
            return cands[0] || '';
        }"""
    )


def _unlock_category(page) -> bool:
    """品类 disabled 时，点「开发负责人」选第一个尝试解锁。"""
    try:
        wrapper = page.locator(".el-select").filter(
            has=page.locator(".el-input__inner[placeholder='开发负责人']")
        ).filter(visible=True).first
        wrapper.wait_for(state="visible", timeout=10000)
        wrapper.click(timeout=8000)
        page.wait_for_timeout(2000)
        item = page.locator(".el-select-dropdown__item").filter(visible=True).first
        item.wait_for(state="visible", timeout=8000)
        txt = (item.inner_text() or "").strip()
        item.click(timeout=5000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        log(f"[diag5] ✓ 已选开发负责人: {txt}")
        return True
    except Exception as e:
        log(f"[diag5] ✗ 解锁失败: {e}")
        return False


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag5] ✗ 未登录")
            browser.close()
            sys.exit(1)

        pool = config["product_pool"]
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(2500)

        # 切美区
        page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('.el-tabs__item')]
                    .find(e => (e.innerText||'').includes('美区产品池'));
                if (el && !el.className.includes('is-active')) el.click();
            }"""
        )
        page.wait_for_timeout(2500)

        # 品类 enabled 检查 / 解锁
        cat = _find_vis_cascader(page)
        log(f"[diag5] 品类选择器: {cat}")
        if cat and cat["disabled"]:
            log("[diag5] 品类 disabled，尝试解锁")
            _unlock_category(page)
            page.wait_for_timeout(1500)
            cat = _find_vis_cascader(page)
            log(f"[diag5] 解锁后: {cat}")

        if not cat or cat["disabled"]:
            log("[diag5] ✗ 品类仍 disabled，无法展开")
            page.screenshot(path=str(ROOT / "runtime" / "diag5_disabled.png"), full_page=True)
            browser.close()
            sys.exit(1)

        # 点击展开品类
        page.mouse.click(cat["x"], cat["y"])
        page.wait_for_timeout(1500)

        # dump 搜索框属性 + 展开面板结构（过滤前）
        search_info = page.evaluate(
            """() => {
                // 先找「品类」cascader 容器
                let catCasc = null;
                document.querySelectorAll('.el-cascader').forEach((c) => {
                    const inp = c.querySelector('.el-input__inner');
                    const ph = (inp && inp.placeholder) || '';
                    const r = c.getBoundingClientRect();
                    if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) catCasc = c;
                });
                if (!catCasc) return { note: 'no-cat-cascader' };
                // 品类 cascader 内部是否有 search-input
                const sIn = catCasc.querySelector('.el-cascader__search-input');
                const out = { catNote: 'found-cat-cascader' };
                if (sIn) {
                    const r = sIn.getBoundingClientRect();
                    out.searchInCat = {
                        ph: sIn.placeholder || '',
                        visible: sIn.offsetParent !== null && r.width > 0,
                        rect: [Math.round(r.x), Math.round(r.y)]
                    };
                } else {
                    out.searchInCat = null;
                }
                // 全局有哪些 search-input，分别属于哪个 cascader
                out.allSearch = [];
                document.querySelectorAll('.el-cascader__search-input').forEach((si, i) => {
                    const r = si.getBoundingClientRect();
                    // 向上找最近的 el-cascader，取其 placeholder
                    let c = si.closest('.el-cascader');
                    const ph = (c && c.querySelector('.el-input__inner')?.placeholder) || '';
                    out.allSearch.push({
                        i, ph, vis: si.offsetParent !== null && r.width > 0,
                        rect: [Math.round(r.x), Math.round(r.y)]
                    });
                });
                return out;
            }"""
        )
        log(f"[diag5] 搜索框归属分析: {search_info}")

        # dump 展开后所有可见节点（过滤前，含层级）
        pre_nodes = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-cascader-node').forEach((n) => {
                    const r = n.getBoundingClientRect();
                    if (n.offsetParent === null || r.width === 0) return;
                    const t = (n.innerText||'').trim().replace(/\\s+/g,' ');
                    if (t) out.push(t.slice(0, 30));
                });
                return out;
            }"""
        )
        log(f"[diag5] 过滤前可见节点({len(pre_nodes)}): {pre_nodes[:15]}")

        has_search = bool(
            search_info
            and search_info != "no-search"
            and search_info.get("searchInCat")
            and search_info["searchInCat"].get("visible")
        )
        log(f"[diag5] has_search(品类内搜索框可见): {has_search}")

        if has_search:
            # 精确定位「品类」cascader 内部的搜索框（页面有多个 search-input，不能取 .first）
            # 用坐标点击品类搜索框（rect [95,246]），再 fill
            cat_rect = search_info["searchInCat"]["rect"]
            try:
                page.mouse.click(cat_rect[0] + 40, cat_rect[1] + 8)
                page.wait_for_timeout(400)
                # 品类搜索框 fill
                filled = page.evaluate(
                    """(leaf) => {
                        let catCasc = null;
                        document.querySelectorAll('.el-cascader').forEach((c) => {
                            const inp = c.querySelector('.el-input__inner');
                            const ph = (inp && inp.placeholder) || '';
                            const r = c.getBoundingClientRect();
                            if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) catCasc = c;
                        });
                        const si = catCasc && catCasc.querySelector('.el-cascader__search-input');
                        if (!si) return 'no-search-input';
                        // 用原生 setter 设值 + 触发 input（element-plus 搜索用 input 事件）
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(si, leaf);
                        si.dispatchEvent(new Event('input', { bubbles: true }));
                        return 'set:' + si.value;
                    }""",
                    LEAF,
                )
                log(f"[diag5] 品类搜索框 fill: {filled}")
                page.wait_for_timeout(1500)
            except Exception as e:
                log(f"[diag5] 品类搜索框操作失败: {e}")

            # 读品类搜索框实际值
            real_val = page.evaluate(
                """() => {
                    let catCasc = null;
                    document.querySelectorAll('.el-cascader').forEach((c) => {
                        const inp = c.querySelector('.el-input__inner');
                        const ph = (inp && inp.placeholder) || '';
                        const r = c.getBoundingClientRect();
                        if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) catCasc = c;
                    });
                    const si = catCasc && catCasc.querySelector('.el-cascader__search-input');
                    return si ? si.value : 'no-input';
                }"""
            )
            log(f"[diag5] 品类搜索框实际值: {real_val!r}")

            # 截图看过滤结果
            page.screenshot(path=str(ROOT / "runtime" / "diag5_search_input.png"), full_page=True)

            # dump 过滤后整个面板文本（看是否有匹配结果）
            after_panel = page.evaluate(
                """() => {
                    const panels = [...document.querySelectorAll('.el-cascader-panel, .el-cascader__dropdown, .el-popper')]
                        .filter(p => p.offsetParent !== null && p.getBoundingClientRect().width > 0);
                    return panels.map(p => (p.innerText||'').trim().replace(/\\n+/g,' | ').slice(0,200)).join('\\n');
                }"""
            )
            log(f"[diag5] 过滤后(「{LEAF}」)面板文本: {after_panel!r}")

            # dump 过滤后可见节点
            nodes = page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('.el-cascader-node').forEach((n) => {
                        const r = n.getBoundingClientRect();
                        if (n.offsetParent === null || r.width === 0) return;
                        const t = (n.innerText||'').trim().replace(/\\s+/g,' ');
                        if (t) out.push(t.slice(0, 50));
                    });
                    return out;
                }"""
            )
            log(f"[diag5] 过滤后可见节点: {nodes}")

            # dump 含叶子的可点击元素结构（过滤结果渲染结构分析）
            struct = page.evaluate(
                """(leaf) => {
                    const out = [];
                    // 找包含叶子文本的最内层可交互元素（无子元素，且文本最短=最内层叶子）
                    const all = [...document.querySelectorAll('.el-cascader__dropdown *, .el-cascader-panel *, .el-cascader-menu *, .el-popper *')];
                    all.forEach((e) => {
                        const r = e.getBoundingClientRect();
                        if (e.offsetParent === null || r.width === 0) return;
                        const t = (e.innerText||'').trim().replace(/\\s+/g,' ');
                        // 无子元素且含叶子文本（过滤结果叶子项），只取 text 最短的最内层
                        if (e.children.length === 0 && t.includes(leaf) && t.length <= 60) {
                            let cls = '';
                            let n = e;
                            for (let k=0;k<5 && n;k++){ cls += (n.className||'').toString().slice(0,45)+' > '; n=n.parentElement; }
                            out.push({tag: e.tagName, text: t.slice(0,40), cls: cls.slice(0,140), rect:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]});
                        }
                    });
                    // 按 text 长度升序（最内层优先）
                    out.sort((a,b)=>a.text.length-b.text.length);
                    return out.slice(0,5);
                }""",
                LEAF,
            )
            log(f"[diag5] 含叶子文本的可点击元素: {struct}")

            # 尝试点击含叶子的最内层文本节点
            if struct:
                rect = struct[0]["rect"]
                log(f"[diag5] 点击叶子元素 rect={rect} text={struct[0]['text']!r}")
                page.mouse.click(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
                page.wait_for_timeout(1500)
                val = _cat_value(page)
                log(f"[diag5] 点击叶子文本后品类值: 「{val}」")
                page.screenshot(path=str(ROOT / "runtime" / "diag5_after_click.png"), full_page=True)
            else:
                log("[diag5] 未找到叶子文本节点，尝试回车")
                page.keyboard.press("Enter")
                page.wait_for_timeout(1500)
                val = _cat_value(page)
                log(f"[diag5] 回车后品类值: 「{val}」")
                page.screenshot(path=str(ROOT / "runtime" / "diag5_after_enter.png"), full_page=True)
        else:
            log("[diag5] ✗ 品类内未找到可见搜索框，dump 面板结构")
            page.screenshot(path=str(ROOT / "runtime" / "diag5_no_search.png"), full_page=True)

        # ===== 验证：若品类已回填，点「搜索」看记录数（确认筛选生效）=====
        cat_now = _cat_value(page)
        log(f"[diag5] 最终品类值: 「{cat_now}」")
        if cat_now and "圣诞节花环" in cat_now:
            # 点「搜索」按钮
            try:
                page.locator("button:has-text('搜索')").first.click(timeout=8000)
                page.wait_for_timeout(3000)
                page.wait_for_timeout(2000)
                # 读记录总数（底部 共 X 条记录）
                total = page.evaluate(
                    """() => {
                        const t = (document.body.innerText||'');
                        const m = t.match(/共\\s*([\\d,]+)\\s*条记录/);
                        return m ? m[1] : (t.match(/共\\s*([\\d,]+)\\s*条/)?.[1] || '?');
                    }"""
                )
                log(f"[diag5] 点搜索后共 {total} 条记录")
                page.screenshot(path=str(ROOT / "runtime" / "diag5_searched.png"), full_page=True)
            except Exception as e:
                log(f"[diag5] 点搜索失败: {e}")
        else:
            log("[diag5] 品类未成功回填，跳过搜索验证")

        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()