"""Phase 2 — 上架计划内 图片/价格 校验 + 批量上架（确定性脚本）。

设计：
- --probe 勘察模式：进入上架计划页，dump 表格列头、图片区、价格区结构，固化选择器。
- --check 校验模式：对目标 SPU 跑 8 张图校验 + SKU 色标对应 + 价格利润试算。
- --run 执行模式：校验通过后批量上架（dry_run 下只输出清单）。

规则（来自 config.verification）：
  · SPU 8 张主图，主图优先白底
  · 每个 SKU 颜色标签与图片一一对应
  · 活动营销费 50%，个人利润 4%–6%，通过调「公司利润率」实现
"""
from __future__ import annotations

import re
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light, safe_click
from src.price_calc import solve_company_margin

# ── 选择器（勘察后固化，2026-08-21 上架计划页） ─────────────────────
# 导航：侧边栏「销售管理」→ 子菜单「上架计划」
SEL_SIDEBAR = ".sidebar-container"
SEL_MENU_SALES = "text=销售管理"
SEL_SUB_LISTING_PLAN = "text=上架计划"
SEL_PLAN_TABLE = ".vxe-table--body-wrapper"
SEL_BATCH_LISTING = "button:has-text('批量刊登')"          # 勘察确认
SEL_ROW_EDIT = "button:has-text('编辑')"                    # 勘察确认（行内编辑）
SEL_ROW_PUBLISH = "button:has-text('刊登')"                 # 勘察确认（行内刊登）
SEL_ROW_DELETE = "button:has-text('删除')"                  # 勘察确认（行内删除）
# 详情页（待勘察：点击「编辑」后进入图片/价格编辑）
SEL_IMAGE_LIST = ".image-list"
SEL_SAVE_IMAGE = "button:has-text('保存')"
SEL_CALC_TABLE = ".price-calc-table"
SEL_RECALC = "button:has-text('重新测算')"
SEL_SAVE_PRICE = "button:has-text('保存算价结果')"


def _open_plan_page(page, config: dict) -> None:
    """导航到上架计划页：侧边栏「销售管理」→ 子菜单「上架计划」。"""
    page.goto(config["app"]["base_url"], wait_until="domcontentloaded", timeout=60000)
    wait_network_idle_light(page)
    page.wait_for_timeout(1500)
    sidebar = page.locator(SEL_SIDEBAR)
    # 展开「销售管理」
    sm = sidebar.locator(SEL_MENU_SALES).first
    if sm.count():
        sm.click(timeout=8000)
        page.wait_for_timeout(1500)
    # 点击「上架计划」
    sub = sidebar.locator(SEL_SUB_LISTING_PLAN).first
    if sub.count():
        sub.click(timeout=8000)
        page.wait_for_timeout(2500)
        log(f"[phase2] 已进入上架计划页: {page.url}")
    else:
        raise RuntimeError("[phase2] ✗ 未找到「上架计划」子菜单")


def _probe_plan(page, config: dict) -> None:
    """勘察上架计划页结构。"""
    _open_plan_page(page, config)

    # 统计关键元素
    for name, sel in {
        "table_上架计划": SEL_PLAN_TABLE,
        "btn_批量刊登": SEL_BATCH_LISTING,
        "btn_编辑": SEL_ROW_EDIT,
        "btn_刊登": SEL_ROW_PUBLISH,
        "btn_删除": SEL_ROW_DELETE,
    }.items():
        try:
            n = page.locator(sel).count()
            log(f"[probe] {'✓' if n else '✗'} {name}: {sel} → {n}")
        except Exception as e:
            log(f"[probe] ✗ {name}: {e}")

    # dump 表格列头
    headers = page.evaluate(
        """() => {
            const t = document.querySelector('.vxe-table');
            if (!t) return [];
            const cols = t.querySelectorAll('.vxe-header-column .vxe-cell, '
                + '.vxe-header-column .vxe-column--title');
            return [...cols].map(c => (c.innerText||'').trim()).filter(Boolean);
        }"""
    )
    log(f"[probe] 表格列头: {headers}")

    shot = ROOT / "runtime" / "probe_phase2.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shot), full_page=True)
    log(f"[probe] 截图: {shot}")


