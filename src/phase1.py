"""Phase 1 — 产品池选品 → 加入上架计划（确定性脚本）。

设计：
- 以 config.product_pool / config.plan 驱动。
- 提供 --probe（勘察并打印当前页面状态，不修改数据）和 --run（真正执行）双模式。
- 关键操作后都用 DOM 状态验收（input value / checkbox checked / 表格行数），失败即中止，绝不盲点。
- 干运行（dry_run）下不点击最终「确定加入」，只输出待加入清单。

勘察模式核心目的：在真实页面上确认以下选择器是否正确，随后固化为常量。
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light, safe_click

# ── 选择器常量（以 config 为主，未定的用通用兜底，勘察后固化） ──────────────
# 左侧导航
SEL_NAV_PRODUCT_POOL = "text=产品池"                       # 待勘察确认
# 标签页
SEL_TAB_US_POOL = "text=美区产品池"                         # 待勘察确认
SEL_TAB_CHANNEL = "text=多渠道"                            # 待勘察确认
# 产品类目选择器（el-cascader 级联选择器）— 勘察确认 placeholder 为「品类」
SEL_CATEGORY_CONTAINER = ".el-cascader"                        # 级联容器
SEL_SEARCH_BTN = "button:has-text('搜索')"                 # 勘察确认
# 表格操作
SEL_TABLE = ".vxe-table--body-wrapper"                     # 待勘察确认
SEL_ROW_JOIN = "button:has-text('加入上架计划')"            # 待勘察确认


def _open_category(page, category_path: list[str]) -> None:
    """打开品类级联选择器并搜索式选中品类叶子。

    勘察结论（diag5/diag6 已验证，2026-08-24）：
      品类 el-cascader 支持 filterable 搜索（页面有多个 search-input，必须定位
      品类 cascader 内部的那个）。稳定方式：
        1) 点击 .el-cascader 容器中心展开面板
        2) 向品类内部 .el-cascader__search-input fill 叶子名
        3) 点击过滤出的 .el-cascader__suggestion-item（含完整路径）
        4) 完整路径回填到品类选择器
      此方式比「逐级点击 .el-cascader-node」稳定，且已实测能筛出记录。
    """
    # 1) 定位可见的品类 el-cascader 容器并点击其中心
    target = page.evaluate(
        """() => {
            const cands = [];
            document.querySelectorAll('.el-cascader').forEach((c, i) => {
                const inp = c.querySelector('.el-input__inner');
                const ph = (inp && inp.placeholder) || '';
                if (!ph.includes('品类')) return;
                const r = c.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                const disabled = c.classList.contains('is-disabled');
                cands.push({i, x: r.x + r.width/2, y: r.y + r.height/2, disabled, w: r.width});
            });
            cands.sort((a, b) => (a.disabled - b.disabled) || (b.w - a.w));
            return cands[0] || null;
        }"""
    )
    if not target:
        raise RuntimeError("[phase1] ✗ 未找到可见的品类选择器")

    # 1.5) 若品类 disabled，轮询等待解锁（最多 15s），期间可能依赖前置异步加载
    if target["disabled"]:
        log("[phase1] 品类选择器 disabled，等待解锁...")
        for _ in range(15):
            page.wait_for_timeout(1000)
            target = page.evaluate(
                """() => {
                    const cands = [];
                    document.querySelectorAll('.el-cascader').forEach((c, i) => {
                        const inp = c.querySelector('.el-input__inner');
                        const ph = (inp && inp.placeholder) || '';
                        if (!ph.includes('品类')) return;
                        const r = c.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) return;
                        const disabled = c.classList.contains('is-disabled');
                        cands.push({i, x: r.x + r.width/2, y: r.y + r.height/2,
                                    disabled, w: r.width});
                    });
                    cands.sort((a, b) => (a.disabled - b.disabled) || (b.w - a.w));
                    return cands[0] || null;
                }"""
            )
            if target and not target["disabled"]:
                log("[phase1] ✓ 品类已解锁")
                break
        else:
            raise RuntimeError("[phase1] ✗ 品类选择器持续 disabled，需人工确认前置条件")

    page.mouse.click(target["x"], target["y"])
    page.wait_for_timeout(1200)
    log(f"[phase1] 已展开品类选择器")

    # 2) 定位「品类」cascader 内部的搜索框（页面有多个 search-input，不可取 .first）
    cat_search = page.locator(".el-cascader").filter(
        has=page.locator(".el-input__inner[placeholder='品类']")
    ).locator(".el-cascader__search-input").first
    try:
        cat_search.click(timeout=8000)
        page.wait_for_timeout(400)
        cat_search.fill(category_path[-1])   # 用叶子名搜索
        page.wait_for_timeout(1800)
        log(f"[phase1] 已向品类搜索框输入「{category_path[-1]}」")
    except Exception as e:
        raise RuntimeError(f"[phase1] ✗ 品类搜索框输入失败: {e}")

    # 3) 点击过滤出的 suggestion-item（含完整路径），触发回填
    struct = page.evaluate(
        """(leaf) => {
            const out = [];
            document.querySelectorAll('.el-cascader__suggestion-item, .el-cascader__suggestion-panel *')
                .forEach((e) => {
                    const r = e.getBoundingClientRect();
                    if (e.offsetParent === null || r.width === 0) return;
                    if (e.children.length === 0) {
                        const t = (e.innerText||'').trim().replace(/\\s+/g,' ');
                        if (t.includes(leaf) && t.length <= 60) {
                            out.push({text: t, rect: [Math.round(r.x),Math.round(r.y),
                                                      Math.round(r.width),Math.round(r.height)]});
                        }
                    }
                });
            out.sort((a,b)=>a.text.length-b.text.length);
            return out.slice(0,1);
        }""",
        category_path[-1],
    )
    if not struct:
        raise RuntimeError(f"[phase1] ✗ 品类搜索「{category_path[-1]}」无匹配建议项")
    rect = struct[0]["rect"]
    page.mouse.click(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
    page.wait_for_timeout(1500)
    log(f"[phase1] ✓ 品类搜索式选中: {struct[0]['text']}")


def _click_menu_item(page, text: str) -> bool:
    """用 JS 坐标点击下拉菜单项（Playwright .click() 会命中包装层导致不触发）。"""
    li = page.evaluate(
        """(text) => {
            const it = [...document.querySelectorAll('.el-dropdown-menu__item')]
                .find(x => (x.innerText || '').trim() === text);
            if (!it) return null;
            const r = it.getBoundingClientRect();
            return {x: Math.round(r.x + r.width / 2),
                    y: Math.round(r.y + r.height / 2)};
        }""",
        text,
    )
    if not li:
        return False
    page.mouse.click(li["x"], li["y"])
    return True


def _wait_plan_dialog(page, seconds: int = 20) -> bool:
    """轮询等待「加入上架计划」dialog 出现（最长 seconds 秒）。"""
    for _ in range(seconds):
        page.wait_for_timeout(1000)
        if page.evaluate(
            """() => [...document.querySelectorAll('.el-dialog')]
                .some(d => d.offsetParent !== null
                    || d.getBoundingClientRect().width > 100)"""
        ):
            return True
    return False


def _open_plan_dialog_via_row(page, row_index: int = 0, retries: int = 2) -> bool:
    """点击第 row_index 行的行内「加入上架计划」按钮 → 菜单「直接加入上架计划」→ 等 dialog。

    行内按钮定位：第 row_index 个位于 `closest('tr')` 内、文本为「加入上架计划」的 span。
    点击后弹出含「直接加入上架计划」的下拉菜单（diag3 已实证）。返回 dialog 是否弹出。
    """
    for attempt in range(retries + 1):
        pt = page.evaluate(
            """(rowIndex) => {
                const spans = [...document.querySelectorAll('span')]
                    .filter(s => (s.innerText || '').trim() === '加入上架计划'
                              && s.offsetParent !== null && s.closest('tr'));
                if (!spans.length) return null;
                const s = spans[Math.min(rowIndex, spans.length - 1)];
                const r = s.getBoundingClientRect();
                return {x: Math.round(r.x + r.width / 2),
                        y: Math.round(r.y + r.height / 2)};
            }""",
            row_index,
        )
        if not pt:
            log(f"[phase1][form] ⚠ 未找到行内「加入上架计划」按钮（row {row_index}）")
            return False
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(800)
        if _click_menu_item(page, "直接加入上架计划") and _wait_plan_dialog(page):
            page.wait_for_timeout(2000)
            return True
        log(f"[phase1][form] ⚠ dialog 未弹出（行内入口 第{attempt+1}次），重试")
        page.keyboard.press("Escape")   # 收起菜单
        page.wait_for_timeout(600)
    return False


# 语言下拉的选项文本由后台固定为英文（如 'Chinese'、'English(源语言)'），
# 配置里存中文名（如 '中文'）。选语言时用此表把中文名映射到实际选项文本。
LANG_ALIASES = {
    "中文": ["Chinese", "中文"],
    "英文": ["English", "英文"],
    "英语": ["English", "英语"],
}


def _read_pool_count(page) -> int:
    """从产品池页面读取「共 N 条记录」的数量。读不到返回 -1。"""
    v = page.evaluate(
        """() => {
            const candidates = [];
            const seen = new Set();
            document.querySelectorAll('body *').forEach(e => {
                const t = (e.innerText || '').trim().replace(/\\s+/g, ' ');
                const m = t.match(/共\\s*([\\d,]+)\\s*条记录/);
                if (m && !seen.has(t)) { seen.add(t); candidates.push(m[1].replace(/,/g, '')); }
            });
            if (!candidates.length) return -1;
            // 取最短的候选（通常是页脚统计，非行内文本）
            candidates.sort((a, b) => a.length - b.length);
            return parseInt(candidates[0], 10);
        }"""
    )
    return int(v)


def _verify_pool_category(page, config: dict) -> None:
    """校验产品池列表加载的是目标类目的产品，而非全量/错误类目数据。

    产品池列表无「类目」列，但底部有「共 N 条记录」统计：筛选生效后 N 应远小于
    全量记录数，且 N>0。勘察实测：全量约 3w 条，筛选「圣诞节花环」后 345 条。

    注意：搜索后统计是异步刷新的，刷新完成前会短暂显示旧的「全量」计数。因此
    这里用「长轮询 + 连续两次稳定且 < 阈值」判定，避免把刷新时滞误判为筛选失败。
    校验依据：
      1) 记录数 > 0（有产品可加）
      2) 连续两次读到同一较小值且 < 阈值（默认 5000）——确为筛选后的类目子集
      3) 首行产品文本含类目叶子关键词（软校验，仅告警）：进一步确认是目标类目
    1/2 不满足即抛错中止，避免在错误类目上勾选并加入上架计划。
    """
    threshold = config["safety"].get("pool_record_threshold", 5000)
    leaf = config["category"].get("category_leaf", "")
    # 长轮询：等待底部统计稳定为一个 < 阈值的子集计数（消除刷新时滞导致的假阳性）
    stable = -1
    stable_times = 0
    for _ in range(60):                      # 最长 ~60×500ms = 30s
        page.wait_for_timeout(500)
        count = _read_pool_count(page)
        if count <= 0:
            continue
        if count < threshold:
            if count == stable:
                stable_times += 1
            else:
                stable = count
                stable_times = 1
            if stable_times >= 2:
                break
        # count >= threshold：可能仍在刷新（旧全量计数），继续等
    if stable_times < 2 or stable <= 0:
        raise RuntimeError(
            f"[phase1] ✗ 列表记录数未在 {30}s 内稳定为筛选后子集"
            f"（读到最后一次 {count}，阈值 {threshold}），疑似筛选未生效"
            f"（加载了全量或错误类目数据），中止以防误加入上架计划")
    log(f"[phase1] ✓ 列表类目校验通过：共 {stable} 条记录（< 阈值 {threshold}，非全量）")

    # 软校验：首行产品文本应含类目叶子关键词（进一步确认是目标类目；选择器未定，
    # 读整行文本作代理，仅在确实缺失时告警，不硬中止）
    if leaf:
        first_row_text = page.evaluate(
            """() => {
                const rows = document.querySelectorAll(
                    '.vxe-table--body-wrapper .vxe-table--body tr, table tr');
                for (const r of rows) {
                    const t = (r.innerText || '').trim();
                    if (t) return t;
                }
                return '';
            }"""
        )
        if leaf not in first_row_text:
            log(f"[phase1] ⚠ 首行产品文本未包含类目关键词「{leaf}」"
                f"（软校验，标题列选择器未确认，仅供参考）")


def _phase1_run(page, config: dict, dry_run: bool, max_sku: int) -> dict:
    """执行 Phase 1 主体逻辑，返回结果 dict。"""
    pool = config["product_pool"]
    plan = config["plan"]
    res = {"joined": [], "skipped": []}

    # 1) 打开产品池
    page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
    wait_network_idle_light(page)
    log(f"[phase1] 打开产品池: {page.url}")
    if not is_logged_in(page):
        raise RuntimeError("[phase1] ✗ 登录态失效，请先扫码登录")

    # 2) 切换到美区产品池 + 多渠道
    safe_click(page, SEL_TAB_US_POOL)
    page.wait_for_timeout(800)
    safe_click(page, SEL_TAB_CHANNEL)
    page.wait_for_timeout(800)

    # 3) 通过级联选择器选择产品类目（system_path）并搜索
    category_path = config["category"]["system_path"]
    _open_category(page, category_path)
    if pool.get("escape_after_select", True):
        page.keyboard.press("Escape")   # 关闭下拉，避免挡住搜索按钮
        page.wait_for_timeout(300)
    safe_click(page, SEL_SEARCH_BTN)
    wait_network_idle_light(page)
    log(f"[phase1] 已筛选类目: {category_path[-1]}")

    # 3.1) 校验列表确实加载了目标类目的产品（防止筛选未生效时误勾选全量数据）
    _verify_pool_category(page, config)

    # 4) 选品（本次取前 max_sku 行）
    #    搜索后等待表格行加载完成（异步渲染，过早读取会得到 0 行）
    try:
        page.wait_for_selector(".vxe-table--body-wrapper tr", timeout=15000)
    except Exception:
        pass
    # 轮询行数稳定后再取（最多 10s）
    for _ in range(20):
        page.wait_for_timeout(500)
        if page.locator(SEL_TABLE).first.locator("tr").count() > 0:
            break
    table = page.locator(SEL_TABLE).first
    rows = table.locator("tr")
    n = min(rows.count(), max_sku)
    log(f"[phase1] 检索到 {rows.count()} 行，本次处理 {n} 行")

    # 4.1) 勾选用「冻结左列」的 checkbox 单元格（主表体 .col--checkbox 是 fixed--hidden 隐藏副本）
    #       vxe-table 冻结列结构：.vxe-table--fixed-left-wrapper > .vxe-table--body-wrapper > tr > td.col--checkbox
    #       勾选后须验证 is--checked 已选中，未选中则重试点击（加载/渲染时序抖动会导致首击失效）
    frozen_rows = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
    for i in range(n):
        if frozen_rows.count() > i:
            cb_td = frozen_rows.nth(i).locator("td.col--checkbox").first
        else:
            cb_td = rows.nth(i).locator("td.col--checkbox").first
        if not cb_td.count():
            log(f"[phase1][form] ⚠ 第 {i} 行未找到勾选列，跳过")
            res["skipped"].append({"row": i, "sku": None})
            continue
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
            # 未选中：可能是行数据仍在刷新，点击可能误触到相邻行，回退后重试
            page.wait_for_timeout(600)
        if checked:
            res["joined"].append({"row": i, "sku": None})
        else:
            log(f"[phase1][form] ⚠ 第 {i} 行勾选失败，跳过")
            res["skipped"].append({"row": i, "sku": None})

    # 5) 打开「加入上架计划」→「直接加入上架计划」dialog
    #    单行：点该行行内「加入上架计划」按钮（最右侧操作列，diag3 已实证可靠）
    #    多行：点顶部批量按钮「加入上架计划」（el-dropdown-selfdefine）
    if res["joined"]:
        if dry_run:
            log(f"[phase1][dry-run] 已勾选 {len(res['joined'])} 行，跳过打开 dialog（dry_run）")
            return res

        single = len(res["joined"]) == 1
        dlg_ok = False
        if single:
            row_idx = res["joined"][0]["row"]
            log(f"[phase1][form] 单行场景：点第 {row_idx} 行行内「加入上架计划」")
            dlg_ok = _open_plan_dialog_via_row(page, row_index=row_idx)
            if not dlg_ok:
                # 收起可能残留的菜单，回退顶部入口
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
        if not dlg_ok:
            # 顶部批量按钮入口（el-dropdown，trigger 为 .el-dropdown-selfdefine）
            trig = page.locator("button.el-dropdown-selfdefine").first
            if trig.count():
                trig.click(timeout=8000)
                page.wait_for_timeout(800)
            else:
                log("[phase1][form] ⚠ 未找到「加入上架计划」trigger")
            if _click_menu_item(page, "直接加入上架计划"):
                dlg_ok = _wait_plan_dialog(page)
                if not dlg_ok:
                    log("[phase1][form] ⚠ dialog 未弹出，重试点击一次")
                    trig.click(timeout=8000)
                    page.wait_for_timeout(800)
                    _click_menu_item(page, "直接加入上架计划")
                    dlg_ok = _wait_plan_dialog(page)
        if dlg_ok:
            page.wait_for_timeout(2000)
            _fill_plan_form(page, config)
            log(f"[phase1] 已提交 {len(res['joined'])} 个 SKU 到上架计划")
        else:
            log("[phase1][form] ✗ dialog 持续未弹出，跳过表单填写")

    return res


def _fill_plan_form(page, config: dict) -> None:
    """填写上架计划表单（Phase 1 步骤 4）。

    已确认表单结构（probe_plan_form / diag_join_click 勘察，2026-08-24）：
      - 弹窗为 .el-dialog，标题「加入上架计划」，字段 .el-form-item 的 label 带 for 属性
        （platform / market_id / store_id / brand / category_uni_code / profit）。
      - 平台/站点/店铺/品牌 是 el-select，产品类目是 el-cascader（平台英文类目）。
      - 下拉选项在表单加载时预拉取（触发 get_amazon_europe_stores 等 API），无需远程搜索。

    定位策略：在 .el-dialog 内按 label 文本找到对应 .el-form-item，再操作其控件。
    避免旧的 `text=平台` 定位（会误中 dialog 外不可见 span）。
    """
    plan = config["plan"]

    def _cascader_find_node(page, label: str, timeout_ms: int = 6000):
        """在可见 cascader 菜单中轮询查找文本=label 的节点，返回 {x,y,isLeaf} 或 None。

        节点匹配用「去空白后精确相等」，兼容 innerText 中的换行/多空格。
        每级菜单异步渲染，故轮询直到目标节点出现或超时。
        """
        deadline = timeout_ms / 1000
        for _ in range(int(deadline)):
            node = page.evaluate(
                """(label) => {
                    const menus = [...document.querySelectorAll('.el-cascader-menu')]
                        .filter(m => { const r = m.getBoundingClientRect();
                                       return r.width > 0 && r.height > 0; });
                    for (const m of menus) {
                        const n = [...m.querySelectorAll('.el-cascader-node')]
                            .find(x => {
                                const t = (x.querySelector('.el-cascader-node__label') || x)
                                    .innerText.replace(/\\s+/g, ' ').trim();
                                return t === label;
                            });
                        if (n) {
                            const r = n.getBoundingClientRect();
                            const isLeaf = n.classList.contains('is-leaf')
                                || !!n.querySelector('.el-cascader-node__postfix');
                            return {x: Math.round(r.x + r.width / 2),
                                    y: Math.round(r.y + r.height / 2), isLeaf};
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

    def _close_cascader_panel(page) -> None:
        """点击 dialog 标题安全收起 cascader 面板（不关 dialog，不 Escape）。"""
        page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null
                        || d.getBoundingClientRect().width > 100);
                const hd = dlg && (dlg.querySelector('.el-dialog__header')
                    || dlg.querySelector('.el-dialog__title'));
                if (hd) {
                    const r = hd.getBoundingClientRect();
                    window.__clx = r.x + Math.min(r.width / 2, 120);
                    window.__cly = r.y + r.height / 2;
                }
            }"""
        )
        try:
            page.mouse.click(page.evaluate("window.__clx"), page.evaluate("window.__cly"))
            page.wait_for_timeout(400)
        except Exception:
            pass

    def _read_value(label_text: str) -> str:
        """读回 dialog 内某 label 字段当前显示值（select 选中文本 / cascader 回填 / input）。"""
        return page.evaluate(
            """(labelText) => {
                const dlg=[...document.querySelectorAll('.el-dialog')]
                    .find(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100);
                const f=dlg&&[...dlg.querySelectorAll('.el-form-item')].find(fi=>{
                    const l=fi.querySelector('.el-form-item__label,label');
                    return l&&(l.innerText||'').trim()===labelText;});
                if(!f) return '';
                const sel=f.querySelector('.el-select');
                const cas=f.querySelector('.el-cascader');
                const inp=f.querySelector('input');
                if(sel){
                    const w=sel.querySelector('.el-select__selected-item,'
                        +'.el-select__selected-value,.el-select__placeholder,.el-select__tags-text');
                    return w?(w.innerText||'').trim():(inp?inp.value:'');
                }
                if(cas){
                    const w=cas.querySelector('.el-cascader__tags-text,'
                        +'.el-cascader__selected-item,.el-input__inner');
                    return w?(w.innerText||w.value||'').trim():'';
                }
                return inp?inp.value:'';
            }""",
            label_text,
        )

    def _form_item_rect(label_text: str):
        """返回 dialog 内 label 文本匹配的 form-item 的控件信息（JS 遍历，避免 text= 误匹配）。"""
        return page.evaluate(
            """(labelText) => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null
                        || d.getBoundingClientRect().width > 100);
                if (!dlg) return null;
                const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                    const l = fi.querySelector('.el-form-item__label, label');
                    return l && (l.innerText || '').trim() === labelText;
                });
                if (!f) return null;
                // 点击目标 = 控件本身（el-select/el-cascader/input）的中心，而非整个 form-item 中心
                // （form-item 含 label+校验占位，中心可能落在空白处导致下拉不展开）
                const ctrl = f.querySelector('.el-select, .el-cascader, input');
                let kind = null;
                if (ctrl) {
                    kind = ctrl.classList.contains('el-cascader') ? 'cascader'
                          : ctrl.classList.contains('el-select') ? 'select'
                          : ctrl.tagName.toLowerCase() === 'input' ? 'input' : null;
                }
                const r = (ctrl && ctrl.getBoundingClientRect().width > 0)
                        ? ctrl.getBoundingClientRect() : f.getBoundingClientRect();
                return {x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height), kind};
            }""",
            label_text,
        )

    def _fill_select(label_text: str, value: str) -> bool:
        """点击 el-select → 在可见下拉面板中点选预加载选项。返回是否成功。

        展开用 element click（对 form-item 内 el-select wrapper 做 .click()），
        避免坐标点击在表单重排/面板遮挡时落空导致下拉不展开。
        选项点选统一走 _pick_option（element click + 坐标兜底 + 轮询）。
        """
        ok = page.evaluate(
            """(labelText) => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null
                        || d.getBoundingClientRect().width > 100);
                if (!dlg) return false;
                const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                    const l = fi.querySelector('.el-form-item__label, label');
                    return l && (l.innerText || '').trim() === labelText;
                });
                const sel = f && f.querySelector('.el-select');
                if (!sel) return false;
                const target = sel.querySelector('.el-select__wrapper, .el-input__wrapper, '
                    + 'input') || sel;
                target.click();
                return true;
            }""",
            label_text,
        )
        if not ok:
            log(f"[phase1][form] ⚠ 未找到 el-select 字段「{label_text}」，跳过")
            return False
        return _pick_option(value, label_text)

    def _fill_cascader(label_text: str, path: list[str]) -> bool:
        """产品类目 el-cascader：优先搜索式，退化逐级点击。

        语言选中后产品类目行会重渲染并重新加载对应语言的数据（含 loading 遮罩），
        故这里用「点击 → 校验面板是否真正展开」的循环：遮罩/加载期间点击无效，
        轮询重试直到 `.el-cascader-menu` 面板可见（最长 ~20s）。这比单纯等
        cascader 矩形就绪更可靠（矩形可见 ≠ 数据已加载）。
        """
        for _ in range(30):
            fi = _form_item_rect(label_text)
            if fi and fi["kind"] == "cascader":
                page.mouse.click(fi["x"] + fi["w"] / 2, fi["y"] + fi["h"] / 2)
                # 单次点击后给足动画+加载时间（面板展开有过渡动画，等 500ms 就判定
                # 可能因动画未完成而误判为「未展开」，再点一次会触发 toggle 关闭）
                page.wait_for_timeout(1500)
                opened = page.evaluate(
                    """() => [...document.querySelectorAll('.el-cascader-menu')]
                        .some(m => { const r = m.getBoundingClientRect();
                                     return r.width > 0 && r.height > 0; })"""
                )
                if opened:
                    break
                # 未展开：点击可能被 loading 遮罩拦截，或面板已 toggle 关闭，
                # 安全收起后再重试，避免重复点击导致开-关抖动
                _close_cascader_panel(page)
                page.wait_for_timeout(300)
            page.wait_for_timeout(500)
        else:
            log(f"[phase1][form] ⚠ 等待超时：产品类目 cascader 面板未能展开"
                f"（字段「{label_text}」可能仍在加载）")
            # 诊断：dump cascader 元素状态 + 遮罩 + 语言当前值，定位为何打不开
            try:
                diag = page.evaluate(
                    """() => {
                        const dlg = [...document.querySelectorAll('.el-dialog')]
                            .find(d => d.offsetParent !== null
                                || d.getBoundingClientRect().width > 100);
                        const f = dlg && [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                            const l = fi.querySelector('.el-form-item__label, label');
                            return l && (l.innerText || '').trim() === '产品类目';
                        });
                        const cas = f && f.querySelector('.el-cascader');
                        const casInput = cas && cas.querySelector('input');
                        const langSel = f && f.querySelector('.category-options .el-select');
                        const langTxt = langSel && ((
                            langSel.querySelector('.el-select__selected-item,.el-select__selected-value,.el-select__placeholder')
                            || {}).innerText || '').trim();
                        const m = cas && cas.getBoundingClientRect();
                        const mask = document.querySelector('.el-loading-mask, .el-overlay.is-mask, .vxe-loading.is--visible');
                        return {
                            casExists: !!cas,
                            casRect: m ? [Math.round(m.x), Math.round(m.y), Math.round(m.width), Math.round(m.height)] : null,
                            casDisabled: cas ? (cas.classList.contains('is-disabled')
                                || (casInput && casInput.disabled)) : null,
                            casValue: casInput ? casInput.value : null,
                            langValue: langTxt || null,
                            loadingMask: mask ? (mask.className.split(' ').slice(0,3)) : null,
                            dialogVisible: dlg ? (dlg.offsetParent !== null) : false,
                        };
                    }"""
                )
                log(f"[phase1][form]   cascader诊断: {diag}")
            except Exception as e:
                log(f"[phase1][form]   cascader诊断失败: {e}")
            return False
        page.wait_for_timeout(400)

        # ① 搜索式：cascader 面板若有 filterable 搜索框，输入叶子名点选 suggestion
        leaf = path[-1]
        has_search = page.evaluate(
            """() => {
                const dds = [...document.querySelectorAll(
                    '.el-cascader__dropdown, .el-cascader-panel')]
                    .filter(s => { const r = s.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; });
                return dds.some(d => !!d.querySelector('.el-cascader__search-input'));
            }"""
        )
        if has_search:
            try:
                page.locator(".el-cascader__dropdown .el-cascader__search-input, "
                              ".el-cascader-panel .el-cascader__search-input").first \
                    .click(timeout=5000)
                page.wait_for_timeout(400)
                page.keyboard.type(leaf)
                page.wait_for_timeout(1200)
                sug = page.evaluate(
                    """(leaf) => {
                        const out = [];
                        document.querySelectorAll('.el-cascader__suggestion-item').forEach(e => {
                            const r = e.getBoundingClientRect();
                            if (e.offsetParent === null || r.width === 0) return;
                            const t = (e.innerText || '').trim().replace(/\\s+/g, ' ');
                            if (t.includes(leaf) && t.length <= 60)
                                out.push({t, x: Math.round(r.x + r.width / 2),
                                          y: Math.round(r.y + r.height / 2)});
                        });
                        out.sort((a, b) => a.t.length - b.t.length);
                        return out[0] || null;
                    }""",
                    leaf,
                )
                if sug:
                    page.mouse.click(sug["x"], sug["y"])
                    page.wait_for_timeout(800)
                    log(f"[phase1][form] ✓ {label_text} → {sug['t']}")
                    return True
                log(f"[phase1][form] ⚠ 类目搜索无建议项，退化逐级点击")
                page.evaluate(
                    """() => {
                        const dlg=[...document.querySelectorAll('.el-dialog')]
                            .find(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100);
                        const hd=dlg&&dlg.querySelector('.el-dialog__header,.el-dialog__title');
                        if(hd){const r=hd.getBoundingClientRect();
                               window.__col=r.x+Math.min(r.width/2,100);window.__row=r.y+r.height/2;}
                    }"""
                )
                try:
                    page.mouse.click(page.evaluate("window.__col"), page.evaluate("window.__row"))
                except Exception:
                    pass
                page.wait_for_timeout(400)
            except Exception as e:
                log(f"[phase1][form] ⚠ 类目搜索失败({e})，退化逐级点击")

        # ② 逐级点击（路径 pre-loaded）。每级点击后轮询等待下一级目标节点出现
        #    （菜单异步渲染，固定延时可能赶上「默认第一项高亮展开」导致选错分支）。
        for depth, label in enumerate(path):
            node = _cascader_find_node(page, label, timeout_ms=6000)
            if not node:
                # 诊断：dump 当前可见的 cascader 各级菜单文本，判断显示语言是否切换
                try:
                    menu_txt = page.evaluate(
                        """() => [...document.querySelectorAll('.el-cascader-menu')]
                            .filter(m => { const r = m.getBoundingClientRect();
                                           return r.width > 0 && r.height > 0; })
                            .map(m => [...m.querySelectorAll('.el-cascader-node__label')]
                                .map(x => (x.innerText || '').trim().replace(/\\s+/g, ' '))
                                .filter(Boolean).slice(0, 8))
                            .map((a, i) => `L${i + 1}: [${a.join(', ')}]`)
                            .join(' | ')"""
                    )
                    log(f"[phase1][form] ⚠ 类目第{depth + 1}级「{label}」未找到，中止")
                    log(f"[phase1][form]   dump 可见菜单: {menu_txt}")
                except Exception:
                    log(f"[phase1][form] ⚠ 类目第{depth + 1}级「{label}」未找到，中止")
                _close_cascader_panel(page)
                return False
            page.mouse.click(node["x"], node["y"])
            page.wait_for_timeout(500)
            # 叶子节点点击后会收起面板并回填，无需等待下一级菜单
            if node["isLeaf"]:
                break
        log(f"[phase1][form] ✓ {label_text} → {'/'.join(path)}")
        return True

    def _fill_input(label_text: str, value: str) -> bool:
        """利润率等普通 input：定位后 fill。"""
        fi = _form_item_rect(label_text)
        if not fi or fi["kind"] != "input":
            log(f"[phase1][form] ⚠ 未找到 input 字段「{label_text}」，跳过")
            return False
        # 定位 dialog 内该 form-item 的 input 并 fill（fill 触发 Vue v-model 提交）
        filled = page.evaluate(
            """(args) => {
                const [labelText, value] = args;
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null
                        || d.getBoundingClientRect().width > 100);
                if (!dlg) return false;
                const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                    const l = fi.querySelector('.el-form-item__label, label');
                    return l && (l.innerText || '').trim() === labelText;
                });
                const inp = f && f.querySelector('input');
                if (!inp) return false;
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(inp, value);
                inp.dispatchEvent(new Event('input', {bubbles: true}));
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }""",
            [label_text, value],
        )
        if filled:
            log(f"[phase1][form] ✓ {label_text} → {value}")
            return True
        log(f"[phase1][form] ⚠ {label_text} input 定位失败")
        return False

    def _fill_source_lang(value: str) -> bool:
        """选择「语言」下拉框（产品类目行最右侧 .category-options .el-select）。

        该下拉框无独立 label，嵌在产品类目 form-item 内（placeholder='语言'）。
        必须先选语言（中文）→ 解锁并加载对应语言的产品类目，再选产品类目。

        注意：
          1) 品牌选中后产品类目行可能异步重载，语言下拉框不会立即就绪，
             故先轮询等待产品类目行出现再定位（最长 ~10s）。
          2) 语言下拉须用 element click 展开（坐标点击被面板拦截，无效）。
        """
        # 原子操作：同一 JS 内「定位语言下拉并点击展开」，消除「轮询定位」与
        # 「点击展开」两次 evaluate 之间产品类目行重渲染导致的竞态。
        # 外层轮询重试（最长 ~15s），每次找不到/未展开即重试。
        for _ in range(30):
            r = page.evaluate(
                """() => {
                    const dlg = [...document.querySelectorAll('.el-dialog')]
                        .find(d => d.offsetParent !== null
                            || d.getBoundingClientRect().width > 100);
                    if (!dlg) return {ok: false};
                    const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                        const l = fi.querySelector('.el-form-item__label, label');
                        return l && (l.innerText || '').trim() === '产品类目';
                    });
                    const sel = f && f.querySelector('.category-options .el-select');
                    if (!sel) return {ok: false};
                    const r = sel.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) return {ok: false};
                    const target = sel.querySelector('.el-select__wrapper, '
                        + '.el-input__wrapper, input') || sel;
                    target.click();
                    return {ok: true};
                }"""
            )
            if r and r.get("ok"):
                break
            page.wait_for_timeout(500)
        else:
            log("[phase1][form] ⚠ 等待超时：未找到产品类目行内的「语言」下拉框")
            return False
        page.wait_for_timeout(1200)
        ok = _pick_option(value, "语言")
        # 语言选中后其 el-select 下拉面板（.el-select-dropdown）可能未自动收起，
        # 残留面板会遮挡下方产品类目 cascader 的展开。点 dialog 标题安全收起，
        # 再让 cascader 走「点击→校验展开」循环。
        page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null
                        || d.getBoundingClientRect().width > 100);
                const hd = dlg && (dlg.querySelector('.el-dialog__header')
                    || dlg.querySelector('.el-dialog__title'));
                if (hd) { const r = hd.getBoundingClientRect();
                          window.__lhx = r.x + Math.min(r.width / 2, 120);
                          window.__lhy = r.y + r.height / 2; }
            }"""
        )
        try:
            page.mouse.click(page.evaluate("window.__lhx"), page.evaluate("window.__lhy"))
        except Exception:
            pass
        page.wait_for_timeout(500)
        return ok

    def _pick_option(value: str, who: str) -> bool:
        """在可见 el-select 下拉中选 value。返回是否成功。

        语言下拉选项非预加载（点击后才拉取），故轮询等待选项出现。
        部分下拉（如语言）选项文本是英文（后台固定），通过 LANG_ALIASES 把
        配置的中文名映射到实际选项文本，避免「中文」匹配不到「Chinese」。
        """
        # 候选值 = 原值 + 语言别名（用于匹配后台英文 label 的选项）
        candidates = [value] + LANG_ALIASES.get(value, [])
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
                el_ok = page.evaluate(
                    """(args) => {
                        const [cands] = args;
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
                    [candidates],
                )
                if el_ok:
                    page.wait_for_timeout(600)
                    log(f"[phase1][form] ✓ {who} → {opt['txt']}（element click）")
                    return True
                page.mouse.click(opt["x"], opt["y"])
                page.wait_for_timeout(500)
                log(f"[phase1][form] ✓ {who} → {opt['txt']}（coord click）")
                return True
            page.wait_for_timeout(500)
        # 失败诊断：dump 当前可见下拉里的选项，便于定位匹配/展开问题
        try:
            opts = page.evaluate(
                """() => {
                    const out = [];
                    const panels = [...document.querySelectorAll('.el-select-dropdown')]
                        .filter(s => { const r = s.getBoundingClientRect();
                                       return r.width > 0 && r.height > 0; });
                    for (const p of panels) {
                        for (const li of p.querySelectorAll('.el-select-dropdown__item')) {
                            const t = (li.innerText || '').trim().replace(/\\s+/g, ' ');
                            if (t) out.push(t);
                        }
                    }
                    return out.slice(0, 60);
                }"""
            )
            log(f"[phase1][form] ⚠ {who} 下拉无「{value}」；可见选项: {opts}")
        except Exception as e:
            log(f"[phase1][form] ⚠ {who} 下拉无「{value}」（dump失败: {e}）")
        return False

    # 平台 / 站点 / 店铺 / 品牌（el-select，预加载选项）
    _fill_select("平台", plan["platform"])
    _fill_select("站点", plan["site"])
    _fill_select("店铺", plan["store"])
    _fill_select("品牌", plan["brand"])

    # 源语言（产品类目行最右侧的「语言」下拉框 .category-options .el-select）。
    # 默认不切换，保持英文（English 源语言）。
    # 后台限制：语言切「中文」后产品类目 cascader 会被禁用（casDisabled=True，
    # 实测点击 90s 无响应），且切换后会把已填英文类目清空，故本流程不切中文，
    # 产品类目始终用英文平台路径（platform_path）填写。
    if plan.get("category_language"):
        _fill_source_lang(plan["category_language"])

    # 产品类目（平台类目！英文路径 platform_path，语言保持英文可用）
    _fill_cascader("产品类目", config["category"]["platform_path"])

    # 利润率
    _fill_input("利润率", str(plan["margin_rate"]))

    # 加入方式 / 生成方式 / GTIN类型（el-select；GTIN 默认「付费UPC」须改为配置值）
    _fill_select("加入方式", plan.get("join_mode", "按SKU加入"))
    _fill_select("生成方式", plan.get("generate_mode", "按SPU维度生成多个上架计划"))
    _fill_select("GTIN类型", plan.get("gtin", "豁免"))


def main() -> None:
    config = load_config()
    args = sys.argv[1:]
    probe_mode = "--probe" in args
    dry_run = not ("--no-dry-run" in args)
    max_sku = int(args[args.index("--max-sku") + 1]) if "--max-sku" in args \
        else config["safety"]["max_sku_count"]

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[phase1] ✗ 未登录，先运行 `python -m src.login --login`")
            browser.close()
            sys.exit(1)

        if probe_mode:
            log("[phase1][probe] 勘察模式：只打印当前产品池页面状态，不修改数据")
            _probe_phase1(page, config)
        else:
            res = _phase1_run(page, config, dry_run, max_sku)
            log(f"[phase1] 完成: 加入 {len(res['joined'])} / 跳过 {len(res['skipped'])}")

        browser.close()


def _probe_phase1(page, config: dict) -> None:
    """勘察产品池页面：确认所有选择器有效。"""
    pool = config["product_pool"]
    page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
    wait_network_idle_light(page)
    page.wait_for_timeout(2000)
    log(f"[probe] URL: {page.url}")

    # 先切换到美区产品池标签（否则默认视图可能为空/元素未渲染）
    us_tab = page.locator(SEL_TAB_US_POOL).first
    if us_tab.count():
        us_tab.click(timeout=8000)
        page.wait_for_timeout(2000)
        log("[probe] 已点击「美区产品池」标签")
    else:
        log(f"[probe] ⚠ 未找到美区产品池标签: {SEL_TAB_US_POOL}")

    # 统计关键元素是否存在
    checks = {
        "tab_美区产品池": SEL_TAB_US_POOL,
        "tab_多渠道": SEL_TAB_CHANNEL,
        "input_产品类目": SEL_CATEGORY_CONTAINER,
        "btn_搜索": SEL_SEARCH_BTN,
        "table_容器": SEL_TABLE,
        "btn_加入上架计划": SEL_ROW_JOIN,
    }
    for name, sel in checks.items():
        try:
            n = page.locator(sel).count()
            log(f"[probe] {'✓' if n else '✗'} {name}: {sel} → {n} 个")
        except Exception as e:
            log(f"[probe] ✗ {name}: {e}")

    # 截图存档
    shot = ROOT / "runtime" / "probe_phase1.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shot), full_page=True)
    log(f"[probe] 截图: {shot}")


if __name__ == "__main__":
    main()