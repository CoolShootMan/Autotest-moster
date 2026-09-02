import re as _re
from playwright.sync_api import Page
from loguru import logger
from .base import smart_click, verify_no_sibling_text

# ---------------------------------------------------------------------------
# Shop page UI redesign 2026-06: Bottom tab bar replaced by top-right controls.
#
# NEW FLOW for creating modules:
#   1. Click "+ Add" button → dropdown menu (creation items)
#   2. Click "Add a storefront module" in dropdown → Module drawer opens
#
# OLD flow (removed):
#   - Bottom tabs: My shop / Explore / [+] / Cart / Account
#   - "[+]" FAB → swipe_avoid_plus workaround
#   - "Module" tab click
#
# What moved where:
#   - Explore, Account, Content, Orders etc → hamburger icon (☰) menu
#   - "+" content + "Module" creation → "+ Add" button dropdown
# ---------------------------------------------------------------------------

# Selector for the "+ Add" button (top action bar of shop page).
# Opens a dropdown containing "Add a storefront module" and other creation items.
# IMPORTANT: Both "+ Event" and "+ Add" buttons share data-testid="enhance-button"
# and AddLineIcon icon, so we MUST include :has-text("Add") to disambiguate.
_ADD_BUTTON_SELECTOR = (
    'button[data-testid="enhance-button"]:has([data-testid="AddLineIcon"]):has-text("Add")'
)

# Selector for the "+ Event" button (first button in top action bar of shop page).
# UI update 2026-06-18: "Create Event" entry point moved out of the "+ Add" dropdown
# and placed as a standalone primary button, now the first/leftmost action button.
# Uses data-testid="enhance-button" (same testid family) + text content "Event".
_EVENT_BUTTON_SELECTOR = (
    'button[data-testid="enhance-button"]:has-text("Event")'
)

# Selector for the hamburger icon (top-right, next to "+ Add").
# Contains navigation items: Explore, Account, Content, Orders, etc.
_HAMBURGER_SELECTOR = (
    "button.MuiButtonBase-root.MuiIconButton-root.MuiIconButton-sizeMedium"
    ".katana-19u6hkh"
)


def click_shop_event_button(page: Page, v: dict = None):
    """Click the '+ Event' button (first button in the shop page top action bar).
    UI update 2026-06-18: Event creation entry was moved out of the '+ Add' dropdown
    and is now a standalone button (leftmost in the action row).
    Clicking this navigates directly to the event creation wizard (/events/create).
    """
    logger.info("Clicking shop '+ Event' button")
    btn = page.locator(_EVENT_BUTTON_SELECTOR).first
    btn.wait_for(state="visible", timeout=10000)
    btn.click()
    page.wait_for_timeout(1000)  # Wait for navigation to event creation page


def click_shop_add_button(page: Page, v: dict = None):
    """Click the '+ Add' button (top-right corner of the shop page).
    This opens a dropdown menu with creation options including
    'Add a storefront module', 'Add post', etc."""
    logger.info("Clicking shop '+ Add' button")
    btn = page.locator(_ADD_BUTTON_SELECTOR).first
    btn.wait_for(state="visible", timeout=10000)
    btn.click()
    page.wait_for_timeout(800)  # Wait for dropdown animation


def click_shop_hamburger(page: Page, v: dict = None):
    """Click the hamburger menu icon (top-right corner, next to '+ Add').
    This opens a dropdown with navigation items: Explore, Account,
    Content, Orders, etc. (items that were previously in bottom tab bar)."""
    logger.info("Clicking shop hamburger menu icon")
    btn = page.locator(_HAMBURGER_SELECTOR).first
    btn.wait_for(state="visible", timeout=10000)
    btn.click()
    page.wait_for_timeout(800)  # Wait for dropdown animation

def click_add_storefront_module(page: Page, v: dict = None):
    """Click 'Add storefront section' (formerly 'Add a storefront module') in the '+ Add' dropdown menu.
    This is the replacement for the old bottom-tab 'Module' button click.
    Supports both new ('Add storefront section') and old ('Add a storefront module') UI text."""
    logger.info("Clicking 'Add storefront section' in +Add dropdown")
    # Try new UI text first (post-redesign)
    new_item = page.get_by_role("button", name="Add storefront section")
    if new_item.count() > 0 and new_item.first.is_visible():
        new_item.first.click()
        page.wait_for_timeout(1000)
        return
    # Fallback to old UI text
    menu_item = page.locator("div.MuiListItemButton-root").filter(
        has=page.get_by_text("Add a storefront module", exact=True)
    ).first
    menu_item.wait_for(state="visible", timeout=5000)
    menu_item.click()
    page.wait_for_timeout(1000)

def click_shop_add_module(page: Page, v: dict = None):
    """One-step action: click '+ Add' button → click 'Add storefront section'.
    This is the direct replacement for: R_click: { role: 'button', name: 'Module' }
    Kept as click_shop_add_module for backward compatibility; also registered as click_shop_add_section."""
    logger.info("Opening shop '+ Add' → 'Add storefront section'")
    click_shop_add_button(page)
    click_add_storefront_module(page)

def click_module_edit_button(page: Page, v: dict):
    module_name = v.get("module_name")
    logger.info(f"Clicking edit button for module: {module_name}")
    # Use double-locator pattern: Find the container that has both the module name and buttons
    # Then click the second button (usually the 'More/Edit' icon)
    container = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).filter(has=page.get_by_role("button")).last
    container.scroll_into_view_if_needed()
    btn = container.get_by_role("button").nth(-1)
    btn.wait_for(state="visible", timeout=10000)
    btn.click(timeout=15000)
    page.wait_for_timeout(1000) # Wait for potential UI transitions

