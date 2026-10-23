# Opportunity Radar

本地优先的个人商业机会情报 MVP：FreshRSS 管理订阅，Python 程序读取 FreshRSS Fever API，调用本地 OpenAI-compatible `llama-server` 做结构化初筛，生成中文邮件日报。

**重要：这是可运行的起步代码，不代表已经在你的电脑上部署或端到端验证。** 首次运行前需要配置 FreshRSS API、模型 ID、SMTP，并逐项审查信息源许可。来源登记表默认全部禁用。

## 组件
- FreshRSS：RSS/Atom 订阅管理
- Python 标准库：去重、调用模型、校验、评分、SQLite、邮件
- 本地 llama.cpp `llama-server`：OpenAI-compatible API
- SQLite：运行、分析和发送记录
- Windows Task Scheduler：每日执行

## 快速开始（Windows PowerShell）
1. 安装 Docker Desktop（WSL2 backend）与 Python 3.11+。然后在本目录创建虚拟环境：`py -3 -m venv .venv`。
2. `docker compose up -d`，打开 `http://127.0.0.1:8088` 完成 FreshRSS 初始化。
3. 在你当前 FreshRSS 版本中启用并验证 Fever API，创建 API 密钥。若 API 不可用，先查官方文档，不要绕过或猜测认证方式。
4. `config/sources.csv` 中的来源均为候选项且默认禁用。逐个核实来源所有者、当前 RSS/API 方式、使用条款、内容保存/摘要/归属要求后，再填写 `permission_status=approved`、`reviewed_at`、`last_verified_at`、本机 FreshRSS 的 `freshrss_feed_id`，并设置 `enabled=true`。运行 `py -3 -m opportunity_radar.source_audit` 检查登记完整性；可选 `--check-urls` 检查 HTTPS 可达性。可达性不代表获得法律许可。`robots.txt` 不是完整的法律许可。
5. 若尚无 `.env`：`Copy-Item .env.example .env`，填写 API、模型和 SMTP 配置。
6. 启动本地模型：`.\deploy\windows\start-model.ps1`（默认 `D:\AI\models\Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf`，SYCL0，16K 上下文，48 层 CPU MoE，端口 8080）。脚本从 `.env` 读取 `OR_LLM_API_KEY`，后台启动后轮询 `/health` 并报告 PID 或失败原因；日志写入 `reports/llama-server.log` 与 `reports/llama-server.err.log`。它使用 GGUF 自带 Jinja 模板、开启 API Key 并把 CORS 限制在本机来源。加 `-Foreground` 可保留前台运行。若改用 `D:\AI\start_server.bat`，选择模型 6 与档位 3（16K），参数与脚本一致；该 bat 不设置 API Key，项目客户端发送的 Bearer 头会被忽略。再用 `Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8080/v1/models"` 核对模型 ID 与 `OR_LLM_MODEL`。
7. 测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`；然后 `.\deploy\windows\test-digest.ps1`。
8. 配好 SMTP 后真实运行：`.\deploy\windows\run-digest.ps1`。
9. 成功收到邮件并检查内容后，再设置任务计划：`.\deploy\windows\install-task.ps1`。

## 报告与评分
- 每次运行生成 `reports/latest-digest.txt` 与 `reports/latest-digest.html`，并按日期目录归档到 `reports/archive/YYYY/MM/DD/`：每次运行保存 `HHMMSS.txt`、`.html`、`.items.json`（结构化分析快照）和 `.manifest.json`（运行 ID、报告哈希、统计与文件清单）。`--render-only` 只更新 latest，不新增归档。详见 `docs/LOCAL_DAILY_ARCHIVE.md`。
- 报告按三条编辑通道组织：执行摘要（3 条，写明发生了什么 / 为什么重要 / 可信度）→ 一、商业、科技与经济情报（A）→ 二、值得验证的商业机会（B）→ 三、技术观察与工程信号（C）→ 四、数据概览 → 五、附录（来源、过滤原因、数据质量、来源审计、评分规则、免责声明）。每条卡片给出事实（仅列可在原文定位的引文）、未核实引文（单独标注，不作为事实）、通道内评估、关键未知和下一步观察。
- 只想调整报告版式时用 `--render-only`，直接基于数据库里已保存的分析重新生成报告，不重新调用模型、不重新评分：
  `.\.venv\Scripts\python.exe -m opportunity_radar.cli --render-only`
- 分数是确定性规则，不由模型直接决定总分。每条内容先按来源声明的 `editorial_lanes` 与内容类型路由到 A/B/C 之一，再用该通道自己的 0–5 分组件加权：
  - A（情报）：重要性、来源可靠性、证据完整度、新颖性、相关性、时效性
  - B（机会）：痛点严重度、买方明确度、买方付费证据、独立佐证、验证可行性、现有方案缺口、新颖性
  - C（技术）：技术成熟度、可复现性、影响范围、来源可靠性、新颖性
  权重、阈值与晋升门槛统一读自 `config/scoring.toml`。**不同通道的分数不可直接比较。**
- 证据状态是显式枚举，不再混用一个字符串：`title_only` / `unlocated_quotes`（E0）、`rss_excerpt_only`（E1）、`full_text_verified` / `primary_source_located` / `multi_source_coverage`（E2）。E0 一律不进入简报（过滤原因 `insufficient_evidence`）。
  - `primary_source_located` 只表示引文可在一手来源自己的发布中定位，即对方确实这样说过，不代表该说法成立。
  - `multi_source_coverage` 只表示同一事件有多个来源的已分析条目，**没有**核对这些来源是否独立、是否转载同一稿源。主张级交叉验证尚未实现。
- 每个通道有独立的 `promote_rank`（进入"优先验证"所需的最低证据等级）：A 为 E1，B 和 C 为 E2。A 通道报告的是公司与行业变化，定位到可靠来源的摘要即可阅读；B 和 C 对买方与行为下结论，需要正文。
- “我们手里到底有多少原文”由 `content_basis` 决定：`title_only`、`excerpt`、`full_text`。**只有人工复核后声明 `content_access_level=full_text` 的来源才能进入 `full_text`**；`auto` 与 `excerpt` 一律按摘要处理。
- `content_basis_estimate` 是程序的完整性估计（长度 ≥ 400 且无 “Read more”/省略号等截断标记即估计为全文），它**只作为复核提示出现在报告里，不参与评分**。理由是 400 字可能是完整短文，也可能是长文的前半段：没有截断标记不等于没有截断。
- **这正是此前“优先验证恒为 0”的根因：旧实现没有任何路径能产出 E2。** 现在 E2 可达，但需要逐个复核来源并显式声明，而不是由长度自动授予。
- 简报分别统计获取、新增、进入分析、成功、失败、已有结果跳过和过滤原因；没有新分析任务时不会输出"没有商业机会"的结论。
- 条目状态：`priority`、`watch`、`filtered`，阈值为各通道自己的 `priority` / `watch`。过滤原因包括招聘、证据不足、无商业信号和低分。
- 判断与分发分开：`status` 是证据与评分的结论；`distribution`（`included` / `deferred`）只表示本期是否进入阅读区。来源单期配额只会让条目 `deferred`，**不会**改写成 `filtered`——被延后的条目保留原等级、分数和证据，列在附录，报告也会说明“不代表价值较低”。
- 每条分析附带确定性信号元数据：`signal_type`、`buyer_type`、`payment_evidence`、`buyer_payment_evidence`、`seller_monetization_signal`、`adoption_signal`、`pain_evidence`、`market_validation`、`delivery_fit`、`source_quality`。**卖方定价或商业支持永远不算买方付费证据**；只有正文明确写出预算、采购、已付费或付费意愿时，`buyer_payment_evidence` 才会命中。
- 抓取按来源轮流取最新条目，避免单个高频源占满每日配额。
- 抓取按来源轮流取最新条目，避免单个高频源占满每日配额。

## 信息来源
`config/sources.csv` 只登记已审查并启用 `freshrss_feed_id` 的来源。仓库模板中的来源全部默认禁用，且不携带任何本机 FreshRSS feed ID。Hacker News Ask/Show、SimScale、preCICE、ParaView、SALOME 论坛和 OpenAI 开发者社区只是候选来源；来源所有权、条款、保存/摘要/归属许可及实际 Feed ID 需由使用者在本地逐一核验。来源 URL 可访问不等于获准保存、分析或再发布。

新增的第一批企业与经济来源（NVIDIA、Microsoft、AMD、Google Research、AWS、IMF、OECD、World Bank、SIA、MIT Technology Review、IEEE Spectrum 等）同样默认 `review_required` 且禁用。

逐来源的实测结论、内容形态与建议动作见 `docs/SOURCE_REVIEW.md`。该文件区分"已实测事实 / 基于证据的判断 / 未核实的假设"；`feed_url` 留空表示**没有找到可验证的 Feed 端点**，不是遗漏。
其中部分行的 `feed_url` 指向新闻页或出版页而非已确认的 RSS 端点，`review_notes` 已注明；启用前必须用 `source_audit --check-urls` 实测替换。

## 依赖与复现
- 运行期只使用 Python 标准库（`sqlite3`、`urllib`、`tomllib`、`html`、`json`），没有第三方依赖；`pyproject.toml` 声明了 Python 3.11+ 和空依赖。
- 当前小规模日报使用 SQL/标准库聚合并生成内联 SVG，不引入 pandas / matplotlib / 前端图表库。若后续需要历史回测、复杂分组或统计分析，再评估 pandas；若需要复杂静态图再评估 matplotlib。任何图表都必须注明时间范围、分母与数据口径。
- 新增依赖前先确认标准库无法满足需求，并记录用途、版本和替代方案；环境用 `.venv` 隔离。

## 证据与审计
- 来源登记表 `config/sources.csv` 包含 `source_type`、`provenance_class`、`canonical_domain`、`terms_url`、`last_verified_at`、`reviewed_at`、可选的 Feed 提供方/提供方条款字段，以及编辑治理字段：`editorial_lanes`（A/B/C，可多选）、`topic_tags`、`source_authority`、`content_access_level`（`auto` / `full_text` / `excerpt` / `title_only`）、`source_cap`（单期最大入选数，0 为不限）。报告里的来源质量优先采用登记表声明，URL 规则只作为回退。
- 审计工具会校验上述字段的取值，并要求启用来源至少声明一条 `editorial_lanes`：**能合法接入不等于该进入简报**。
- 文章记录区分发布时间与抓取时间，并保存 `content_source`、`retrieval_status` 和内容哈希；同一 URL 内容变化会追加到 `article_versions`、更新当前文章元数据并触发重新分析。旧分析写入 `analysis_history`；内容变化后旧人工标签失效，避免继续套用旧结论。
- 每条引文在分析时分配稳定 ID（`e1`、`e2`…），并记录定位信息（`title` / `summary` / `unlocated`）与字符位置；报告以 `[e1]` 前缀展示，附录汇总可定位与无法定位的引文数量。定位前会去除 HTML 标签、反转义实体并统一引号与空白。
- 来源身份与内容证明力分开：论坛用户帖记为一手用户表达，即使内容只是功能请求；GitHub Releases 记为项目记录；官方发布才记为官方宣传。
- 每次分析保存模型标识、提示词版本、提示词内容哈希和规则版本。`prompts/analyst.md` 与 `prompts/shared/` 中的共享约束会共同进入运行时 Prompt；修改提示词时递增版本并核对报告中的 Prompt hash。
- 人工复核同时写入当前状态表 `reviews` 和追加式历史表 `review_history`，保留修改前的标签、理由和时间。
- 报告先写临时文件、通过结构校验后再原子替换；校验失败时保留上一份有效报告。

## 来源登记审计

```powershell
py -3 -m opportunity_radar.source_audit
py -3 -m opportunity_radar.source_audit --check-urls
```

该工具检查启用来源的登记完整性、HTTPS 地址、重复 Feed ID、来源声明和复核日期；`--check-urls` 仅检查网络可达性。它不能证明内容准确、来源身份绝对真实、获得法律许可或允许长期保存。

## 人工复核
机器只负责排序，是否值得投入由人工判断。复核结果写入数据库的 `reviews` 表，可用于统计机器的命中率和误报率。

```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.review list --limit 20
.\.venv\Scripts\python.exe -m opportunity_radar.review label <key前缀> real_pain --note "原文证据充分"
.\.venv\Scripts\python.exe -m opportunity_radar.review stats
```

标签：`real_pain`（真实问题）、`commercial_intent`（采购/预算/付费意愿）、`competitive_signal`（竞品发布）、`technical_reference`（技术参考）、`weak_evidence`（证据不足）、`irrelevant`（与方向无关）。

`stats` 会给出三个关键指标：机器候选被人工判为噪声的比例（误报率）、人工认定需求被机器排进候选区的比例（命中率），以及机器状态与人工标签的交叉表。

## 本地管理后台
- 启动：`.\deploy\windows\start-admin.ps1`，或 `.\.venv\Scripts\python.exe -m opportunity_radar.admin_server`；打开 http://127.0.0.1:8090。
- 功能：状态总览、来源编辑（可从 FreshRSS 读取真实 Feed ID）、收件人管理与测试邮件、立即运行日报、注册每日任务、查看日志和最新 HTML 报告。
- 来源编辑作用于 `OR_SOURCES_PATH` 指向的本地注册表（默认 `config/sources.local.csv`）；仓库中的 `config/sources.csv` 是 31 个候选源模板（含企业官方、投资者关系、产业协会、宏观经济与专业媒体），默认全部禁用。
- 收件人保存到 `config/recipients.json`（已被 `.gitignore` 排除），文件存在时优先于 `.env` 的 `OR_EMAIL_TO`。SMTP 账号和授权码始终只从 `.env` 读取，页面不会显示。
- 后台没有多用户认证，只监听 `127.0.0.1`，不要映射到局域网或公网。

## 端到端验收
```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.acceptance
```
逐项检查配置、来源审计、FreshRSS、本地模型、SQLite、报告、邮件配置和 Windows 计划任务；`--send-mail` 会额外发一封测试信，`--json` 输出机器可读结果。关键项失败时返回非零。

## 管理 API 契约
- 成功响应：`{"ok": true, "request_id": "...", ...payload}`；失败响应：`{"ok": false, "error": {"code": "...", "message": "...", "details": []}, "request_id": "..."}`。
- 错误码：`VALIDATION_ERROR`、`FORBIDDEN`、`SOURCE_VALIDATION_FAILED`、`FRESHRSS_UNAVAILABLE`、`SMTP_FAILED`、`SMTP_AUTH_FAILED`、`RUN_ALREADY_ACTIVE`、`SCHEDULE_FAILED`、`REPORT_MISSING`、`NOT_FOUND`、`INTERNAL_ERROR`。
- GET 和 POST 都校验 Host/Origin，只接受本机来源；来源与收件人写入有字段级校验和写入锁。
- 运行状态以 SQLite 的 `runs` 表为准，记录 `run_id`、`stage`、`status`、`exit_code`、报告路径和哈希；状态包括 `success`、`partial_failed`、`failed`、`analysis_failed`、`no_new_content`、`dry_run`。
- 邮件按收件人逐条记录在 `deliveries` 表；失败的地址可以在后台单独重试，不会重复发给已成功的地址。
- 前端拆分为 `admin/index.html`、`admin/assets/app.css`、`admin/assets/app.js`，包含 loading / empty / error 状态、键盘焦点管理与表单错误定位。

## 邮件与运行可靠性
- 先单独验证邮件配置，不生成报告：`.\.venv\Scripts\python.exe -m opportunity_radar.mail_test`。它只发送一封测试邮件；SMTP 成功只代表发送端完成提交，不代表已送达或被阅读。
- 163 邮箱使用 `smtp.163.com:465` + 授权码（不是登录密码），配置 `OR_SMTP_SECURITY=ssl`、`OR_SMTP_STARTTLS=false`。其他服务商按文档选择 `ssl` / `starttls` / `none`；旧的 `OR_SMTP_TLS` 仍作为兼容别名读取。
- `OR_EMAIL_TO` 支持英文逗号或分号分隔的多个地址，程序会**逐人单独发送**，收件人之间看不到彼此地址。
- 投递幂等：同一份报告（标题与报告哈希相同）成功发送后不会重复发送，记录为 `skipped_duplicate`。
- 无新内容时不发信：`analyzed=0` 且 `updated=0` 时只保存报告，记录为 `skipped_no_new_content`；设置 `OR_EMAIL_ON_EMPTY=true` 可改为始终发送。
- 全部分析失败时不发送正常简报，运行记为 `analysis_failed`；连续失败达到 `OR_ALERT_AFTER_FAILURES`（默认 3）时发送告警邮件。
- 本机来源登记放在 `config/sources.local.csv`（已被 `.gitignore` 排除），通过 `.env` 中的 `OR_SOURCES_PATH` 指向它；仓库内的 `sources.csv` 保持禁用且不含本机 Feed ID。
- `mail.txt`、`.env`、数据库、报告和日志都不提交；邮箱凭据只保留在 `.env`。

## 约束
- 未确认许可的来源保持禁用；不绕过登录、验证码、付费墙或技术限制。
- 模型只做初筛，不证明营收、市场规模或法律结论。
- 邮件包含简短摘要与原始链接，不复制完整文章。
- 模型/SMTP/API 故障应记录并可诊断。
- `.env`、数据库和运行日志不要提交到公开 GitHub。

## API 说明
客户端使用 FreshRSS Fever API。Fever API 的可用性和配置可能因 FreshRSS 版本而异；需在实际实例中验证。每个获准来源必须在 `config/sources.csv` 中填写对应的 `freshrss_feed_id`；程序只处理映射到已批准来源的文章。请在 FreshRSS API 返回结果中核对 feed ID，不要猜测。
