"""
Safety gate classifier for desktop automation operations.
Implements bilingual (Chinese & English) classification for high-risk operations:
- File destruction (critical risk)
- Financial transactions (critical risk)
- System alterations & shutdown (high risk)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_DANGEROUS_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # 1. File destruction (Critical)
    (
        re.compile(
            r"(删除|清空|格式化|销毁|彻底删除|强力清空|粉碎|清空回收站|del\s+|del\b|delete\s+|delete\b|rmdir|format\s+|format\b|drop\s+table|truncate|delete_file|delete_directory|empty_trash|format_disk|rm\s+-rf|unlink)",
            re.IGNORECASE,
        ),
        "file_destruction",
        "critical",
    ),
    # 2. Financial transactions (Critical)
    (
        re.compile(
            r"(支付|付款|转账|充值|提现|免密支付|结账|购买|买入|转存|扫码支付|pay\s+|pay\b|payment|checkout|transfer\s+|transfer\b|wire\s+|wire\b|buy\s+|buy\b|purchase|order_pay)",
            re.IGNORECASE,
        ),
        "financial_transaction",
        "critical",
    ),
    # 3. System alterations & power management (High)
    (
        re.compile(
            r"(关机|重启|注销|注册表|修改注册表|shutdown|regedit|powershell(\.exe)?(\b|\s+)|\breg(\.exe)?\s+(add|delete|import|copy)\b|taskkill|net\s+stop|kill_process|modify_registry|reboot_system|shutdown_system|run_script|install_software|uninstall_software|update_permissions)",
            re.IGNORECASE,
        ),
        "system_alteration",
        "high",
    ),
]

_LEGACY_DANGEROUS_ACTIONS = {
    "delete_file": {"category": "file_destruction", "risk_level": "critical", "description": "This action permanently deletes a file"},
    "delete_directory": {"category": "file_destruction", "risk_level": "critical", "description": "This action permanently deletes a directory and its contents"},
    "format_disk": {"category": "file_destruction", "risk_level": "critical", "description": "This action formats a disk volume and destroys all data"},
    "empty_trash": {"category": "file_destruction", "risk_level": "critical", "description": "This action permanently removes all items from Recycle Bin"},
    "kill_process": {"category": "system_alteration", "risk_level": "high", "description": "This action forcefully terminates a running process"},
    "reboot_system": {"category": "system_alteration", "risk_level": "high", "description": "This action restarts the computer"},
    "shutdown_system": {"category": "system_alteration", "risk_level": "high", "description": "This action shuts down the computer"},
    "modify_registry": {"category": "system_alteration", "risk_level": "high", "description": "This action modifies Windows Registry settings"},
    "run_script": {"category": "system_alteration", "risk_level": "high", "description": "This action executes arbitrary script code"},
    "install_software": {"category": "system_alteration", "risk_level": "high", "description": "This action installs or modifies system software"},
    "uninstall_software": {"category": "system_alteration", "risk_level": "high", "description": "This action removes installed software"},
    "update_permissions": {"category": "system_alteration", "risk_level": "high", "description": "This action changes permissions"},
}

_DANGEROUS_ACTIONS = _LEGACY_DANGEROUS_ACTIONS
DANGEROUS_PATTERNS = _DANGEROUS_PATTERNS


def check_safety(action: Optional[str]) -> Dict[str, Any]:
    """
    Classify desktop action safety across Chinese and English commands.

    Returns contract dictionary:
    {
        "needs_confirmation": bool,
        "risk_level": "none" | "low" | "medium" | "high" | "critical",
        "category": "file_destruction" | "financial_transaction" | "system_alteration" | "safe",
        "reason": str,
        "description": str,
        "action": str
    }
    """
    if action is None:
        return {
            "needs_confirmation": False,
            "risk_level": "none",
            "category": "safe",
            "reason": "empty input",
            "description": "empty input",
            "action": "",
        }

    raw_action = str(action)
    stripped = raw_action.strip()
    if not stripped:
        return {
            "needs_confirmation": False,
            "risk_level": "none",
            "category": "safe",
            "reason": "empty input",
            "description": "empty input",
            "action": raw_action,
        }

    # Clean zero-width spaces/invisible characters that could bypass simple matching
    clean_action = re.sub(r"[\u200b\u200c\u200d\uFEFF]", "", raw_action)
    # Normalize whitespace between CJK characters (e.g., '删 除' -> '删除')
    clean_action = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", clean_action)

    # Check dangerous pattern matches
    for pattern, category, risk_level in _DANGEROUS_PATTERNS:
        if pattern.search(clean_action):
            reason = f"Matched dangerous pattern in category '{category}'"
            return {
                "needs_confirmation": True,
                "risk_level": risk_level,
                "category": category,
                "reason": reason,
                "description": reason,
                "action": raw_action,
            }

    # Backward compatibility: normalized dictionary lookup
    action_lower = clean_action.lower().replace(" ", "_").replace("-", "_")
    if action_lower in _LEGACY_DANGEROUS_ACTIONS:
        info = _LEGACY_DANGEROUS_ACTIONS[action_lower]
        return {
            "needs_confirmation": True,
            "risk_level": info["risk_level"],
            "category": info["category"],
            "reason": info["description"],
            "description": info["description"],
            "action": raw_action,
        }

    return {
        "needs_confirmation": False,
        "risk_level": "none",
        "category": "safe",
        "reason": "safe",
        "description": "safe",
        "action": raw_action,
    }


def confirm_action(action: Optional[str]) -> Dict[str, Any]:
    """Alias for check_safety."""
    return check_safety(action)