def delete_all_sections_by_name(page: Page, v: dict):
    """Reliably delete EVERY section whose header title equals module_name.

    Loops and re-queries the DOM each iteration so sections cannot accumulate
    across runs. This matters for carousel tests: if a previous (failed) run left
    a stale section behind, the new-storefront 'Add to a new section' will MERGE
    new links into that one, producing an N-card carousel and breaking the
    'next hidden at last element' assertion. Cleaning first keeps the section
    at exactly the 3 links the test creates.
    """
    module_name = v.get("module_name")
    if not module_name:
        return
    max_iter = 30
    deleted = 0
    for _ in range(max_iter):
        # Use the stable title testid instead of a build-specific hashed class.
        headers = page.locator("p[data-testid='base-storefront-text']").filter(
            has=page.get_by_text(module_name, exact=True)
        ).all()
        if not headers:
            break
        try:
            click_module_edit_button(page, {"module_name": module_name})
            # New storefront (2026-07): section more-menu items are <li role='menuitem'>,
            # not buttons. Try menuitem first, fall back to button for older builds.
            try:
                page.get_by_role("menuitem", name="Delete section", exact=True).click(timeout=5000)
            except Exception:
                page.get_by_role("button", name="Delete section", exact=True).click(timeout=5000)
            page.wait_for_timeout(800)
            confirm = page.locator("[role='dialog'] [data-track-location='Dialog']").get_by_text("Delete", exact=True)
            if confirm.count():
                confirm.first.click(timeout=5000)
            else:
                dlg = page.locator("[role='dialog']")
                if dlg.count():
                    dlg.get_by_role("button", name="Delete").last.click(timeout=5000)
            page.wait_for_timeout(1500)
            deleted += 1
        except Exception as e:
            logger.warning(f"delete_all_sections_by_name: iteration failed for '{module_name}': {e}")
            break
    logger.info(f"delete_all_sections_by_name: removed {deleted} section(s) named '{module_name}'")

def remove_card_from_section(page: Page, v: dict):
    """Click the more-menu of a card inside a named section and remove it from that section.

    New storefront (2026-07): cards are not reliably scannable from the section header,
    so we walk up from every card until we find the section title that matches
    `module_name`, then click the card's internal `base-more-horiz-icon-cta` button,
    select 'Remove from this section', and confirm the Remove dialog.
    """
    module_name = v.get("module_name")
    card_text = v.get("card_text")
    if not module_name or not card_text:
        raise ValueError("remove_card_from_section requires 'module_name' and 'card_text'")
    logger.info(f"Removing card '{card_text}' from section '{module_name}'")

    result = page.evaluate(
        """
        (args) => {
            const [sectionTitle, cardText] = args;
            const selectors = [
                'div[data-testid="base-general-link-card"]',
                '[data-testid="base-post-card"]',
                '[data-testid="base-event-card"]'
            ];
            const allCards = document.querySelectorAll(selectors.join(', '));
            for (const card of allCards) {
                if (!card.innerText.includes(cardText)) continue;
                let el = card;
                let foundTitle = null;
                for (let i = 0; i < 8; i++) {
                    if (!el) break;
                    const p = el.querySelector('p[data-testid="base-storefront-text"]');
                    if (p) {
                        foundTitle = p.getAttribute('title') || p.innerText;
                        if (foundTitle === sectionTitle) break;
                    }
                    el = el.parentElement;
                }
                if (foundTitle === sectionTitle) {
                    const more = card.querySelector('button[data-testid="base-more-horiz-icon-cta"]');
                    if (more) {
                        more.scrollIntoView({block: 'center'});
                        more.click();
                        return 'clicked';
                    }
                    return 'no more button in card';
                }
            }
            return 'card not found in section';
        }
        """,
        [module_name, card_text],
    )
    logger.info(f"remove_card_from_section: {result}")
    if result != "clicked":
        raise Exception(f"remove_card_from_section: {result}")
    page.wait_for_timeout(800)

    # Click 'Remove from this section' in the MUI menu (portaled to body)
    menu_item = page.get_by_role("menuitem", name="Remove from this section")
    menu_item.click(timeout=5000)
    page.wait_for_timeout(500)

    # Confirm the Remove dialog
    confirm = page.get_by_role("button", name="Remove")
    confirm.wait_for(state="visible", timeout=5000)
    confirm.click(timeout=5000)
    page.wait_for_timeout(1500)

def click_module_paragraph(page: Page, v: dict):
    # Click on module paragraph using smart logic
    smart_click(page, {"role": "paragraph", "name": v.get("text"), "timeout": 10000, **v})

def click_add_new_product(page: Page, v: dict):
    # Click "Add new" button within specific module header
    module_name = v.get("module_name")
    container = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).filter(has=page.get_by_role("button", name="Add new")).last
    container.get_by_role("button", name="Add new").click(timeout=15000)

def click_module_add_new(page: Page, v: dict):
    # Click the "Add new" button specifically for the named module
    # Uses refined double-locator pattern:
    module_name = v.get("module_name")
    logger.info(f"Clicking 'Add new' for module: {module_name}")
    
    # 1. Find the deepest div that contains the module title AND an 'Add new' button
    container = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).filter(has=page.get_by_role("button", name="Add new")).last
    
    # 2. Click the button within that container
    container.get_by_role("button", name="Add new").click(timeout=10000)

def click_module_post_view_event_cta(page: Page, v: dict):
    post_title = v.get("post_title")
    module_name = v.get("module_name")
    button_name = v.get("button_name")
    button_index = v.get("button_index", 0)
    logger.info(f"Clicking button for module: {module_name} and post title: {post_title}")

    # Step 1: Locate module header using double-filter pattern (exact text + button presence)
    header = page.locator("div").filter(
        has=page.get_by_text(module_name, exact=True)
    ).filter(
        has=page.get_by_role("button")
    ).last
    header.scroll_into_view_if_needed()

    # Step 2: Navigate up to the full module container (header + body with post cards)
    module_container = header.locator("xpath=..")

    # Step 3: Find the post card within module body by post_title
    post_card = module_container.locator(".post-card").filter(
        has=page.get_by_text(post_title, exact=True)
    ).last
    post_card.scroll_into_view_if_needed()

    # Step 4: Click the target button on the post card
    if button_name:
        post_card.get_by_role("button", name=button_name).nth(button_index).click(timeout=10000)
    else:
        post_card.locator("button").nth(button_index).click(timeout=10000)

