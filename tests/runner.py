# tests/runner.py
# Unified Test Runner for win-automation-mcp

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

import time
import json
import argparse
import unittest
import importlib
from typing import Dict, List, Any, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TIER_MODULES = {
    1: ("Tier 1: Feature Verification", "tests.test_tier1_features"),
    2: ("Tier 2: Boundaries & Corners", "tests.test_tier2_boundaries"),
    3: ("Tier 3: Cross-Feature Combinations", "tests.test_tier3_combinations"),
    4: ("Tier 4: Realistic Scenarios", "tests.test_tier4_scenarios"),
    5: ("Tier 5: Adversarial & Forensic", "tests.test_tier5_adversarial"),
}

class TierTestResult(unittest.TestResult):
    def __init__(self, verbose: bool = False):
        super().__init__()
        self.verbose = verbose
        self.passed: List[unittest.TestCase] = []
        self.start_times: Dict[str, float] = {}
        self.durations: Dict[str, float] = {}

    def startTest(self, test: unittest.TestCase):
        super().startTest(test)
        self.start_times[str(test)] = time.time()
        if self.verbose:
            print(f"  RUN: {test}", end=" ... ", flush=True)

    def addSuccess(self, test: unittest.TestCase):
        super().addSuccess(test)
        self.passed.append(test)
        duration = time.time() - self.start_times.get(str(test), time.time())
        self.durations[str(test)] = duration
        if self.verbose:
            print(f"[PASS] ({duration:.3f}s)")

    def addFailure(self, test: unittest.TestCase, err):
        super().addFailure(test, err)
        duration = time.time() - self.start_times.get(str(test), time.time())
        self.durations[str(test)] = duration
        if self.verbose:
            print(f"[FAIL] ({duration:.3f}s)")

    def addError(self, test: unittest.TestCase, err):
        super().addError(test, err)
        duration = time.time() - self.start_times.get(str(test), time.time())
        self.durations[str(test)] = duration
        if self.verbose:
            print(f"[ERROR] ({duration:.3f}s)")

    def addSkip(self, test: unittest.TestCase, reason: str):
        super().addSkip(test, reason)
        duration = time.time() - self.start_times.get(str(test), time.time())
        self.durations[str(test)] = duration
        if self.verbose:
            print(f"[SKIP] ({reason})")

def filter_suite(suite: unittest.TestSuite, pattern: Optional[str]) -> unittest.TestSuite:
    if not pattern:
        return suite
    filtered = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            sub_filtered = filter_suite(item, pattern)
            if sub_filtered.countTestCases() > 0:
                filtered.addTest(sub_filtered)
        elif isinstance(item, unittest.TestCase):
            test_id = item.id()
            if pattern.lower() in test_id.lower():
                filtered.addTest(item)
    return filtered

def run_tier(tier_num: int, tier_name: str, module_name: str, verbose: bool = False,
             fail_fast: bool = False, pattern: Optional[str] = None) -> Dict[str, Any]:
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return {
            "tier": tier_num, "name": tier_name, "status": "NOT_FOUND",
            "total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
            "duration": 0.0, "failures": [], "error_details": []
        }

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(mod)
    if pattern:
        suite = filter_suite(suite, pattern)

    result = TierTestResult(verbose=verbose)
    result.failfast = fail_fast

    start_time = time.time()
    suite.run(result)
    duration = time.time() - start_time

    failures_list = [{"test": str(t), "trace": tr} for t, tr in result.failures]
    errors_list = [{"test": str(t), "trace": tr} for t, tr in result.errors]

    total_count = result.testsRun
    passed_count = len(result.passed)
    failed_count = len(result.failures)
    error_count = len(result.errors)
    skipped_count = len(result.skipped)

    status = "PASSED" if (failed_count == 0 and error_count == 0 and total_count > 0) else "FAILED"
    if total_count == 0:
        status = "EMPTY"

    return {
        "tier": tier_num, "name": tier_name, "status": status,
        "total": total_count, "passed": passed_count, "failed": failed_count,
        "errors": error_count, "skipped": skipped_count, "duration": duration,
        "failures": failures_list, "error_details": errors_list
    }

