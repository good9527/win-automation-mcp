"""
Diagnostics and self-testing submodule.
"""

from win_automation.diagnostics.doctor import doctor, run_doctor
from win_automation.diagnostics.selftest import (
    selftest_selector,
    selftest_batch,
    selftest_server_contracts,
    selftest_clipboard,
    selftest_notepad,
    selftest_ocr,
    selftest_win32,
    selftest_uia_patterns,
    run_selftest,
)

__all__ = [
    "doctor",
    "run_doctor",
    "selftest_selector",
    "selftest_batch",
    "selftest_server_contracts",
    "selftest_clipboard",
    "selftest_notepad",
    "selftest_ocr",
    "selftest_win32",
    "selftest_uia_patterns",
    "run_selftest",
]
