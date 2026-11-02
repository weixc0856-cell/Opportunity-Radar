# R2 Batch 12 人工参考集（10 篇）

建立时间：2026-11-02

标注范围：Ten sample articles. All currency/percent expressions with an explicit unit in the supplied title or RSS text are annotated. Bare integers, URL/image ids, version numbers and identifiers are not economic numbers and are not in the recall denominator. Title-only figures are annotated with expected_claim=false and the N5 rejection reason. Period is what the supplied text states; no year is inferred from publication time.

人工参考集独立于 N2/N3 模型输出，按原文标题与 RSS 正文建立。

## BEA News — Personal Income and Outlays, September 2026

- article_id：`1793288504794278`
- 预期正文 Claim：9
- 备注：September 2026 is stated in the title; the body says September. Months are explicit in both.

| 原文 | value | unit/scale | subject | predicate | disposition | relation/direction/comparison | period | evidence | expected claim |
|---|---:|---|---|---|---|---|---|---|---|
| `$54.5 billion` | 54.5 | USD billion | personal income | personal_income | claim_value | change/increase/unknown | 2026-09 | body | True |
| `0.2 percent` | 0.2 | %  | personal income | personal_income | claim_value | rate/not_applicable/monthly_rate | 2026-09 | body | True |
| `$52.7 billion` | 52.7 | USD billion | disposable personal income | disposable_personal_income | claim_value | change/increase/unknown | 2026-09 | body | True |
| `0.2 percent` | 0.2 | %  | disposable personal income | disposable_personal_income | claim_value | change/increase/unknown | 2026-09 | body | True |
| `$113.1 billion` | 113.1 | USD billion | personal consumption expenditures | personal_consumption_expenditures | claim_value | change/increase/unknown | 2026-09 | body | True |
| `0.5 percent` | 0.5 | %  | personal consumption expenditures | personal_consumption_expenditures | claim_value | change/increase/unknown | 2026-09 | body | True |
| `$113.0 billion` | 113.0 | USD billion | personal outlays | personal_outlays | claim_value | change/increase/unknown | 2026-09 | body | True |
| `$911.1 billion` | 911.1 | USD billion | personal saving | personal_saving | claim_value | level/not_applicable/level | 2026-09 | body | True |
| `3.8 percent` | 3.8 | %  | personal saving rate | personal_saving_rate | claim_value | rate/not_applicable/level | 2026-09 | body | True |

## BEA News — U.S. International Trade in Goods and Services, August 2026

- article_id：`1792727557470834`
- 预期正文 Claim：6
- 备注：July 2026 and August 2026 are stated; July's year is in the opening sentence's August 2026 context. The revised state is explicit for the July figure.

| 原文 | value | unit/scale | subject | predicate | disposition | relation/direction/comparison | period | evidence | expected claim |
|---|---:|---|---|---|---|---|---|---|---|
| `$92.8 billion` | 92.8 | USD billion | u.s. goods and services trade deficit | trade_deficit | claim_value | level/not_applicable/level | 2026-07 | body | True |
| `$105.6 billion` | 105.6 | USD billion | u.s. goods and services trade deficit | trade_deficit | claim_value | change/increase/period_change | 2026-08 | body | True |
| `$12.8 billion` | 12.8 | USD billion | goods deficit | goods_deficit | claim_value | change/increase/period_change | 2026-08 | body | True |
| `$136.6 billion` | 136.6 | USD billion | goods deficit | goods_deficit | claim_value | level/not_applicable/level | 2026-08 | body | True |
| `$0.1 billion` | 0.1 | USD billion | services surplus | services_surplus | claim_value | change/increase/unknown | 2026-08 | body | True |
| `$31.0 billion` | 31.0 | USD billion | services surplus | services_surplus | claim_value | level/not_applicable/level | 2026-08 | body | True |

## BEA News — GDP (Advance Estimate), 3rd Quarter 2026

- article_id：`1793288504794279`
- 预期正文 Claim：2
- 备注：Third quarter 2026 is explicit; second quarter shares the same 2026 context. annual_rate is explicit.

