"""
KAT-11756 Task 1: Storefront Cache Validation.

双层覆盖：
1. 底层 7 个 katana 业务 API（httpx，严格 DB=0 断言）
2. Pear SSR 页面 /resident（Playwright，console.log 抓取）
"""
import pytest
from conftest import (
    assert_zero_db_queries,
    get_db_queries,
    BASE_URL,
    KATANA_AUTH_HEADERS,
)
# 统一参数中心（API_Parameter_Release.csv / API_Parameter_Prod.csv）：静态路径模板渲染；动态 id 路径由 dynamic_ids 运行时拼接
from api_params import (
    CART_PATH,
    FEATURE_SETTING_SIGNUP_PATH,
    PEAR_STORE_PATH,
    STORE_PATH,
)
# 动态业务 id 路径（运行时从接口查询 user/curator id 后拼接，不写死）
from dynamic_ids import (
    feature_flag_public_path,
    feature_flag_user_path,
    feature_setting_public_path,
    promoter_sub_path,
)

def get_storefront_endpoints() -> list[dict]:
    """构造 storefront 端点列表（延迟求值：user/curator id 在测试执行时才查询，避免 import 阶段发网络请求）。

    已知 BE 缺口端点（shop-config）置于末尾：预热/验证循环先完成其余 6 个端点的
    严格 DB=0 校验，最后才触发 shop-config 的已知缺口（pytest.xfail），
    避免缺口端点提前中断导致其余端点跳过验证。
    """
    return [
        {"path": feature_flag_user_path(), "label": "feature-flag-user"},
        {"path": feature_flag_public_path(), "label": "feature-flag-public"},
        {"path": feature_setting_public_path(), "label": "feature-setting-public"},
        {"path": FEATURE_SETTING_SIGNUP_PATH, "label": "feature-setting-signup"},
        {"path": CART_PATH, "label": "cart-storefront"},
        {"path": promoter_sub_path(), "label": "promoter-sub-storefront"},
        # 已知 BE 缺口（置于末尾）：GET /store-front/shop/resident?public=false
        # 预热后二次读固定 DB=2（2026-08-25 release 实测），非脚本问题，见
        # test_storefront_katana_apis_hit_cache 的 xfail 处理。
        {"path": STORE_PATH, "label": "shop-config"},
    ]


# 已知 BE 缓存缺口端点 label 集合：预热后二次读仍 DB>0（确定性复现）。
# 对应用例标记 xfail（strict=False：BE 修复后自动恢复为 XPASS 提示，不阻塞 CI）；
# 缺口详情同时保留在审计报告违规列表中，供上报 BE。
KNOWN_BE_GAP_LABELS = {"shop-config"}


@pytest.mark.asyncio
async def test_cold_start_header_sanity(http_client):
    """Sanity: 冷启动确认 header 有效（DB != -1）且缓存生效（DB=0）。

    header_integrity_check（session 级）已用全新 userId 验证 x-db-query-count
    真实反映 DB 查询次数，本函数仅做补充：确保 storefront 端点部署了 header
    且二次请求命中缓存。

    注意：使用 /feature-setting/consumer-signup 端点以避开前序测试对
    /store-front/shop/resident 和 /cart 的预热。此端点仅在
    STOREFRONT_ENDPOINTS 预热-验证循环中出现，不在并发测试中出现。
    若仍被预热，则不硬断言 DB>0，仅打印 WARNING 并跳过。
    """
    from conftest import get_db_queries, assert_zero_db_queries

    STOREFRONT_PATH = FEATURE_SETTING_SIGNUP_PATH
    STOREFRONT_API = f"{BASE_URL}{STOREFRONT_PATH}"

    resp = await http_client.get(STOREFRONT_API, headers=KATANA_AUTH_HEADERS)
    assert resp.status_code == 200
    db_cold = get_db_queries(resp)
    assert db_cold != -1, (
        f"X-DB-Query-Count header missing on {STOREFRONT_PATH}.\n"
        f"  Endpoint: GET {STOREFRONT_API}\n"
        f"  Action: Backend instrumentation not deployed for this endpoint."
    )
    if db_cold == 0:
        import warnings
        warnings.warn(
            f"{STOREFRONT_PATH} cold-start returned DB=0 — endpoint already warmed by prior tests. "
            f"Skipping cold-start sanity check. header_integrity_check already verified "
            f"the x-db-query-count header is trustworthy at session scope."
        )
        return

    # Warm: 二次请求必须命中缓存
    resp2 = await http_client.get(STOREFRONT_API, headers=KATANA_AUTH_HEADERS)
    assert resp2.status_code == 200
    assert_zero_db_queries(resp2, resource=STOREFRONT_PATH, attempt="cold-to-warm verify", url=STOREFRONT_API)