def main():
    parser = argparse.ArgumentParser(description="win-automation-mcp Multi-Tier Test Suite Runner")
    parser.add_argument("-t", "--tier", default="all",
                        help="Tiers to run: all, single tier (1), or comma-separated (1,2,3)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose test execution output")
    parser.add_argument("-f", "--fail-fast", action="store_true", help="Stop execution on first failure")
    parser.add_argument("-k", "--pattern", default=None, help="Filter tests by name pattern")
    parser.add_argument("--json", default=None, help="Write summary JSON report to specified path")

    args = parser.parse_args()

    if args.tier == "all":
        target_tiers = [1, 2, 3, 4]
        try:
            importlib.import_module("tests.test_tier5_adversarial")
            target_tiers.append(5)
        except ModuleNotFoundError:
            pass
    else:
        try:
            target_tiers = [int(x.strip()) for x in args.tier.split(",")]
        except ValueError:
            print(f"Error: Invalid tier argument {args.tier}. Use all, 1, 1,2, etc.")
            sys.exit(2)

    print("=" * 76)
    print(" win-automation-mcp Multi-Tier Test Suite Runner")
    print("=" * 76)

    tier_results = []
    total_all = 0
    passed_all = 0
    failed_all = 0
    errors_all = 0
    skipped_all = 0
    total_start = time.time()

    for tier in target_tiers:
        if tier not in TIER_MODULES:
            print(f"[!] Warning: Unknown tier {tier}, skipping.")
            continue
        tier_name, module_name = TIER_MODULES[tier]
        print(f"\n>> Executing [Tier {tier}] {tier_name}...")
        res = run_tier(tier, tier_name, module_name, verbose=args.verbose,
                       fail_fast=args.fail_fast, pattern=args.pattern)
        tier_results.append(res)

        total_all += res["total"]
        passed_all += res["passed"]
        failed_all += res["failed"]
        errors_all += res["errors"]
        skipped_all += res["skipped"]

        if res["status"] == "NOT_FOUND":
            print(f"   [SKIP] Module {module_name} not found (planned for future milestone).")
        elif res["status"] == "EMPTY":
            print(f"   [EMPTY] No tests matched filter pattern in {module_name}.")
        else:
            status_tag = f"[{res['status']}]"
            print(f"   {status_tag:8s} {res['passed']}/{res['total']} passed ({res['failed']} fail, {res['errors']} err, {res['skipped']} skip) in {res['duration']:.3f}s")

        if args.fail_fast and (res["failed"] > 0 or res["errors"] > 0):
            print("\n[!] Fail-fast triggered. Stopping test run.")
            break

    total_duration = time.time() - total_start

    print("\n" + "=" * 76)
    print(" EXECUTION SUMMARY")
    print("=" * 76)
    print(f"{'Tier / Test Suite':<40} | {'Status':<8} | {'Passed':<7} | {'Failed':<6} | {'Time':<7}")
    print("-" * 76)
    for r in tier_results:
        display_name = f"[Tier {r['tier']}] " + r["name"].split(": ")[-1]
        p_str = str(r['passed'])
        f_str = str(r['failed'])
        d_str = f"{r['duration']:.3f}s"
        print(f"{display_name:<40} | {r['status']:<8} | {p_str:<7} | {f_str:<6} | {d_str:<7}")
    print("-" * 76)
    overall_status = "PASSED" if (failed_all == 0 and errors_all == 0 and total_all > 0) else "FAILED"
    p_all_str = str(passed_all)
    f_all_str = str(failed_all)
    t_dur_str = f"{total_duration:.3f}s"
    print(f"{'TOTAL':<40} | {overall_status:<8} | {p_all_str:<7} | {f_all_str:<6} | {t_dur_str:<7}")
    print("=" * 76)

    all_failures = []
    for r in tier_results:
        for f in r["failures"]:
            all_failures.append((r["tier"], f["test"], f["trace"], "FAILURE"))
        for e in r["error_details"]:
            all_failures.append((r["tier"], e["test"], e["trace"], "ERROR"))

    if all_failures:
        print("\n" + "!" * 76)
        print(f" FAILURE & ERROR DETAILS ({len(all_failures)} total)")
        print("!" * 76)
        for tier_num, test_id, trace, ftype in all_failures:
            print(f"\n--- [{ftype}] [Tier {tier_num}] {test_id} ---")
            print(trace.strip())
        print("!" * 76)

    overall_passed = (failed_all == 0 and errors_all == 0 and total_all > 0)
    print(f"\nOVERALL RESULT: {'[PASSED] ALL TESTS SUCCESSFUL' if overall_passed else '[FAILED] SOME TESTS FAILED'}")

    if args.json:
        report_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_tests": total_all,
            "passed": passed_all,
            "failed": failed_all,
            "errors": errors_all,
            "skipped": skipped_all,
            "duration": total_duration,
            "overall_status": "PASSED" if overall_passed else "FAILED",
            "tiers": tier_results
        }
        with open(args.json, "w", encoding="utf-8") as jf:
            json.dump(report_data, jf, indent=2)
        print(f"Report JSON written to: {args.json}")

    sys.exit(0 if overall_passed else 1)

if __name__ == "__main__":
    main()
