# R1 第二批（实体对齐与候选关联）— 实施与验收记录

日期：2026-11-01
状态：**实现完成，测试通过，真实数据副本验证通过；未写入生产库**
上游：`docs/PRD.md` §5.3、`docs/IMPLEMENTATION_PLAN.md` §6、`docs/R1_BATCH1_ACCEPTANCE_2026-11-01.md`

---

## 1. 范围

在第一批的事件/证据/主张之上，建立三件东西：

1. **实体**：把结构化来源里的公司变成可复用的一条记录（CIK、名称、别名）。
2. **提及**：在系统真正持有的文本里找到这些名字，记下命中的原文与置信度。
3. **候选关联**：把结构化主张与事件、事件与事件之间的可能关系记下来，**只记候选，不合并**。

不做：实体消歧（同一名称指向多个公司）、事件合并、模型判定、跨语言名称、因果推断。

---

## 2. 数据契约（已冻结）

### 2.1 表

```sql
entities(entity_id PK, entity_type, canonical_name, canonical_key UNIQUE, cik, ticker, created_at)
entity_aliases(entity_id, alias, alias_key, method, created_at, PK(entity_id, alias_key))
entity_mentions(mention_id PK, entity_id, target_kind, target_key, method,
                matched_text, confidence, created_at,
                UNIQUE(entity_id, target_kind, target_key, method))
event_links(link_id PK, left_kind, left_key, right_kind, right_key,
            relation, basis, confidence, status, evidence_json, created_at,
            UNIQUE(left_kind,left_key,right_kind,right_key,relation,basis))
```

`PRAGMA user_version` 升到 2；仍是附加式建表，旧库打开即补齐。

### 2.2 别名与匹配

- 别名**只从登记名称派生**：原名、去掉公司后缀（Inc./Corp./Company/Ltd./PLC…）、去掉开头的
  `The`。例：`The Coca-Cola Company` → `The Coca-Cola Company` / `Coca-Cola` / `The Coca-Cola`。
- 匹配是**整词、大小写不敏感**；`Applesauce` 不会命中 `Apple`，`Apple's` 会命中。
- 规范化名（canonical）置信度 0.9，派生别名 0.75。
- **股票代码不参与匹配**：`CAT`、`KO`、`ARM` 这类三字母与普通词冲突，错误提及比漏掉提及更糟。
  代码记录在实体上，留给后续带消歧的批次。

### 2.3 关联

| 关系 | 含义 | 生成条件 | 置信度 |
|---|---|---|---|
| `same_subject` | 一条结构化主张与一个事件在说同一家公司、时间相近 | 实体相同且期间结束日与事件首次出现相差 ≤ 120 天 | 0.6 |
| `shared_entity` | 两个事件各自提到同一家公司 | 实体相同且两个事件首次出现相差 ≤ 7 天 | 0.5 |

- **所有关联初始状态都是 `candidate`**。接受/拒绝只能通过 `record_decision()` 写入，
  并在 `event_corrections` 里留下追加式记录；链接本身不改变任何事件或文章。
- `basis` 记录是靠什么连起来的，`evidence_json` 记录当时的依据（实体、期间、时间差），
  使关系在事后可复核。

### 2.4 证据画像

`event_profile(event_id)` 分别给出：

| 输出 | 含义 |
|---|---|
| `articles` / `evidences` / `claims` | 数量 |
| `source_families` | 去重后的来源族 |
| `independence` | 每条证据的独立性判定分布（当前 RSS 全部 `unknown`） |
| `evidence_kinds` | 引文 / SEC 事实 / EIA 观测 |
| `independent_corroboration` | 只有"≥2 个来源族 **且** 没有 unknown"才为真 |
| `quality_note` | 未达成时明确写出"证据数量不等于独立佐证，也不等于证据质量" |

三者分开计数，不允许用一个数字代表"可信度"。

---

## 3. 真实数据验证（副本）

