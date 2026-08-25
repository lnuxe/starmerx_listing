"""聚焦诊断探针：展开产品类目 cascader，逐级点击并截图/DOM dump。

目的：看清 el-cascader 展开时「多列菜单」的真实结构与点击行为，定位
「逐级点击走完四级、日志 ✓，但 input 未回填」的根因。

流程：
  1) 复用 dry-run：登录 → 切美区/多渠道 → 选品类 → 勾选首行 → 打开「加入上架计划」dialog
  2) 填写解锁字段（平台/站点/店铺/品牌 select），使产品类目 cascader 可用
  3) 展开 cascader，逐级点击四级路径；每级点击后：
       - dump 当前所有可见 `.el-cascader-menu` 列的节点文本（L1/L2/L3/L4 各自显示什么）
       - dump cascader input 当前值
       - 截图存档
  4) 叶子点击后再次 dump 全部列 + input + 截图，确认是否回填

运行：.venv/bin/python scripts/diag_cascader_columns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light, safe_click
from src.phase1 import (SEL_TAB_US_POOL, SEL_TAB_CHANNEL, SEL_TABLE,
                        SEL_SEARCH_BTN,
                        _open_category, _open_plan_dialog_via_row,
                        _verify_pool_category)

SHOT_DIR = ROOT / "runtime" / "diag_cascader"


def _dump_menus(page, tag: str) -> None:
    """dump 当前所有可见 cascader 菜单列的节点文本 + input 值。"""
    info = page.evaluate(
        """() => {
            const menus = [...document.querySelectorAll('.el-cascader-menu')]
                .filter(m => { const r = m.getBoundingClientRect();
                               return r.width > 0 && r.height > 0; })
                .map(m => {
                    const nodes = [...m.querySelectorAll('.el-cascader-node')]
                        .map(n => {
                            const label = (n.querySelector('.el-cascader-node__label') || n)
                                .innerText.replace(/\\s+/g, ' ').trim();
                            const cls = n.className;
                            const hasPostfix = !!n.querySelector('.el-cascader-node__postfix');
                            const hasArrow = !!n.querySelector('.el-cascader-node__arrow');
                            const hasLeafCls = cls.includes('is-leaf');
                            const hasExpandable = cls.includes('is-expandable');
                            const markers = [
                                hasPostfix ? 'P' : '',          // 有展开箭头(=有子级父节点)
                                hasArrow ? 'A' : '',
                                hasLeafCls ? 'leaf' : '',
                                hasExpandable ? 'exp' : '',
                            ].filter(Boolean).join('+');
                            return `${label}[${markers || '·'}]`;
                        });
                    return `[${nodes.join(', ')}]`;
                });
            // cascader input 值
            const dlg = [...document.querySelectorAll('.el-dialog')]
                .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
            const f = dlg && [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                const l = fi.querySelector('.el-form-item__label, label');
                return l && (l.innerText || '').trim() === '产品类目';
            });
            const cas = f && f.querySelector('.el-cascader');
            const casInput = cas && cas.querySelector('input');
            const tags = cas ? [...cas.querySelectorAll('.el-cascader__tags-text, '
                + '.el-cascader__selected-item, .el-cascader__selected-value, '
                + '.el-tag')].map(n => (n.innerText || '').trim()).filter(Boolean) : [];
            const inputVal = casInput ? casInput.value : '';
            const active = cas && [...cas.querySelectorAll('.el-cascader-node.is-active')]
                .map(n => (n.querySelector('.el-cascader-node__label') || n)
                    .innerText.replace(/\\s+/g, ' ').trim());
            return { menus, tags, inputVal, active };
        }"""
    )
    log(f"[diag][{tag}] 菜单列({len(info['menus'])}): " + (" | ".join(info["menus"]) or "(空)"))
    log(f"[diag][{tag}] input值='{info['inputVal']}' tags={info['tags']} 激活={info['active']}")
    try:
        page.screenshot(path=str(SHOT_DIR / f"{tag}.png"), full_page=False)
    except Exception:
        pass


def _fill_select(page, label_text: str, value: str) -> bool:
    """点击 el-select 并点选选项（element click + 候选匹配 + 轮询，对齐 phase1）。"""
    ok = page.evaluate(
        """(labelText) => {
            const dlg = [...document.querySelectorAll('.el-dialog')]
                .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
            if (!dlg) return false;
            const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                const l = fi.querySelector('.el-form-item__label, label');
                return l && (l.innerText || '').trim() === labelText;
            });
            const sel = f && f.querySelector('.el-select');
            if (!sel) return false;
            const target = sel.querySelector('.el-select__wrapper, .el-input__wrapper, input') || sel;
            target.click();
            return true;
        }""",
        label_text,
    )
    if not ok:
        log(f"[diag] ✗ 未找到 el-select 字段「{label_text}」")
        return False
    # 候选 = 原值 + 常见别名（Tik Tok/TikTok 之类），element click + 轮询
    candidates = [value, "Tik Tok" if value == "TikTok" else value]
    for _ in range(10):
        opt = page.evaluate(
            """(cands) => {
                const panels = [...document.querySelectorAll('.el-select-dropdown')]
                    .filter(s => { const r = s.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; });
                const hits = [];
                for (const p of panels) {
                    for (const li of p.querySelectorAll('.el-select-dropdown__item')) {
                        const t = (li.innerText || '').trim().replace(/\\s+/g, ' ');
                        if (cands.some(c => t === c || (t.includes(c) && t.length <= 40)))
                            hits.push({t, el: li});
                    }
                }
                if (!hits.length) return null;
                hits.sort((a, b) => a.t.length - b.t.length);
                const r = hits[0].el.getBoundingClientRect();
                return {x: Math.round(r.x + r.width / 2),
                        y: Math.round(r.y + r.height / 2), txt: hits[0].t};
            }""",
            candidates,
        )
        if opt:
            try:
                el_ok = page.evaluate(
                    """(cands) => {
                        const panels = [...document.querySelectorAll('.el-select-dropdown')]
                            .filter(s => { const r = s.getBoundingClientRect();
                                           return r.width > 0 && r.height > 0; });
                        const hits = [];
                        for (const p of panels) {
                            for (const li of p.querySelectorAll('.el-select-dropdown__item')) {
                                const t = (li.innerText || '').trim().replace(/\\s+/g, ' ');
                                if (cands.some(c => t === c || (t.includes(c) && t.length <= 40)))
                                    hits.push(li);
                            }
                        }
                        if (!hits.length) return false;
                        hits.sort((a, b) => {
                            const ta = (a.innerText || '').trim().replace(/\\s+/g, ' ');
                            const tb = (b.innerText || '').trim().replace(/\\s+/g, ' ');
                            return ta.length - tb.length;
                        });
                        hits[0].click();
                        return true;
                    }""",
                    candidates,
                )
            except Exception:
                el_ok = False
            if el_ok:
                page.wait_for_timeout(600)
                log(f"[diag] ✓ {label_text} → {opt['txt']}（element click）")
                return True
            page.mouse.click(opt["x"], opt["y"])
            page.wait_for_timeout(500)
            log(f"[diag] ✓ {label_text} → {opt['txt']}（coord click）")
            return True
        page.wait_for_timeout(500)
    log(f"[diag] ✗ {label_text} 下拉无「{value}」")
    return False


def _find_node(page, label: str, timeout_ms: int = 6000):
    """在可见 cascader 菜单中轮询查找文本=label 的节点，返回 {x,y,isLeaf, col} 或 None。"""
    deadline = timeout_ms / 1000
    for _ in range(int(deadline)):
        node = page.evaluate(
            """(label) => {
                const menus = [...document.querySelectorAll('.el-cascader-menu')]
                    .filter(m => { const r = m.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; });
                for (let ci = 0; ci < menus.length; ci++) {
                    const n = [...menus[ci].querySelectorAll('.el-cascader-node')]
                        .find(x => {
                            const t = (x.querySelector('.el-cascader-node__label') || x)
                                .innerText.replace(/\\s+/g, ' ').trim();
                            return t === label;
                        });
                    if (n) {
                        const r = n.getBoundingClientRect();
                        // 叶子 = 无展开箭头/postfix 且无 is-expandable（Element Plus 语义）
                        const isLeaf = !n.querySelector('.el-cascader-node__postfix, '
                            + '.el-cascader-node__arrow')
                            && !n.classList.contains('is-expandable');
                        return {x: Math.round(r.x + r.width / 2),
                                y: Math.round(r.y + r.height / 2),
                                isLeaf, col: ci};
                    }
                }
                return null;
            }""",
            label,
        )
        if node:
            return node
        page.wait_for_timeout(500)
    return None


def main() -> None:
    config = load_config()
    pool = config["product_pool"]
    plan = config["plan"]
    path = config["category"]["platform_path"]

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"[diag] 目标类目英文路径: {'/'.join(path)}")

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag] ✗ 未登录，先 `./run.sh login`")
            browser.close()
            sys.exit(1)

        # 1) 打开产品池 + 切美区/多渠道
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        if not is_logged_in(page):
            log("[diag] ✗ 跳转后登录态失效")
            browser.close()
            sys.exit(1)
        safe_click(page, SEL_TAB_US_POOL)
        page.wait_for_timeout(800)
        safe_click(page, SEL_TAB_CHANNEL)
        page.wait_for_timeout(800)

        # 2) 选品类 + 触发搜索筛选 + 校验（含重试，避免筛选渲染时滞）
        for attempt in range(3):
            try:
                _open_category(page, config["category"]["system_path"])
                if pool.get("escape_after_select", True):
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                safe_click(page, SEL_SEARCH_BTN)
                wait_network_idle_light(page)
                log(f"[diag] 已筛选类目: {config['category']['system_path'][-1]}")
                _verify_pool_category(page, config)
                break
            except RuntimeError as e:
                log(f"[diag] 品类选中/校验失败(第{attempt+1}次): {e}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1500)
                if attempt == 2:
                    raise

        # 3) 勾选首行 + 打开「加入上架计划」dialog
        if not _open_plan_dialog_via_row(page, row_index=0):
            log("[diag] ✗ 未能打开加入上架计划 dialog")
            browser.close()
            sys.exit(1)

        # 4) 填写解锁字段（平台/站点/店铺/品牌），使 cascader 可用
        for label, val in [("平台", plan["platform"]), ("站点", plan["site"]),
                           ("店铺", plan["store"]), ("品牌", plan["brand"])]:
            ok = _fill_select(page, label, val)
            log(f"[diag] 解锁 select「{label}」= {val} -> {'✓' if ok else '✗'}")

        # 5) 展开产品类目 cascader
        fi = None
        for _ in range(30):
            fi = page.evaluate(
                """() => {
                    const dlg = [...document.querySelectorAll('.el-dialog')]
                        .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                    const f = dlg && [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                        const l = fi.querySelector('.el-form-item__label, label');
                        return l && (l.innerText || '').trim() === '产品类目';
                    });
                    if (!f) return null;
                    const cas = f.querySelector('.el-cascader');
                    const r = cas ? cas.getBoundingClientRect() : null;
                    if (!r || r.width === 0) return null;
                    return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
                }"""
            )
            if fi:
                page.mouse.click(fi["x"], fi["y"])
                page.wait_for_timeout(1500)
                opened = page.evaluate(
                    """() => [...document.querySelectorAll('.el-cascader-menu')]
                        .some(m => { const r = m.getBoundingClientRect();
                                     return r.width > 0 && r.height > 0; })"""
                )
                if opened:
                    break
            page.wait_for_timeout(500)
        _dump_menus(page, "00_展开后_初始")

        # 6) 逐级点击四级路径，每级点击后 dump + 截图
        for depth, label in enumerate(path):
            node = _find_node(page, label, timeout_ms=6000)
            if not node:
                log(f"[diag] 第{depth+1}级「{label}」未找到，中止")
                _dump_menus(page, f"0{depth+1}_未找到_{label}")
                break
            log(f"[diag] 点击第{depth+1}级「{label}」 col={node['col']} "
                f"isLeaf={node['isLeaf']} @({node['x']},{node['y']})")
            # 命中诊断：节点 rect vs 所在列面板 rect，判断是否越界/被截断
            geo = page.evaluate(
                """(label) => {
                    const panels = [...document.querySelectorAll('.el-cascader-menu')]
                        .filter(m => { const r = m.getBoundingClientRect();
                                       return r.width > 0 && r.height > 0; });
                    for (let ci = 0; ci < panels.length; ci++) {
                        const p = panels[ci];
                        const n = [...p.querySelectorAll('.el-cascader-node')].find(x =>
                            (x.querySelector('.el-cascader-node__label') || x)
                                .innerText.replace(/\\s+/g, ' ').trim() === label);
                        if (!n) continue;
                        const r = n.getBoundingClientRect();
                        const pr = p.getBoundingClientRect();
                        return {
                            col: ci,
                            node: {x: r.x, y: r.y, w: r.width, h: r.height},
                            panel: {x: pr.x, y: pr.y, w: pr.width, h: pr.height},
                            inside: r.y >= pr.y && r.y + r.height <= pr.y + pr.height,
                            scrollTop: p.scrollTop, scrollH: p.scrollHeight, clientH: p.clientHeight,
                            disp: getComputedStyle(p).display,
                        };
                    }
                    return null;
                }""",
                label,
            )
            if geo:
                log(f"[diag]   {label} col{geo['col']} 节点rect={geo['node']} "
                    f"面板rect={geo['panel']} inside={geo['inside']} "
                    f"scrollTop={geo['scrollTop']}/{geo['scrollH']} clientH={geo['clientH']} "
                    f"disp={geo['disp']}")
            # 优先 element click（可命中滚动/被遮挡节点），失败再坐标兜底
            el_ok = False
            try:
                el_ok = page.evaluate(
                    """(label) => {
                        const panels = [...document.querySelectorAll('.el-cascader-menu')]
                            .filter(m => { const r = m.getBoundingClientRect();
                                           return r.width > 0 && r.height > 0; });
                        for (const p of panels) {
                            const n = [...p.querySelectorAll('.el-cascader-node')].find(x =>
                                (x.querySelector('.el-cascader-node__label') || x)
                                    .innerText.replace(/\\s+/g, ' ').trim() === label);
                            if (n) { n.scrollIntoView({block: 'center'}); n.click(); return true; }
                        }
                        return false;
                    }""",
                    label,
                )
            except Exception:
                el_ok = False
            if not el_ok:
                page.mouse.click(node["x"], node["y"])
            page.wait_for_timeout(900)
            _dump_menus(page, f"0{depth+1}_点击后_{label}")
            if node["isLeaf"]:
                break

        # 7) 叶子点击后：尝试 Enter + 再点一次，观察回填变化
        log("[diag] == 叶子点击后额外验证 ==")
        _dump_menus(page, "10_叶子点击后")
        page.keyboard.press("Enter")
        page.wait_for_timeout(800)
        _dump_menus(page, "11_Enter后")

        # 8) 收尾：Escape 关闭 dialog（不提交）
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        browser.close()
        log("[diag] 完成，截图在 " + str(SHOT_DIR))


if __name__ == "__main__":
    main()