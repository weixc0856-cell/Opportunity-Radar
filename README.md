# Opportunity Radar

本地优先的商业机会情报 MVP：FreshRSS 管理订阅，Python 程序读取 FreshRSS Fever API，调用本地 OpenAI-compatible `llama-server` 做结构化初筛，生成中文邮件日报。

**这是可运行的起步代码，不代表已经部署或端到端验证。** 首次运行前需要配置 FreshRSS API、模型 ID、SMTP，并逐项审查信息源许可。来源登记表默认全部禁用。

## 组件
- FreshRSS：RSS/Atom 订阅管理
- Python 标准库：去重、调用模型、校验、评分、SQLite、邮件
- 本地 llama.cpp `llama-server`：OpenAI-compatible API
- SQLite：运行、分析和发送记录
- Windows Task Scheduler：每日执行

## 快速开始（Windows PowerShell）
1. 安装 Docker Desktop（WSL2 backend）与 Python 3.11+，创建虚拟环境：`py -3 -m venv .venv`。
2. `docker compose up -d`，打开 `http://127.0.0.1:8088` 完成 FreshRSS 初始化。
3. 在当前 FreshRSS 版本中启用并验证 Fever API，创建 API 密钥。若 API 不可用，先查官方文档，不要绕过或猜测认证方式。
4. `config/sources.csv` 中的来源均为候选项且默认禁用。逐个核实来源所有者、RSS/API 方式、使用条款、内容保存与摘要要求后，填写 `permission_status=approved`、`reviewed_at`、`last_verified_at`、对应的 `freshrss_feed_id`，并设置 `enabled=true`。运行 `py -3 -m opportunity_radar.source_audit` 检查登记完整性；`--check-urls` 只检查 HTTPS 可达性，不代表获得许可。
5. 若尚无 `.env`：`Copy-Item .env.example .env`，填写 API、模型和 SMTP 配置。实例相关的 Feed ID 与复核日期放在 `config/sources.local.csv`，通过 `OR_SOURCES_PATH` 指向。
6. 启动本地模型：`.\deploy\windows\start-model.ps1`。脚本参数包括 `-ModelPath`、`-ServerExe`、`-Device`、`-ContextSize`，默认值可在脚本顶部修改；它从 `.env` 读取 `OR_LLM_API_KEY`，后台启动后轮询 `/health`，日志写入 `reports/llama-server.log` 与 `reports/llama-server.err.log`。加 `-Foreground` 可保留前台运行。设置 `OR_MODEL_AUTOSTART=1` 后，CLI 在模型不可达时会自动调用同一脚本并等待就绪，失败以退出码 3 结束。
7. 测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`；然后 `.\deploy\windows\test-digest.ps1`。
8. 配好 SMTP 后真实运行：`.\deploy\windows\run-digest.ps1`。
9. 成功收到并检查邮件后，再设置任务计划：`.\deploy\windows\install-task.ps1`。

## 报告与评分
- 每次运行生成 `reports/latest-digest.txt` 与 `latest-digest.html`，并按日期归档到 `reports/archive/YYYY/MM/DD/`：`HHMMSS.txt`、`.html`、`.items.json`（分析快照）和 `.manifest.json`（运行 ID、报告哈希、统计与文件清单）。`--render-only` 只更新 latest，不新增归档。
- 报告按三条编辑通道组织：执行摘要 → 一、商业、科技与经济情报（A）→ 二、值得验证的商业机会（B）→ 三、技术观察与工程信号（C）→ 四、数据概览 → 五、附录。
- 分数是确定性规则：每条内容先按来源声明的 `editorial_lanes` 与内容类型路由到 A/B/C，再用该通道自己的 0–5 分组件加权。权重、阈值与晋升门槛统一读自 `config/scoring.toml`。**不同通道的分数不可直接比较。**
- 证据状态是显式枚举：`title_only` / `unlocated_quotes`（E0）、`rss_excerpt_only`（E1）、`full_text_verified` / `primary_source_located` / `multi_source_coverage`（E2）。E0 不进入简报。
  - `primary_source_located` 只表示引文可在一手来源自己的发布中定位，不代表该说法成立。
  - `multi_source_coverage` 只表示同一事件有多个来源的已分析条目，**没有**核对这些来源是否独立或转载同一稿源。
- 每个通道有独立的 `promote_rank`：A 为 E1，B 和 C 为 E2。
- `content_basis` 由 `content_access_level` 决定：**只有人工复核后声明 `full_text` 的来源才能进入 `full_text`**；`auto` 与 `excerpt` 一律按摘要处理。长度估计只作为复核提示，不参与评分。
- 判断与分发分开：`status` 是证据与评分的结论；`distribution`（`included` / `deferred`）只表示本期是否进入阅读区。来源单期配额只会让条目 `deferred`，**不会**改写成 `filtered`。
- 每条分析附带确定性信号元数据：`signal_type`、`buyer_type`、`payment_evidence`、`buyer_payment_evidence`、`seller_monetization_signal`、`adoption_signal`、`pain_evidence`、`market_validation`、`delivery_fit`、`source_quality`。**卖方定价或商业支持不算买方付费证据。**
- 抓取按来源轮流取最新条目，避免单个高频源占满每日配额。需要固定时间窗口时使用 `OR_SAMPLE_SINCE` / `OR_SAMPLE_UNTIL`（UTC，since 含、until 不含）；报告会打印取数池、窗口内条数与最终取样数。

## 信息来源与治理
- `config/sources.csv` 是仓库模板：来源全部默认禁用，且不携带任何实例专用的 FreshRSS feed ID，目前包含 47 行候选。
- 实际使用的登记放在 `config/sources.local.csv`（`.gitignore` 排除），由 `.env` 的 `OR_SOURCES_PATH` 指向。仓库模板与本地登记结构相同。
- 来源 URL 可访问不等于获准保存、分析或再发布；未确认许可的来源保持禁用。`robots.txt` 不是完整的法律许可。
- 治理字段：
  - `editorial_lanes`（A/B/C）：来源可进入哪些编辑通道，启用前必须声明。
  - `intelligence_lines`：来源服务的情报主线（政策、宏观、企业、产业、新闻、科技、机会、工程、维护），与通道正交，不参与评分。
  - `content_access_level`（`auto` / `full_text` / `excerpt` / `title_only`）：Feed 实际提供多少正文。
  - `source_cap`：单期最大入选条数，0 为不限；超额条目只 deferred。
  - `full_text_fetch`（`none` / `article_page`）：是否允许抓取条目页面获取正文。默认关闭；开启不改变证据等级，仍需复核后声明 `full_text`。

## 结构化数据与页面监测
- `config/datasets.csv` + `opportunity_radar/datasets.py`：结构化时间序列的独立登记，不与文章混用。`python -m opportunity_radar.datasets --check` 探测已批准数据集的最新期间；许可未核对的数据集保持 `blocked`。
- `config/page_watch.csv` + `opportunity_radar/page_monitor.py`：对没有 Feed 的官方页面做低频变更监测。只保存链接与标题，先读 robots.txt，遵守最小间隔，401/403/429 不重试，不执行 JavaScript。

## 依赖与复现
- 运行期只使用 Python 标准库（`sqlite3`、`urllib`、`tomllib`、`html`、`json`），没有第三方依赖；`pyproject.toml` 声明 Python 3.11+ 与空依赖。
- 日报聚合与图表使用 SQL/标准库和内联 SVG。需要历史回测或复杂统计时再评估 pandas；需要复杂静态图时再评估 matplotlib。任何图表都必须注明时间范围、分母与数据口径。
- 新增依赖前先确认标准库无法满足需求，并记录用途、版本和替代方案；环境用 `.venv` 隔离。

## 证据与审计
- 文章记录区分发布时间与抓取时间，保存 `content_source`、`retrieval_status` 和内容哈希；同一 URL 内容变化会追加到 `article_versions`、更新当前元数据并触发重新分析。旧分析写入 `analysis_history`；内容变化后旧人工标签失效。
- 每条引文在分析时分配稳定 ID（`e1`、`e2`…），记录定位信息（`title` / `summary` / `unlocated`）与字符位置；报告以 `[e1]` 前缀展示，附录汇总可定位与无法定位的数量。
- 来源身份与内容证明力分开：论坛用户帖记为一手用户表达；GitHub Releases 记为项目记录；官方发布才记为官方宣传。
- 每次分析保存模型标识、提示词版本、提示词内容哈希和规则版本。修改提示词时递增版本并核对报告中的 Prompt hash。
- 人工复核同时写入 `reviews` 与追加式 `review_history`，保留修改前的标签、理由和时间。
- 报告先写临时文件、通过结构校验后原子替换；校验失败时保留上一份有效报告。

## 来源登记审计
```powershell
py -3 -m opportunity_radar.source_audit
py -3 -m opportunity_radar.source_audit --check-urls
```
该工具检查启用来源的登记完整性、HTTPS 地址、重复 Feed ID、来源声明、复核日期与治理字段取值；`--check-urls` 仅检查网络可达性，不能证明内容准确、来源身份真实、获得法律许可或允许长期保存。

## 人工复核
机器只负责排序，是否值得投入由人工判断。复核结果写入 `reviews` 表，可用于统计命中率与误报率。

```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.review list --limit 20
.\.venv\Scripts\python.exe -m opportunity_radar.review label <key前缀> real_pain --note "原文证据充分"
.\.venv\Scripts\python.exe -m opportunity_radar.review stats
```

标签：`real_pain`、`commercial_intent`、`competitive_signal`、`technical_reference`、`weak_evidence`、`irrelevant`。

## 本地管理后台
- 启动：`.\deploy\windows\start-admin.ps1`，或 `.\.venv\Scripts\python.exe -m opportunity_radar.admin_server`；打开 `http://127.0.0.1:8090`。
- 功能：状态总览、来源编辑（可从 FreshRSS 读取真实 Feed ID）、收件人管理与测试邮件、立即运行日报、注册每日任务、查看日志和最新 HTML 报告。
- 来源编辑作用于 `OR_SOURCES_PATH` 指向的登记表；后台没有多用户认证，只监听 `127.0.0.1`，不要映射到局域网或公网。
- 收件人保存到 `config/recipients.json`（`.gitignore` 排除），存在时优先于 `OR_EMAIL_TO`。SMTP 账号和授权码只从 `.env` 读取，页面不会显示。

