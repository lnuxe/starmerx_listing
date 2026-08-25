"""DOM 操作辅助工具：定位、快照、滚动、状态读取。

提供确定性代码所需的通用 DOM 原语，避免每个脚本重复造轮子。
"""
from __future__ import annotations

from src.config import log


def snapshot_interactive(page, max_depth: int = 10) -> str:
    """返回页面的可交互元素可访问性树（供调试/勘察用）。"""
    try:
        return page.accessibility.snapshot()
    except Exception:
        # playwright 无 accessibility.snapshot 时退回 DOM 摘要
        return page.evaluate(
            """() => {
                const els = document.querySelectorAll(
                    'button, a, input, select, textarea, [role=button], [role=tab]'
                );
                return [...els].slice(0, 200).map((e, i) => {
                    const r = e.getBoundingClientRect();
                    const txt = (e.innerText || e.value || e.placeholder || '')
                        .trim().replace(/\\s+/g, ' ').slice(0, 60);
                    return `${i}:<${e.tagName.toLowerCase()}> ${txt} @(${Math.round(r.x)},${Math.round(r.y)})`;
                }).join('\\n');
            }"""
        )


def table_headers(page, table_selector: str = ".vxe-table") -> list[str]:
    """读取 vxe-table 的列头文本列表。"""
    return page.evaluate(
        """(sel) => {
            const t = document.querySelector(sel);
            if (!t) return [];
            const cols = t.querySelectorAll('.vxe-table--header .vxe-header-column .vxe-cell, '
                + '.vxe-table--header .vxe-header-column .vxe-column--title');
            return [...cols].map(c => c.innerText.trim()).filter(Boolean);
        }""",
        table_selector,
    )


def scroll_table_horizontal(page, selector: str = ".vxe-table--body-wrapper", px: int = 3000) -> None:
    """横向滚动宽表容器，露出操作列/价格列。"""
    page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            if (el) el.scrollLeft = arguments[1];
        }""",
        selector,
        px,
    )


def wait_network_idle_light(page, timeout_ms: int = 15000) -> None:
    """轻量等待网络空闲（SPA 数据加载），超时不报错。"""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def safe_click(page, selector: str, timeout_ms: int = 8000) -> bool:
    """点击元素并验收（未抛异常即视为成功）。"""
    try:
        page.click(selector, timeout=timeout_ms)
        return True
    except Exception as e:
        log(f"[dom] 点击失败 {selector}: {e}")
        return False


def input_value(page, selector: str) -> str:
    """读取输入框当前值。"""
    try:
        return page.input_value(selector, timeout=3000)
    except Exception:
        return ""


def is_checked(page, selector: str) -> bool:
    """读取复选框选中态。"""
    try:
        return page.is_checked(selector, timeout=3000)
    except Exception:
        return False


def is_visible(page, selector: str) -> bool:
    try:
        return page.is_visible(selector, timeout=2000)
    except Exception:
        return False