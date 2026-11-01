# 端到端来源质量验证（E2E Source Quality Run，2026-10-23）

> 本轮只做**观测**：不修改评分权重、证据门槛、晋升规则或准入校验。
> 两个组使用隔离数据库、同一台模型、同一份代码；所有原始产物保存在 `data/e2e-2026-10-23/`
> （被 `.gitignore` 排除，仅本机留存）。
> 人工抽查是**单人判断**，不是标注集，不能当作准确率。

## 一、当前版本复验（先做）

`data/e2e-2026-10-23/verify-current-version.txt`，2026-10-23 12:48 起执行：

| 检查 | 结果 |
|---|---|
| `unittest discover` | 328 tests，OK |
| `source_audit` | 43 行；14 启用；0 error / 0 warning |
| `datasets --check` | 2 行；1 approved；Eurostat HTTP 200，最新期间 2025-12 = 2.0 |
| `page_monitor` | 国家统计局 `skipped_interval`（上次 03:58Z，间隔 6h）；gov.cn `blocked`（JS 渲染） |
| `acceptance` | 8 passed / 0 failed（23 feeds、模型在线、报告、邮件配置、计划任务） |

`git status` 显示 README 等文件存在外部改动，按要求保留未还原；`git diff --check` 只报告 CRLF 提示，无空白错误。

## 二、公平对照的影子运行

| 项 | 基线组 | 候选组 |
|---|---|---|
| 来源 | 原有 7 个社区/论坛（feed id 3–9） | 新增 7 个官方/媒体（feed id 17–23） |
| 配置 | `baseline-community.csv` | `candidate-official.csv` |
| 数据库 | `baseline.sqlite3` | `candidate.sqlite3` |
| 报告 | `reports-baseline/` | `reports-candidate/` |
| 上限 | `OR_MAX_ARTICLES=30` | 同左 |
| 模式 | `--dry-run`（不发送邮件） | 同左 |
| 模型 | Qwen3-30B-A3B-Instruct-2507-Q4_K_M | 同左 |

**采样方式**：`FreshRSSClient.fetch_articles` 已按来源轮流取最新条目（`freshrss_client.py:52-63`），
因此两组都是**按来源分层**，不是按全局最新条数截断。实际分布见下表。

**时间窗口**：两组都在 2026-10-23 运行，但条目的发布时间范围不同——
基线 2026-09-03 至 10-23，候选 2026-10-05 至 10-23。基线包含更早的条目，因为论坛发帖量低于新闻/官方发布。
**这一点没有完全满足"相同时间窗口"的要求**，是本次设计的已知偏差。

## 三、结果总表

| 指标 | 基线（社区） | 候选（官方/新闻） |
|---|---|---|
| 样本量 | **30** | **30**（28 成功分析，2 失败） |
| 实际参与来源 | 7 | 6（BEA 0 条，见 §四） |
| 运行时长 | 28.0 分钟 | 19.8 分钟 |
| 分析成功率 | 30/30（100%） | 28/30（93.3%） |
| 通道 | B 25 · C 5 | A 28 |
| `priority` | 3 | 11 |
| `watch` | 9 | 11 |
| `filtered` | 18 | 6 |
| 因 `source_cap` 延后（`deferred`） | 0 | **14** |
| E2 / E1 / E0 | **15 / 11 / 4** | **0 / 22 / 6** |
| 引文定位率 | 101/105（96.2%） | 51/52（98.1%） |
| 情报主线 | 工程 17 · 市场机会 13 · 科技 13 | 宏观 12 · 国际新闻 10 · 企业资本 6 |
| 跨来源同事件键 | 0 | 0 |
| 重复事件（管道判定） | 0 | 0 |

## 四、来源健康度与两个具体缺陷

| 来源 | 条目 | 正文中位 | 空正文率 | 最新条目 | 本轮产出 |
|---|---|---|---|---|---|
| hn-ask | 160 | 561 | 0% | 10-23 | 5 |
| hn-show | 443 | 139 | 0% | 10-23 | 4 |
| simscale-forum | 34 | 1081 | 0% | 10-22 | 5 |
| precice-forum | 31 | 1476 | 0% | 10-20 | 4 |
| paraview-forum | 34 | 844 | 0% | 10-22 | 4 |
| salome-forum | 31 | 802 | 0% | 10-22 | 4 |
| openai-community | 377 | 1680 | 0% | 10-23 | 4 |
| us-bea | 10 | 472 | 0% | 10-06 | **0** |
| us-census | 10 | 106 | 0% | 10-15 | **1** |
| us-fed | 20 | 100 | 5% | 10-16 | 6 |
| uk-ons | 10 | 168 | 0% | 10-22 | 6 |
| nvidia-newsroom | 20 | 370 | 0% | 10-23 | 6 |
| bbc-news | 32 | 118 | 0% | 10-23 | 6 |
| nyt-home | 19 | 150 | 0% | 10-23 | 5 |