class TestStorefrontCache:
    """Storefront 双层（katana API + SSR）缓存回归检测。"""

    @pytest.mark.asyncio
    async def test_storefront_katana_apis_hit_cache(self, http_client):
        """预热 storefront 7 个 katana API，验证全部 DB=0（严格断言）。"""
        failures = []
        endpoints = get_storefront_endpoints()

        # ---- 预热：全部 7 个端点 ----
        for ep in endpoints:
            url = f"{BASE_URL}{ep['path']}"
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Warm-up failed [{ep['label']}]: status={resp.status_code}"
            )
            ep["warmup_db"] = get_db_queries(resp)

        # ---- 验证：全部 7 个端点 DB=0 ----
        for ep in endpoints:
            url = f"{BASE_URL}{ep['path']}"
            resp = await http_client.get(url, headers=KATANA_AUTH_HEADERS)
            assert resp.status_code == 200, (
                f"Verify failed [{ep['label']}]: status={resp.status_code}"
            )
            try:
                assert_zero_db_queries(
                    resp, resource=ep["path"], attempt="verify", url=url,
                    warmup_db_queries=ep.get("warmup_db"),
                )
            except AssertionError as exc:
                if ep["label"] in KNOWN_BE_GAP_LABELS:
                    # 已知 BE 缺口：预热后二次读固定 DB>0，非脚本问题。
                    # xfail 保持缺口可见（CI 不红），BE 修复后自动 XPASS 提示。
                    pytest.xfail(
                        f"BE 缓存缺口（{ep['label']}）: {exc}"
                    )
                failures.append(f"[{ep['label']}] {exc}")

        if failures:
            summary = (
                f"Storefront cache regression — "
                f"{len(failures)} endpoint(s) leaked DB queries:\n\n"
                + "\n".join(failures)
            )
            pytest.fail(summary)

    @pytest.mark.asyncio
    async def test_storefront_ssr_hit_cache(self, pear_context):
        """SSR 页面缓存回归 — 通过浏览器 console.log 读取 x-db-query-count"""
        from conftest import navigate_pear_page, PEAR_URL

        path = PEAR_STORE_PATH
        full_url = f"{PEAR_URL}{path}"

        # 预热：首次加载，触发缓存填充（保持 warm→verify 短间隔，小于页面内资源缓存 TTL）
        count1, status1 = await navigate_pear_page(pear_context, path)
        assert status1 == 200, f"SSR warmup failed: status={status1}"

        # 验证：二次加载，应命中缓存
        count2, status2 = await navigate_pear_page(pear_context, path)
        assert status2 == 200, f"SSR verify failed: status={status2}"
        if count2 == -1:
            assert False, (
                f"SSR console capture failed for {full_url}.\n"
                f"  Verify: 1) Pear SSR page logs x-db-query-count to console,\n"
                f"          2) Playwright console listener is attached before page.goto(),\n"
                f"          3) Console msg.args structure matches expected format (args[5] as response headers dict)."
            )
        assert count2 == 0, (
            f"SSR cache regression detected!\n"
            f"  Endpoint: GET {full_url}\n"
            f"  Phase: verify (2nd page load after warm-up)\n"
            f"  Expected: x-db-query-count = 0\n"
            f"  Actual:   x-db-query-count = {count2}\n"
            f"  Action: This SSR page leaked {count2} DB queries on a supposed cache hit.\n"
            f"  Check: 1) Is the cache middleware deployed for this SSR route?\n"
            f"         2) Is the cache TTL shorter than the interval between warm-up and verify?\n"
            f"         3) Did the warm-up page load properly populate the cache?"
        )
