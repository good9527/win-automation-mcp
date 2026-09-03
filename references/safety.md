# Safety and verification

## Confirmation protocol

The engine recognizes destructive, financial, account, installation, message,
permission, and security-setting actions. Call:

```powershell
python tools.py confirm "install the downloaded application"
```

If `needs_confirmation` is true, stop and ask the user. After the user agrees,
pass `confirmed: true` to `execute_batch` or `--confirmed` to `batch`.

The engine returns this shape without executing any step when confirmation is
missing:

```json
{
  "ok": false,
  "error": "confirmation_required",
  "failure_category": "safety",
  "requires_confirmation": true,
  "confirmations": [{"category": "Delete data", "action": "delete file.txt"}]
}
```

Do not treat `risk_flags` or a successful `check_safety` call as execution
approval. The approval is a separate user decision.

## Verification protocol

An action result of `ok: true` means the automation method completed. It does
not by itself prove that the application reached the intended state. Add one
of the following:

- `expect` in a batch step.
- `verify=true` on a tool that supports it.
- `uia_wait`, `win32_control_wait`, or a wait variant.
- `pixel_wait`, `visual_stable_wait`, or `uia_stable_wait`.
- A negative absence check for dialogs, banners, or old values.

Report both action success and postcondition verification to the caller.