| 步骤 | 结果 |
|---|---|
| `entities`（生产库副本） | 10 个实体（10 家 SEC 覆盖公司）、2 条提及（Apple、NVIDIA 各一）、2 篇文章命中 |
| `links`（生产库副本 + 摄取库副本） | 考虑 2,719 条结构化主张，生成 **3 条 claim↔event 候选关联**，0 条 event↔event |
| 重跑 | 实体/提及/关联新增全部为 0（幂等） |

3 条关联全部是 NVIDIA：三条期间结束于 2026-07-26 的主张（相隔 94 天）连到 2026-10-27 的
NVIDIA 事件，`basis=entity_period_window`，状态 `candidate`。

Apple 没有生成关联：唯一提到 Apple 的文章**没有分析记录**（117 篇文章中 9 篇尚未分析），因此
没有事件可连。这是数据现状，不是规则失效。

### 3.1 事件级关联的真实数据验证

在草稿副本里加入一篇**不同的** NVIDIA 报道（不同标题、不同 URL、两天后）：

- 事件层：**没有合并**，事件数 108 → 109，NVIDIA 相关事件 2 个；
- 关联层：生成 1 条 `shared_entity` 候选关联（时间差 41 小时），claim↔event 关联从 3 条变为 6 条
  （三条主张分别连到两个事件）。

这正是本批要证明的行为：**不确定的相似不合并，但记成候选。**

---

## 4. 测试

| 项 | 数值 |
|---|---|
| 新增文件 | `tests/test_linking.py`（14 项） |
| 全量 | **618 项通过**（第二批前 604） |

覆盖：别名派生与长度门槛；整词匹配（`Applesauce` 不命中）；置信度分级；实体种子与提及幂等；
期间窗口内/外；无事件时不连；事件间候选关联与窗口；接受/拒绝写入追加式纠错；证据画像
在独立性未知时不得声称独立佐证。

---

## 5. 未部署到生产

本批只在数据库副本上验证。生产库仍是第一批回填后的状态（19 张表，`user_version=1`），
没有 `entities` / `entity_mentions` / `event_links` 数据。要落地：

```
python -m opportunity_radar.unified_main entities
python -m opportunity_radar.unified_main links --ingest-db data/ingest/opportunity_radar_ingest.sqlite3
```

第一次打开生产库时会自动补建这批表并把 `user_version` 升到 2。

---

## 6. 限制与遗留

1. **语料里几乎没有公司名**：117 篇文章只有 2 篇提到 SEC 覆盖的公司。实体对齐的产出量由语料
   决定，不由代码决定；要真正产生跨来源关联，需要提高财经/公司新闻的来源覆盖（属于 S0/S1 的
   范围）。
2. **股票代码不匹配**：见 §2.2。需要消歧规则或上下文判断后再加。
3. **实体消歧未做**：同名不同公司、子公司与母公司都会被当作同一个实体。
4. **9 篇文章没有分析**，因此没有事件，也就没有关联；提及仍然记录。
5. **`independent_corroboration` 目前永远为假**：来源登记表仍无 `source_family` 字段，
   RSS 证据的独立性都是 `unknown`。这是正确的保守结果，不是缺陷。
6. **没有自动接受任何关联**：语料积累后需要一个人工或规则化的接受流程，本批只提供记录与接口。

---

## 7. 与设计的差异

| `IMPLEMENTATION_PLAN.md` §6 | 本批实现 | 原因 |
|---|---|---|
| 关系类型含 `duplicate_wire` / `follow_up` / `derived_from` 等 | 只实现 `same_story` / `same_subject` / `shared_entity` | 其余关系需要实体类型与事件语义，当前无法可靠区分 |
| 事件候选分级（`candidate` 合并判定） | 用 `event_links.status='candidate'` 表达，不产生合并候选 | 没有实体/类型抽取时，"高度重叠"与"共享关键词"无法分开 |
| 来源独立性要求 ≥2 个来源族 | 已实现判定逻辑，但来源族字段尚未登记，结果恒为未知 | 来源治理批次未开始 |
