"""一次性验证脚本 v2：有头模式确认「圣诞节花环」叶子是否有数据。

相比 v1 的修正：
  1. 读取品类选择器 input 的值，确认叶子确实被选中（v1 未读，无法判断筛选是否生效）
  2. 读取底部「共 X 条记录」，用记录总数判定筛选结果（比数表格行更可靠）
  3. 搜索后等待表格记录数从全量变化（轮询），避免时序误判
  4. 截图记录页面状态供人工确认

全程不修改任何数据。用法: python -m scripts.verify_category
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light, safe_click
from src.phase1 import _open_category

SEL_SEARCH_BTN = "button:has-text('搜索')"


def _category_input_value(page) -> str:
    """读取品类选择器 input 的展示值（确认选中了哪个叶子）。"""
    try:
        return page.evaluate(
            """() => {
                const cands = [];
                document.querySelectorAll('.el-cascader').forEach((c) => {
                    const inp = c.querySelector('.el-input__inner');
                    const ph = (inp && inp.placeholder) || '';
                    if (!ph.includes('品类')) return;
                    const r = c.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    cands.push((inp && inp.value) || '');
                });
                return cands[0] || '';
            }"""
        )
    except Exception:
        return "<读取失败>"


def _category_enabled(page) -> bool:
    """判断品类选择器（可见的那个）是否 enabled。"""
    try:
        return page.evaluate(
            """() => {
                let vis = null;
                document.querySelectorAll('.el-cascader').forEach((c) => {
                    const inp = c.querySelector('.el-input__inner');
                    const ph = (inp && inp.placeholder) || '';
                    const r = c.getBoundingClientRect();
                    if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) {
                        vis = c;
                    }
                });
                if (!vis) return false;
                return !vis.classList.contains('is-disabled')
                    && !(vis.querySelector('.el-input')||{}).classList?.contains('is-disabled');
            }"""
        )
    except Exception:
        return False


def _select_dev_owner(page) -> bool:
    """点「开发负责人」下拉，选第一个选项，尝试解锁品类。"""
    try:
        # 定位「开发负责人」下拉（placeholder 匹配，可见）
        wrapper = page.locator(".el-select").filter(
            has=page.locator(".el-input__inner[placeholder='开发负责人']")
        ).filter(visible=True).first
        wrapper.wait_for(state="visible", timeout=10000)
        wrapper.click(timeout=8000)
        page.wait_for_timeout(2000)

        # 等下拉选项渲染后点第一个可见项
        item = page.locator(".el-select-dropdown__item").filter(visible=True).first
        item.wait_for(state="visible", timeout=8000)
        txt = (item.inner_text() or "").strip()
        item.click(timeout=5000)
        log(f"[verify] ✓ 已选开发负责人: {txt}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        return bool(txt)
    except Exception as e:
        log(f"[verify] ✗ 选开发负责人失败: {e}")
        return False


def _total_records(page) -> int | None:
    """读取底部「共 X 条记录」。"""
    try:
        return page.evaluate(
            """() => {
                const m = document.body.innerText.match(/共\\s*([\\d,]+)\\s*条/);
                return m ? parseInt(m[1].replace(/,/g, '')) : null;
            }"""
        )
    except Exception:
        return None


def _sample_rows(page, limit: int = 10) -> list[str]:
    """从可见的 vxe 表格行取前若干行文本（每行截断）。"""
    try:
        return page.evaluate(
            """(lim) => {
                const wrap = document.querySelector('.vxe-table--body-wrapper');
                if (!wrap) return [];
                const out = [];
                for (const tr of wrap.querySelectorAll('tr')) {
                    if (out.length >= lim) break;
                    const txt = (tr.innerText || '').trim().replace(/\\s+/g, ' ');
                    if (txt) out.push(txt.slice(0, 80));
                }
                return out;
            }""",
            limit,
        )
    except Exception as e:
        log(f"[verify] ✗ 读取产品行失败: {e}")
        return []


def main() -> None:
    config = load_config()
    category_path = config["category"]["system_path"]
    leaf = category_path[-1]

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[verify] ✗ 未登录，先 `python -m src.login --login`")
            browser.close()
            sys.exit(1)

        pool = config["product_pool"]
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        log(f"[verify] 已打开产品池: {page.url}")

        # 切到「美区产品池」tab（多渠道是默认/独立控件，不在此处理）
        tab_ok = False
        try:
            item = page.locator(".el-tabs__item:has-text('美区产品池')").first
            item.wait_for(state="visible", timeout=15000)
            cls = item.get_attribute("class") or ""
            if "is-active" in cls:
                tab_ok = True
                log("[verify] ✓ 美区产品池已激活，跳过")
            else:
                item.click(timeout=8000)
                page.wait_for_timeout(1500)
                cls2 = item.get_attribute("class") or ""
                tab_ok = "is-active" in cls2
                log(f"[verify] ✓ 已切到美区产品池（active={tab_ok}）")
        except Exception as e:
            log(f"[verify] ✗ 切美区产品池失败: {e}")
        page.wait_for_timeout(1500)

        # 记录初始全量记录数
        init_total = _total_records(page)
        log(f"[verify] 初始全量记录数: {init_total}")

        # 解锁品类：若品类 disabled，先点「开发负责人」选第一个（品类依赖前置）
        if not _category_enabled(page):
            log("[verify] 品类选择器 disabled，尝试先选开发负责人解锁")
            _select_dev_owner(page)

        log(f"[verify] 正在选择品类: {' → '.join(category_path)}")
        _open_category(page, category_path)
        if pool.get("escape_after_select", True):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        # 读取品类选择器展示值，确认叶子选中
        picked = _category_input_value(page)
        log(f"[verify] 品类选择器当前值: 「{picked}」")

        safe_click(page, SEL_SEARCH_BTN)
        wait_network_idle_light(page)

        # 轮询等待记录数变化（筛选生效），最多等 20s
        total = None
        for _ in range(20):
            total = _total_records(page)
            if total is not None and total != init_total:
                break
            page.wait_for_timeout(1000)
        log(f"[verify] 筛选后记录数: {total}（初始 {init_total}）")

        rows = _sample_rows(page)
        log(f"[verify] 前 {len(rows)} 行样本:")
        for r in rows:
            log(f"[verify]   · {r}")

        shot = ROOT / "runtime" / f"verify2_{leaf}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot), full_page=True)
        log(f"[verify] 截图: {shot}")

        # 判定：以记录数是否收敛到非全量为准
        if total is not None and init_total is not None and total < init_total:
            log(f"[verify] ✓ 结论: 「{leaf}」筛选后 {total} 条（< 初始 {init_total}），叶子有数据")
        elif total is not None and total == 0:
            log(f"[verify] ✗ 结论: 「{leaf}」筛选后 0 条，叶子无数据")
        else:
            log(f"[verify] ⚠ 结论: 记录数未变化（{total}），筛选可能未生效，需人工查看品类选择器值")

        page.wait_for_timeout(4000)
        browser.close()


if __name__ == "__main__":
    main()