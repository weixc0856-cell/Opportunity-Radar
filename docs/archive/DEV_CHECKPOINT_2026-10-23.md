# 开发检查点（2026-10-23）

> 状态：**FROZEN**。本检查点记录 README 脱敏、栏目级新闻源、两处运行时缺陷修复与模型按需启动。
> `data/checkpoint-2026-10-23-dev/CHECKPOINT_MANIFEST.json` 保存 24 个关键文件的 SHA-256 与 git 状态。
> **本检查点不等于来源已达生产验收。**
>
> 冻结后重切一次：P1 的只读审计工具需要一个可选的 `include_html` 参数（默认关闭、不改变管道行为），
> 并新增了 `tools/fulltext_audit.py` 与 `docs/FULL_TEXT_AUDIT_2026-10-23.md`。manifest 已更新到当前状态；
> 评分、证据与通道逻辑仍未改动。

## 一、本轮变更

| 变更 | 内容 | 验证 |
|---|---|---|
| README 脱敏 | 移除本机路径、邮箱服务商、实例启用数量与"本机"表述；同步当前实现与文档索引 | 全文检索无盘符路径、邮箱、`个人`、`本机` |
| 栏目级新闻源 | 新增 BBC/NYT 的 Business 与 Technology 四个 Feed（feed id 24–27） | 客户端逐个取数 50/49/21/23 条；4 篇冒烟 4/4 分析成功 |
| 旧首页源退役 | `bbc-news`(22)、`nyt-home`(23) 本机置为禁用，注明被栏目级 Feed 取代 | 审计 0 error；历史 Feed 保留 |
| Feed 排序修复 | `sorted(feed_ids)` 按字符串排序会让 `'17'` 先于 `'3'`，小样本时低 ID 来源无配额 | 2 个单测；数字优先排序 |
| Windows 编码修复 | 报告含 `£` 时 `print(body)` 在 GBK 控制台抛异常，整轮被误记为失败 | stdout/stderr 重配 UTF-8；复跑通过 |
| 模型按需启动 | `OR_MODEL_AUTOSTART=1` 时检查 `/health` 并调用 `start-model.ps1`，失败退出 3 | 6 个单测；本次实际启动成功 |
| 正文获取机制 | `full_text_fetch=none|article_page`，默认全关；遵守 robots、拒绝 401/403/429 与跨域跳转 | 20 个单测；试抓 4 个页面 |

## 二、登记与来源

- 登记表 47 行；仓库模板 0 启用；本机 15 启用；审计 0 error / 0 warning。
- 新增（本机启用）：`bbc-business`(24)、`nyt-business`(25)、`bbc-technology`(26)、`nyt-technology`(27)。
- 退役（本机禁用）：`bbc-news`(22)、`nyt-home`(23)。
- 此前已完成：BEA 的 http→https 同域升级；Census 因无条目级链接禁用。

## 三、验证

- 单元测试 **371 通过**；模板审计 47 行 / 0 启用 / 0 error。
- 数据集登记 2 行 / 1 approved / 0 error。
- 两批冻结实验归档哈希复核 0 不匹配：
  - `data/e2e-2026-10-23/ARCHIVE_MANIFEST.json`
  - `data/e2e-round2-2026-10-23/ARCHIVE_MANIFEST.json`
- 评分权重、证据门槛、通道逻辑（`scoring.toml`、`evidence.py`、`lanes.py`）未改动。

## 四、边界

- **没有**提交、推送、创建 PR 或合并。
- 本机登记、数据库、报告与日志均在 `.gitignore` 覆盖范围内。
- 旧来源保持禁用，历史实验数据未被覆盖。
- 371 项测试通过、审计无错误、冒烟成功，**不构成**"所有来源已通过生产验收"。

## 五、下一阶段（按顺序）

1. **P1 正文完整性抽样**：对 NVIDIA、ONS、Federal Reserve 逐源抽样，比较 Feed 摘要与原文页，记录正文长度、容器、日期、失败与许可限制。技术达标且许可可确认后才开启 `full_text_fetch`；不得因来源权威或正文较长就声明 `full_text_verified`。
2. **P2 A 通道评分口径复核**：在输入质量验证后，离线比较"重要性"与"可行动性"，保留现有结果作为基线，不直接改生产评分。
3. **P3 受控验证**：固定窗口、样本规则、模型与评分配置，来源盲化，人工评价相关性、噪声率、可行动性与误分类率。

状态语义必须分开：`full_text_fetch`（机制）≠ `content_access_level=full_text`（人工批准）≠ `full_text_verified`（单条内容核验）≠ `primary_source_located`（引文可定位，不证明事实）。
