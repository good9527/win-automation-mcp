"""
Common types, dataclasses, TypedDict definitions, and exception hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union


# ---------------------------------------------------------------------------
# Exception Hierarchy
# ---------------------------------------------------------------------------

class WinAutomationError(Exception):
    """Base exception for all win-automation errors."""
    pass


class WindowNotFoundError(WinAutomationError):
    """Raised when a target window HWND or title is not found."""
    pass


class ElementNotFoundError(WinAutomationError):
    """Raised when a target UIAutomation element is not found."""
    pass


class ControlNotFoundError(WinAutomationError):
    """Raised when a native Win32 control is not found."""
    pass


class ActionTimeoutError(WinAutomationError, TimeoutError):
    """Raised when an operation or wait condition exceeds its timeout."""
    pass


class SafetyError(WinAutomationError):
    """Raised when an operation is blocked by the safety gate."""
    pass


class HelperError(WinAutomationError):
    """Raised when communication with the resident helper service fails."""
    pass


# ---------------------------------------------------------------------------
# Geometry Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Point:
    x: int
    y: int

    def to_tuple(self) -> Tuple[int, int]:
        return (self.x, self.y)

    def to_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y}


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center(self) -> Point:
        return Point(
            x=self.left + self.width // 2,
            y=self.top + self.height // 2,
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
        }


# ---------------------------------------------------------------------------
# TypedDict Definitions
# ---------------------------------------------------------------------------

class WindowInfo(TypedDict, total=False):
    hwnd: int
    title: str
    class_name: str
    rect: Dict[str, int]
    is_visible: bool
    is_enabled: bool
    is_minimized: bool
    is_maximized: bool
    pid: int
    process_name: str


class ElementInfo(TypedDict, total=False):
    index: int
    name: str
    automation_id: str
    control_type: str
    class_name: str
    rect: Dict[str, int]
    is_enabled: bool
    is_offscreen: bool
    has_keyboard_focus: bool
    patterns: List[str]


class Selector(TypedDict, total=False):
    name: Optional[str]
    automation_id: Optional[str]
    control_type: Optional[str]
    class_name: Optional[str]
    index: Optional[int]
    match: Optional[str]