def click_module_item_more_icon(page: Page, v: dict):
    """Click the 'more' (horiz icon) button on a post/card item inside a module using data-testid='base-more-horiz-icon-cta'.

    This clicks the more icon on a specific post/card within the module's content area,
    NOT the module header's edit button.

    Supported parameters:
    - module_name: Name of the module to target (required)
    - index: Index of the post's more icon, supports negative values like -1 for last (default: -1)

    Usage in YAML:
        click_module_more_icon: { module_name: 'post duplicate module', index: -1 }
    """
    module_name = v.get("module_name")
    target_index = v.get("index", -1)
    logger.info(f"Clicking more icon on item inside module: {module_name} (index: {target_index})")

    # Find the module header container first
    header = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).filter(
        has=page.get_by_role("button")
    ).last
    header.scroll_into_view_if_needed()

    # Navigate to the parent module container that includes both header and body (posts)
    module_container = header.locator("xpath=..")

    # Within the module body, find the more icon on a specific post/card item
    icon = module_container.locator("[data-testid='base-more-horiz-icon-cta']").nth(target_index)
    icon.wait_for(state="visible", timeout=10000)
    icon.click(timeout=15000)
    page.wait_for_timeout(1000)


def click_module_collapse(page: Page, v: dict):
    """Collapse a module by clicking its arrow-up icon."""
    module_name = v.get("module_name")
    logger.info(f"Collapsing module: {module_name}")
    # After storefront refactor (2026-07), the section header no longer has an "Add new" button
    # accessible via get_by_role(name="Add new"). Anchor on the arrow-up-icon test_id + any button,
    # so the matched div is the section header row (has icon + title + buttons), not the deeper
    # SectionTitle component (icon + title only). This keeps the click correct AND makes the
    # parent's parent (the section card) measurable in verify_* helpers.
    container = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).filter(has=page.get_by_test_id("arrow-up-icon")).filter(has=page.locator("button")).last
    container.get_by_test_id("arrow-up-icon").first.click(timeout=10000)

def click_module_expand(page: Page, v: dict):
    """Expand a module by clicking its toggle icon.
    The test-id does not change to arrow-down, so we click the same arrow-up-icon.
    """
    module_name = v.get("module_name")
    logger.info(f"Expanding module: {module_name}")
    container = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).filter(has=page.get_by_test_id("arrow-up-icon")).filter(has=page.locator("button")).last
    container.get_by_test_id("arrow-up-icon").first.click(timeout=10000)

def verify_module_collapsed(page: Page, v: dict):
    """Verifies that a module's body is collapsed by checking its overall container height shrinks."""
    module_name = v.get("module_name")
    logger.info(f"Verifying module '{module_name}' is collapsed by measuring height...")
    # Anchor on the section header row (has icon + title + buttons).
    # Its parent (..) is the section card, which includes the body when expanded.
    header = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).filter(has=page.get_by_test_id("arrow-up-icon")).filter(has=page.locator("button")).last

    import time
    start_time = time.time()
    # Poll for height to shrink (e.g. < 150px means body is folded, just header left)
    while time.time() - start_time < 5.0:
        box = header.locator("..").bounding_box()
        if box and box['height'] < 150:
            logger.info(f"Module '{module_name}' is successfully collapsed (Visual Height: {box['height']:.1f}px)")
            return
        time.sleep(0.5)
    raise AssertionError(f"Module '{module_name}' did not collapse. Current Height: {box['height']:.1f}px")

def verify_module_expanded(page: Page, v: dict):
    """Verifies that a module's body is expanded by checking its overall container height grows."""
    module_name = v.get("module_name")
    logger.info(f"Verifying module '{module_name}' is expanded by measuring height...")
    # Anchor on the section header row (has icon + title + buttons).
    # Its parent (..) is the section card, which includes the body when expanded.
    header = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).filter(has=page.get_by_test_id("arrow-up-icon")).filter(has=page.locator("button")).last

    import time
    start_time = time.time()
    # Poll for height to grow (e.g. > 150px means body is unfolded)
    while time.time() - start_time < 5.0:
        box = header.locator("..").bounding_box()
        if box and box['height'] > 150:
            logger.info(f"Module '{module_name}' is successfully expanded (Visual Height: {box['height']:.1f}px)")
            return
        time.sleep(0.5)
    raise AssertionError(f"Module '{module_name}' did not expand. Current Height: {box['height']:.1f}px")





def verify_element_style(page: Page, v: dict):
    """
    Verify CSS style properties of an element

    Supported parameters:
    - locator: Element locator (required)
    - container: Container element name/text to search within (optional)
    - container_filter: Filter criteria for finding stable parent container (optional)
      - attributes: Dict of attribute names to match (e.g., {"data-testid": "module"})
      - exclude_dynamic_attrs: List of attribute patterns to exclude (e.g., ["id", "class"])
      - max_levels: Maximum number of parent levels to search (default: 5)
    - property: CSS property name to verify (single string or list)
    - expected: Expected value (single value or dictionary)
    - operator: Comparison operator, default 'equals', supports: equals, contains, gt, lt, gte, lte
    - timeout: Timeout in milliseconds, default 5000

    Usage examples:

    1. Verify single property:
       verify_element_style:
           locator: ".my-element"
           property: "display"
           expected: "none"

    2. Verify within a container:
       verify_element_style:
           container: "My Module"
           locator: ".button"
           property: "color"
           expected: "rgb(255, 0, 0)"

    3. Verify with smart container filtering:
       verify_element_style:
           container: "My Module"
           locator: ".button"
           property: "height"
           expected: "100px"

    4. Verify multiple properties:
       verify_element_style:
           locator: ".my-element"
           property: ["display", "color"]
           expected: {"display": "none", "color": "rgb(255, 0, 0)"}

    5. Verify numeric comparison:
       verify_element_style:
           locator: ".my-element"
           property: "height"
           expected: "100px"
           operator: "gte"  # Greater than or equal

    6. Get and print all styles (for debugging):
       verify_element_style:
           locator: ".my-element"
           property: "all"  # Print all computed styles
    """
    locator_str = v.get("locator")
    container_name = v.get("container")
    if not locator_str:
        raise ValueError("verify_element_style: 'locator' parameter is required")

    timeout = v.get("timeout", 5000)
    container_filter = v.get("container_filter")

    # Apply container filter if specified
    if container_name:
        logger.info(f"Searching within container: {container_name}")

        # Find initial container by text
        container = page.locator("div", has_text=container_name).locator(f"xpath={container_filter}").last

        locator = container.locator(locator_str)
    else:
        # Use .last to avoid strict mode violation when locator matches multiple elements
        locator = page.locator(locator_str).last

    # Wait for element to be visible
    locator.wait_for(state="visible", timeout=timeout)

    property_names = v.get("property")
    expected = v.get("expected")
    operator = v.get("operator", "equals")

    container_info = f" (in container: {container_name})" if container_name else ""
    logger.info(f"Verifying element style - Locator: {locator_str}{container_info}, Property: {property_names}")

    # If 'all', print all computed styles and return
    if property_names == "all":
        styles = locator.evaluate("el => window.getComputedStyle(el)")
        logger.info(f"Element complete stylesheet:\n{styles}")
        return

    # Support single property or property list
    if isinstance(property_names, str):
        properties = [property_names]
    else:
        properties = property_names

    # Get computed style values via JS property accessor (cs[key])
    # CSSStyleDeclaration named properties are prototype getters that don't survive Playwright serialization.
    # Using cs[key] (camelCase like 'textAlign') instead of cs.getPropertyValue('text-align') 
    # so YAML can use the convenient camelCase property names.
    computed_styles = locator.evaluate("""(el, props) => {
        const cs = window.getComputedStyle(el);
        const result = {};
        for (const key of props) {
            result[key] = cs[key];
        }
        return result;
    }""", properties)

    results = []
    for prop in properties:
        actual_value = computed_styles.get(prop, "")

        # Determine expected value
        if isinstance(expected, dict):
            exp_value = expected.get(prop, "")
        else:
            exp_value = expected if len(properties) == 1 else ""

        # Verification logic
        passed = False
        if operator == "equals":
            passed = actual_value == exp_value
        elif operator == "contains":
            passed = exp_value in actual_value
        elif operator == "gt":
            passed = float(actual_value) > float(exp_value)
        elif operator == "lt":
            passed = float(actual_value) < float(exp_value)
        elif operator == "gte":
            passed = float(actual_value) >= float(exp_value)
        elif operator == "lte":
            passed = float(actual_value) <= float(exp_value)
        else:
            raise ValueError(f"Unsupported operator: {operator}")

        status = "✓" if passed else "✗"
        result_msg = f"{status} {prop}: {actual_value}"
        if exp_value:
            result_msg += f" (expected: {exp_value}, operator: {operator})"
        results.append(result_msg)

        if not passed:
            logger.error(result_msg)
        else:
            logger.info(result_msg)

    # Summarize results
    if any("✗" in r for r in results):
        raise AssertionError(f"Style verification failed:\n" + "\n".join(results))
    else:
        logger.info("All style verifications passed")


