# Debug Report: Post_setting_for_venue_map.yaml — UI 漂移

**Date**: 2026-08-31  
**YAML**: `test_case/UI/Test_Katana/All_YAML/Post/Post_setting_for_venue_map.yaml`  
**Baseline (2026-08-24, allure-results/20260824_180330)**: **37 用例 — 17 passed / 15 broken / 5 failed (≈46% pass)**  
**Cookie**: 已重捕获 (3 个账号) — 之前 8/24 的 cookie 已过期 (access token 当天过期 + refresh 数天 TTL)。  
**Root cause (单一)**: **事件/文章 UI 整体重构**（介于 8/24 与 8/31 之间上线）。这不是零散漂移，是一次较大 UX 改版：把 `Posts` tab 改单数 `Post`、把 post 详情子 tab 的 `Settings` 抽成独立页 `/post/<id>/settings`、把 `enablePaymentRestriction` + access code 弹窗改成 `isAccessRestricted`("Restrict post access") toggle + 单页 Save。

---

## 1. 真实新 UI（浏览器实测，2026-08-31 重捕获 cookie 后）

`event-for-UI-auto-venue-map` 详情 = modal `/events/<id>/view`。

### 顶层 event tabs
`Event | Post | Attendees | Co-hosts | Sales` — **`Posts` tab 已删**，改单数 `Post`。

### `Post` tab（直显文章，无 post card 可点）
- URL hash 形如 `#tab=POSTS,eventTab=TicketsMerch,postTab=...`
- 文章子 tab: `Content | Selling | Co-selling | Coupons` — **`Settings` 子 tab 已删**。
- 三个 action card: `Content / Style / Settings`（**`Settings` 是 card 不是 tab**，点击 → 导航到独立页 `/post/<id>/settings?redirect=...`）。
- `Settings` card 是进 post 设置的唯一入口。

### `/post/<id>/settings` 独立页（截图 23, 30）
toggles: `hideInStore / isPurchaseQuantityLimited / checkoutInPost(On) / allowExpire / **isAccessRestricted** ("Restrict post access") / isOrderConfirmationNoteEnabled / enableRedirectUrl / **enablePaymentRestriction** / isPostFormEnabled / isPurchaseApprovalRequired / isRecommendationSectionTextEnabled` + 底部**单一个 `Save`**。

### Event tab 内子 tab（在 Event 模态里，截图 02/06）
`Tickets & Merch | Info & Media | Lineup` — `Tickets & Merch` 下列出 section/ticket 卡片（`General Admission 01 / 02 / General Admission`），每张卡 `Tools / View units`。**`General Admission 01/02` 是 ticket 产品**（不是表行），点击进 product 编辑器 `/events/<id>/products/<pid>?mode=TICKET`，子 tab `Basic | Advanced`。

### `Advanced` tab（ticket 编辑器，截图 24）
`Ticket status / Commission % / Tax rate % (Use event default tax) / Custom fees (Edit) / Require customer-provided details / Enable multi-day pass` + Save。**Commission 是每 ticket 字段，不是批量按钮**（`Batch set commission for all products` 按钮未找到 — 可能已移走/改名为全局 commission 入口，未确认）。

### Event 顶部 `Settings` 卡片（截图 10）
小 modal `Event settings`：5 个 checkbox（Charge tax / Add custom fees / Exclude Pear.Us Venue / Show fee breakdown / Show buyer info on venue map）+ Save。**不包含 access code 或 payment restriction**（post 级设置在 post settings 页）。

---

## 2. Drift → 旧 YAML → 需改成什么（按失败用例归类）

旧导航模板: `open /events → click event → R_click_posts_tab(Posts) → R_click_post_card / R_click_post("View post") → post modal tabs`。  
新导航: `open /events → click event → R_click_posts_tab(Post) → [不再有 post card] → 在 Post 视图内 → 对应子 tab 或点 Settings card`。

