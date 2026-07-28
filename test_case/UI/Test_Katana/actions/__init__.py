

from playwright.sync_api import Page
from .base import (
    open_url,
    smart_click,
    _smart_click_with_fallback,
    smart_fill,
    fill_numeric,
    smart_check,
    smart_swipe,
    smart_sleep,
    smart_press,
    smart_add_cookies,
    clear_cookies,
    smart_upload,
    smart_screenshot,
    smart_if,
    smart_wait,
    wait_for_selector,
    wait_for_url,
    save_html,
    click_modal_close,
    verify_text_visible,
    verify_text_hidden,
    verify_value,
    verify_value_near,
    verify_all_commission_values,
    reload_page,
    go_back,
    page_scroll,
    scroll_tab_content,
    execute_not_recognized_scan,
    run_workflow_script,
    duplicate_post,
    wait_toast,
    scroll_to_bottom,
    drag_element,
    drag_and_drop_by_coordinates,
    swipe_to_element,
    fill_stripe_iframe,
    smart_click_optional,
    ensure_auto_archive,
    smart_click_retry,
    handle_modal,
    auto_handle_modals,
    create_session,
    switch_session,
    close_session,
    delete_coseller_if_exists,
    execute_js,
    verify_no_sibling_text,
)

from .module import (
    click_module_edit_button, click_module_paragraph, click_add_new_product,
    click_module_add_new, click_module_post_view_event_cta, click_module_item_more_icon,
    click_module_collapse, click_module_expand, verify_module_collapsed, verify_module_expanded,
    verify_element_style, verify_child_element_count,
    verify_element_contains_text, verify_carousel_scroll, verify_carousel_nav_hidden_at_last,
    delete_all_sections_by_name, remove_card_from_section,
    verify_section_card_count,
    select_content_card,
    click_container_button,
    click_shop_event_button,
    click_shop_add_button, click_shop_hamburger, click_add_storefront_module, click_shop_add_module,
)
from .product import (

    click_add_button_regex, verify_product_clickable, click_products_nav_icon,
    click_products_tab_t2129, click_bell_button, click_product_plus_button,
    click_product_image, verify_post_exists, R_click_follow, 
    click_close_toast, verify_toast_message, select_replacement_product,
    click_by_coordinates, click_relative_to_selector, move_relative_to_selector
)
from .form import (
    verify_submission_details, verify_message_content, click_form_more_menu,
    click_submission_details_back, click_contact_form,
    download_submission_csv, verify_csv_data, capture_total_count, verify_date
)
from .layout import (
    verify_top_aligned_layout, verify_waterfall_layout,
    goto_storefront, publish_button_click, verify_navigation_after_publish,
    click_mui_svg_icon, click_products_text, wait_for_product_cards
)
from .collabs import verify_invitation_link_clipboard

def smart_click_scan(page: Page, v: dict):
    """
    Full fallback click (equivalent to smart_click + fallback_scan=True).
    Same as writing: R_click: { name: 'xxx', fallback_scan: true } in YAML.

    Recommended for: nested dialogs, multi-layer Drawers, elements obscured by container overlays.
    For regular test cases, continue using R_click or click (fast locate by default, no Page-level Search).
    """
    if isinstance(v, dict):
        v = {**v, "fallback_scan": True}
    else:
        v = {"fallback_scan": True}
    smart_click(page, v)