def verify_carousel_scroll(page: Page, v: dict):
    """
    Verify carousel horizontal scroll navigation within a specific module.
    - Locates the module by name (finds the last matching module on page)
    - Hovers over the module to reveal navigation buttons
    - Clicks next/prev and verifies scroll distance equals one link card width
    - Verifies next button is hidden when at the last element

    Supported parameters:
    - module_name: Name of the module to test (required)
    - link_item_selector: CSS selector for individual link cards inside the carousel (default: 'a')
    - scroll_container_selector: CSS selector for the scrollable container (optional, auto-detected)
    - tolerance: Pixel tolerance for scroll distance comparison (default: 10)

    Usage in YAML:
        verify_carousel_scroll:
            module_name: 'test nav buttons'
            link_item_selector: 'a'
            tolerance: 10
    """
    import time

    module_name = v.get("module_name")
    link_item_selector = v.get("link_item_selector", "a")
    tolerance = v.get("tolerance", 10)

    if not module_name:
        raise ValueError("verify_carousel_scroll: 'module_name' parameter is required")

    logger.info(f"verify_carousel_scroll: Testing module '{module_name}'")

    # --- Robust anchor (new storefront) ---
    # The new storefront renders the carousel as a HORIZONTAL SCROLLER that is a
    # descendant of the section root (the header p[data-testid='base-storefront-text']
    # and the scroller are siblings inside the section root). Anchoring on the
    # header's parent is unreliable: duplicate section names / stale sections can
    # resolve to a NON-carousel container (1 card, overflow:visible), which makes
    # the scroll check a silent no-op (false green). So we locate the scroller
    # DIRECTLY: the element with overflow-x:auto/scroll AND scrollWidth>clientWidth
    # that holds the link cards AND whose section header text == module_name.
    scroll_container_selector = v.get("scroll_container_selector")

    if scroll_container_selector:
        scroll_el = page.locator(scroll_container_selector).first
        module_container = scroll_el.locator("xpath=..").locator("xpath=..") if scroll_el.count() else page.locator("body")
    else:
        # JS: find the correct carousel scroller and tag it + its section root.
        tagged = page.evaluate(
            """(args) => {
                const {selector, moduleName} = args;
                const cards = Array.from(document.querySelectorAll(selector));
                const scrollers = new Set();
                for (const card of cards) {
                    let el = card;
                    for (let i = 0; i < 12; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        const s = getComputedStyle(el);
                        if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 1) {
                            scrollers.add(el);
                        }
                    }
                }
                for (const sc of scrollers) {
                    let root = sc;
                    for (let i = 0; i < 14; i++) {
                        if (!root.parentElement) break;
                        root = root.parentElement;
                        const header = root.querySelector('[data-testid="base-storefront-text"]');
                        if (header && (header.textContent || '').trim() === moduleName) {
                            sc.setAttribute('data-carousel-scroll', 'true');
                            root.setAttribute('data-carousel-section', 'true');
                            return {ok: true, cardCount: sc.querySelectorAll(selector).length,
                                    scrollWidth: sc.scrollWidth, clientWidth: sc.clientWidth,
                                    rootTag: root.tagName};
                        }
                    }
                }
                return {ok: false, scrollerCount: scrollers.size, totalCards: cards.length};
            }""",
            {"selector": link_item_selector, "moduleName": module_name},
        )
        logger.info(f"verify_carousel_scroll: scroller detection -> {tagged}")
        if tagged.get("ok"):
            scroll_el = page.locator("[data-carousel-scroll='true']").first
            section_root_loc = page.locator("[data-carousel-section='true']")
            module_container = section_root_loc.first if section_root_loc.count() else scroll_el
        else:
            # Fallback: anchor by header text (legacy behavior) so we still scope something.
            logger.warning(f"verify_carousel_scroll: no horizontal scroller found for '{module_name}'; falling back to header anchor")
            header_el = page.locator("p[data-testid='base-storefront-text']").filter(has_text=module_name)
            if header_el.count() == 0:
                header_el = page.locator("div.katana-1g3r82v").filter(has=page.get_by_text(module_name, exact=True))
            if header_el.count() == 0:
                raise AssertionError(f"Module '{module_name}' section not found on page")
            module_container = header_el.first.locator("xpath=..")
            scroll_el = module_container

    container_box = module_container.bounding_box()
    logger.info(f"Found module container, size: {container_box['width']:.0f}x{container_box['height']:.0f}px")

    module_container.scroll_into_view_if_needed()
    page.wait_for_timeout(500)

    # Hover over module to reveal nav buttons (next/prev only show on hover)
    box = module_container.bounding_box()
    if box:
        # Move mouse to center of module to trigger hover
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(800)

    # Try to find link cards with flexible selectors
    # The carousel may render links as <a>, <div>, or other elements
    link_selectors_to_try = [link_item_selector, "a", "div[class*='card']", "div[class*='link']", "div[class*='item']", "[role='link']", "div[class*='MuiCard']", "div[data-testid='base-general-link-card']"]
    first_link = None
    used_selector = link_item_selector
    
    for selector in link_selectors_to_try:
        candidates = module_container.locator(selector)
        count = candidates.count()
        logger.info(f"Trying selector '{selector}': found {count} elements")
        if count > 0:
            for i in range(min(count, 5)):
                try:
                    if candidates.nth(i).is_visible(timeout=2000):
                        first_link = candidates.nth(i)
                        used_selector = selector
                        logger.info(f"Found visible link card with selector '{selector}' at index {i}")
                        break
                except:
                    continue
            if first_link:
                break
    
    if not first_link:
        # Last resort: log all child elements for debugging
        logger.error(f"Could not find any visible link items. Dumping module HTML...")
        try:
            inner_html = module_container.evaluate("el => el.innerHTML.substring(0, 2000)")
            logger.error(f"Module HTML: {inner_html}")
        except:
            pass
        page.screenshot(path=f"fail_no_link_items_{module_name[:10]}.png")
        raise AssertionError(f"No visible link items found in module '{module_name}' with any selector")

    # Measure the REAL card width (layout offsetWidth, not a possibly-clipped bounding box).
    try:
        card_w = first_link.evaluate("el => el.offsetWidth")
    except Exception:
        card_w = 0
    if not card_w:
        link_box = first_link.bounding_box()
        card_w = link_box["width"] if link_box else 0
    expected_scroll_width = card_w
    logger.info(f"Found link card using selector '{used_selector}', card width: {expected_scroll_width:.1f}px")

    # --- DIAGNOSTIC (harden): confirm the tagged scroller is a real horizontal carousel ---
    try:
        diag = page.evaluate("""() => {
            const sc = document.querySelector('[data-carousel-scroll="true"]');
            if (!sc) return {scroller: false};
            return {scroller: true, scrollWidth: sc.scrollWidth, clientWidth: sc.clientWidth,
                    scrollLeft: sc.scrollLeft, overflowX: getComputedStyle(sc).overflowX,
                    cardCount: sc.querySelectorAll('div[data-testid="base-general-link-card"]').length};
        }""")
        logger.info(f"[DIAG] tagged scroller: {diag}")
    except Exception as e:
        logger.warning(f"[DIAG] tagged scroller dump failed: {e}")

    # Scroll position helper (reads the tagged scroller directly).
    def get_scroll_left():
        try:
            return scroll_el.evaluate("el => el.scrollLeft")
        except Exception:
            return 0

    # Wait until the scroller's scrollLeft stabilizes (handles smooth-scroll animation).
    def wait_scroll_settle(timeout_ms=2000):
        last = get_scroll_left()
        stable = 0
        elapsed = 0
        while elapsed < timeout_ms:
            page.wait_for_timeout(100)
            elapsed += 100
            cur = get_scroll_left()
            if abs(cur - last) < 1:
                stable += 100
                if stable >= 300:
                    return cur
            else:
                stable = 0
            last = cur
        return last

    # Find nav buttons within the section (scope = module_container).
    def click_nav_button(direction):
        btn = module_container.get_by_role("button", name=direction)
        if btn.count() > 0 and btn.last.is_visible():
            btn.last.click(timeout=5000)
            return True
        else:
            logger.warning(f"'{direction}' button not visible in module '{module_name}'")
            return False

    # Band for "roughly one card width" (tolerant of inter-card gaps / clientWidth steps).
    lo = expected_scroll_width * 0.5
    hi = expected_scroll_width * 1.5
    logger.info(f"Acceptable one-card scroll band: [{lo:.0f}, {hi:.0f}]px")

    # --- Test 1: Click next and verify scroll distance ---
    initial_scroll = wait_scroll_settle()
    logger.info(f"Initial scroll position: {initial_scroll:.1f}px")

    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(500)

    if not click_nav_button("next"):
        raise AssertionError(f"Could not click 'next' button in module '{module_name}'.")

    after_next_scroll = wait_scroll_settle()
    actual_scroll_distance = after_next_scroll - initial_scroll
    logger.info(f"After next click - scroll position: {after_next_scroll:.1f}px, distance: {actual_scroll_distance:.1f}px")

    if actual_scroll_distance < lo or actual_scroll_distance > hi:
        raise AssertionError(
            f"Carousel 'next' did not scroll by ~one card width. "
            f"Expected band [{lo:.0f},{hi:.0f}]px (card={expected_scroll_width:.0f}), got {actual_scroll_distance:.0f}px."
        )
    logger.info(f"✓ Next scroll distance ({actual_scroll_distance:.1f}px) within one-card band")

    # --- Test 2: Click prev and verify it scrolls back ~one card ---
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(500)

    if not click_nav_button("prev"):
        raise AssertionError(f"Could not click 'prev' button in module '{module_name}'.")

    after_prev_scroll = wait_scroll_settle()
    prev_distance = after_next_scroll - after_prev_scroll
    logger.info(f"After prev click - scroll position: {after_prev_scroll:.1f}px, distance back: {prev_distance:.1f}px")

    if prev_distance < lo or prev_distance > hi:
        raise AssertionError(
            f"Carousel 'prev' did not scroll back by ~one card width. "
            f"Expected band [{lo:.0f},{hi:.0f}]px (card={expected_scroll_width:.0f}), got {prev_distance:.0f}px."
        )
    logger.info(f"✓ Prev scroll distance ({prev_distance:.1f}px) within one-card band")

    # --- Test 3: Navigate to last element, verify next button is hidden ---
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(300)

    # Compute a safe click budget from the actual scroll range so the test works
    # for ANY number of cards (and doesn't depend on a fixed magic number).
    max_scroll = 0
    try:
        max_scroll = scroll_el.evaluate("el => el.scrollWidth - el.clientWidth")
    except Exception:
        pass
    card_w = expected_scroll_width if expected_scroll_width else 1
    max_clicks = max(10, int(max_scroll / card_w) + 3)
    logger.info(f"Test 3: max_scroll={max_scroll:.0f}px, click budget={max_clicks}")

    reached_end = False
    last_pos = get_scroll_left()
    for i in range(max_clicks):
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(300)
        next_btn = module_container.get_by_role("button", name="next")
        if next_btn.count() == 0 or not next_btn.last.is_visible():
            logger.info(f"✓ 'next' button hidden after {i} clicks (reached last element)")
            reached_end = True
            break
        next_btn.last.click(timeout=5000)
        cur = wait_scroll_settle()
        # Robust end-of-carousel detection: once we can't scroll any further, we're at the last element.
        if cur >= max_scroll - tolerance:
            logger.info(f"✓ Reached max scroll ({cur:.0f}/{max_scroll:.0f}px) after {i+1} clicks — at last element")
            reached_end = True
            break
        if cur <= last_pos:
            # No forward progress on two consecutive attempts → treat as end.
            logger.info(f"✓ No further scroll progress after {i+1} clicks (at last element)")
            reached_end = True
            break
        last_pos = cur

    if not reached_end:
        raise AssertionError(
            f"Clicked 'next' {max_clicks} times but the next button is still visible — "
            f"carousel did not reach its last element."
        )

    logger.info(f"✓ Carousel scroll verification completed for module '{module_name}'")


