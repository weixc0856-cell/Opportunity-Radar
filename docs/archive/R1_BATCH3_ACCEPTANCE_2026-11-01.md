# R1 第三批（来源谱系与独立佐证）— 实施与验收记录

日期：2026-11-01
状态：**实现完成，测试通过，真实数据副本验证通过；未写入生产库**
上游：`docs/PRD.md` §5.3 / §6.2、`docs/IMPLEMENTATION_PLAN.md` §6.4、`docs/R1_BATCH2_ACCEPTANCE_2026-11-01.md`

---

## 1. 范围

解决一个具体问题：**两篇文章不等于两个来源，两个来源族也不等于两条独立证据。**

本批交付：

1. 来源谱系登记表（`config/source_lineage.csv`），为每个启用源记录所属机构、来源类型、
   联合发布组、独立性状态与判断依据。
2. 把谱系写回证据行（`evidences.source_family`、`independence`、`lineage_basis`、
   `syndication_group`）。
3. 证据画像重写：文章数、来源数、来源族数、可计入佐证的单元数分开统计。

不做：修改评分规则、修改日报发布逻辑、把未确认的来源标成独立。

---

## 2. 数据契约（已冻结）

### 2.1 登记表字段

| 字段 | 说明 |
|---|---|
| `source_id` | 与 `config/sources.local.csv` 一致的来源 ID |
| `source_family` | **机构**级标识，不是域名，也不是 feed |
| `lineage_kind` | `official_statistics` / `first_party_announcement` / `news_organisation` / `community_forum` / `aggregator` / `other` |
| `parent_source` | 上级来源（当前全部为空） |
| `syndication_group` | 同一稿件的联合发布组；**没有证据就不填** |
| `ownership_group` | 所属机构集团 |
| `independence` | `independent_primary` / `independent_secondary` / `syndicated` / `republished` / `derived_from_same_source` / `unknown` |
| `basis` | 这条判断的依据（人写的一句话） |
| `basis_source` | 依据来自哪里（当前都指向 `config/sources.local.csv` 的字段） |
| `reviewed_at` / `review_status` | 复核日期与状态（`declared` / `verified`） |

登记表放在独立文件而不是 `sources.local.csv`：后者是本机文件、被 gitignore，谱系判断需要
版本控制、可 diff、可追溯到人和日期。

### 2.2 当前登记结果

15 个启用源 → **12 个来源族**：

| 族 | 源 | 独立性 |
|---|---|---|
| `bbc` | bbc-business、bbc-technology | independent_secondary |
| `nyt` | nyt-business、nyt-technology | independent_secondary |
| `ycombinator-hn` | hn-ask、hn-show | unknown |
| `bea` / `federal-reserve` / `ons` | 各自一个官方源 | independent_primary |
| `nvidia` | nvidia-newsroom | independent_primary（公告的原始出处，非独立核实） |
| `openai` / `precice` / `paraview` / `salome` / `simscale` | 各自一个论坛 | unknown |

**不设联合发布组**：没有任何证据证明 BBC 两个栏目、NYT 两个栏目转发了同一篇稿件，
因此 `syndication_group` 全部为空。没有依据就不填。

### 2.3 佐证判定

```
可计入佐证单元 = { 来源族(或联合发布组) | 该族至少有一条独立性为 primary/secondary 的证据 }
independent_corroboration = 单元数 >= 2
```

- 同一机构的两个栏目 → 1 个族 → 不构成佐证。
- 未知独立性的来源 → 不进入分子，也不进入分母的解释。
- 共享联合发布组的不同机构 → 合并为 1 个单元（有登记时才生效）。

---

## 3. 真实数据验证（副本）

### 3.1 应用谱系

在生产库副本上执行 `unified_main lineage`：

| 项 | 结果 |
|---|---|
| 应用的源 | 15 |
| 更新的证据 | 220（首次）／0（重跑） |
| 独立性分布 | independent_primary 4 个源、independent_secondary 4 个源、unknown 7 个源 |
| 证据族分布 | ycombinator-hn 109、openai 24、nyt 17、simscale 17、paraview 15、bbc 14、bea 8、nvidia 7、precice 5、ons 3、federal-reserve 1 |
| 未登记来源 | 无 |
| 迁移 | `user_version` 2 → 3，`evidences` 新增 `lineage_basis`、`syndication_group` 两列（附加式），integrity ok |

### 3.2 三种佐证情形

用一篇真实的 preCICE 论坛文章（族 `precice`，独立性 unknown）作为基础事件，在两个副本上
复制成不同来源的同标题文章（72 小时内，因此属同一事件）：