def _check_images(page, config: dict) -> list[str]:
    """图片校验：返回问题列表（空 = 通过）。"""
    issues = []
    v = config["verification"]
    target = v["spu_image_count"]

    img_els = page.locator(f"{SEL_IMAGE_LIST} img")
    count = img_els.count()
    if count < target:
        issues.append(f"图片不足：{count}/{target} 张")

    # 主图白底校验（读取像素，勘察后按真实 DOM 位置取主图）
    if v["main_image_white_bg"] and count > 0:
        white = _is_main_white(page, img_els.first)
        if white is not None and not white:
            issues.append("主图非白底")

    # SKU 色标与图片一一对应（勘察后实现精确比对）
    return issues


def _is_main_white(page, img_el) -> bool | None:
    """判断主图是否白底（采样像素，勘察后校准阈值）。"""
    try:
        return page.evaluate(
            """async (el) => {
                try {
                    const img = new Image();
                    img.crossOrigin = 'anonymous';
                    img.src = el.currentSrc || el.src;
                    await img.decode();
                    const c = document.createElement('canvas');
                    c.width = 40; c.height = 40;
                    const ctx = c.getContext('2d');
                    ctx.drawImage(img, 0, 0, 40, 40);
                    const d = ctx.getImageData(0,0,40,40).data;
                    let white = 0;
                    for (let i=0;i<d.length;i+=4){
                        if(d[i]>240&&d[i+1]>240&&d[i+2]>240) white++;
                    }
                    return white/(d.length/4) > 0.7;
                } catch(e) { return null; }
            }""",
            img_el,
        )
    except Exception:
        return None


def _read_num(page, header_text: str, default: float) -> float:
    """按列头读取数值单元格（勘察后实现）。占位返回 default。"""
    # 待勘察：横向滚动找到列头 → 取同列单元格 → 解析数字
    return default


# ── 利润测算抽屉：真实页面二分搜索（2026-08-21 已跑通） ─────────────
# 已验证交互原语：
#   · 打开抽屉后主表列头含「利润($)/利润率」「活动营销费($) / 占比」
#   · 行内公司利润率输入框 = 该行第3个可见 input（input[2]）
#   · 用 page.fill('#__margin2__', val) 修改（原生 setter/键盘均不触发 vxe 提交）
#   · 点「重新测算」后个人利润率 = 个人利润/收入，随公司利润率线性变化
#   · 目标个人利润率 4-6% 需公司利润率大幅下调（本批约 5%，见 config.margin_adjust_min）

def _open_profit_drawer(page, row_idx: int = 0) -> bool:
    """点击上架计划表格某行的「价格」列「编辑」按钮（col12，第3个编辑按钮），打开利润测算抽屉。"""
    try:
        # 轮询等待主表数据行渲染出编辑按钮（异步加载）
        btns = None
        for _ in range(25):
            btns = page.locator(".vxe-table button:has-text('编辑')")
            if btns.count() >= row_idx * 4 + 3:
                break
            page.wait_for_timeout(1000)
        n = btns.count()
        # 每行4个编辑按钮（col10文案/col11图片/col12价格/col13属性），价格=第3个
        idx = row_idx * 4 + 2
        if idx >= n:
            log(f"[phase2] ✗ 编辑按钮不足: {n}, 需 idx={idx}")
            return False
        btns.nth(idx).click(timeout=8000)
        page.wait_for_timeout(3500)
        return page.evaluate(_JS_HAS_MAIN_TABLE)
    except Exception as e:
        log(f"[phase2] ✗ 打开利润抽屉失败: {e}")
        return False


_JS_HAS_MAIN_TABLE = """() => {
    const roots = [...document.querySelectorAll(
        '.el-drawer:not([style*="display: none"]), .el-dialog:not([style*="display: none"])')]
        .filter(r => r.offsetParent !== null || r.getBoundingClientRect().width > 0);
    const root = roots.find(r => (r.innerText||'').includes('保存算价')) || roots[0];
    if (!root) return false;
    for (const tb of root.querySelectorAll('.vxe-table, table')) {
        const heads = [...tb.querySelectorAll('.vxe-header-column .vxe-cell, th')]
            .map(h => (h.innerText||'').trim()).filter(Boolean);
        if (heads.includes('利润($)/利润率') && heads.includes('活动营销费($) / 占比')) return true;
    }
    return false;
}"""