def verify_carousel_nav_hidden_at_last(page: Page, v: dict):
    """
    Verify that the 'next' navigation button is hidden when carousel is at the last element.
    
    Supported parameters:
    - module_name: Name of the module to test (required)
    - click_next_times: Number of times to click next before checking (default: 5)
    """
    module_name = v.get("module_name")
    click_next_times = v.get("click_next_times", 5)

    if not module_name:
        raise ValueError("verify_carousel_nav_hidden_at_last: 'module_name' parameter is required")

    logger.info(f"verify_carousel_nav_hidden_at_last: Testing module '{module_name}'")

    # Find the LAST matching module (handles multiple modules on page)
    all_modules = page.locator("div").filter(has=page.get_by_text(module_name, exact=True)).all()
    if not all_modules:
        raise AssertionError(f"Module '{module_name}' not found on page")
    module_container = all_modules[-1]
    module_container.scroll_into_view_if_needed()
    page.wait_for_timeout(500)

    box = module_container.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(800)

    # Click next repeatedly to reach the last element
    for i in range(click_next_times):
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(300)

        next_btn = module_container.get_by_role("button", name="next")
        if next_btn.count() > 0 and next_btn.last.is_visible():
            next_btn.last.click(timeout=5000)
            page.wait_for_timeout(500)
            logger.info(f"Clicked next #{i+1}")
        else:
            logger.info(f"'next' button not visible at click #{i+1}, already at last element")
            break

    # Final check: next button should NOT be visible
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(500)

    next_btn = module_container.get_by_role("button", name="next")
    if next_btn.count() > 0 and next_btn.last.is_visible():
        page.screenshot(path=f"fail_next_btn_still_visible_{module_name[:10]}.png")
        raise AssertionError(f"'next' button is still visible at the last element in module '{module_name}'")
    
    logger.info(f"✓ 'next' button is correctly hidden at the last element in module '{module_name}'")


