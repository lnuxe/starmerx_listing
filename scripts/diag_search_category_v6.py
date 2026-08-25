"""诊断脚本 v6：确认搜索式选中后品类路径的 DOM 展示来源，并验证点搜索能搜出记录。

v5 已证明：fill「圣诞节花环」→ 点击 suggestion-item → 品类回填完整路径。
但 _cat_value 读到空格（读 .el-input__inner.value 不匹配选中态）。

本脚本：
  1. 搜索式选中「圣诞节花环」
  2. dump 选中后品类输入框区域的完整 DOM（找出路径文本实际渲染元素）
  3. 修正品类值读取：读选中态展示文本
  4. 点「搜索」按钮，验证记录数 > 0（筛选闭环）
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light

LEAF = "圣诞节花环"


def _cat_value(page):
    """读品类选中态展示路径文本（优先读 el-input__inner value，否则读选中态容器文本）。"""
    return page.evaluate(
        """() => {
            const cands = [];
            document.querySelectorAll('.el-cascader').forEach((c) => {
                const inp = c.querySelector('.el-input__inner');
                const ph = (inp && inp.placeholder) || '';
                const r = c.getBoundingClientRect();
                if (!ph.includes('品类')) return;
                if (c.offsetParent === null || r.width === 0) return;
                // 1) input value
                let v = (inp && inp.value) || '';
                // 2) 选中态展示（el-cascader__tags 或 input 的父容器渲染路径）
                if (!v) {
                    const tag = c.querySelector('.el-cascader__tags');
                    if (tag) v = (tag.innerText||'').trim().replace(/\\s+/g,' ');
                }
                if (!v) {
                    // 3) 兜底：input 父 el-input 的 textContent
                    const wrap = inp && inp.closest('.el-input');
                    if (wrap) v = (wrap.innerText||'').trim().replace(/\\s+/g,' ');
                }
                cands.push(v);
            });
            return cands[0] || '';
        }"""
    )


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag6] ✗ 未登录")
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

        # 品类选择器（disabled 则解锁）
        cat = page.evaluate(
            """() => {
                const cands = [];
                document.querySelectorAll('.el-cascader').forEach((c) => {
                    const inp = c.querySelector('.el-input__inner');
                    const ph = (inp && inp.placeholder) || '';
                    const r = c.getBoundingClientRect();
                    if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) {
                        const disabled = c.classList.contains('is-disabled')
                            || (c.querySelector('.el-input') || {}).classList?.contains('is-disabled');
                        cands.push({x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), disabled: !!disabled});
                    }
                });
                cands.sort((a,b)=>(a.disabled-b.disabled)||(a.y-b.y));
                return cands[0] || null;
            }"""
        )
        log(f"[diag6] 品类选择器: {cat}")
        if cat and cat["disabled"]:
            log("[diag6] 品类 disabled，尝试解锁")
            try:
                page.locator(".el-select").filter(
                    has=page.locator(".el-input__inner[placeholder='开发负责人']")
                ).filter(visible=True).first.click(timeout=8000)
                page.wait_for_timeout(2000)
                page.locator(".el-select-dropdown__item").filter(visible=True).first.click(timeout=8000)
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
            except Exception as e:
                log(f"[diag6] 解锁失败: {e}")
            cat = page.evaluate(
                """() => {
                    const cands = [];
                    document.querySelectorAll('.el-cascader').forEach((c) => {
                        const inp = c.querySelector('.el-input__inner');
                        const ph = (inp && inp.placeholder) || '';
                        const r = c.getBoundingClientRect();
                        if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) {
                            const disabled = c.classList.contains('is-disabled')
                                || (c.querySelector('.el-input') || {}).classList?.contains('is-disabled');
                            cands.push({x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), disabled: !!disabled});
                        }
                    });
                    cands.sort((a,b)=>(a.disabled-b.disabled)||(a.y-b.y));
                    return cands[0] || null;
                }"""
            )
            log(f"[diag6] 解锁后: {cat}")

        if not cat or cat["disabled"]:
            log("[diag6] ✗ 品类仍 disabled")
            browser.close()
            sys.exit(1)

        # 点击展开品类
        page.mouse.click(cat["x"], cat["y"])
        page.wait_for_timeout(1500)

        # 品类内搜索框 fill 叶子名
        page.locator(".el-cascader").filter(
            has=page.locator(".el-input__inner[placeholder='品类']")
        ).locator(".el-cascader__search-input").first.click(timeout=5000)
        page.wait_for_timeout(400)
        page.locator(".el-cascader").filter(
            has=page.locator(".el-input__inner[placeholder='品类']")
        ).locator(".el-cascader__search-input").first.fill(LEAF)
        page.wait_for_timeout(1800)

        # dump 过滤后 suggestion-item（含叶子的可点击项）
        struct = page.evaluate(
            """(leaf) => {
                const out = [];
                document.querySelectorAll('.el-cascader__suggestion-item, .el-cascader__suggestion-panel *').forEach((e) => {
                    const r = e.getBoundingClientRect();
                    if (e.offsetParent === null || r.width === 0) return;
                    if (e.children.length === 0) {
                        const t = (e.innerText||'').trim().replace(/\\s+/g,' ');
                        if (t.includes(leaf) && t.length <= 60) {
                            out.push({text: t, rect: [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]});
                        }
                    }
                });
                out.sort((a,b)=>a.text.length-b.text.length);
                return out.slice(0,3);
            }""",
            LEAF,
        )
        log(f"[diag6] 过滤后 suggestion-item: {struct}")

        if struct:
            rect = struct[0]["rect"]
            page.mouse.click(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
            page.wait_for_timeout(1500)
            val = _cat_value(page)
            log(f"[diag6] 点击叶子后品类值: 「{val}」")

            # dump 选中后品类输入框区域 DOM（路径文本渲染来源）
            dom = page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('.el-cascader').forEach((c) => {
                        const inp = c.querySelector('.el-input__inner');
                        const ph = (inp && inp.placeholder) || '';
                        const r = c.getBoundingClientRect();
                        if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) {
                            // dump 品类容器完整结构（含路径文本渲染）
                            const show = [...c.querySelectorAll('.el-input__inner, .el-cascader__tags, .el-cascader__tags *')]
                                .filter(e => (e.innerText||e.value||'').trim())
                                .map(e => ({tag: e.tagName, cls: (e.className||'').toString().slice(0,40), v: (e.value||e.innerText||'').trim().slice(0,60)}));
                            out.push(show);
                        }
                    });
                    return out;
                }"""
            )
            log(f"[diag6] 选中后品类容器文本渲染源: {dom}")
            page.screenshot(path=str(ROOT / "runtime" / "diag6_after_click.png"), full_page=True)

            # 点「搜索」按钮验证记录数
            try:
                page.locator("button:has-text('搜索')").first.click(timeout=8000)
                page.wait_for_timeout(3000)
                page.wait_for_timeout(2000)
                total = page.evaluate(
                    """() => {
                        const t = (document.body.innerText||'');
                        const m = t.match(/共\\s*([\\d,]+)\\s*条记录/);
                        return m ? m[1] : (t.match(/共\\s*([\\d,]+)\\s*条/)?.[1] || '?');
                    }"""
                )
                log(f"[diag6] 点搜索后共 {total} 条记录")
                page.screenshot(path=str(ROOT / "runtime" / "diag6_searched.png"), full_page=True)
            except Exception as e:
                log(f"[diag6] 点搜索失败: {e}")
        else:
            log("[diag6] ✗ 未找到 suggestion-item，尝试回车")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            val = _cat_value(page)
            log(f"[diag6] 回车后品类值: 「{val}」")

        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()