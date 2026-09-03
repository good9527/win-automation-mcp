"""
Safety submodule for desktop automation operations.
"""

from .gate import check_safety, confirm_action, _DANGEROUS_ACTIONS

__all__ = ["check_safety", "confirm_action", "_DANGEROUS_ACTIONS"]