def _snap_row0(page) -> dict:
    """读取主表首行关键字段（按列头标题动态定位，colid 会随 SKU 变体数漂移）。

    真实 DOM（2026-08-27 勘察确认）：
      - 公司利润率 input  = 列头「利润($)/利润率」对应 td 的 input，填百分比，suffix %
      - 活动营销费 input  = 列头「活动营销费($) / 占比」对应 td 的 input，suffix %
      - 个人利润率        = 「利润($)/利润率」cell 文本内「个人: <金额> <Y%>」里的 Y

    注意：colid 不固定（SPU#3=col_58/69，SPU#4=col_100/111，因竞品参照列数量不同
    而偏移），必须用列头标题反查 colid，不能硬编码。
    """
    return page.evaluate(
        """() => {
            const roots = [...document.querySelectorAll(
                '.el-drawer:not([style*="display: none"]), .el-dialog:not([style*="display: none"])')]
                .filter(r => r.offsetParent !== null || r.getBoundingClientRect().width > 0);
            const root = roots.find(r => (r.innerText||'').includes('保存算价')) || roots[0];
            if (!root) return { note: 'no drawer' };

            // 按列头标题反查 colid（标题会因 SKU 变体数不同而漂移，故动态解析）
            const colidByTitle = {};
            for (const th of root.querySelectorAll('th')) {
                const cid = th.getAttribute('colid');
                const title = (th.innerText||'').trim().replace(/\\s+/g, '');
                if (cid) colidByTitle[title] = cid;
            }
            const marginCid = colidByTitle['利润($)/利润率'];
            const feeCid = colidByTitle['活动营销费($)/占比'];
            if (!marginCid || !feeCid) return { note: 'no 利润/活动营销费 col', colidByTitle };

            const tdMargin = root.querySelector('td[colid="' + marginCid + '"]');
            const tdFee = root.querySelector('td[colid="' + feeCid + '"]');
            if (!tdMargin || !tdFee) return { note: 'no td for 利润/活动营销费' };

            const inpMargin = tdMargin.querySelector('input');
            const inpFee = tdFee.querySelector('input');
            if (!inpMargin || !inpFee) return { note: 'no inputs' };

            // 打 id 标记，供 fill 用
            inpMargin.id = '__margin2__';
            inpFee.id = '__mkt_fee__';

            const margin = parseFloat(inpMargin.value);   // 公司利润率 %（当前 40）
            const mkt_fee = parseFloat(inpFee.value);     // 活动营销费输入框原始值

            // 活动营销费「占比%」= 该 cell 内 span 主数值
            const feeSpan = tdFee.querySelector('.vxe-cell span');
            const feePct = feeSpan ? parseFloat(feeSpan.innerText) : null;

            // 个人利润率 = 利润 cell 文本里「个人: <金额> <Y%>」
            const text = tdMargin.innerText;
            const m = text.match(/个人:\\s*[\\d.]+\\s+([\\d.]+)%/);
            return {
                margin,
                mkt_fee,
                mkt_fee_pct: feePct,
                personal_pct: m ? parseFloat(m[1]) : null,
                text,
            };
        }"""
    )


def _blur(page) -> None:
    """点击页面左上角空白处触发 blur，使 vxe 输入框提交值。

    关键：vxe-table 的单元格 input 在 fill 后不会立即 commit，必须失焦
    （blur）才写入数据模型；否则「重新测算」仍用旧值计算。
    """
    try:
        page.locator("body").click(position={"x": 3, "y": 3})
        page.wait_for_timeout(300)
    except Exception:
        pass


def _set_company_margin(page, value: float) -> bool:
    """用 fill + blur 修改首行公司利润率输入框（触发 vxe 提交）。"""
    try:
        page.fill("#__margin2__", f"{value:.2f}")
        page.wait_for_timeout(200)
        _blur(page)
        return True
    except Exception as e:
        log(f"[phase2] ✗ 设置公司利润率失败: {e}")
        return False


def _set_activity_marketing_rate(page, pct: float) -> bool:
    """用 fill + blur 修改首行活动营销费占比输入框（后缀 %，填占比数值）。"""
    try:
        page.fill("#__mkt_fee__", f"{pct:.2f}")
        page.wait_for_timeout(200)
        _blur(page)
        return True
    except Exception as e:
        log(f"[phase2] ✗ 设置活动营销费占比失败: {e}")
        return False


