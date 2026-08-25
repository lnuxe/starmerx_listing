"""利润试算引擎（纯算法，无 DOM 依赖，可单测）。

目标：调整「公司利润率」使「个人利润」落在目标区间（默认 4%–6%）。

公式（待勘察后从真实页面核对）：
    personal_profit = f(price, company_margin, activity_marketing_rate, ...)

文档要求：活动营销费占比固定 50%，通过调整「公司利润率」让个人利润落 4%–6%。

设计：
- 试算公式做成可插拔（_calc_personal_profit），勘察真实页面后替换为精确公式。
- 二分/步进搜索「公司利润率」，带 max_iterations 上限，超出即报「需人工介入」，杜绝死循环。
- 边界（margin_adjust_min/max）来自 config.verification，未确认前保持保守。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProfitResult:
    ok: bool                 # 是否找到满足区间解
    company_margin: float | None
    personal_profit: float | None
    iterations: int
    message: str
    history: list[tuple[float, float]] = field(default_factory=list)  # (margin, personal_profit)


def _calc_personal_profit(company_margin: float, activity_rate: float) -> float:
    """估算个人利润率（占位公式，待勘察后替换为真实测算）。

    占位模型：个人利润 ≈ (1 - activity_rate) * company_margin * K
    真实平台公式未知，故用线性占位；勘察到真实公式后替换本函数即可。
    """
    # 占位：个人利润随公司利润率上升，活动费扣减
    # K 经校准使占位公式在 [0.30,0.60]×50% 活动费下可解，证明二分引擎逻辑正确。
    # 勘察到真实平台测算公式后替换本函数即可。
    K = 0.24  # 占位缩放系数，勘察后校准
    return max(0.0, (1 - activity_rate) * company_margin * K)


def solve_company_margin(
    activity_rate: float,
    target_min: float,
    target_max: float,
    margin_min: float,
    margin_max: float,
    max_iterations: int = 20,
) -> ProfitResult:
    """在 [margin_min, margin_max] 内二分搜索「公司利润率」，使个人利润落 [target_min, target_max]。

    有界迭代：最多 max_iterations 次，超出返回 ok=False + 提示人工介入。
    """
    hist: list[tuple[float, float]] = []
    lo, hi = margin_min, margin_max

    for it in range(1, max_iterations + 1):
        mid = (lo + hi) / 2
        profit = _calc_personal_profit(mid, activity_rate)
        hist.append((mid, profit))

        if target_min <= profit <= target_max:
            return ProfitResult(True, mid, profit, it,
                                f"命中区间：公司利润率 {mid:.4f} → 个人利润 {profit:.4%}")
        if profit < target_min:
            lo = mid   # 利润太低，上调公司利润率
        else:
            hi = mid   # 利润太高，下调公司利润率

        if (hi - lo) < 1e-6:
            break

    best = hist[-1] if hist else (margin_min, 0.0)
    return ProfitResult(False, best[0], best[1], len(hist),
                        f"未在 {max_iterations} 次内命中区间（末态 个人利润 {best[1]:.4%}），"
                        f"需人工介入或调整边界")


if __name__ == "__main__":
    # 自测
    r = solve_company_margin(0.50, 0.04, 0.06, 0.30, 0.60)
    print(r)
    assert r.ok, "应能命中区间"
    print("self-test PASS")