| 情形 | 事件内来源族 | 独立性分布 | 佐证单元 | 独立佐证 |
|---|---|---|---|---|
| **独立来源**（基础 + bbc-business + us-bea） | bbc、bea、ycombinator-hn | unknown 5 / secondary 5 / primary 5 | **2** | **true** |
| **同机构双栏目**（基础 + bbc-business + bbc-technology） | bbc、ycombinator-hn | unknown 5 / secondary 10 | **1** | **false** |
| **未知来源**（基础 + hn-show） | ycombinator-hn | unknown 10 | **0** | **false** |

第二种是本批要证明的核心：10 条 `independent_secondary` 证据、2 个 feed、同一个机构，
**不是两个独立来源**。

---

## 4. 测试

| 项 | 数值 |
|---|---|
| 新增文件 | `tests/test_lineage.py`（14 项） |
| 全量 | **632 项通过**（第三批前 618） |

覆盖：登记表校验（缺族、缺依据、词表外取值、未登记来源、已提交登记表本身必须合法）；
应用与幂等；未登记来源保持 unknown；跨族佐证成立；同族双栏目不成立；未知来源不计入；
联合发布组合并为一个单元。

---

## 5. 未部署到生产

本批只在副本上验证。生产库仍是第二批部署后的状态（`user_version=2`，证据全部 `unknown`）。
落地命令：

```
python -m opportunity_radar.unified_main lineage
```

首次运行会自动补 `evidences` 的两个新列、把 `user_version` 升到 3，并按登记表更新 220 条证据。

---

## 6. 限制与遗留

1. **谱系依据来自登记字段，不是独立核实**：`basis_source` 指向 `sources.local.csv` 的
   `canonical_domain` / `feed_provider` / `source_type`。这是"已记录的判断"，不是"已验证的事实"；
   `review_status` 全部是 `declared`。
2. **转载与联合发布无法自动识别**：`syndication_group` 目前全为空。真正的转载识别需要正文相似度
   或通讯社标记，属于后续批次。
3. **论坛与聚合平台一律 unknown**：用户发言的独立性无法确定，这是保守结果。
4. **`nvidia-newsroom` 标为 `independent_primary`**：它是一手发布方，但**不是**对自身说法
   的独立核实。族级计数保证它不会与自己构成佐证；画像的 `quality_note` 仍会说明来源性质。
5. **来源族不进入评分与日报**：本批只影响证据画像与数据，评分规则、证据门槛、发布门禁均未改动。
6. **新增来源需要同步登记**：未登记的源保持 `unknown`，不会静默继承别的源的族。

---

## 7. 与设计的差异

| `IMPLEMENTATION_PLAN.md` / PRD | 本批实现 | 原因 |
|---|---|---|
| 谱系字段进入 `sources` 登记表 | 独立的 `config/source_lineage.csv` | `sources.local.csv` 是本机文件且被 gitignore；谱系需要版本控制与 diff |
| `multi_source_coverage` 改为要求 ≥2 个独立来源族 | 已实现判定逻辑，但未接入证据状态机 | 证据状态机属于评分链路，本批按要求不改 |
| 转载/联合发布识别 | 字段与计数规则已就绪，数据为空 | 没有可核实的转载证据时不填，避免虚构 |

---

## 8. 生产部署记录（2026-11-01）

### 8.1 备份

`data/archive/r1-batch3-deploy-2026-11-01/`，含 `SHA256SUMS.txt`：

| 备份 | SHA-256 | 字节 | 表数 | `user_version` |
|---|---|---|---|---|
| `opportunity_radar.sqlite3.bak` | `f4bb12caa65d8539…` | 2,654,208 | 23 | 2 |
| `opportunity_radar_ingest.sqlite3.bak` | `4437346ac5e1aa32…` | 5,357,568 | 18 | 2 |

### 8.2 执行

| 命令 | 结果 |
|---|---|
| `unified_main lineage`（生产库） | 应用 15 个源、更新 220 条证据；未登记来源 0 |
| 摄取库兼容迁移 | `evidences` 补 `lineage_basis`、`syndication_group` 两列，`user_version` 2 → 3 |
| 重跑 `lineage` | 更新 0 条（幂等） |

### 8.3 部署后状态

| 项 | 生产库 | 摄取库 |
|---|---|---|
| SHA-256 | `ab199788cea710a8…` | `08124ab9a2838c2d…` |
| 表数 / `user_version` | 23 / **3** | 18 / **3** |
| `integrity_check` | ok | ok |

证据按来源族：ycombinator-hn 109、openai 24、simscale 17、nyt 17、paraview 15、bbc 14、
bea 8、nvidia 7、precice 5、ons 3、federal-reserve 1。

证据按独立性：unknown 170、independent_secondary 31、independent_primary 19。

业务表 articles 117 / analyses 108 / runs 14 / deliveries 26 与部署前一致。
