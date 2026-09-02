# T1742 诊断结论 + Post_setting 重构冲刺计划

## 1. T1742 重新诊断（证据，非盲换）

**动作**：之前 un-skip 跑了一次 `testT1742`（pytest 为闸门），仍在 `verify_post_offer` 失败：
`Text 'Offer up to 10%' not found`，traceback 显示
`waiting for get_by_text("event-for-ui-auto-venue-map").first.get_by_text("Offer up to 10%").first`
—— 这反而**证明 scope 修复（base.py）生效**（scope 容器被正确套用）。

**根因（查 `step_captures/testT1742/manifest.json` 失败步 DOM）**：
- 失败那一刻页面在 `/events` 列表页（或 Selling 管理 tab）。scope 文本 `event-for-ui-auto-venue-map`
  在列表页命中了**事件卡片**（mui-stack），而非 post 卡片 → 容器内没有 "Offer up to 10%"。
- step[9] 的 post 详情 Selling-tab DOM：post 卡片是 `"Select post"` 管理卡（`URL / 标题 / Published`），
  **没有** "Offer up to X%" 文字。
- 交叉比对 `step_captures/testAddNewUpdateModule`（PASS 样本）："Offer up to 0%" 出现在
  **公开 post 卡片** `autotestshop/post/<slug>` 上，卡片 name = `标题\n价格\nslug\nOffer up to 0%`。
  即该 label 只渲染在**公开 post 卡片**，不在 Selling 管理 tab / 事件列表。

**结论**：`verify_post_offer` 的断言目标（"Offer up to 10%"）与测试当时所在页面（Selling/列表）不匹配
→ 结构性漂移，**不是 locator 能盲修的**。叠加 Commission UI 已重构（批量→per-ticket Advanced 字段），
当前 flow 是否还会产出 post 级 "Offer up to 10%" 仍未确认。

**处置**：`testT1742` 重新 `skip: true`，注释写清上述根因，纳入重构冲刺。
（teardown 里的第二个 `verify_post_offer` "Offer up to 8%" 同样结构性错误，随整例 skip 不跑。）

**4 次 pytest 迭代后的最终根因（2026-09-02）**：这例不是 locator 能修，是**导航可达性**问题。
- Commission "Offer up to X%" **只渲染在公开 post 页** `autotestshop/post/<slug>`（testAddNewUpdateModule 印证）。
- 组织者视角的 Post  tab 卡片是 `Select post` **开关**（不导航、无 offer 文案）；事件页内嵌 shop 预览也不显示 offer；Commission 流程结束后页面落在全局 `/events/settings`（无 "View post"）。
- slug 是动态生成，YAML 无法硬编码公开 URL。
- ⇒ verify 目标在重构后的组织者流程里**不可达**。需二选一才能解：① 在 post-settings / Post tab 暴露 "View post" 按钮；② 框架加 "按 slug 打开公开 post" 动作；或 ③ 真·浏览器（agent-browser 沙箱冷启挂起）确认新 offer 位置。已 re-defer。

## 2. ADR：Commission 校验目标结构性漂移

```
# ADR-Post-Commission-Verify
## Status: Accepted (deferred-to-refactor-sprint)
## Context
Post Setting 页 venue_map 重构后，commission "Offer up to X%" 仅渲染在公开 post 卡片
(autotestshop/post/<slug>)，而 T1742/T2705 的 verify_post_offer 在 Selling 管理 tab / 事件列表页断言，
且 Commission 录入 UI 由批量改为 per-ticket Advanced 字段。
## Decision
T1742/T2705 暂缓；重构时把校验挪到公开 post 卡片（或事件 Posts 公开卡）并确认新 commission 录入流
确实产出 post 级 offer 文案；禁止仅改 locator。
## Consequences
+ 不会因盲修 locator 产生假 PASS
- 这两例在重构成前不覆盖 commission 展示
```

## 3. Post_setting 重构冲刺清单（按 feature，需真实浏览器确认）

| Feature | 涉及用例 | 已知漂移 | 冲刺动作 |
|---|---|---|---|
| Commission 展示/录入 | T1742, T2705(owner/guest) | 批量→per-ticket Advanced；offer 仅公开卡渲染；**组织者流程无法导航到公开 post（T1742 已证不可达）** | T1742 BLOCKED（需 UI 暴露 View post 或框架 slug 导航）；T2705 待查 |
| Variants / 依赖票 | T2515, T2874, T2705 | variant 选择 UI 重构 | 重写 variant 选择流 |
| Co-seller 下游备注 | T3991_VerifyPartner | "Add a note for co-sellers" 入口移至 Co-selling 子 tab，textbox 删除 | 重写备注录入流 |
| Access code | T4955 | enablePaymentRestriction→isAccessRestricted；access code 子流程消失 | 重写 access code 流 |
| Merch | T5332, T5443 | Merch 子 tab 重构 | 重写 Merch 步（T5332 重构中 recon 跑） |
| +997 buyer 路径 | T3686_CosellerResell | 框架按 ENV 统一 +999，点不到 partner 专属 "Manually add co-sellers" | 需决定 cookie/角色策略 |

**门禁**：每例改完必须本地 pytest 跑通（step_captures 当眼睛，因 agent-browser 沙箱冷启动挂起）；
跑通后才交付，发布前先告知。

## 4. 冲刺进度（venue_map 文件 + 跨文件 sprint）

| 用例 | 文件 | 状态 | 根因 / 下一步 |
|---|---|---|---|
| T1742 (Commission 展示) | venue_map | **re-deferred (2026-09-02, 4 次 pytest 实证)** | 公开 post 卡片不可达（见 §1）。需 UI 暴露 View post / 框架加 slug 导航 / 真浏览器。 |
| T5332 (Merch 全部插入 RTE) | venue_map | **recon: FAIL** (2026-09-02) | `assert 'merch 001' not found in page content`；post 内容只有 ticket，无 merch。截图（`fail_assert_testT5332_VerifyGuest.png`）确认 post 页只渲染 General Admission/Buy Ticket，merch 没进来。**根因疑似**：Merch 子 tab 重构后 RTE `Insert → Insert all merch` 流程或入口变了（Merch 001/002 物料可能也未建）。需确认新 Insert 流程标签 + 物料前置条件。**tractable**。 |
| T5443 | venue_map | 未跑 | T5332 修完带过 |
| T2705 / T3991 / T3686 / T4955 / T2515 / T2874 | Post_setting.yaml | 已 skip (上一轮) | 变体/备注/access code/seat-buy 等结构性漂移，待逐个 recon |

## 5. 本轮门禁经验

- pytest 循环适合**定位**（recon）：拿 step_captures 失败步 DOM + 失败截图，反推 UI 漂移。
- pytest 循环**不适合**修结构性导航 gap（像 T1742 这种 verify 目标在另一域的）：4 次迭代证伪后应立刻 re-defer，不要硬磕。
- 验证类 assertion（`found_in_content` 文本搜）失败时，截图（`fail_assert_*.png`）比 capture JSON 更有用（capture 有时只存操作步 DOM，不存最终渲染页）。

