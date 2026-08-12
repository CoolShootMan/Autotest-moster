import re
from loguru import logger
from playwright.sync_api import Page
from .base import smart_click

def click_add_button_regex(page: Page, v: dict):
    # Use smart_click for "Add" button
    smart_click(page, {"name": "^Add$", "role": "button", "timeout": 10000, **v})

def verify_product_clickable(page: Page, v: dict):
    # Verify product is clickable via smart_click
    smart_click(page, {"name": v.get("text"), "timeout": 10000, **v})

def click_products_nav_icon(page: Page, v: dict):
    # Click navigation icon via locator fallback in smart_click
    smart_click(page, {
        "locator": ".MuiSvgIcon-root.MuiSvgIcon-fontSizeMedium.shop-text-color", 
        "index": 0, 
        "name": "Products Nav Icon",
        "timeout": 10000,
        **v
    })

def click_products_tab_t2129(page: Page, v: dict):
    # Use smart_click with container context logic
    smart_click(page, {
        "locator": "#simple-popover", 
        "name": "Products", 
        "exact": True, 
        "timeout": 10000,
        **v
    })

def click_bell_button(page: Page, v: dict):
    # Highly specific but now AI-protected
    smart_click(page, {
        "locator": ".katana-15rqjx2", 
        "index": 0, 
        "name": "Bell/Follow button", 
        "timeout": 10000,
        **v
    })

def click_product_plus_button(page: Page, v: dict):
    # Target the + button in product stack
    smart_click(page, {
        "locator": ".MuiStack-root.katana-1xl4abm > .MuiButtonBase-root", 
        "index": 0, 
        "name": "Product Plus Button",
        "timeout": 10000,
        **v
    })

def click_product_image(page: Page, v: dict):
    smart_click(page, {"role": "img", "name": "Image of Product", "timeout": 10000, **v})

def R_click_follow(page: Page, v: dict):
    # Smart handler for initial follow: handles "Already Following" state
    logger.info("Executing smart R_click_follow...")
    
    # Crash Check (Already covered in test_ui.py but kept for safety in custom flows)
    if page.get_by_text("Something went wrong!", exact=True).is_visible():
        raise Exception("Application Crashed")
    
    # 1. Check if 'About' modal is open
    about_modal = page.locator("div[role='dialog'], .MuiDialog-root").filter(has_text="About").first
    if not about_modal.is_visible():
        scope = page
    else:
        logger.info("R_click_follow: Found 'About' modal.")
        scope = about_modal
    
    # 2. Check for "Follow"
    follow_btn = scope.get_by_role("button", name="Follow", exact=True).first
    if follow_btn.is_visible():
        follow_btn.click()
        logger.info("R_click_follow: Clicked 'Follow'.")
    else:
        # 3. Check for "Following"
        following_btn = scope.get_by_role("button", name="Following", exact=True).first
        if following_btn.is_visible():
            logger.info("R_click_follow: Found 'Following' - User is already following. performing reset.")
            following_btn.click()
            
            # 4. Handle Unfollow Confirmation
            unfollow_confirm = page.get_by_role("button", name="Unfollow Anyway").first
            unfollow_confirm.wait_for(state="visible", timeout=5000)
            unfollow_confirm.click()
            
            # 5. Wait for "Follow" to appear and click it
            try:
                follow_btn = scope.get_by_role("button", name="Follow", exact=True).first
                follow_btn.wait_for(state="visible", timeout=7000)
                follow_btn.click()
                logger.info("R_click_follow: Reset complete and clicked 'Follow'.")
            except:
                # Fallback: Reload page is the safest way to ensure clean state
                logger.warning("R_click_follow: 'Follow' not found. Reloading page and reopening modal...")
                page.reload(wait_until="load")
                page.wait_for_timeout(5000)
                
                # Re-open About modal
                page.get_by_role("img", name="Logo").click(force=True)
                
                # Wait for About modal to appear
                about_modal = page.locator("div[role='dialog'], .MuiDialog-root").filter(has_text="About").first
                try:
                    about_modal.wait_for(state="visible", timeout=5000)
                    scope = about_modal
                except:
                    scope = page
                    
                follow_btn = scope.get_by_role("button", name="Follow", exact=True).first
                follow_btn.wait_for(state="visible", timeout=10000)
                follow_btn.click()
                logger.info("R_click_follow: Reset complete (with Reload) and clicked 'Follow'.")
        else:
            logger.error("R_click_follow: Neither 'Follow' nor 'Following' found!")
            page.screenshot(path="fail_smart_follow.png")
            raise Exception("Follow button missing")

def verify_post_exists(page: Page, v: dict):
    # Verify post button exists with title and price via smart_click (Wait only)
    # Using smart_click without actually clicking by leveraging its locator search
    target_name = v.get("text") or "Image of Product test T2129"
    try:
        page.get_by_role("button", name=re.compile(target_name)).wait_for(state="visible", timeout=10000)
        logger.info(f"Post '{target_name}' verified in Posts tab")
    except Exception as e:
        logger.error(f"Post verification failed: {e}")
        page.screenshot(path="fail_post_verify.png")
        raise

def click_close_toast(page: Page, v: dict):
    # Streamlined toast dismissal
    try:
        toasts = page.locator(".MuiSnackbar-root").all()
        for toast in toasts:
            if toast.is_visible():
                logger.info(f"Hiding toast: {toast.inner_text()[:40]}...")
                toast.evaluate("element => element.style.display = 'none'")
        page.wait_for_timeout(1000)
    except: pass