### 缺陷 1：BEA 的条目链接全部是 `http://`

BEA 的 RSS 条目 `<link>` 使用 `http://www.bea.gov/...`，而 `FreshRSSClient._articles()` 只接受
`https://` 开头的 URL（`freshrss_client.py:22`），所以 10 条全部被丢弃，本轮贡献 0。
实测 `http` 链接会 301 到 `https`（HTTP 200）。

这不是抓取失败，而是**登记了却永远不产出**。修复方式二选一，本轮均未执行：

1. 在客户端对**同一来源域名**的 `http` 链接做一次 301 校验后升级为 `https`（需要新增测试与超时预算）；
2. 在找到 BEA 的 https 端点前，把 `us-bea` 设为禁用，避免"已启用但 0 产出"的假象。

### 缺陷 2：Census 的 Feed 没有条目级链接

Census 的 RSS 每个 `<item>` 都是空 `<link/>` 与空 `<guid/>`，FreshRSS 回退成列表页地址
`https://www.census.gov/newsroom/press-releases.html`。13 条条目因此共享同一个 URL，管道按 URL 去重后只剩 1 条，
且报告里的"原文链接"指向列表页而不是具体发布页。

**结论：该端点不具备可追溯性，建议在找到按条目给出链接的端点前禁用 `us-census`。** 本轮未改配置，以免污染已完成的运行。

### 分析失败（2 条，6.7%）

两条都是模型返回的 `category` 不在 `schema.CATEGORIES` 枚举内，被 `parse_model_json` 拒绝：
Fed 的 enforcement action 与 NYT 的 Starshield 报道。管道行为正确（失败计入 `errors`，不进入报告），
但这说明长文本来源的 JSON 合规率低于社区短贴。**没有为提升成功率而放宽校验。**

### 配额效应

候选组 22 条达到 `watch`/`priority`，但 `source_cap` 只允许每个来源 1–2 条进入阅读区，
最终 **14 条 deferred**，实际展示 8 条。基线组未触发配额（12 条达到门槛，低于各源上限 3）。
配额没有改写任何条目的 `status` 或证据等级，这一点符合设计。

## 五、人工抽查（单人判断，方法可复现）

对两组各取每 3 条中的 1 条（共 20 条），只读标题、摘要与证据状态，按三档判断：

- **可行动**：有具体问题、可验证事实或可跟进的商业/政策信号；
- **弱**：真实信息但属例行发布、活动通知或厂商自述，缺少下一步；
- **噪声**：与商业判断无关。

| 组 | 可行动 | 弱 | 噪声 |
|---|---|---|---|
| 基线抽样 10 条 | 3 | 4 | 3 |
| 候选抽样 10 条 | 0 | 8 | 2 |

整组通读后的判断（非抽样，仅供对照）：

| 组 | 可行动 | 弱 | 噪声 | 说明 |
|---|---|---|---|---|
| 基线 30 条 | 14 | 9 | 7 | 可行动项几乎全部是 CAE/CFD 的具体故障与付费用户投诉 |
| 候选 28 条 | 5 | 19 | 4 | 可行动项集中在 ONS  earnings、EU 金融机构采用开源模型、黑色素瘤疫苗、NVIDIA DSX 电力瓶颈 |

**最重要的一条结论：候选组的主线覆盖明显变宽，但单条可行动率明显下降。**
原因不是"官方来源没用"，而是当前官方 Feed 只给标题+短摘要：
- 美联储的执法终止、银行申请批准、会议纪要，没有细节就无法判断影响；
- ONS 大量是犯罪/武器/时间使用统计的数据表发布，属例行公报；
- BBC/NYT 首页流里混有娱乐、体育、天气。

## 六、结论

**改善成立的部分**

1. A 通道从"无输入"变为 28 条，宏观、国际新闻、企业资本三条主线首次有真实条目。
2. 过滤率从 60% 降到 21%，`insufficient_evidence` 取代 `low_score` 成为唯一过滤原因——官方来源的摘要更可定位。
3. 引文定位率 98.1%，与基线持平；证据规则没有被绕过。

**没有解决的部分**

1. **E2 为 0**。七个新来源全部是摘要级，A 通道停在 E1。这是本轮最明确的能力缺口。
2. **官方 ≠ 有用**。候选组弱信息占 68%（19/28），大量是例行发布与娱乐新闻。
3. **两个来源实际不可用**（BEA 0 条、Census 1 条），说明"端点可解析"不等于"能产出可追溯条目"。
4. **配额把 14/22 条挡在阅读区外**，实际日报只展示 8 条；来源增加带来的是候选量，不是展示量。