| 旧 YAML 步骤 | 新现实 | 影响的失败用例 |
|---|---|---|
| `R_click_posts_tab: {role:'tab', name:'Posts'}` | tab 改名为 `Post` | **~30 处**。✅ **已改**（`name:"Posts"` → `name:"Post"`，29 处，replace_all，0 残留）。 |
| `R_click_post_card: {role:'button', name:'event-for-ui-auto-venue-map', index:0}` 或 `R_click_post: {role:'button', name:'View post'}` | Post tab 直达文章，**无 post card 按钮可点**。此步需**整步删除**。 | T1742, T3686_teardown, T4038, T2069(teardown), T4955(2), T2515_VerifyDisabled, T2874_VerifyGuestCheckoutTwo, T3991, T3683, T2830_VerifyPartner, T4735_VerifyPartner, T5332, T5443_VerifyGuest, T5390, T5442, T5440, T3811, T3686_CosellerResell 等。⚠️ **未改**（删步骤 = flow 改动，需逐用例重跑验证）。 |
| `R_click_setting_tab: {role:'tab', name:'Settings'}`（post 内的） | post 详情**无 Settings tab**。`Settings` 是 action card → 跳 `/post/<id>/settings`。 | T4955_Partner, T4955_Guest(teardown), T2705（execute_js 找 Settings tab）。✅ **已改**（`R_click_setting_tab*` / `click_setting_tab*` / `wait_advanced_loaded` 等共 8 处 → `R_click_settings_card: {role:'button', name:'Settings'}` + `R_click_settings_card_teardown` / `_2` / `_verify` / `_reset`）。但 T4955 等后续独立 settings 页 UI（access code 子流程消失）仍待 flow 重写。 |
| `check_payment_restriction: {locator:"input[name='enablePaymentRestriction']"}` | 该 input **仍存在**（post settings 页里），但配套 access code 子流程（`Set up access code` / `Enter access code` / `Confirm` / `Apply`）**消失**——toggle `isAccessRestricted` 后只有底部 `Save`，无弹窗。 | **T4955_Partner + T4955_Guest 需 flow 重写**。整个 access code 机制改了。 |
| `R_click_Co-selling` → `R_click_Co-sellers`（sub-tab） | **🔴 已实锤根因**：post 的 `Co-selling` 子 tab 真实文本是 `Co‑selling`，中间用 **U+2011 不间断连字符**（非 ASCII `-`）。YAML 写的是普通减号 → `get_by_role('tab', name='Co-selling')` 返回 0 → 这正是 T3991 "Co-selling not found" 的真凶（浏览器实测 `name='Co‑selling'` count=1）。已改 3 处（`R_click_Co-selling`×2 + `click_coselling_tab`）。`Co-sellers` **不再是独立 tab**——开启 Co-selling 后它只是 Co‑selling 面板内的**表格列标题（TH）**；co-seller 管理 inline 在面板里。已删 2 处过时导航步（`R_click_Co-sellers` / `click_cosellers_tab`）。**下一层**：开启 Co-selling 会弹 "Customize product settings"（commission）dialog 需关；且 "Manually add co-sellers" 是 partner 侧按钮（owner +999 视图不显示）——T1742/T3991 的 Co-sellers 流程还需补 enable-toggle + dialog 处理。 | T1742, T3686_teardown, T3686_CosellerResell, T3991。✅ 第 0 层（Co-selling 文本）已修；⚠️ Co-sellers enable/dialog 流程待续。 |
| `R_click_batch_set: {role:'button', name:'Batch set commission for all products'}` | **找不到该按钮**。Commission 是 per-ticket Advanced 字段。批量入口可能移走/改名。 | **T1742 需 flow 重写**。 |
| `text=5 people` / `text=9 people`（variant 行） | venue map 的 "5/9 people" 是 storefront 端 ticket variant 标签。`General Admission` 卡片在 Selling/Event 视图都存在（3 张：01/02/无尾）。 | T2705_VerifyPartner, T2705_VerifyGuest, T2515_VerifyDisabled_WithVariant, T4955_Guest_VerifyAccessCode。⚠️ **未改**。 |
| `text=Merch` / `merch 001` | event 顶有 `+ Add merch`，但没找到 `merch 001` 命名的现成 merch；需先创建。 | T5442, T5332, T5332_VerifyGuest。⚠️ **未改**。 |
| `text=Continue` / `Yes, please` / `View post` / `Add 3/20 product(s)` / order nav timeout | storefront/guest 流相关，逐个需在新 UI 复核。 | T3683, T3811, T4735, T2874, T3767, T2830_VerifyGuest。⚠️ **未改**。 |
| `event-for-UI-auto-venue-map` 找不到（T3686_teardown, T5440） | event **存在**（/events 有 2 matches）。失败发生在**后续步骤**（tab/post card），不是事件丢失。改 tab 改名后应能推进。 | T3686_teardown, T5440。 |

