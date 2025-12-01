# Auto Test Framework v2.0 - 技术指南

## 目录
- [1. 项目架构](#1-项目架构)
- [2. 测试执行流程](#2-测试执行流程)
- [3. 核心机制](#3-核心机制)
- [4. 添加新测试用例](#4-添加新测试用例)
- [5. 扩展步骤处理器](#5-扩展步骤处理器)
- [6. 调试技巧](#6-调试技巧)
- [7. 常见问题](#7-常见问题)

---

## 1. 项目架构

### 1.1 核心组件

```
autotest-monster/
├── test_case/UI/Test_Katana/
│   ├── conftest.py              # Pytest fixture 配置 (认证、浏览器上下文)
│   ├── test_ui.py               # 测试执行引擎 (步骤处理器)
│   ├── Katana_curator_smoke.yaml # 测试用例定义 (数据驱动)
│   └── cookie_release.json      # 登录状态保存
├── page/
│   └── home.py                  # UI 操作封装层
├── tools/
│   ├── __init__.py              # 工具函数 (Allure 集成等)
│   └── update_test_status.py   # ONS 测试状态更新脚本
├── gemini-tasks/                # 调试脚本存放目录
└── main.py                      # 测试套件启动入口
```

### 1.2 数据流

```
YAML 测试定义 → conftest.py (pytest fixtures) 
              ↓
        test_ui.py (步骤解析与执行)
              ↓
        page/home.py (Playwright 操作封装)
              ↓
        浏览器自动化执行
              ↓
        Allure 报告 + 截图/录屏
```

---

## 2. 测试执行流程

### 2.1 完整流程

```bash
python main.py
```

**执行步骤:**
1. `main.py` 配置 logger、Allure 路径
2. 调用 `pytest` 执行 `test_case/UI/Test_Katana/test_ui.py`
3. `conftest.py` 创建 session-scoped 的 `browser` 和 `context` fixtures
4. `test_ui.py` 的 `test_case` 函数被参数化执行 (每个 YAML 用例一次)
5. 测试完成后,`main.py` 触发 `update_test_status.py` 更新 ONS 状态
6. 生成 Allure HTML 报告

### 2.2 单个测试用例执行

```bash
# 运行特定用例 (例如 smokecases16 = testT4279)
pytest test_case/UI/Test_Katana/test_ui.py::test_case[smokecases16-chromium] --headed -v

# 带登录状态
pytest test_case/UI/Test_Katana/test_ui.py::test_case[smokecases16-chromium] --headed -v --storage-state=test_case/UI/Test_Katana/cookie_release.json
```

---

## 3. 核心机制

### 3.1 数据驱动测试

测试用例定义在 `Katana_curator_smoke.yaml` 中,采用 YAML 格式:

```yaml
testT855:
    description: "Verify Share button functionality"
    test_step:
        open: "https://release.pear.us/yu-xiao"
        sleep_after_open: 2000
        click_button_text_share:
            text: 'Share'
        sleep_after_click_share: 2000
    expect_result:
        description: "Share dialog should appear"
        assertions:
            - assertion_type: "element_visible_by_text"
              text: "Share"
```

**字段说明:**
- `description`: 用例描述
- `test_step`: 测试步骤 (键名对应 `test_ui.py` 中的处理器)
- `expect_result`: 断言定义

### 3.2 认证管理

#### 登录状态 (默认)
`conftest.py` 的 `context` fixture 默认加载 `cookie_release.json`:

```python
@pytest.fixture(scope="session")
def context(browser, browser_context_args, pytestconfig, request):
    storage_state = pytestconfig.getoption("--storage-state")
    if storage_state:
        context = browser.new_context(storage_state=storage_state, **browser_context_args)
    else:
        context = browser.new_context(**browser_context_args)
    # ...
```

#### Guest 模式 (访客)
对于不需要登录的测试 (如联系表单),在 YAML 中添加 `guest: true`:

```yaml
testT4279:
    guest: true  # 强制使用 guest 模式,忽略全局 storage-state
    description: "Verify submitting the contact form"
    test_step:
        open: "https://release.pear.us/yu-xiao"
        # ...
```

`test_ui.py` 检测到 `guest: true` 后,会创建一个独立的 browser context:

```python
def test_case(smokecases1, page: Page, browser: Browser, request):
    val = list(smokecases1.values())[0]
    
    if val.get("guest", False):
        context = browser.new_context()  # 无 storage_state
        page = context.new_page()
        request.addfinalizer(lambda: context.close())
    # ...
```

**重要**: 这样即使在 `main.py` 中全局带 `--storage-state` 参数运行所有测试,guest 测试也能正常工作。

### 3.3 步骤处理器

`test_ui.py` 中的 `test_case` 函数遍历 `test_step` 字典,根据键名前缀匹配处理器:

```python
for k, v in test_step.items():
    if k.startswith("open"):
        page.goto(v)
    elif k.startswith("sleep"):
        page.wait_for_timeout(v)
    elif k.startswith("R_click"):
        page_element_role_click(page, v["role"], v["name"])
    elif k.startswith("fill"):
        if "role" in v:
            page_element_input_role_fill(page, v["role"], v["name"], v["value"])
        elif "name" in v:
            page.locator(f'input[name="{v["name"]}"], textarea[name="{v["name"]}"]').fill(v["value"])
    # ... 更多处理器
```

**键名约定:**
- 键名前缀决定使用哪个处理器 (例如 `R_click_submit` 匹配 `startswith("R_click")`)
- 后缀 (如 `_submit`) 仅用于可读性,不影响逻辑
- 数字后缀 (如 `click1`, `click2`) 用于同一步骤类型的多次调用

---

## 4. 添加新测试用例

### 4.1 准备工作

1. **录制操作**: 使用 `playwright codegen` 录制测试步骤
   ```bash
   playwright codegen https://release.pear.us/yu-xiao --save-storage=test_case/UI/Test_Katana/cookie_release.json
   ```
   
2. **保存录制**: 将生成的代码保存到 `recordings/T{用例编号}.txt`

3. **提取定位器**: 从录制代码中提取关键的元素定位器 (role, name, selector 等)

### 4.2 编写 YAML 定义

在 `Katana_curator_smoke.yaml` 中添加新用例:

```yaml
testT{编号}:
    description: "测试用例描述"
    test_step:
        open: "https://release.pear.us/your-page"
        sleep_after_open: 2000
        
        # 点击按钮 (通过 role + name)
        R_click_button:
            role: "button"
            name: "Submit"
        
        # 填充文本框 (通过 role + name)
        fill_email:
            role: "textbox"
            name: "Enter your email"
            value: "test@example.com"
        
        # 填充文本框 (通过 name 属性)
        fill_note:
            name: "Note"
            value: "Test message"
        
        # 点击文本元素
        click_text_link:
            text: "Create a Post"
        
        sleep_after_submit: 2000
    
    expect_result:
        description: "期望页面显示成功消息"
        assertions:
            - assertion_type: "element_visible_by_text"
              text: "Success"
```

### 4.3 常用步骤示例

| 操作 | YAML 示例 | 说明 |
|------|----------|------|
| 打开页面 | `open: "https://example.com"` | 导航到 URL |
| 等待 | `sleep_after_open: 2000` | 毫秒为单位 |
| 点击按钮 | `R_click_submit: {role: "button", name: "Submit"}` | 通过 role + name |
| 点击文本 | `click_text_link: {text: "Link text"}` | 通过文本内容 |
| 点击按钮(文本) | `click_button_text_share: {text: "Share"}` | 通过 button 文本 |
| 填充输入框 | `fill_email: {role: "textbox", name: "Email", value: "test@example.com"}` | 通过 role + name |
| 填充输入框 | `fill_note: {name: "Note", value: "message"}` | 通过 name 属性 |
| 填充输入框 | `fill_placeholder_title: {placeholder: "Title", value: "My Title"}` | 通过 placeholder |
| 上传文件 | `upload_file: {text: "Upload", file_path: "path/to/file.jpg"}` | 点击上传按钮并选择文件 |
| 关闭弹窗 | `click_modal_close: {}` | 关闭模态框 |
| 滚动页面 | `swipe: {x: 0, y: 500}` | 滚动坐标 |

### 4.4 断言示例

```yaml
expect_result:
    description: "验证结果"
    assertions:
        # 验证文本可见
        - assertion_type: "element_visible_by_text"
          text: "Success message"
        
        # 验证元素文本
        - assertion_type: "element_text"
          role: "heading"
          value: "Expected heading"
        
        # 验证元素可见性
        - assertion_type: "element_visible"
          role: "button"
          visible: true
```

---

## 5. 扩展步骤处理器

### 5.1 添加新的步骤类型

如果现有的步骤处理器无法满足需求,在 `test_ui.py` 的 `test_case` 函数中添加新的 `elif` 分支:

```python
# 在 test_ui.py 的步骤处理循环中添加
elif k.startswith("your_new_action"):
    # 实现你的逻辑
    element = page.locator(v["selector"])
    element.hover()  # 示例:悬停
    logger.info(f"Hovered over {v['selector']}")
```

### 5.2 示例:添加双击处理器

```python
elif k.startswith("double_click"):
    if "role" in v:
        page.get_by_role(v["role"], name=v.get("name")).dblclick()
    elif "selector" in v:
        page.locator(v["selector"]).dblclick()
    logger.info(f"Double clicked {v}")
```

对应的 YAML:
```yaml
double_click_item:
    role: "button"
    name: "Edit"
```

### 5.3 添加自定义断言

在 `expect_result` 处理部分添加新的断言类型:

```python
elif assertion_type == "url_contains":
    expected_url_part = assertion.get("url_part")
    assert expected_url_part in page.url, f"URL does not contain '{expected_url_part}'"
```

YAML 使用:
```yaml
expect_result:
    assertions:
        - assertion_type: "url_contains"
          url_part: "/success"
```

---

## 6. 调试技巧

### 6.1 使用调试脚本

在 `gemini-tasks/` 目录下创建独立的调试脚本来验证定位器:

```python
# gemini-tasks/debug_my_feature.py
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    
    # 使用登录状态
    context = browser.new_context(
        storage_state="../test_case/UI/Test_Katana/cookie_release.json",
        **p.devices['iPhone 12 Pro']
    )
    page = context.new_page()
    
    page.goto("https://release.pear.us/your-page")
    page.wait_for_timeout(2000)
    
    # 测试定位器
    element = page.locator("your-selector")
    print(f"Found {element.count()} elements")
    print(f"Is visible: {element.is_visible()}")
    
    input("Press Enter to close...")
    context.close()
    browser.close()
```

运行:
```bash
python gemini-tasks/debug_my_feature.py
```

### 6.2 查看元素属性

```python
# 获取元素的所有可用 roles
all_buttons = page.get_by_role("button").all()
for i, btn in enumerate(all_buttons):
    print(f"[{i}] {btn.inner_text()}")

# 检查元素是否可见
element = page.locator("div.my-class")
print(f"Visible: {element.is_visible()}")
print(f"Count: {element.count()}")
```

### 6.3 截图调试

在 YAML 中添加截图步骤:

```yaml
test_step:
    open: "https://example.com"
    screenshot_before_click:
        name: "before_action.png"
    R_click_button:
        role: "button"
        name: "Submit"
    screenshot_after_click:
        name: "after_action.png"
```

对应的处理器 (在 `test_ui.py` 中):
```python
elif k.startswith("screenshot"):
    screenshot_name = v.get("name", "screenshot.png")
    page.screenshot(path=f"test-result/{screenshot_name}")
```

### 6.4 Headed 模式运行

```bash
pytest test_case/UI/Test_Katana/test_ui.py::test_case[smokecases16-chromium] --headed -v
```

这会显示浏览器窗口,方便观察执行过程。

---

## 7. 常见问题

### 7.1 元素定位失败

**问题**: `TimeoutError: Locator.click: Timeout 90000ms exceeded`

**原因**:
- 元素尚未加载
- 定位器错误
- 元素被其他元素遮挡

**解决方案**:
1. 增加等待时间: `sleep_after_open: 3000`
2. 使用更稳定的定位器 (优先使用 `role` + `name`)
3. 检查元素是否在 iframe 中
4. 使用 `scroll_into_view_if_needed()` (需要在处理器中实现)

### 7.2 Guest 模式与登录模式混淆

**问题**: Guest 测试在全局登录状态下失败

**解决方案**:
确保在 YAML 中添加 `guest: true`:
```yaml
testT4279:
    guest: true
    description: "..."
```

### 7.3 动态内容加载

**问题**: 元素在初次尝试时不存在

**解决方案**:
1. 使用 `wait_for_selector` (需要在处理器中实现)
2. 增加 `sleep` 时间
3. 等待特定的网络请求完成 (需要自定义处理器)

### 7.4 弹窗处理

**问题**: 弹窗阻挡后续操作

**解决方案**:
在步骤中添加关闭弹窗步骤:
```yaml
test_step:
    open: "https://example.com"
    click_modal_close: {}  # 关闭弹窗
    # 继续后续操作
```

### 7.5 文件上传

**问题**: 如何上传文件

**解决方案**:
使用 `upload` 步骤 (在 `test_ui.py` 中已实现):
```yaml
upload_file:
    text: "Upload"  # 触发文件选择器的元素文本
    file_path: "data/test_image.jpg"  # 相对于项目根目录
```

---

## 附录: 快速参考

### Playwright 常用定位器

| 方法 | 示例 | 说明 |
|------|------|------|
| `get_by_role` | `page.get_by_role("button", name="Submit")` | 推荐,基于语义 |
| `get_by_text` | `page.get_by_text("Click me")` | 通过文本内容 |
| `get_by_placeholder` | `page.get_by_placeholder("Enter email")` | 通过 placeholder |
| `locator` | `page.locator("button.submit")` | CSS/XPath 选择器 |
| `get_by_label` | `page.get_by_label("Email:")` | 通过 label 文本 |

### 步骤键名前缀速查

| 前缀 | 用途 | 示例 |
|------|------|------|
| `open` | 打开 URL | `open: "https://..."` |
| `sleep` | 等待 | `sleep_after_open: 2000` |
| `R_click` | 点击 (role) | `R_click_submit: {role: "button", name: "Submit"}` |
| `click_text` | 点击文本 | `click_text_link: {text: "Link"}` |
| `click_button_text` | 点击按钮(文本) | `click_button_text_share: {text: "Share"}` |
| `click_modal_close` | 关闭弹窗 | `click_modal_close: {}` |
| `fill` | 填充输入框 | `fill_email: {role: "textbox", ...}` |
| `fill_placeholder` | 填充(placeholder) | `fill_placeholder_title: {placeholder: "Title", ...}` |
| `upload` | 上传文件 | `upload_file: {text: "Upload", file_path: "..."}` |
| `swipe` | 滚动页面 | `swipe: {x: 0, y: 500}` |
| `check` | 勾选复选框 | `check_agree: {role: "checkbox", name: "I agree"}` |

---

## 联系与支持

如有问题,请参考:
- [Playwright 官方文档](https://playwright.dev/python/)
- [Pytest 官方文档](https://docs.pytest.org/)
- [README.md](./README.md) - 使用文档