**不能声称的部分**

- 样本仍只有每组 30 条，且时间窗口不完全一致；
- 人工判断是单人、无盲法，不能当作准确率；
- 没有多日重复运行，无法判断稳定性与长期结构占比。

## 七、验收

| 项 | 结果 | 说明 |
|---|---|---|
| 运行可复现 | **PASS** | 配置、DB、日志、报告、指标 JSON 全部留存 |
| 数据隔离 | **PASS** | 两个独立数据库，无并发进程，无历史复用 |
| 报告可生成 | **PASS** | 两份完整报告与归档 |
| 指标有原始记录 | **PASS** | `tools/e2e_metrics.py` 从 DB + items.json + FreshRSS 快照生成 |
| 证据规则未被绕过 | **PASS** | E2 仍为 0；失败条目被拒绝而非降级 |
| 样本量达到 30/组 | **PASS** | 30 / 30 |
| 相同时间窗口 | **FAIL** | 基线含 9 月初条目，候选从 10 月初开始 |
| 多日稳定性 | **NOT_RUN** | 单次运行 |
| 人工盲评 | **NOT_RUN** | 单人非盲抽查 |
| 条款与许可 | **BLOCKED** | 仍全部为 unknown |
| 连续失败率 | **NOT_RUN** | 单次运行无法计算 |

## 八、下一步（按优先级）

1. **修复 BEA 链接协议**：同域 `http → https` 的 301 校验与升级，并补测试；在修复前先禁用 BEA。
2. **禁用 Census**：端点无条目级链接，无法提供可追溯的原文地址。
3. **正文获取**：这是 E2 的唯一出路。先评估官方页面/Press release 的 HTML 抓取，而不是降 `promote_rank`。
4. **降低例行公报噪声**：政策/统计来源应优先接入"有决策含义"的栏目（如 ONS 的 earnings、GDP），而不是全量发布日历。
5. **多日运行**：连续 7 天、每天 30 条，统计来源成功率、主线占比、稳定 E2/E1 分布，再决定保留与淘汰。

## 九、复现与产物

```powershell
$env:OR_SOURCES_PATH='data/e2e-2026-10-23/baseline-community.csv'
$env:OR_DB_PATH='data/e2e-2026-10-23/baseline.sqlite3'
$env:OR_REPORT_DIR='data/e2e-2026-10-23/reports-baseline'
$env:OR_LOG_PATH='data/e2e-2026-10-23/baseline.log'
$env:OR_MAX_ARTICLES='30'
.\.venv\Scripts\python.exe -m opportunity_radar.cli --dry-run
```

候选组替换为 `candidate-official` / `candidate.sqlite3` / `reports-candidate`。
重跑前必须删除对应的 SQLite 文件，否则文章会被当作"已分析"跳过。

指标生成：

```powershell
.\.venv\Scripts\python.exe tools\e2e_metrics.py --label baseline-community ^
  --db data\e2e-2026-10-23\baseline.sqlite3 ^
  --items <archive>\2026-10-23-131715.items.json ^
  --manifest <archive>\2026-10-23-131715.manifest.json ^
  --config data\e2e-2026-10-23\baseline-community.csv ^
  --freshrss data\e2e-2026-10-23\freshrss-snapshot.sqlite3 ^
  --out data\e2e-2026-10-23\baseline-metrics.json
```

| 产物 | 路径 |
|---|---|
| 复验输出 | `data/e2e-2026-10-23/verify-current-version.txt` |
| 组配置 | `data/e2e-2026-10-23/{baseline-community,candidate-official}.csv` |
| 运行数据库 | `data/e2e-2026-10-23/{baseline,candidate}.sqlite3` |
| 报告与归档 | `data/e2e-2026-10-23/reports-{baseline,candidate}/` |
| 指标 | `data/e2e-2026-10-23/{baseline,candidate}-metrics.json` |
| FreshRSS 快照 | `data/e2e-2026-10-23/freshrss-snapshot.sqlite3` |
| 运行日志与完整标准输出 | `data/e2e-2026-10-23/{baseline,candidate}.log` 与 `*.out`（`.out` 含完整报告） |


## 十、归档冻结（2026-10-23T05:57Z）

**状态：FROZEN。** 本文结果与下列原始产物自此刻起不再修改；BEA/Census 修复、正文获取、第二轮对照均另开任务，
不并入这批数据。冻结后没有重跑、没有覆盖报告、没有改动数据库。

### 10.1 产物对应关系