def _recalc_profit(page) -> bool:
    """点击抽屉内「重新测算」，等待加载完成。

    用 JS 直接 click 以绕过 el-loading-mask 遮罩的可见性拦截；点击后等待
    抽屉内 loading 遮罩消失（重新测算完成），避免紧接着的读取读到旧值。
    """
    try:
        clicked = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                if (!root) return false;
                const btn = [...root.querySelectorAll('button')]
                    .find(b => (b.innerText||'').trim() === '重新测算');
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        # 等待抽屉内 loading 遮罩消失（重新测算完成）
        for _ in range(20):
            busy = page.evaluate(
                """() => {
                    const roots = [...document.querySelectorAll(
                        '.el-drawer:not([style*="display: none"]), '
                        + '.el-dialog:not([style*="display: none"])')]
                        .filter(r => r.offsetParent !== null
                            || r.getBoundingClientRect().width > 0);
                    const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                        || roots[0];
                    if (!root) return false;
                    const mask = root.querySelector('.el-loading-mask, .el-overlay, .vxe-loading');
                    if (mask && mask.getBoundingClientRect().width > 0) return true;
                    return false;
                }"""
            )
            if not busy:
                break
            page.wait_for_timeout(500)
        page.wait_for_timeout(800)
        return clicked
    except Exception as e:
        log(f"[phase2] ✗ 点重新测算失败: {e}")
        return False


def _auto_adjust_company_margin(page, config: dict) -> dict:
    """二分搜索公司利润率，使首行个人利润率落入目标区间。

    返回: {"ok": bool, "margin": 目标公司利润率%, "personal_pct": 实际个人利润率%,
           "message": str}
    dry-run（不点保存）由调用方控制。
    """
    v = config["verification"]
    lo = v["margin_adjust_min"] * 100      # 公司利润率下限 %
    hi_default = v["margin_adjust_max"] * 100

    s0 = _snap_row0(page)
    cur = s0.get("margin")
    if cur is None:
        return {"ok": False, "message": f"无法读取公司利润率: {s0.get('note')}"}
    # 上限以当前值或配置上限取大者（当前值通常即配置上限）
    hi = max(hi_default, cur)

    target_lo = v["personal_profit_min"] * 100
    target_hi = v["personal_profit_max"] * 100
    log(f"[phase2][利润] 目标个人利润率 {target_lo}%–{target_hi}% | "
        f"公司利润率搜索范围 {lo}%–{hi}%（当前 {cur}%）")

    best = None
    for step in range(v.get("max_binary_steps", 14)):
        mid = round((lo + hi) / 2, 2)
        if abs(mid - lo) < 0.01 or abs(mid - hi) < 0.01:
            break
        _set_company_margin(page, mid)
        _recalc_profit(page)
        s = _snap_row0(page)
        pct = s.get("personal_pct")
        if pct is None:
            log(f"[phase2][利润] step{step}: 公司利润率={mid}% → 个人利润率=读取失败")
            break
        log(f"[phase2][利润] step{step}: 公司利润率={mid}% → 个人利润率={pct}%")
        best = (mid, pct)
        if target_lo <= pct <= target_hi:
            log(f"[phase2][利润] ✓ 命中: 公司利润率={mid}% → 个人利润率={pct}%")
            return {"ok": True, "margin": mid, "personal_pct": pct,
                    "message": f"公司利润率调至 {mid}% → 个人利润率 {pct}%"}
        if pct > target_hi:
            hi = mid      # 个人利润率太高 → 降低公司利润率
        else:
            lo = mid      # 个人利润率太低 → 升高公司利润率

    if best:
        log(f"[phase2][利润] ✗ 未命中目标区间，最近: 公司利润率={best[0]}% → 个人利润率={best[1]}%")
        return {"ok": False, "margin": best[0], "personal_pct": best[1],
                "message": f"未命中 {target_lo}-{target_hi}%（最近 公司利润率{best[0]}%→个人{best[1]}%）。"
                           "可能需调整 margin_adjust_min（公司利润率下限）"}
    return {"ok": False, "message": "利润试算未收敛"}