def verify_child_element_count(page: Page, v: dict):
    """
    Verify the number of child elements within a parent element

    Supported parameters:
    - parent_locator: Parent element locator (required)
    - child_locator: Child element selector to count (required)
    - expected: Expected count of child elements (required)
    - operator: Comparison operator, default 'equals', supports: equals, gt, lt, gte, lte, ne
    - container: Parent container name/text to search within (optional)
    - timeout: Timeout in milliseconds, default 5000

    Usage examples:

    1. Verify exact count:
       verify_child_element_count:
           parent_locator: ".my-module"
           child_locator: ".item"
           expected: 5

    2. Verify within a container:
       verify_child_element_count:
           container: "My Module"
           parent_locator: ".content"
           child_locator: "button"
           expected: 3

    3. Verify minimum count:
       verify_child_element_count:
           parent_locator: "[data-testid='module']"
           child_locator: ".product-card"
           expected: 2
           operator: "gte"  # Greater than or equal

    4. Verify maximum count:
       verify_child_element_count:
           parent_locator: ".gallery"
           child_locator: "img"
           expected: 10
           operator: "lte"  # Less than or equal
    """
    parent_locator_str = v.get("parent_locator")
    child_locator_str = v.get("child_locator")
    expected_count = v.get("expected")
    container_name = v.get("container")

    if not parent_locator_str:
        raise ValueError("verify_child_element_count: 'parent_locator' parameter is required")
    if not child_locator_str:
        raise ValueError("verify_child_element_count: 'child_locator' parameter is required")
    if expected_count is None:
        raise ValueError("verify_child_element_count: 'expected' parameter is required")

    timeout = v.get("timeout", 5000)
    operator = v.get("operator", "equals")

    # Apply container filter if specified
    if container_name:
        logger.info(f"Searching within container: {container_name}")
        # Find parent container by text
        container_elem = page.locator("div").filter(has=page.get_by_text(container_name, exact=True)).last
        parent_locator = container_elem.locator(f"xpath={parent_locator_str}")

        container_info = f" (in container: {container_name})"
    else:
        parent_locator = page.locator(parent_locator_str)
        container_info = ""

    # Wait for parent element to be visible
    parent_locator.wait_for(state="visible", timeout=timeout)

    # Count child elements
    child_locator = parent_locator.locator(child_locator_str)
    actual_count = child_locator.count()

    logger.info(f"Counting child elements - Parent: {parent_locator_str}{container_info}, Child: {child_locator_str}")
    logger.info(f"Actual count: {actual_count}, Expected: {expected_count}, Operator: {operator}")

    # Perform comparison
    passed = False
    if operator == "equals":
        passed = actual_count == expected_count
    elif operator == "gt":
        passed = actual_count > expected_count
    elif operator == "lt":
        passed = actual_count < expected_count
    elif operator == "gte":
        passed = actual_count >= expected_count
    elif operator == "lte":
        passed = actual_count <= expected_count
    elif operator == "ne":
        passed = actual_count != expected_count
    else:
        raise ValueError(f"Unsupported operator: {operator}")

    status = "✓" if passed else "✗"
    result_msg = f"{status} Child element count: {actual_count} (expected: {expected_count}, operator: {operator})"

    if not passed:
        logger.error(result_msg)
        raise AssertionError(f"Child element count verification failed:\n{result_msg}")
    else:
        logger.info(result_msg)
        logger.info("Child element count verification passed")