| 组 | DB `run_id` | DB `report_hash` | manifest `report_hash` | items | analyses | failures |
|---|---|---|---|---|---|---|
| baseline | 1 | `190fb13f3236e972` | 同左 | 30 | 30 | 0 |
| candidate | 1 | `2464b469afa13070` | 同左 | 28 | 28 | 2 |

DB 的 `runs.report_path` 指向对应的归档 TXT；manifest 的 `article_count` 与 items 数一致；两组归档目录各自独立。

### 10.2 版本与指纹

| 项 | 值 |
|---|---|
| 代码版本 | git HEAD `16e97b1a369a2d0e933dcb94f42f298f6cf4a262`，工作区 dirty（29 项，含本批未提交改动与外部修改的 README） |
| 模型 | `Qwen3-30B-A3B-Instruct-2507-Q4_K_M` |
| 基线配置 | `baseline-community.csv` · SHA-256 `a688803ba5ff1c92b048a681955b14b74e2cad395cf7c0a5be3ee4fbdb73a807` |
| 候选配置 | `candidate-official.csv` · SHA-256 `947b549e71286feede8520db75d4d79600b31f380049d36d481372a102b13ea2` |
| 基线 DB | SHA-256 `4c06e87868f978763511e24276e2810004ac4dc86ab87c005ea44d214aa03f2b` |
| 候选 DB | SHA-256 `59fb3ac630f5292bfda31f8a7ec85e98c6c9e8e7ed47a9bfcf34a0ee374715aa` |
| FreshRSS 快照 | SHA-256 `0209c30a957350ddbd0f8982149b830eee5c1727f0f444d532a0c8ad6f63e14d` |
| 全部文件 | 24 个，共 7,215,173 字节；清单与逐文件哈希见 `data/e2e-2026-10-23/ARCHIVE_MANIFEST.json` |

### 10.3 安全扫描

对 24 个产物逐一搜索 `.env` 中的 5 个敏感值（收件人列表、SMTP 用户名、SMTP 授权码、FreshRSS API key、模型 API key）：
**0 命中**。归档只含分析结果、引文与链接，不含文章正文，也不含凭证。

### 10.4 指标定义

| 指标 | 定义 | 边界 |
|---|---|---|
| E0 / E1 / E2 | 由 `evidence.EVIDENCE_RANK` 映射：`title_only`、`unlocated_quotes`→E0；`rss_excerpt_only`→E1；`full_text_verified`、`primary_source_located`、`multi_source_coverage`→E2 | E2 不表示事实成立；多来源覆盖未核对独立性 |
| 成功分析 | 模型输出通过 `schema.parse_model_json` 且写入 `analyses` 的条目数 | 失败条目不计入，也不降级放行 |
| `deferred` | 达到 watch/priority 但超过来源 `source_cap`，本期不进入阅读区 | `status`、分数、证据不变 |
| 引文定位率 | `evidence` 中 `field != unlocated` 的引文 / 全部引文 | 只表示能在收到的文本里定位 |
| 跨来源同事件键 | 同一 `event_key`（标题规范化）出现在 ≥2 个来源 | 只是标题相似，不是转载识别 |
| 可行动 / 弱 / 噪声 | 人工单次判断：有具体问题或可跟进信号 / 例行发布或厂商自述 / 与商业判断无关 | 单人、非盲，不是准确率 |

### 10.5 归档边界

- 产物位于 `data/`，被 `.gitignore` 排除；本轮**未提交、未推送、未创建 PR、未合并**。
- 未修改本轮任何报告、数据库、指标文件；未恢复 README 的外部修改。
- 时间窗口 FAIL、许可 BLOCKED、多日稳定性与盲评 NOT_RUN 原样保留，不因主流程成功而改写。

### 10.6 缺失的产物与原因

| 产物 | 状态 | 原因 |
|---|---|---|
| 模型服务原始日志 | **未归档** | 当前 `llama-server.exe`（PID 25532，10:32 启动）的标准输出没有落盘；`reports/llama-server.err.log` 停留在 2026-10-22，不覆盖本轮。模型调用改由 `analyses` 表的模型标识、提示词版本/哈希与 `candidate.log` 中的失败行佐证。 |
| FreshRSS API 原始响应 | 未归档 | 客户端直连 Fever API，不落盘；以 FreshRSS 快照 + 运行数据库中的文章记录为准。 |
| 文章正文 | 未归档（设计如此） | 只保存分析、引文与链接，避免复制第三方全文。 |
| 代码快照 | 未打包 | 记录 git HEAD 与 dirty 状态；工作区未提交，因此没有可复现的 tag。 |

**归档完整性结论**：24 个产物哈希一致、无未登记文件；对应关系（run_id / report_hash / 条目数）已核对；
凭证扫描 0 命中；模型服务日志缺失已如实记录。除上述缺口外，本批可以冻结。