---

## 3. 已做的改动（保守、最小作用域）

- `test_case/UI/Test_Katana/All_YAML/Post/Post_setting_for_venue_map.yaml`  
  → `name: "Posts"` → `name: "Post"`（29 处，`R_click_posts_tab*` 的 tab locator）。`replace_all`，`grep` 残留 0。  
- **`testT3811` 导航层修复 + 已 pytest 验证**: 删除 Step 17 `R_click_post_card: {name:'View post'}` + sleep（Post tab 现在直显文章，无 View post 按钮）。**pytest 实跑结果**: T3811 不再卡在 View post，**已推进到下一层错误** (`R_click_customize_products: {name:'Customize'}` not found) — 证明删除 View post 是正确导航修复，下游 post 视图已成功到达。
- **`testT3991_VerifyPartner` 导航层修复（未 pytest 验）**: 在 `R_click_my_event` 后插入 `R_click_posts_tab: {name:'Post'}`；line 159 `click_setting_tab_2: {role:'tab', name:'Settings'}` → `R_click_settings_card: {role:'button', name:'Settings'}`。Co-selling 现在是 Post tab 内的子 tab，不再是 event 顶层 tab。
- 删了 `_venue_probe*.py` `_probe_login.py` `_probe_customize.py`（debug 探针脚本，按项目规矩用完即删）。  
- 重捕获 cookie: `test_case/UI/Test_Katana/cookie_release{,_co_seller,_partner_coseller}.json`（system py3.9 + playwright **1.55.0** 装回 chromium-1187 + headless_shell-1187 后跑通）。  
- framework / conftest.py 未动。沙箱可重跑（见 §5 命令）。

### 2026-09-01 机械修复批次（按用户"先改简单、再逐个类似"的指令）

**本轮方法**：浏览器探针（`_probe_coselling*.py`，只读 DOM dump + 截图，未污染数据）逐一确认真实 locator，再改 YAML。

1. **Settings tab → Settings card（button）全改完**（8 处）：
   `R_click_setting_tab` / `R_click_setting_tab_teardown` / `R_click_setting_tab_2` / `R_click_setting_tab_reset` / `click_setting_tab` / `click_setting_tab_2` / `R_click_selling_tab`(misnamed, 实为 Settings) / `wait_advanced_loaded` 全部 `role:'tab',name:'Settings'` → `role:'button',name:'Settings'`。跨用例 key 唯一性已核对（testT2281 内 2134 已有 `R_click_settings_card`，故 2204 改用 `R_click_settings_card_verify`）。`grep` 残留 `tab+Settings` = 0。

2. **Co-selling 文本根因实锤 + 修复**（3 处）：
   `R_click_Co-selling`×2（`"tab",name:"Co-selling"`）→ `name:"Co‑selling"`（**U+2011**）；`click_coselling_tab`（`'tab',name:'Co-selling'`）→ `name:'Co‑selling'`。Python 校验三处 name 值 codepoint 均为 `0x2011`，YAML 仍 37 用例可解析。

3. **Co-sellers 不再是 tab → 删过时导航步**（2 处）：
   `R_click_Co-sellers`(T1742/T3686) 与 `click_cosellers_tab`(T3991) 改为 `[UI drift]` 注释。浏览器实测：开启 Co-selling 后 "Co-sellers" 仅为面板内表格列标题（TH），不可作导航 tab。

4. **探针实证的新事实**（供后续 flow 重写）：
   - Post 视图子 tab 实测 = `Content | Selling | Co‑selling | Coupons`（U+2011 仅出现在 `Co‑selling`；`Co-hosts` 仍是普通减号 U+002D，无需改）。
   - 点 `Turn on Co-selling` 开关 → 弹出 **"Customize product settings"** dialog（commission 设置，含 `Batch set commission for all products` / `Cancel` / `Save`）。旧 `R_click_batch_set` 按钮其实在**这个 dialog 里**（之前说"找不到"是因未开启 Co-selling + 未到 dialog）。
   - "Manually add co-sellers" 按钮是 **partner（+997）侧** UI；owner（+999）Co-selling 面板只显示 commission dialog + co-sellers 表格，不显示该按钮。框架 conftest 按 ENV 选 `cookie_release.json`(=+999)，**所有用例含 "_VerifyPartner" 都用 +999 cookie**，故 partner 视图靠数据/导航模拟，非换 cookie。