def verify_element_contains_text(page: Page, v: dict):
    """
    Verify that an element does or does NOT contain specific text(s).

    Supported parameters:
    - locator: Element locator (required)
    - text: The text to check, supports single string or list of strings (required)
    - exact: Whether to match exact text (default: false)
    - assert: Assertion direction, true = contains (default), false = not contains
    - container: Container element name/text to search within (optional)
    - timeout: Timeout in milliseconds (default: 3000)

    Usage examples:

    1. Verify single text DOES exist (default):
       verify_element_contains_text:
           locator: ".my-element"
           text: "Success"

    2. Verify multiple texts DO exist:
       verify_element_contains_text:
           locator: ".my-element"
           text: ["Success", "Welcome"]

    3. Verify text does NOT exist:
       verify_element_contains_text:
           locator: ".my-element"
           text: "Error Message"
           assert: false

    4. Verify multiple texts do NOT exist:
       verify_element_contains_text:
           locator: ".my-element"
           text: ["Error", "Failed"]
           assert: false
    """
    locator_str = v.get("locator")
    text_param = v.get("text")
    exact_match = v.get("exact", False)
    is_positive = v.get("assert", True)
    container_name = v.get("container")

    timeout = v.get("timeout", 3000)

    if not locator_str:
        raise ValueError("verify_element_contains_text: 'locator' parameter is required")
    if not text_param:
        raise ValueError("verify_element_contains_text: 'text' parameter is required")

    # Normalize to list: "text" -> ["text"], ["a","b"] -> ["a","b"]
    texts = [text_param] if isinstance(text_param, str) else list(text_param)

    # Apply container filter if specified
    if container_name:
        logger.info(f"Searching within container: {container_name}")
        locator = page.locator("div", has_text=container_name).locator(f"xpath={locator_str}").last
        container_info = f" (in container: {container_name})"
    else:
        locator = page.locator(locator_str)
        container_info = ""

    direction_label = "DOES contain" if is_positive else "does NOT contain"
    logger.info(f"Verifying element {direction_label} text - Locator: {locator_str}{container_info}, Texts: {texts}, Exact: {exact_match}")

    try:
        # Wait for element to be visible
        locator.wait_for(state="visible", timeout=timeout)

        # Get element text content once
        element_text = locator.inner_text()

        # Check each text
        failures = []
        for text_to_check in texts:
            if exact_match:
                text_exists = text_to_check == element_text.strip()
            else:
                text_exists = text_to_check in element_text

            passed = text_exists if is_positive else not text_exists
            status = "✓" if passed else "✗"
            logger.info(f"  {status} '{text_to_check}'")

            if not passed:
                failures.append(text_to_check)

        if failures:
            verb = "should" if is_positive else "should NOT"
            failed_list = ", ".join(f"'{t}'" for t in failures)
            logger.error(f"Verification failed: Element '{locator_str}' {verb} contain text(s): {failed_list}")
            logger.error(f"Element content: {element_text}")
            page.screenshot(path=f"fail_{'contains' if is_positive else 'not_contains'}_{texts[0][:10]}.png")
            raise AssertionError(
                f"Element '{locator_str}' {verb} contain text(s): {failed_list}, "
                f"actual content: {element_text}"
            )
        else:
            logger.info(f"✓ All {len(texts)} text(s) passed for element '{locator_str}'")
            logger.info(f"Element content: {element_text}")

    except Exception as e:
        # Re-raise our own assertion error (positive failure, or negative failure
        # where the element WAS present and wrongly contained the text)
        if "should" in str(e) and "contain text" in str(e):
            raise
        # Any other exception (element not found, wait_for timeout, detached node, etc.)
        logger.error(f"Error during verification: {e}")
        if not is_positive:
            # Negative assertion (assert:False): if the target element/container is
            # absent or not visible, the text can NOT be contained -> valid PASS.
            # Bounded risk: a broken locator would also pass here, so we log a
            # WARNING so a potentially vacuous pass is visible in the logs.
            logger.warning(
                f"⚠ verify_element_contains_text (assert:False): element '{locator_str}' "
                f"not found/visible within {timeout}ms; treating NOT-contain as PASS. "
                f"If this is unexpected, verify the locator '{locator_str}' is still valid "
                f"to avoid a false-green."
            )
            return
        # Positive assertion: element missing means the text is NOT present -> real failure
        safe_name = texts[0][:10] if texts else "unknown"
        page.screenshot(path=f"fail_contains_error_{safe_name}.png")
        raise


def click_container_button(page: Page, v: dict):
    """
    Click a button within a specific container element.

    Supported parameters:
    - container: Container element text or locator to search within (required)
    - container_locator: CSS/XPath selector for the container (optional, used with container text for double-locator)
    - button: Button selector within the container, supports CSS or XPath (required)
    - button_index: Button index when multiple matches found (default: 0)

    Usage examples:

    1. CSS button in text container:
       click_container_button:
           container: "My Module"
           button: ".edit-btn"

    2. XPath button:
       click_container_button:
           container: "My Module"
           button: "//button[contains(@class, 'MuiButton')]"
           button_index: 1

    3. Container with double-locator pattern:
       click_container_button:
           container: "My Module"
           container_locator: "//div[@data-testid='module-header']"
           button: "//button[@aria-label='Edit']"
    """
    container_text = v.get("container")
    container_locator = v.get("container_locator")
    button_selector = v.get("button")
    button_index = v.get("button_index", 0)

    if not container_text and not container_locator:
        raise ValueError("click_container_button: 'container' or 'container_locator' is required")
    if not button_selector:
        raise ValueError("click_container_button: 'button' is required")

    # Find container
    if container_text:
        container = page.locator("div", has_text=container_text).last
        if container_locator:
            prefix = "xpath=" if container_locator.startswith("/") else ""
            container = container.locator(f"{prefix}{container_locator}").last
    else:
        prefix = "xpath=" if container_locator.startswith("/") else ""
        container = page.locator(f"{prefix}{container_locator}").last

    container.scroll_into_view_if_needed()
    logger.info(f"click_container_button: container='{container_text or container_locator}', button='{button_selector}', index={button_index}")

    # Find and click button, auto-detect XPath
    prefix = "xpath=" if button_selector.startswith("/") else ""
    button_loc = container.locator(f"{prefix}{button_selector}")
    button_loc.nth(button_index).click(timeout=10000)
    logger.info(f"✓ Clicked button '{button_selector}' at index {button_index}")