# Registry for exact match keys
ACTIONS = {
    "open": open_url,
    # Generic overrides
    "click_modal_close": click_modal_close,
    "R_click": smart_click,
    "R_click_scan": smart_click_scan,   # Explicitly enable Page-level Search + AI fallback
    "fill": smart_fill,
    "check": smart_check,
    "swipe": smart_swipe,
    "sleep": smart_sleep,
    "press": smart_press,
    "upload": smart_upload,
    "add_cookies": smart_add_cookies,
    "clear_cookies": clear_cookies,
    "screenshot": smart_screenshot,
    
    # Module specific
    "click_module_edit_button": click_module_edit_button,
    "click_module_paragraph": click_module_paragraph,
    "click_add_new_product": click_add_new_product,
    "click_module_post_view_event_cta": click_module_post_view_event_cta,
    "click_module_item_more_icon": click_module_item_more_icon,
    "click_module_collapse": click_module_collapse,
    "click_module_expand": click_module_expand,
    "verify_module_collapsed": verify_module_collapsed,
    "verify_module_expanded": verify_module_expanded,
    "verify_element_style": verify_element_style,
    "verify_child_element_count":verify_child_element_count,
    "verify_no_sibling_text": verify_no_sibling_text,
    "verify_element_contains_text": verify_element_contains_text,
    "drag_element": drag_element,
    "drag_and_drop_by_coordinates": drag_and_drop_by_coordinates,
    "swipe_to_element": swipe_to_element,
    "click_container_button": click_container_button,

    "handle_modal": handle_modal,
    "auto_handle_modals": auto_handle_modals,
    "create_session": create_session,
    "switch_session": switch_session,
    "close_session": close_session,
    "verify_carousel_scroll": verify_carousel_scroll,
    "verify_carousel_nav_hidden_at_last": verify_carousel_nav_hidden_at_last,
    "delete_all_sections_by_name": delete_all_sections_by_name,
    "remove_card_from_section": remove_card_from_section,
    "verify_section_card_count": verify_section_card_count,
    "select_content_card": select_content_card,

    # Product/Social specific
    "click_add_button_regex": click_add_button_regex,
    "click_add_button_regex_final": click_add_button_regex,
    "verify_product_clickable": verify_product_clickable,
    "click_products_nav_icon": click_products_nav_icon,
    "click_products_tab_t2129": click_products_tab_t2129,
    "click_bell_button": click_bell_button,
    "click_bell_button_reopen": click_bell_button, # Same handler
    "click_product_plus_button": click_product_plus_button,
    "click_product_image": click_product_image,
    "verify_post_exists": verify_post_exists,
    "R_click_follow": R_click_follow,
    
    # Form specific
    "verify_submission_details": verify_submission_details,
    "verify_message_content": verify_message_content,
    "verify_email_content": verify_message_content, # Reuse
    "verify_phone_content": verify_message_content, # Reuse
    "click_form_more_menu": click_form_more_menu,
    "click_submission_details_back": click_submission_details_back,
    "click_contact_form": click_contact_form,

    # Layout specific
    "verify_top_aligned_layout": verify_top_aligned_layout,
    "verify_waterfall_layout": verify_waterfall_layout,
    "verify_follow_message": verify_toast_message,
    "verify_unfollow_message": verify_toast_message,
    "verify_unfollow_message_final": verify_toast_message,
    "verify_refollow_message": verify_toast_message,

    # T3370 Layout Specific
    "goto_storefront_top_aligned": goto_storefront,
    "goto_storefront_waterfall": goto_storefront,
    "publish_button_click_top_aligned": publish_button_click,
    "publish_button_click_waterfall": publish_button_click,
    "verify_navigation_after_publish_top_aligned": verify_navigation_after_publish,
    "verify_navigation_after_publish_waterfall": verify_navigation_after_publish,
    "click_mui_svg_icon_top_aligned": click_mui_svg_icon,
    "click_mui_svg_icon_waterfall": click_mui_svg_icon,
    "click_products_text_top_aligned": click_products_text,
    "click_products_text_waterfall": click_products_text,
    "wait_for_product_cards_top_aligned": wait_for_product_cards,
    "wait_for_product_cards_waterfall": wait_for_product_cards,
    "check_label_top_aligned": smart_check,
    "check_label_waterfall": smart_check,
    "verify_invitation_link_clipboard": verify_invitation_link_clipboard,
    "verify_text_visible": verify_text_visible,
    "verify_text_hidden": verify_text_hidden,
    "verify_value": verify_value,
    "verify_value_near": verify_value_near,
    "verify_all_commission": verify_all_commission_values,
    "verify_cta_type_4": verify_no_sibling_text,
    "click_module_add_new": click_module_add_new,
    "click_shop_event_button": click_shop_event_button,
    "click_shop_add_button": click_shop_add_button,
    "click_shop_hamburger": click_shop_hamburger,
    "click_add_storefront_module": click_add_storefront_module,
    "click_shop_add_module": click_shop_add_module,
    # Section aliases (post storefront redesign: module -> section)
    "click_shop_add_section": click_shop_add_module,
    "click_section_edit_button": click_module_edit_button,
    "click_add_storefront_section": click_add_storefront_module,
    "verify_product_visible": verify_text_visible,
    "select_replacement_product": select_replacement_product,
    "click_by_coordinates": click_by_coordinates,
    "click_relative_to_selector": click_relative_to_selector,
    "move_relative_to_selector": move_relative_to_selector,
    "reload": reload_page,
    "go_back": go_back,
    "page_scroll": page_scroll,
    "scroll_tab_content": scroll_tab_content,
    "execute_not_recognized_scan": execute_not_recognized_scan,
    "run_workflow_script": run_workflow_script,
    "duplicate_post": duplicate_post,
    "download_submission_csv": download_submission_csv,
    "verify_csv_data": verify_csv_data,
    "capture_total_count": capture_total_count,
    "verify_date": verify_date,
    "scroll_to_bottom": scroll_to_bottom,
    "fill_stripe_iframe": fill_stripe_iframe,
    "smart_click_optional": smart_click_optional,
    "smart_click_retry": smart_click_retry,
    "delete_coseller_if_exists": delete_coseller_if_exists,
    "execute_js": execute_js,
    "ensure_auto_archive": ensure_auto_archive,
}


