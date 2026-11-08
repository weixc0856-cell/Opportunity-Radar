# 来源合规核验（2026-11-08）

范围：为补齐**政策 / 宏观 / 科技研究**三类内容，对 `config/sources.local.csv` 中
`permission_status=review_required` 的候选源做一次可追溯核验。**本文不启用任何来源**；
启用与否由使用者确认后在 `config/sources.local.csv` 里改，并记入 `reviewed_at`。

## 方法与产物

| 工具 | 产物 | 内容 |
|---|---|---|
| `tools/compliance_probe.py` | `reports/compliance/2026-11-08.json` | 每个源的 feed 状态、条目数、robots.txt 判定 |
| `tools/compliance_terms.py` | `reports/compliance/terms/*.txt` | 条款页正文（逐源留档） |

判定看三件事：**feed 是否官方提供且可访问**、**robots.txt 是否允许我们取该路径**、
**条款是否允许个人非商业使用**。本项目是个人、本地、非商业摘要；只保存逐字引文与链接，
不复刻全文，不对外分发。

## 判定标准

- **A 可批准**：官方 RSS；robots 允许；许可明确（公共领域 / OGL / 开放元数据）。
- **B 可批准但需限制**：条款允许个人非商业使用，但同时限制复制/再分发。
  只存逐字引文、标题、链接与出处；不生成可替代原文的内容。
- **C 需人工确认**：条款页无法自动抓取（403/202/404）、或条款未覆盖 RSS。
- **D 不批准**：robots 明确禁止，或需要付费/书面许可。

## 结果

### A · 可批准

| 源 | 主线 | feed | robots | 依据 |
|---|---|---|---|---|
| U.S. BLS | macro_economy | 200，12 条 | 允许 | 版权页：*"everything that we publish … is in the public domain"*，要求注明 *"cite the Bureau of Labor Statistics as the source"*；BLS 徽标为注册商标，不得使用 |
| U.S. Census | macro_economy | 200，10 条 | 允许 | 美国联邦政府作品（17 U.S.C. §105）；政策页与数据页均无 RSS 限制 |
| UK ONS（已批准） | macro_economy | 200，10 条 | 无 robots.txt | 条款：*"published under the Open Government Licence (OGL)"*；OGL v3.0 需署名；部分图片/视频豁免，不在 OGL 内 |
| Google Research / DeepMind / Google AI | technology_research | 200，100/100/20 条 | 允许 | 官方 RSS；Google 条款未禁止个人阅读与引用；仍按 B 的引文口径执行 |
| arXiv cs.AI / cs.LG | technology_research | 200 | 无 robots.txt | API 条款：元数据 *"CC0"*，内容可 *"for your own personal use, or for research purposes"*；**限速：每 3 秒不超过 1 次请求，单连接**；再分发电子印本需版权方许可 |

> arXiv 的限速是硬约束：现有客户端按 feed 顺序抓取，两个 arXiv feed 会连续请求。
> 若批准，需要在该源上加入 ≥3s 间隔，否则属于违反对方条款。

### B · 可批准但需限制（只存引文与链接）

| 源 | 主线 | feed | robots | 条款要点 |
|---|---|---|---|---|
| Hugging Face Blog | technology_research | 200，899 条 | 允许 | 开源许可内容沿用原许可；*"You may not alter, reproduce, republish, license any of our proprietary materials"* |
| Microsoft Official / Research | technology_research / corporate | 200，各 10 条 | 允许 | *"Personal and Non-Commercial Use Limitation"*；同时限制复制、再发布 |
| AWS Machine Learning Blog | technology_research | 200，13 条 | 允许 | 个人使用许可；禁止 *"resale or commercial use"*、data mining |
| TechCrunch AI | international_news | 200，20 条 | 允许 | *"solely for your personal noncommercial use"*；允许保存单页副本并保留版权声明 |
| MIT Technology Review | technology_research | 200，10 条 | 允许 | RSS 属于其 *"Services"*；授权为个人的、非独占的有限许可；禁止搜索引擎以外的抓取 |
| AMD Investor Relations | corporate_capital | 200，10 条 | 允许 | 禁止为商业目的复制/分发；个人阅读不受限 |

### C · 需人工确认

| 源 | 原因 |
|---|---|
| OpenAI News | 条款页对脚本返回 403；官网 RSS 可用（653 条）。需人工在浏览器确认条款后再定 |
| IEEE Spectrum | 条款页返回 202（反爬挑战）；feed 可用（30 条）。需人工确认 |
| NVIDIA IR / IMF / OECD / World Bank / SIA | 注册表无 `feed_url`，需先找到官方 RSS 并核验，再进入评估 |
| Reuters / AP / AFP | 无 feed；均为商业授权内容，按 D 处理更稳妥 |

### D · 不批准

| 源 | 原因 |
|---|---|
| 中国人民银行（cn-pbc） | `robots.txt`：**`Disallow: /`**。该站拒绝自动访问，不得抓取 |

