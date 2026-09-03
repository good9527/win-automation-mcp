"""
Vision and screen capture submodule.
"""

from win_automation.vision.dxcam_manager import DXCamManager
from win_automation.vision.capture import (
    observe_window,
    capture_window_screenshot,
    capture_desktop_screenshot,
    screenshot,
    desktop_screenshot,
    screenshot_b64,
    desktop_point,
    get_window_state,
    _capture_window_screenshot,
    _capture_desktop_screenshot,
)
from win_automation.vision.pixel import (
    pixel,
    pixel_wait,
    desktop_pixel,
    desktop_pixel_wait,
)
from win_automation.vision.stability import (
    visual_stable_wait,
    desktop_visual_stable_wait,
)
from win_automation.vision.match import (
    locate_image,
    desktop_locate_image,
    image_wait,
    desktop_image_wait,
    image_click,
    desktop_image_click,
    wait_image,
    click_image,
    desktop_wait_image,
    desktop_click_image,
)
from win_automation.vision.visual_row import (
    visual_row,
    visual_row_click,
    visual_row_scroll,
    visual_row_scroll_click,
)

__all__ = [
    "DXCamManager",
    "observe_window",
    "capture_window_screenshot",
    "capture_desktop_screenshot",
    "screenshot",
    "desktop_screenshot",
    "screenshot_b64",
    "desktop_point",
    "get_window_state",
    "_capture_window_screenshot",
    "_capture_desktop_screenshot",
    "pixel",
    "pixel_wait",
    "desktop_pixel",
    "desktop_pixel_wait",
    "visual_stable_wait",
    "desktop_visual_stable_wait",
    "locate_image",
    "desktop_locate_image",
    "image_wait",
    "desktop_image_wait",
    "image_click",
    "desktop_image_click",
    "wait_image",
    "click_image",
    "desktop_wait_image",
    "desktop_click_image",
    "visual_row",
    "visual_row_click",
    "visual_row_scroll",
    "visual_row_scroll_click",
]
