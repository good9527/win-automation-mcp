"""
UIAutomation submodule of win-automation-mcp.
Provides COM-based UIAutomation inspection, pattern execution, selector queries,
tree traversal, signature caching, and dynamic repair.
"""

from win_automation.uia.engine import (
    get_uia_client,
    _get_uia_client,
    _get_root_element,
    _element_from_handle,
    _get_supported_patterns,
    _get_typed_pattern,
    _uia_element_by_index,
    element_from_point,
)
from win_automation.uia.tree import (
    build_accessibility_tree,
    desktop_accessibility,
    build_desktop_tree,
    find_elements,
    desktop_find_elements,
    get_element,
    get_desktop_element,
    desktop_get_element,
    uia_stable_wait,
    desktop_uia_stable_wait,
)
from win_automation.uia.patterns import (
    click_index,
    perform_action,
    desktop_click_index,
    desktop_perform_action,
    desktop_click_element,
    desktop_action,
    perform_secondary_action,
    find_item_in_container,
    item_container_find,
)
from win_automation.uia.repair import (
    uia_selector_repair_find,
    uia_cell_selector_repair_find,
    wait_for_element,
)
from win_automation.uia.cache import (
    _remember_uia_element_signatures,
    _remember_uia_scan_options,
    _last_uia_scan_options,
)


__all__ = [
    "get_uia_client",
    "_get_uia_client",
    "_get_root_element",
    "_element_from_handle",
    "_get_supported_patterns",
    "_get_typed_pattern",
    "_uia_element_by_index",
    "build_accessibility_tree",
    "desktop_accessibility",
    "build_desktop_tree",
    "find_elements",
    "desktop_find_elements",
    "get_element",
    "get_desktop_element",
    "desktop_get_element",
    "uia_stable_wait",
    "desktop_uia_stable_wait",
    "element_from_point",
    "click_index",
    "perform_action",
    "desktop_click_index",
    "desktop_perform_action",
    "desktop_click_element",
    "desktop_action",
    "perform_secondary_action",
    "find_item_in_container",
    "item_container_find",
    "uia_selector_repair_find",
    "uia_cell_selector_repair_find",
    "wait_for_element",
    "_remember_uia_element_signatures",
    "_remember_uia_scan_options",
    "_last_uia_scan_options",
]