def verify_toast_message(page: Page, v: dict):
    # Verify toast message appears with AI-ready error handling
    text = v["text"]
    timeout = v.get("timeout", 10000)
    try:
        # 1. Direct Locator Check
        toast_locator = page.locator(".MuiSnackbar-root").filter(has_text=re.compile(text, re.I))
        toast_locator.wait_for(state="visible", timeout=timeout)
        logger.info(f"Verified toast: {text}")
    except Exception as e:
        logger.warning(f"Toast '{text}' not found in Snackbar. Checking page content...")
        # 2. Page Content Fallback (AI-like robustness)
        try:
            page.get_by_text(re.compile(text, re.I)).first.wait_for(state="visible", timeout=timeout//2)
            logger.info(f"Verified text '{text}' visible (fallback)")
        except:
            logger.error(f"Toast message '{text}' MISSING.")
            page.screenshot(path="fail_toast_verify.png")
            if v.get("optional"):
                logger.warning(f"Toast '{text}' optional -> not failing the test.")
                return
            raise AssertionError(f"Toast message '{text}' not found.")

def select_replacement_product(page: Page, v: dict):
    product_name = v.get("name") or v.get("text")
    logger.info(f"Selecting replacement product: {product_name}")
    
    # Scope to the visible drawer that contains "Select items to replace"
    drawer = page.locator('.MuiDrawer-root, .MuiDialog-root').filter(has_text=re.compile("Select items to replace", re.I)).filter(visible=True).last
    if drawer.count() == 0:
        logger.warning("Target drawer not found by title, using topmost visible modal.")
        drawer = page.locator('.MuiModal-root:visible, .MuiDialog-root:visible').last

        
    # Relaxed match: allow the name to be part of the text or the exact text
    candidates = [
        drawer.get_by_text(product_name, exact=True),
        drawer.get_by_role("paragraph").filter(has_text=re.compile(product_name, re.I)),
        drawer.locator('.MuiCardActionArea-root').filter(has_text=re.compile(product_name, re.I)),
        drawer.locator('.MuiStack-root').filter(has_text=re.compile(product_name, re.I)),
        drawer.locator('div').filter(has_text=re.compile(product_name, re.I))
    ]
    
    card = None
    for c in candidates:
        if c.count() > 0:
            # Pick the most visible one
            for i in range(c.count()):
                if c.nth(i).is_visible():
                    card = c.nth(i)
                    break
        if card: break
            
    if card:
        logger.info(f"Found card for '{product_name}'. Clicking...")
        card.click(position={'x': 10, 'y': 10}, force=True)
    else:
        logger.error(f"Could not find replacement card for '{product_name}'")
        # Fallback to coordinate if provided in 'v'
        if 'x' in v and 'y' in v:
            logger.info("Using fallback coordinates...")
            page.mouse.click(v['x'], v['y'])
        else:
            page.screenshot(path=f"fail_select_{product_name}.png")
            raise Exception(f"Replacement product '{product_name}' not found.")
    
    logger.info(f"Successfully selected replacement '{product_name}'")


def click_by_coordinates(page: Page, v: dict):
    x = v.get("x")
    y = v.get("y")
    if x is not None and y is not None:
        logger.info(f"Clicking at coordinates: ({x}, {y})")
        page.mouse.click(x, y)
    else:
        logger.error("click_by_coordinates: missing x or y in arguments")
        raise ValueError("Missing coordinates")

def click_relative_to_selector(page: Page, v: dict):
    # Support both direct params and nested wrapper dict (e.g. {action_name: {locator, x, y}})
    params = v.get("click_relative_to_selector", v) if isinstance(v, dict) else v
    selector = params.get("locator")
    offset_x = params.get("x", 0)
    offset_y = params.get("y", 0)
    if not selector:
        logger.error("click_relative_to_selector: missing 'locator' in arguments")
        raise ValueError("Missing locator for click_relative_to_selector")
    logger.info(f"Clicking relative to {selector} with offset ({offset_x}, {offset_y})")
    
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=10000)
    box = loc.bounding_box()
    if box:
        x = box['x'] + (box['width'] / 2 if offset_x == "center" else offset_x)
        y = box['y'] + (box['height'] / 2 if offset_y == "center" else offset_y)
        page.mouse.click(x, y)
    else:
        logger.error(f"Could not get bounding box for {selector}")
        raise Exception(f"Element {selector} has no bounding box")


def move_relative_to_selector(page: Page, v: dict):
    """Move the real mouse cursor to a position relative to a selector, without clicking."""
    # Support both direct params and nested wrapper dict (e.g. {action_name: {locator, x, y}})
    params = v.get("move_relative_to_selector", v) if isinstance(v, dict) else v
    selector = params.get("locator")
    offset_x = params.get("x", 0)
    offset_y = params.get("y", 0)
    if not selector:
        logger.error("move_relative_to_selector: missing 'locator' in arguments")
        raise ValueError("Missing locator for move_relative_to_selector")
    logger.info(f"Moving mouse relative to {selector} with offset ({offset_x}, {offset_y})")
    
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=10000)
    box = loc.bounding_box()
    if box:
        x = box['x'] + (box['width'] / 2 if offset_x == "center" else offset_x)
        y = box['y'] + (box['height'] / 2 if offset_y == "center" else offset_y)
        page.mouse.move(x, y)
    else:
        logger.error(f"Could not get bounding box for {selector}")
        raise Exception(f"Element {selector} has no bounding box")