## 对"政策内容为零"的直接结论

注册表里唯一的 `policy_regulation` 源是人民银行，且：

1. 提供的是 HTML 栏目页，不是 RSS；
2. `robots.txt` 明确 `Disallow: /`。

因此**政策线在现有注册表内无法合规补齐**，必须新增有官方 RSS 且允许抓取的政策源
（如国务院政策文件库、发改委、工信部、财政部等的 RSS/公告页），逐条走同样的核验。
在新增之前，日报的政策线会一直是空的——这是现状，不应被报告体例掩盖。

## 政策源调研（新增候选，未启用）

现有注册表内政策线为零，下面是 2026-11-08 找到的官方候选。**本次不启用**，等你确认。

| 候选 | 状态 | 许可/条款 | 建议 |
|---|---|---|---|
| 中国政府网 RSS `https://www.gov.cn/pushinfo/v150203/rss.xml` | 200，60 条，robots 允许 | 网站声明：*"版权归本网站所属"*；*"任何媒体、网站或商业机构不得对原文内容进行商业性转载"*；英文站：*"Without written authorization … shall not be republished or used in any form"* | **C 需你决定**。个人本地、非商业、只存标题+短引文+链接，仍在"used in any form"的字面之外有争议；不默认启用 |
| 欧盟委员会新闻稿 RSS `https://ec.europa.eu/commission/presscorner/api/rss?language=en` | 200，10 条，robots 允许 | 委员会复用政策 / **CC BY 4.0**：允许复用，"provided appropriate credit is given and changes are indicated" | **A 可批准**（需署名、标注改动） |
| UK GOV.UK 新闻与公告 Atom `https://www.gov.uk/search/news-and-communications.atom` | 200，20 条，robots 允许 | GOV.UK 内容通常为 **OGL v3.0**（署名即可复用） | **A 可批准**（需署名） |
| 国家发改委 / 工信部 | HTML 栏目页，无 RSS；robots 403/404 | 无 RSS 授权路径 | 只能走 `page_watch` 页面监测，需另做条款核验 |

补充：美国政策/监管数据（Federal Register）已在隔离 pilot 通道（`pilot/`），按项目规则
不进入 RSS 业务表与日报正文；这不是缺失，是设计。

## 批准后的启用步骤

1. 在 `config/sources.local.csv` 中把选定源改 `permission_status=approved`、`enabled=true`、
   填 `reviewed_at`，并把 `freshrss_feed_id` 对应到实际订阅；
2. 在 FreshRSS 里添加订阅（当前 27 个；上述候选多数尚未订阅）；
3. 运行 `python -m opportunity_radar.source_audit`，确认 0 个阻塞错误；
4. 跑一次 `--dry-run`，检查新源是否进入对应主线、引文是否可定位；
5. 在 `docs/PROJECT_STATUS.md` 记录启用日期与范围。

## 执行结果（2026-11-08）

经使用者确认，已批准并启用 14 个源（原先 15 个 → 现 29 个）：

| source_id | feed id | 主线 |
|---|---|---|
| us-bls | 28 | macro_economy |
| us-census | 18 | macro_economy |
| google-research | 29 | technology_research |
| deepmind-blog | 11 | technology_research |
| google-ai-blog | 30 | technology_research |
| huggingface-blog | 12 | technology_research |
| microsoft-blog | 31 | technology_research / corporate_capital |
| microsoft-research | 32 | technology_research |
| aws-ml-blog | 33 | technology_research |
| techcrunch-ai | 14 | international_news |
| mit-tech-review | 34 | technology_research |
| amd-ir | 35 | corporate_capital |
| arxiv-cs-ai | 36 | technology_research |
| arxiv-cs-lg | 37 | technology_research |

同步改动：

- `config/sources.local.csv`：14 行改 `approved` / `enabled=true` / `reviewed_at` /
  `last_verified_at=2026-11-08`，并绑定 FreshRSS feed id；备份在
  `config/sources.local.csv.bak-2026-11-08`。
- FreshRSS：OPML 导入 14 个订阅（27 → 37），已触发一次全量抓取。
- `OR_MAX_ARTICLES`：20 → 40（源从 15 个增至 29 个，20 个名额会让每个源分不到一条）。
- `freshrss_client.fetch_articles`：对 `rss.arxiv.org` 加 ≥3.2 s 的请求间隔。
- `source_audit`：47 行 / 29 enabled / **0 错误 0 警告**。

已知情况：

- arXiv 周末不发布更新（feed 自带 `skipDays: Saturday/Sunday`），周末两个 feed 为空属正常。
- 政策线仍为 0：候选已列在上一节，等确认后才启用。

## 限制

本文件是按 robots.txt 与站点条款原文做的**工程核验**，不是法律意见；条款可能变更，
每年复核一次并更新 `last_verified_at`。任何"允许"结论都以"个人、本地、非商业、
只存引文与链接"为前提；改变分发方式需要重新评估。