def _find_target_rows(page, config: dict) -> list[int]:
    """定位「目标品类 + 草稿（未刊登）」的行索引。

    关键：上架计划页首行可能是「已刊登」或非目标品类（如 Christmas Trees），
    这类行调低公司利润率会触发「公司利润率需高于15%」低毛利拦截。
    只应处理「品类 = 目标品类（platform_path 末级）+ 上架状态 = 草稿」的行。

    列定位（2026-08-27 勘察确认）：
      - col_22 = 品类（如 "Wreaths, Garlands & Swags"）
      - col_25 = 上架状态（如 "草稿"）
    """
    target_cat = config["category"]["platform_path"][-1]

    # 轮询等待主表数据行 + 品类列渲染（vxe 虚拟滚动右侧列懒加载，需等待）
    rows = None
    for _ in range(30):
        rows = page.evaluate(
            """(targetCat) => {
                const bodies = [...document.querySelectorAll('.vxe-table--body-wrapper')];
                let body = bodies.sort((a,b) =>
                    b.querySelectorAll('tr').length - a.querySelectorAll('tr').length)[0];
                if (!body) return [];
                const trs = [...body.querySelectorAll('tr')];
                if (!trs.length) return [];
                // 按列头标题反查 colid（品类/上架状态）
                const colidByTitle = {};
                for (const th of document.querySelectorAll('th')) {
                    const cid = th.getAttribute('colid');
                    const t = (th.innerText||'').trim();
                    if (cid) colidByTitle[t] = cid;
                }
                const catCid = colidByTitle['品类'];
                const statusCid = colidByTitle['上架状态'];
                if (!catCid || !statusCid) return [];
                const out = [];
                trs.forEach((tr, i) => {
                    let cellCat = '', status = '';
                    for (const td of tr.querySelectorAll('td')) {
                        const cid = td.getAttribute('colid');
                        if (cid === catCid) cellCat = (td.innerText||'').trim();
                        else if (cid === statusCid) status = (td.innerText||'').trim();
                    }
                    if (cellCat === targetCat && status === '草稿') out.push(i);
                });
                return out;
            }""",
            target_cat,
        )
        if rows:
            break
        page.wait_for_timeout(1000)
    return rows or []


def _check_price(page, config: dict, row_idx: int = 0) -> list:
    """价格/利润校验：打开利润抽屉 → 自动试算公司利润率使个人利润落目标区间（dry-run 不保存）。"""
    issues = []
    v = config["verification"]
    if not _open_profit_drawer(page, row_idx):
        issues.append("无法打开利润测算抽屉")
        return issues

    shot = ROOT / "runtime" / f"profit_row{row_idx}_drawer.png"
    page.screenshot(path=str(shot), full_page=True)
    log(f"[phase2][利润] 抽屉截图: {shot}")

    # 抽屉打开默认「0 个 sku / 暂无数据」，需点「搜索」加载该 SPU 的测算行
    # 注意：搜索按钮必须限定在抽屉根内定位，避免命中主表其它按钮 / 被遮罩拦截
    try:
        page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                if (!root) return false;
                const btn = [...root.querySelectorAll('button')]
                    .find(b => (b.innerText||'').trim() === '搜索');
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
        # 轮询等待抽屉测算表格出现数据行
        for _ in range(25):
            if _snap_row0(page).get("margin") is not None:
                break
            page.wait_for_timeout(1000)
    except Exception as e:
        log(f"[phase2][利润] 点搜索失败: {e}")

    # 读首行快照（同时给 公司利润率/活动营销费 输入框打 id 标记）
    s0 = _snap_row0(page)
    if s0.get("margin") is None:
        issues.append(f"无法读取首行测算数据: {s0.get('note')}")
        return issues

    # ① 先把活动营销费占比设为 config 要求（默认 50%），重新测算
    mkt_rate = v["activity_marketing_rate"] * 100
    cur_fee = s0.get("mkt_fee")
    log(f"[phase2][利润] 活动营销费占比：当前 {cur_fee}% → 目标 {mkt_rate}%")
    if cur_fee is None or abs(cur_fee - mkt_rate) > 0.01:
        if _set_activity_marketing_rate(page, mkt_rate):
            _recalc_profit(page)
            log(f"[phase2][利润] ✓ 已设活动营销费占比 {mkt_rate}% 并重新测算")
        else:
            issues.append("设置活动营销费占比失败")

    # ② 调整公司利润率使个人利润落入目标区间
    res = _auto_adjust_company_margin(page, config)
    if not res.get("ok"):
        issues.append(res.get("message", "利润试算未命中"))

    # dry-run：只报告，不点「保存算价结果」
    if config["safety"].get("dry_run", True):
        log(f"[phase2][利润][dry-run] 目标公司利润率={res.get('margin')}%，"
            f"个人利润率={res.get('personal_pct')}%（未保存算价结果）")
    else:
        try:
            page.get_by_role("button", name="保存算价结果").click(timeout=5000)
            page.wait_for_timeout(2500)
            log(f"[phase2][利润] ✓ 已保存算价结果（公司利润率={res.get('margin')}%）")
        except Exception as e:
            issues.append(f"保存算价结果失败: {e}")

    # 关闭抽屉：点抽屉关闭按钮（Escape 在 input 聚焦时可能只取消输入态，不关抽屉）
    _close_profit_drawer(page)
    return issues