| 原文 | value | unit/scale | subject | predicate | disposition | relation/direction/comparison | period | evidence | expected claim |
|---|---:|---|---|---|---|---|---|---|---|
| `3.4 percent` | 3.4 | %  | real gross domestic product | real_gross_domestic_product | claim_value | change/increase/annual_rate | 2026-Q3 | body | True |
| `2.2 percent` | 2.2 | %  | real gross domestic product | real_gross_domestic_product | claim_value | change/increase/annual_rate | 2026-Q2 | body | True |

## BBC Business — Google value plunges by $500bn as AI fears rattle Wall Street

- article_id：`1793312435473550`
- 预期正文 Claim：0
- 备注：The figure is only in the title; N5's title-only rule should reject it as a Claim. It remains a valid N1 candidate and N2 claim_value in the title.

| 原文 | value | unit/scale | subject | predicate | disposition | relation/direction/comparison | period | evidence | expected claim |
|---|---:|---|---|---|---|---|---|---|---|
| `$500bn` | 500 | USD billion | google | market_value | claim_value | change/decrease/unknown | — | title | False |

## BBC Technology — US tech stocks see sharp falls as AI spending nears $1tn

- article_id：`1793374852678200`
- 预期正文 Claim：0
- 备注：The figure is only in the title; the body has no numeric claim.

| 原文 | value | unit/scale | subject | predicate | disposition | relation/direction/comparison | period | evidence | expected claim |
|---|---:|---|---|---|---|---|---|---|---|
| `$1tn` | 1 | USD trillion | ai spending | ai_spending | claim_value | level/not_applicable/unknown | — | title | False |

## NYT Technology — Intel’s Shares Plunge 20% as A.I. Hinders Some Parts of Its Business

- article_id：`1793312435473530`
- 预期正文 Claim：1
- 备注：The 20% is title-only and should be rejected by N5. The revenue figure is in the body; the text says third quarter but not the year, so period is left empty rather than inferred.

| 原文 | value | unit/scale | subject | predicate | disposition | relation/direction/comparison | period | evidence | expected claim |
|---|---:|---|---|---|---|---|---|---|---|
| `20%` | 20 | %  | intel shares | share_price | claim_value | change/decrease/unknown | — | title | False |
| `$16.5 billion` | 16.5 | USD billion | intel | revenue | claim_value | level/not_applicable/level | — | body | True |

## NYT Technology — The Key Numbers From Anthropic’s IPO Filing

- article_id：`1793043644300033`
- 预期正文 Claim：0
- 备注：The supplied RSS text contains no economic figure; image URL digits are not economic numbers. This is a control for N1/N2 noise.

无经济数字；URL/图片编号不计入经济数字。

## NVIDIA Newsroom — NVIDIA and Oracle Expand NVIDIA Vera Rubin to Multi-Gigawatt Scale and Bring NVIDIA Vera CPU to Oracle Cloud Infrastructure

- article_id：`1793119256721124`
- 预期正文 Claim：0
- 备注：No digit-bearing economic figure in the supplied text; 'multi-gigawatt' is a word. Image URL digits are not economic numbers.

无经济数字；URL/图片编号不计入经济数字。

## OpenAI Developer Community — [Feature request] Give ChatGPT the ability to edit plain text files

- article_id：`1793576442054607`
- 预期正文 Claim：0
- 备注：No economic figure; image and link URLs contain digits. This is a control for non_claim/unclassified handling.

无经济数字；URL/图片编号不计入经济数字。

## SimScale Forum — The simulation results are anomalous.

- article_id：`1793317257235701`
- 预期正文 Claim：0
- 备注：No economic figure; the workbench URL contains a long digit id. This is a control for non_claim/unclassified handling.

无经济数字；URL/图片编号不计入经济数字。

## 覆盖范围与未标注范围

- 标注了带明确单位/百分号的金额、百分比与百分点，以及它们的标题/正文位置。
- 未标注：URL/图片 id、版本号、引用编号、裸整数；这些不作为 N1 召回分母，但用于检查 N2/N5 是否错误地当成经济数字。
- 标题-only 数字标注为 expected_claim=false，并给出 N5 应拒绝的原因；它们仍计入 N1/N2 的候选与语义检查。
- 期间只记录原文明确给出的时间；不从发布时间推断年份。