5. **Promotion 子 tab 合并进 Coupons 子 tab（4 处）**：浏览器实测 post 视图子 tab 仅 `Content | Selling | Co‑selling | Coupons`；点开 **Coupons** 子 tab 内含 "Promotion and Coupons" 标题 + **"Promotional announcements"** 区块（"Add multiple announcements..."）+ coupon 开关。旧 `Promotion` tab 已消失。修复：`R_click_promotion_tab`×3（T4038/T2069/T3779）+ `R_click_promotion_tab_td`（T3767）→ `R_click_coupons_tab` / `R_click_coupons_tab_td`（`role:'tab',name:'Coupons'`）。步骤注释同步更新。**pytest 实证 T4038 PASSED**（Coupons tab → Add announcements → fill ×3 → submit → Save → toast "Post promotions updated" 全跑通，announcements 后续步骤无需改）。**T2069 PASSED、T3779 PASSED**（coupon 创建流：`R_click_coupons_tab` → create coupon → auto-apply → save → toast 全跑通）。**T3767 穿过 Promotion/Coupons 层**（到 `R_click_place_order` → `wait_for_url` 才失败）——`wait_for_url: {url:"*order*"}` 下单后未等到含 "order" 的 URL，属**结账/guest 流漂移（独立层，非 Promotion）**，待 checkout flow 调查。

6. **清理**：`_probe_coselling*.py`（8 个）+ `_probe_*.py`（promo×2）+ `_probe_*.png` 按规矩用完即删。

### 2026-09-01 pytest 实证（testT3991_VerifyPartner）
定向跑单用例，日志确认 `click_coselling_tab → Clicked 'Co‑selling'` ✅ —— **旧 "Co-selling not found" 失败层已解**。下一层失败：`Manually add co-sellers` element not found。
→ 浏览器实测锁定根因：**该按钮纯 partner(+997)侧**；框架 conftest 按 ENV 选 `cookie_release.json`(=+999)，所有用例（含 "_VerifyPartner"）都跑 +999 → owner 视图 Co-selling 面板只有 `Turn on Co-selling` / commission dialog(`Batch set commission...`/`Cancel`/`Save`/`Start Customizing`)，**无 "Manually add co-sellers"**。这是角色/cookie 不匹配，非 locator 改名能解。

**待用户决策（T3991 下一层）**：
- (a) 给 partner 用例配 +997 cookie（需 framework/conftest 支持 per-test cookie 选择），或
- (b) 重写 testT3991 验证 owner 侧 co-seller 管理（若存在），或
- (c) 该用例 post-restructure 已不可达则 `skip: true` + 找产品确认。
另：开启 Co-selling 弹 "Customize product settings" commission dialog（旧 `R_click_batch_set` 按钮其实在此 dialog 内），T1742 的 Commission 批量流程改写时应优先复用此 dialog 而非另找全局入口。

---

## 4. 仍需手动重写 flow 的用例（按"剩余漂移层"分组）

**A. 仅导航漂移（Posts→Post 已改 + post card 步骤删除）— ~25 个用例**: 改名后预计多数 broken 会推进到下一层错误。需逐个**删除 post card 那一步**或改成新路径。  
- 高置信（仅删 post card）: T1742_pre, T3686_teardown, T4038, T2069_teardown, T3686_CosellerResell, T3991, T5440, T5442, T5443, T5390, T3811, T2830_VerifyPartner, T4735_VerifyPartner。  
- **建议先在 IDE 跑一次**（基线已变），用新报错定位下一步。

