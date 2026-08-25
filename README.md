# Starmerx 上架自动化（MVP：圣诞花环单品类）

基于 Playwright 的确定性浏览器自动化，实现「产品池 → 加入上架计划 → 图片/价格校验 → 批量上架」全流程。
**规则校验用纯代码（确定性），LLM 仅做视觉/语义兜底**，确保利润试算、图片校验可复现、不失控。

## 技术栈
- Python 3.13 + Playwright 1.62（确定性 DOM 操作）
- 阿里云通义千问 Qwen（预留，仅规则层失败时兜底）
- 登录：钉钉扫码 + storageState 持久化（约 2 天过期）

## 快速开始
```bash
# 1. 初始化环境（首次）
chmod +x run.sh
./run.sh login                # 弹出浏览器，钉钉扫码（首次/过期）

# 2. 勘察真实页面结构（确认选择器，不修改数据）
./run.sh probe-phase1         # 勘察产品池页
./run.sh probe-phase2         # 勘察上架计划页

# 3. 跑通单品类（默认干运行：只检查不上架）
./run.sh phase1 --max-sku 1   # 选 1 个 SKU 加入上架计划
./run.sh phase2              # 图片/价格校验（干运行）

# 4. 正式执行（确认无误后）
./run.sh phase1 --no-dry-run --max-sku 5
./run.sh phase2 --no-dry-run
```

## 项目结构
```
starmerx_listing/
├── run.sh                 # 一键启动脚本
├── config.json            # 全部配置（固定表单值/类目/校验规则/安全开关）
├── src/
│   ├── main.py            # 四阶段编排入口
│   ├── login.py           # 钉钉扫码 + storageState 持久化
│   ├── phase1.py          # 产品池 → 加入上架计划
│   ├── phase2.py          # 图片/价格校验 + 批量上架
│   ├── price_calc.py      # 利润试算引擎（有界二分，防死循环）
│   ├── dom.py             # DOM 操作辅助
│   └── config.py          # 配置/日志
├── scripts/
│   └── probe_product_pool.py  # 独立勘察工具
└── runtime/               # storage_state.json、勘察截图、日志
```

## 关键规则（来自 config.json）
| 项 | 值 |
|----|-----|
| 平台/站点/店铺/品牌 | Tik Tok / tiktok.com / Garvee Mate / 无品牌 |
| 系统类目（产品池） | 家居厨具→节日饰品→圣诞花环花带→圣诞花带装饰 |
| 平台类目（上架表单） | Home Supplies→Festive→Wreaths, Garlands & Swags |
| SPU 图片 | 8 张（含白底主图），SKU 色标一一对应 |
| 活动营销费占比 | 50% |
| 个人利润目标 | 4%–6%（通过调「公司利润率」实现） |
| 公司利润率边界 | 0.30–0.60（**待确认 P1**，见下） |
| GTIN / 生成方式 | 豁免 / 按SPU维度生成多上架计划 |

## ⚠️ 待确认事项（上线前必须解决）
1. **利润率下限/上限（P1）**：个人利润 4-6% 的「公司利润率」可调边界当前暂定 0.30–0.60。
   若边界错误，利润试算可能永远无法命中区间而死循环。
   → 需你在真实「利润测算」弹窗中确认公司利润率的可调范围。
2. **真实利润公式**：`src/price_calc.py` 中的个人利润公式为**占位模型**（`K=0.24` 缩放），
   勘察到「利润测算」弹窗的真实测算逻辑后需替换为精确公式。

## 安全设计
- **默认干运行**：所有阶段只检查、只输出清单，不真正上架。加 `--no-dry-run` 才执行。
- **利润试算有界**：最多 20 次迭代，未命中即报「需人工介入」，绝不无限循环。
- **勘察优先**：任何新页面先跑 probe 确认选择器，确认后才进入执行模式。
- **操作验收**：每次点击后用 DOM 状态确认（input value / checkbox checked），失败即中止。

## 部署（阿里云）
- 推荐轻量 2C2G Ubuntu（香港/新加坡节点，需先测试 `op.starmerx.com` 可达性）
- cron 每日定时 + storageState 过期自动提醒重扫
- 详见 `docs/DEPLOYMENT.md`（待编写）