def get_action(name):
    """
    Get action function by name.
    Supports exact match from ACTIONS registry,
    and fallback to smart handlers for prefixes.
    """
    # 1. Exact match
    if name in ACTIONS:
        return ACTIONS[name]
    
    # 2. Prefix mapping
    if name.startswith("click_module_edit_button"):
        return click_module_edit_button
    elif name.startswith("click_module_paragraph"):
        return click_module_paragraph
    elif name.startswith("click_add_new_product"):
        return click_add_new_product
    elif name.startswith("click_module_add_new"):
        return click_module_add_new
    elif name.startswith("click_shop_event_button"):
        return click_shop_event_button
    elif name.startswith("click_shop_add_button"):
        return click_shop_add_button
    elif name.startswith("click_shop_hamburger"):
        return click_shop_hamburger
    elif name.startswith("click_add_storefront_module"):
        return click_add_storefront_module
    elif name.startswith("click_shop_add_module"):
        return click_shop_add_module
    elif name.startswith("click_module_post_view_event_cta"):
        return click_module_post_view_event_cta
    elif name.startswith("click_module_item_more_icon"):
        return click_module_item_more_icon
    elif name.startswith("verify_element_style"):
        return verify_element_style
    elif name.startswith("verify_child_element_count"):
        return verify_child_element_count
    elif name.startswith("verify_element_contains_text"):
        return verify_element_contains_text
    elif name.startswith("drag_element"):
        return drag_element
    elif name.startswith("drag_and_drop_by_coordinates"):
        return drag_and_drop_by_coordinates
    elif name.startswith("swipe_to_element"):
        return swipe_to_element
    elif name.startswith("handle_modal"):
        return handle_modal
    elif name.startswith("auto_handle_modals"):
        return auto_handle_modals
    elif name.startswith("create_session") or name.startswith("session_"):
        return create_session
    elif name.startswith("switch_session"):
        return switch_session
    elif name.startswith("close_session"):
        return close_session
    elif name.startswith("click_container_button"):
        return click_container_button
    elif name.startswith("select_content_card"):
        return select_content_card


    if name.startswith("R_click_scan") or name.startswith("click_scan"):
        return smart_click_scan
    if name.startswith("smart_click_optional"):
        return smart_click_optional
    if name.startswith("smart_click_retry"):
        return smart_click_retry
    if name.startswith("R_click") or name.startswith("click") or name.startswith("l_click"):
        return smart_click
    elif name.startswith("move_relative_to_selector") or name.startswith("move_mouse") or name.startswith("move_to"):
        return move_relative_to_selector
    elif name.startswith("if_"):
        return smart_if
    elif name.startswith("fill_numeric"):
        return fill_numeric
    elif name.startswith("fill"):
        return smart_fill
    elif name.startswith("check") or name.startswith("uncheck"):
        return smart_check
    elif name.startswith("swipe") or name.startswith("scroll"):
        return smart_swipe
    elif name.startswith("sleep"):
        return smart_sleep
    elif name.startswith("press"):
        return smart_press
    elif name.startswith("upload") or name.startswith("wait_for_upload"):
        return smart_upload
    elif name.startswith("screenshot"):
        return smart_screenshot
    elif name.startswith("save_html") or name.startswith("save_full_html"):
        return save_html
    elif name.startswith("wait_for_selector"):
        return wait_for_selector
    elif name.startswith("wait_for_url") or name.startswith("verify_navigation"):
        return wait_for_url
    elif name.startswith("open"):
        return open_url
    elif name.startswith("reload"):
        return reload_page
    elif name.startswith("go_back"):
        return go_back
    elif name.startswith("wait_toast"):
        return wait_toast
    elif name.startswith("page_scroll"):
        return page_scroll
    elif name.startswith("wait_"):
        return smart_wait

    
    # Special prefixes that map to specific functions
    if name.startswith("click_close_toast"):
        return click_close_toast
    
    if name.startswith("verify_no_sibling"):
        return verify_no_sibling_text
    if name.startswith("verify_carousel_nav_hidden"):
        return verify_carousel_nav_hidden_at_last
    if name.startswith("verify_carousel_scroll"):
        return verify_carousel_scroll
    if name.startswith("verify_toast"):
        return verify_toast_message
    if name.startswith("verify_hidden"):
        return verify_text_hidden
    if name.startswith("verify_value"):
        return verify_value
    if name.startswith("verify"):
        return verify_text_visible

        
    if name.startswith("select_a_for_b") or name.startswith("select_b_for_c"):
        return select_replacement_product
    if name.startswith("execute_js"):
        return execute_js
        
    # Add other prefix handlers here as we migrate them
    
    return None
