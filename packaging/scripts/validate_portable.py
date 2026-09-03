import json
import hashlib
import os
import sys


root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app_dir = os.path.join(root, "app")
sys.path.insert(0, app_dir)
os.environ["PYTHONPATH"] = app_dir


def _validate_skill_artifacts() -> dict:
    skill_dir = os.path.join(root, "skill", "desktop-control-portable")
    document_path = os.path.join(skill_dir, "SKILL.md")
    required_references = ("cli.md", "mcp.md", "safety.md", "recovery.md")
    checks = {"document": False, "utf8": False, "frontmatter": False, "references": False, "hash": False}
    errors = []
    try:
        with open(document_path, "r", encoding="utf-8") as handle:
            document = handle.read()
        checks["document"] = True
        checks["utf8"] = "\ufffd" not in document
        if not checks["utf8"]:
            errors.append("SKILL.md contains Unicode replacement characters")
        checks["frontmatter"] = (
            document.startswith("---\n")
            and "\nname: desktop-control-portable\n" in document
            and "\ndescription:" in document
            and "\n---\n" in document[4:]
        )
        if not checks["frontmatter"]:
            errors.append("SKILL.md frontmatter is missing or has the wrong name")
    except Exception as exc:
        errors.append(f"cannot read SKILL.md: {exc}")

    reference_errors = []
    for name in required_references:
        path = os.path.join(skill_dir, "references", name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                if "\ufffd" in handle.read():
                    reference_errors.append(f"{name} contains Unicode replacement characters")
        except Exception as exc:
            reference_errors.append(f"{name}: {exc}")
    checks["references"] = not reference_errors
    errors.extend(reference_errors)

    manifest_path = os.path.join(root, "VERSION.json")
    try:
        with open(manifest_path, "r", encoding="utf-8-sig") as handle:
            manifest = json.load(handle)
        expected_hash = str(manifest.get("skill_document_hash") or "").lower()
        with open(document_path, "rb") as handle:
            actual_hash = hashlib.sha256(handle.read()).hexdigest().lower()
        checks["hash"] = bool(expected_hash and expected_hash == actual_hash)
        if not checks["hash"]:
            errors.append("VERSION.json skill_document_hash does not match installed SKILL.md")
    except Exception as exc:
        errors.append(f"cannot validate VERSION.json skill hash: {exc}")
    return {"ok": not errors and all(checks.values()), "checks": checks, "errors": errors}


skill_contract = _validate_skill_artifacts()
import tools


checks = {
    "skill_contract": skill_contract,
    "selector": tools.selftest_selector(),
    "batch": tools.selftest_batch(),
    "server_contracts": tools.selftest_server_contracts(timeout=45.0),
}
summary = {
    name: {
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
    }
    for name, result in checks.items()
}
summary["ok"] = all(item["ok"] for item in summary.values())
print(json.dumps(summary, ensure_ascii=False, indent=2))
raise SystemExit(0 if summary["ok"] else 1)