## 端到端验收
```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.acceptance
```
逐项检查配置、来源审计、FreshRSS、本地模型、SQLite、报告、邮件配置和 Windows 计划任务；`--send-mail` 额外发送测试信，`--json` 输出机器可读结果。关键项失败时返回非零。

## 管理 API 契约
- 成功：`{"ok": true, "request_id": "...", ...}`；失败：`{"ok": false, "error": {"code": "...", "message": "...", "details": []}, "request_id": "..."}`。
- 错误码：`VALIDATION_ERROR`、`FORBIDDEN`、`SOURCE_VALIDATION_FAILED`、`FRESHRSS_UNAVAILABLE`、`SMTP_FAILED`、`SMTP_AUTH_FAILED`、`RUN_ALREADY_ACTIVE`、`SCHEDULE_FAILED`、`REPORT_MISSING`、`NOT_FOUND`、`INTERNAL_ERROR`。
- GET 与 POST 都校验 Host/Origin，只接受来自回环地址的请求；来源与收件人写入有字段级校验和写入锁。
- 运行状态以 `runs` 表为准，记录 `run_id`、`stage`、`status`、`exit_code`、报告路径和哈希。
- 邮件按收件人逐条记录在 `deliveries`；失败地址可单独重试，不会重复发给已成功的地址。