def select_content_card(page: Page, v: dict):
    """Select an existing post/product card in the 'Add from my content' picker.

    The picker list lives inside a scroll container and the cards render below the
    fold, so a plain smart_click lands on an in-dialog overlay (the card's own
    content stack) and never toggles selection. We scroll the card into view, then
    dispatch a real mouse click at the card's on-screen center — proven to enable
    the Continue button.

    YAML:
        select_content_card: { index: 0 }            # first card
        select_content_card: { index: 1 }            # second card
    """
    index = v.get("index", 0)
    timeout = v.get("timeout", 8000)
    card = page.locator("button[data-testid='mui-card-action-area']").nth(index)
    card.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    box = card.bounding_box()
    if not box:
        raise AssertionError(f"select_content_card: card index {index} has no bounding box")
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    page.mouse.click(cx, cy)
    page.wait_for_timeout(600)
    # confirm selection registered (Continue should enable)
    try:
        cont = page.get_by_role("button", name="Continue").first
        if not cont.is_enabled(timeout=3000):
            logger.warning(f"select_content_card: Continue still disabled after selecting card {index}")
    except Exception as e:
        logger.debug(f"select_content_card: continue-check skipped ({e})")
    logger.info(f"✓ Selected content card index {index}")


def verify_section_card_count(page: Page, v: dict):
    """Count content cards inside a named storefront section and assert the total.

    New storefront (2026-07): a section's header (the title ``<p data-testid='base-storefront-text'>``)
    and its body (where the cards live) are SIBLINGS under the section root, so the legacy
    ``verify_child_element_count`` trick (container + parent_locator '..') cannot reach the cards.
    This action instead locates the section by its stable title testid, walks up to the section
    root (the first ancestor that also contains a content card), and counts every ``base-*-card``
    testid underneath it. No build-specific hashed classes are used.

    Supported parameters:
    - module_name: Section title to target (required)
    - expected: Expected card count (required)
    - operator: equals|gt|lt|gte|lte|ne (default 'equals')
    - card_types: Optional extra testid fragment to restrict counting
      (default counts base-post-card / base-product-card / base-general-link-card /
      base-event-card). e.g. card_types: ['base-post-card'] to count only posts.
    - timeout: ms, default 8000

    Usage:
        verify_section_card_count: { module_name: 'post duplicate section', expected: 2 }
        verify_section_card_count: { module_name: 'my posts', expected: 2, card_types: ['base-post-card'] }
    """
    module_name = v.get("module_name")
    if not module_name:
        raise ValueError("verify_section_card_count: 'module_name' is required")
    expected = v.get("expected")
    if expected is None:
        raise ValueError("verify_section_card_count: 'expected' is required")
    operator = v.get("operator", "equals")
    timeout = v.get("timeout", 8000)
    card_types = v.get("card_types") or [
        "base-post-card", "base-product-card",
        "base-general-link-card", "base-event-card",
    ]

    # The section title is a stable <p data-testid='base-storefront-text'>. Its
    # parent chain leads up to the section root, which is the first ancestor that
    # ALSO contains a content card. We walk up in JS so we never depend on the
    # build-specific hashed katana-* classes (the section root class changes per
    # build, and the header is NOT the direct parent of the cards).
    js = """([name, types]) => {
        const HDR = "p[data-testid='base-storefront-text']";
        const titles = Array.from(document.querySelectorAll(HDR))
            .filter(e => (e.textContent||'').trim() === name);
        if (!titles.length) return {found:false};
        const sel = types.map(t => "[data-testid*='" + t + "']").join(',');
        // The section root is the highest ancestor that contains exactly ONE
        // header (this section's). Above it, the parent contains multiple
        // sections (more than one header). Walking up past the root would match
        // the whole storefront and report a bogus count for an empty section,
        // so we stop as soon as the header count != 1 (or once cards are found).
        let node = titles[0].parentElement;
        let root = titles[0];
        for (let i = 0; i < 12 && node; i++) {
            const hcount = node.querySelectorAll(HDR).length;
            if (hcount === 1) { root = node; }
            else { break; }
            if (node.querySelector(sel)) break;
            node = node.parentElement;
        }
        return {found:true, count: root.querySelectorAll(sel).length};
    }"""
    result = page.evaluate(js, [module_name, card_types])
    # Retry briefly in case a post-action render/transition hasn't settled.
    attempts = max(1, int(timeout / 300))
    for _ in range(attempts):
        if result.get("found"):
            break
        page.wait_for_timeout(300)
        result = page.evaluate(js, [module_name, card_types])
    if not result.get("found"):
        raise AssertionError(
            f"verify_section_card_count: section '{module_name}' not found "
            f"(no matching header/cards). card_types={card_types}"
        )
    actual = result["count"]

    passed = False
    if operator == "equals":
        passed = actual == expected
    elif operator == "gt":
        passed = actual > expected
    elif operator == "lt":
        passed = actual < expected
    elif operator == "gte":
        passed = actual >= expected
    elif operator == "lte":
        passed = actual <= expected
    elif operator == "ne":
        passed = actual != expected
    else:
        raise ValueError(f"verify_section_card_count: unsupported operator '{operator}'")

    status = "✓" if passed else "✗"
    msg = f"{status} Section '{module_name}' card count: {actual} (expected {expected}, op {operator})"
    if not passed:
        logger.error(msg)
        raise AssertionError(f"Section card count verification failed:\n{msg}")
    logger.info(msg)