def _close_profit_drawer(page) -> None:
    """可靠关闭利润抽屉：点关闭按钮 + Escape 兜底 + 等待遮罩消失。"""
    try:
        page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                if (!root) return false;
                // 优先点 el-drawer/el-dialog 顶部的关闭按钮
                const closeBtn = root.querySelector(
                    '.el-drawer__close-btn, .el-dialog__headerbtn, '
                    + '[aria-label="Close"], [aria-label="close"]');
                if (closeBtn) { closeBtn.click(); return true; }
                return false;
            }"""
        )
    except Exception:
        pass
    page.wait_for_timeout(800)
    # Escape 兜底
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    # 等待遮罩消失
    for _ in range(20):
        gone = page.evaluate(
            """() => {
                const mask = [...document.querySelectorAll('.el-overlay, .v-modal')]
                    .filter(m => m.getBoundingClientRect().width > 0
                        && getComputedStyle(m).display !== 'none');
                return mask.length === 0;
            }"""
        )
        if gone:
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(500)


def _run_checks(page, config: dict) -> dict:
    """对当前上架计划页所有待上架 SPU 执行校验。"""
    v = config["verification"]
    report = {"image_issues": [], "price_issues": [], "ok_spus": 0, "fail_spus": 0}

    table = page.locator(SEL_PLAN_TABLE).first
    # vxe-table 异步渲染，等待数据行出现（probe 因后续多次 count 累计了额外等待才读到行，
    # 这里须显式等待，否则紧接 _open_plan_page 的 2500ms 可能不够）
    try:
        table.locator("tr").first.wait_for(state="attached", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    rows = table.locator("tr")
    total = rows.count()
    log(f"[phase2] 上架计划共 {total} 行")

    # 只处理「目标品类 + 草稿」行，跳过已刊登/非目标品类行（避免低毛利拦截）
    target_rows = _find_target_rows(page, config)
    target_cat = config["category"]["platform_path"][-1]
    log(f"[phase2] 目标品类「{target_cat}」草稿行: {target_rows}（共 {len(target_rows)} 行）")
    if not target_rows:
        log("[phase2] ✗ 未找到目标品类草稿行")
        return report

    for i in target_rows:
        spu = f"SPU#{i}"
        log(f"[phase2] 校验 {spu}（目标品类草稿）...")

        # 图片校验（点击行内「编辑」进入详情页——详情页结构待勘察，暂跳过）
        # 注意：safe_click 期望 (page, selector)，此处 row 是 Locator，不可混用。
        # 图片校验尚未勘察详情页结构，MVP 阶段跳过，聚焦价格/利润算价。

        # 价格校验：打开该行利润测算抽屉 → 自动试算公司利润率（_check_price 内部完成）
        price_issues = _check_price(page, config, row_idx=i)
        if price_issues:
            report["price_issues"].append({spu: price_issues})
            report["fail_spus"] += 1
        else:
            report["ok_spus"] += 1

    log(f"[phase2] 校验完成: 通过 {report['ok_spus']} / 问题 {report['fail_spus']}")
    return report


def main() -> None:
    config = load_config()
    args = sys.argv[1:]
    probe_mode = "--probe" in args
    dry_run = not ("--no-dry-run" in args)

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[phase2] ✗ 未登录，先 `python -m src.login --login`")
            browser.close()
            sys.exit(1)

        if probe_mode:
            _probe_plan(page, config)
        else:
            _open_plan_page(page, config)
            report = _run_checks(page, config)
            if dry_run:
                log(f"[phase2][dry-run] 校验报告: 图片问题 {len(report['image_issues'])} / "
                    f"价格问题 {len(report['price_issues'])}（未批量上架）")
            else:
                log("[phase2] 待勘察后接入批量上架动作")

        browser.close()


if __name__ == "__main__":
    main()