## 邮件与运行可靠性
- 先单独验证邮件配置：`.\.venv\Scripts\python.exe -m opportunity_radar.mail_test`。SMTP 成功只代表发送端完成提交，不代表已送达或被阅读。
- 端口 465 通常使用隐式 TLS（`OR_SMTP_SECURITY=ssl`），587 通常使用 `starttls`；需要的是邮箱服务商提供的授权码，不是登录密码。
- `OR_EMAIL_TO` 支持英文逗号或分号分隔多个地址；程序逐人单独发送，收件人之间看不到彼此地址。
- 投递幂等：同一份报告（标题与报告哈希相同）成功发送后不会重复发送，记录为 `skipped_duplicate`。
- 无新内容时不发信：`analyzed=0` 且 `updated=0` 时只保存报告；`OR_EMAIL_ON_EMPTY=true` 可改为始终发送。
- 全部分析失败时不发送正常简报，运行记为 `analysis_failed`；连续失败达到 `OR_ALERT_AFTER_FAILURES` 时发送告警邮件。

## 约束
- 未确认许可的来源保持禁用；不绕过登录、验证码、付费墙或技术限制。
- 模型只做初筛，不证明营收、市场规模或法律结论。
- 邮件包含简短摘要与原始链接，不复制完整文章。
- 模型/SMTP/API 故障应记录并可诊断。
- `.env`、数据库、报告和运行日志不提交到公开仓库。

## API 说明
客户端使用 FreshRSS Fever API。Fever API 的可用性和配置可能因 FreshRSS 版本而异；需在实际实例中验证。每个获准来源必须配置准确的 `freshrss_feed_id`；程序只处理映射到已批准来源的文章。

## 文档索引
- `docs/EVIDENCE_AND_LANES.md`：通道、证据等级与分发语义
- `docs/SOURCE_POLICY.md`：来源准入、治理字段、正文获取
- `docs/SOURCE_REVIEW.md`：来源实测与缺陷修复记录
- `docs/SOURCE_CONSOLIDATION_PLAN.md`：信源整合方案与候选来源实测
- `docs/DATASETS.md`：结构化数据登记
- `docs/PAGE_MONITORING.md`：无 Feed 页面的变更监测
- `docs/FULL_TEXT_FETCH.md`：正文获取与 `full_text` 复核流程
- `docs/SHADOW_RUN_2026-10-23.md`、`docs/E2E_SOURCE_QUALITY_2026-10-23.md`、`docs/E2E_ROUND2_RESULTS_2026-10-23.md`：影子运行与两轮来源质量实验
- `docs/SHADOW_ROUND2_DESIGN.md`：预注册实验设计
- `docs/OPERATIONS.md`、`docs/LOCAL_DAILY_ARCHIVE.md`：运行与归档
