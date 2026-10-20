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
4. 只在 `config/sources.csv` 登记并启用已审查许可的来源；同时确保 每个已批准来源都必须填写其 `freshrss_feed_id`，程序只处理映射到已批准来源的 feed。`robots.txt` 不是完整的法律许可。
5. 若尚无 `.env`：`Copy-Item .env.example .env`，填写 API、模型和 SMTP 配置。
6. 启动本地模型：`.\.deploy\windows\start-model.ps1`（默认 `D:\AI\models\Qwen3.5-4B_Q4_k_m.gguf`，端口 8080）。脚本从 `.env` 读取 `OR_LLM_API_KEY`，后台启动后轮询 `/health` 并报告 PID 或失败原因；日志写入 `reports/llama-server.log` 与 `reports/llama-server.err.log`。它沿用 GGUF 自带模板并关闭 thinking，同时开启 API Key、把 CORS 限制在本机来源。加 `-Foreground` 可保留前台运行。注意：共用的 `D:\AI\start_server.bat` 对 Qwen 强制 `--chat-template chatml`，会让 Qwen3.5 把整个 token 预算耗在 `<think>` 里而不返回 JSON；它也不设置 API Key。再用 `Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8080/v1/models" -Headers @{Authorization="Bearer <key>"}` 核对实际模型 ID 并写入 `OR_LLM_MODEL`。
7. 测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`；然后 `.\.deploy\windows\test-digest.ps1`。
8. 配好 SMTP 后真实运行：`.\.deploy\windows\run-digest.ps1`。
9. 成功收到邮件并检查内容后，再设置任务计划：`.\.deploy\windows\install-task.ps1`。

## 报告与评分
- 每次运行生成 `reports/latest-digest.txt` 与 `reports/latest-digest.html`，并按日期归档到 `reports/archive/YYYY-MM-DD.*`。
- 报告采用决策简报结构：执行摘要（先给结论）→ 关键发现（事实 / 初判 / 商业评估 / 关键未知 / 建议验证）→ 商业评估表 → 战略含义 → 建议行动 → 附录（来源、过滤原因、数据质量、评分规则、免责声明）。
- 只想调整报告版式时用 `--render-only`，直接基于数据库里已保存的分析重新生成报告，不重新调用模型、不重新评分：
  `.\.venv\Scripts\python.exe -m opportunity_radar.cli --render-only`
- 分数是确定性规则，不由模型直接决定总分：需求明确度、付费证据、可执行性、个人可行性、新颖性各 0–5 分，权重与阈值统一读自 `config/scoring.toml`。
- 证据等级分为 `none` / `title` / `untraceable` / `summary` / `full_text`。仅标题级或无法在输入中定位的证据会把分数封顶在 `watch` 阈值以下，不能进入"优先验证"。
- 简报分别统计获取、新增、进入分析、成功、失败、已有结果跳过和过滤原因；没有新分析任务时不会输出"没有商业机会"的结论。
- 条目状态：`priority`（≥75）、`watch`（55–74）、`filtered`（低于阈值或未通过硬性过滤），过滤原因包括招聘、无商业信号、内容不足和低分。
- 每条分析附带确定性信号元数据：`signal_type`（付费需求/用户痛点/部署障碍/产品缺口/技术趋势）、`buyer_type`、`payment_evidence`、`delivery_fit`、`source_quality`。付费证据只从文章正文读取，不采信模型自己写的商业信号。
- 抓取按来源轮流取最新条目，避免单个高频源占满每日配额。

## 信息来源
`config/sources.csv` 只登记已审查并启用 `freshrss_feed_id` 的来源。当前默认启用：Hacker News Ask/Show、SimScale、preCICE、ParaView、SALOME 论坛和 OpenAI 开发者社区；HN 首页因条目通常只有标题而默认禁用。论坛类来源的 RSS 自带正文，是当前唯一能让证据等级达到 `summary` 的输入。

## 依赖与复现
- 运行期只使用 Python 标准库（`sqlite3`、`urllib`、`tomllib`、`html`、`json`），没有第三方依赖；`pyproject.toml` 声明了 Python 3.11+ 和空依赖。
- 图表用聚合后的真实数据生成内联 SVG，不引入 pandas / matplotlib / 前端图表库。
- 新增依赖前先确认标准库无法满足需求，并记录用途、版本和替代方案；环境用 `.venv` 隔离。

## 证据与审计
- 来源登记表 `config/sources.csv` 现在包含 `source_type`、`provenance_class`、`canonical_domain`、`terms_url`、`last_verified_at`。报告里的来源质量优先采用登记表声明，URL 规则只作为回退。
- 文章记录区分发布时间与抓取时间，并保存 `content_source`、`retrieval_status` 和内容哈希；同一 URL 内容变化会追加到 `article_versions`，旧分析仍关联旧版本。
- 每条引文在分析时分配稳定 ID（`e1`、`e2`…），并记录定位信息（`title` / `summary` / `unlocated`）与字符位置；报告以 `[e1]` 前缀展示，附录汇总可定位与无法定位的引文数量。定位前会去除 HTML 标签、反转义实体并统一引号与空白。
- 来源身份与内容证明力分开：论坛用户帖记为一手用户表达，即使内容只是功能请求；GitHub Releases 记为项目记录；官方发布才记为官方宣传。
- 每次分析保存模型标识、提示词版本和规则版本。提示词是版本化资产，位于 `prompts/analyst.md`，首行 `VERSION: N`；共享约束见 `prompts/shared/`。
- 人工复核同时写入当前状态表 `reviews` 和追加式历史表 `review_history`，保留修改前的标签、理由和时间。
- 报告先写临时文件、通过结构校验后再原子替换；校验失败时保留上一份有效报告。

## 人工复核
机器只负责排序，是否值得投入由人工判断。复核结果写入数据库的 `reviews` 表，可用于统计机器的命中率和误报率。

```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.review list --limit 20
.\.venv\Scripts\python.exe -m opportunity_radar.review label <key前缀> real_pain --note "原文证据充分"
.\.venv\Scripts\python.exe -m opportunity_radar.review stats
```

标签：`real_pain`（真实问题）、`commercial_intent`（采购/预算/付费意愿）、`competitive_signal`（竞品发布）、`technical_reference`（技术参考）、`weak_evidence`（证据不足）、`irrelevant`（与方向无关）。

`stats` 会给出三个关键指标：机器候选被人工判为噪声的比例（误报率）、人工认定需求被机器排进候选区的比例（命中率），以及机器状态与人工标签的交叉表。

## 约束
- 未确认许可的来源保持禁用；不绕过登录、验证码、付费墙或技术限制。
- 模型只做初筛，不证明营收、市场规模或法律结论。
- 邮件包含简短摘要与原始链接，不复制完整文章。
- 模型/SMTP/API 故障应记录并可诊断。
- `.env`、数据库和运行日志不要提交到公开 GitHub。

## API 说明
客户端使用 FreshRSS Fever API。Fever API 的可用性和配置可能因 FreshRSS 版本而异；需在实际实例中验证。每个获准来源必须在 `config/sources.csv` 中填写对应的 `freshrss_feed_id`；程序只处理映射到已批准来源的文章。请在 FreshRSS API 返回结果中核对 feed ID，不要猜测。
