# tests/contracts.py
"""
Interface Contracts and Live Package Imports for E2E Test Suite.
Delegates directly to production win_automation modules.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from win_automation.safety.gate import check_safety, DANGEROUS_PATTERNS
from win_automation.helper.security import generate_session_token, verify_request
from win_automation.state.persistence import save_state, load_state
from win_automation.vision.dxcam_manager import DXCamManager
from win_automation.ocr.finder import run_ocr
from win_automation.server.compact_tools import (
    COMPACT_TOOLS,
    COMPACT_TOOL_SCHEMAS,
    get_compact_tool_schemas,
    calculate_serialized_schema_size,
)

__all__ = [
    "COMPACT_TOOLS",
    "COMPACT_TOOL_SCHEMAS",
    "DANGEROUS_PATTERNS",
    "check_safety",
    "generate_session_token",
    "verify_request",
    "save_state",
    "load_state",
    "DXCamManager",
    "run_ocr",
    "get_compact_tool_schemas",
    "calculate_serialized_schema_size",
]
