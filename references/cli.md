# CLI reference

Use `python tools.py <command> ...` from the repository, or use
`$env:DESKTOP_CONTROL_HOME\CONTROL.cmd` from a portable installation.

## Target and lifecycle

```powershell
python tools.py list_windows
python tools.py list_apps
python tools.py launch notepad
python tools.py wait-window --title "Save As" --timeout 10
python tools.py wait-event object-show --hwnd <hwnd> --timeout 5
python tools.py foreground
python tools.py activate <hwnd>
python tools.py focus-hwnd <child_hwnd>
python tools.py control-boundary <hwnd>
python tools.py helper-status
python tools.py helper-status --restart
python tools.py helper-status --elevated --start
```

## Semantic actions

```powershell
python tools.py observe <hwnd>
python tools.py accessibility <hwnd> --view control
python tools.py find <hwnd> --type button --name "Save"
python tools.py wait <hwnd> --type button --name "OK" --timeout 10
python tools.py action <hwnd> <index> Invoke
python tools.py smart-click <hwnd> --name "Save" --type button
python tools.py smart-wait-click <hwnd> --name "OK" --type button --timeout 10 --repair
python tools.py smart-text <hwnd> "query" --name "Search" --type edit
python tools.py smart-wait-text <hwnd> "query" --name "Search" --type edit --timeout 10
python tools.py smart-select <hwnd> "Beta" --type listbox
python tools.py smart-cell <hwnd> --row-text "Beta" --column-name "State"
```

Use `--no-uia` only for a known-bad UIA provider. Use coordinate fallback only
with `--allow-coordinate-fallback` and a fresh screenshot.

## Native and dialog actions

```powershell
python tools.py file-dialog info
python tools.py file-dialog open "C:\Path\file.txt" --verify-close
python tools.py file-dialog cancel --verify-close
python tools.py menu-tree <hwnd>
python tools.py menu-action <hwnd> --path "File/Save"
python tools.py child-windows <hwnd> --include-text
python tools.py window-from-point <x> <y>
python tools.py win32-control-info <hwnd>
python tools.py win32-control-action <hwnd> --action select --text "Beta"
python tools.py msaa-window <hwnd>
python tools.py msaa-action <hwnd> --action default --path "1/2"
```

## Visual fallbacks and verification

```powershell
python tools.py screenshot <hwnd> --output current.png
python tools.py locate-image <hwnd> button.png 0.85
python tools.py image-wait <hwnd> button.png 0.85 --timeout 10
python tools.py ocr <hwnd> --engine windows
python tools.py ocr-wait <hwnd> "Ready" --timeout 10
python tools.py pixel-wait <hwnd> 20 30 "#22c55e" --timeout 5 --tolerance 8
python tools.py visual-stable-wait <hwnd> --timeout 5 --stable-ticks 2
python tools.py uia-stable-wait <hwnd> --timeout 5 --stable-ticks 2
```

## Batch and safety

```powershell
python tools.py confirm "delete file.txt"
python tools.py batch '[{"command":"activate","args":{"hwnd":123}}]' --stop-on-error
python tools.py batch-file workflow.json --stop-on-error --confirmed
python tools.py selftest selector
python tools.py selftest batch
python tools.py selftest server-contracts
```

`--confirmed` is accepted only after explicit user confirmation. Without it,
the engine blocks a batch containing a recognized sensitive action.