**B. Post Settings 路径改动（tab→card + 独立页）**: T4955_Partner, T4955_Guest_VerifyAccessCode(teardown), T2705（execute_js 找 Settings tab 需改）。  
- T4955 的 `R_click_setting_tab` → `R_click_settings_card: {role:'button', name:'Settings'}` **全局已改完（2026-09-01，8 处）**；剩跳页后的独立 settings 页 UI（access code 子流程消失）待 flow 重写。  
- **T4955 的 access code 子流程（`Set up access code` / `Enter access code` / `Confirm` / `Apply`）已消失**。要决定: (a) 改用 `isAccessRestricted` + `enablePaymentRestriction` toggle（但 access code dialog 没了 → T4955_Guest 断言"Access code required"会挂），或 (b) 标 `skip: true` + 找产品确认 access code 流程的新设计。

**C. Commission / Merch / 变体 / guest flow 重写**:  
- T1742（Batch commission 入口消失 → 改为 per-ticket Advanced Commission，或找全局 commission 入口）。  
- T5332 / T5442（merch 001 需先创建 merch 才能引用）。  
- T2705（`Select` 按钮 + variant 表 5/9 people 路径 — 创建流程）。  
- T2515_VerifyDisabled（`text=5 people` 在 storefront 端存在但 selector/精确度需校）。  
- T3683 / T3767 / T2830_VerifyGuest / T2874 / T4735（guest/storefront 流需逐个在新 UI 复刻）。

**D. 应用崩溃 / 超时**: T3686_CosellerResell（"Application crashed after step: reload_page"）和 T3767（order nav timeout）— 这两类是潜在 app 侧问题，需要 sandbox 跑 + 看崩溃截图，不只是 locator 修。

---

## 5. 复刻/重跑命令

**沙箱**（system py3.9，headless，`--output` 指 TEMP 绕 safe-delete）：
```
py -3.9 -m pytest test_case/UI/Test_Katana/test_ui.py --yaml=All_YAML/Post/Post_setting_for_venue_map.yaml -k "Txxxx" -o addopts="-vs --tb=short --screenshot=only-on-failure --video=retain-on-failure" -p no:cacheprovider --output="C:/Users/tester/AppData/Local/Temp/pw_results"
```

**IDE**: `main.py` → 自动 allure generate + report + open。

---

## 6. 证据截图

`d:/monster_test/Autotest-monster/.workbuddy/tmp_venue/`（gitignored，留作本轮参考）：
- `02_event_detail.png` — 事件 modal，Event tab 顶 tabs
- `07_post_tab.png` — Post 视图，3 个 action card (Content/Style/Settings)，tabs Content/Selling/Co-selling/Coupons
- `10_event_settings.png` — Event settings 小 modal
- `11_section_GA01.png` — General Admission 01 编辑器（Basic）
- `20_post_selling.png` — Post Selling tab 的 product 列表（3 张 General Admission 卡片）
- `23_post_settings_card.png` — **post settings 独立页**（`/post/<id>/settings`）
- `24_ga01_advanced.png` — ticket Advanced tab（Commission / Tax rate / Custom fees）
- `30_post_settings_before.png` / `31_post_settings_toggled.png` — toggle 切换前后（probe 误点了 Order confirmation note，见说明）

---

## 7. 给用户的下一步建议

1. **节奏确认（来自 T3811 pytest 实跑）**: 单改 tab 改名只是 navigation 第 0 层；每个 fail 用例至少还有 1–2 层下游 drift（post card 删除 / Settings tab→card / 缺失的 Customize / 等）。**不要批量盲改 40+ 步骤**（违反"verify before deliver"原则）。  
2. **正确节奏**: 一次改一个 test，用 pytest 跑验 → 确认推进到下一层错误 → 修下一层 → 循环。T3811 已示范这个节奏（删 View post → pytest → 发现 Customize 漂移）。  
3. 用 `git diff` 复核我已改的部分（应全部是 `name:"Posts"→"Post"` + T3811 删 View post + T3991 插入 Post tab + Settings→card，无副作用）。  
4. **决定 T4955**: access code 流程在新 UI 里**子流程消失** —— 建议 (a) 跳新 flow 试一次，或 (b) `skip: true` + 找产品确认。  
5. **T1742 Batch commission**: 决定迁移到 per-ticket Advanced Commission 还是找新全局入口。  
6. 剩余 ~18 个 broken / failed 逐个按 B/C/D 改 flow，每改一个 IDE 跑验证。
