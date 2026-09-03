"""
Win32 structures, constants, DLL function signatures, and remote buffer management.
Contains all 29 ctypes structure classes and Windows API wrappers.
"""

from __future__ import annotations

import sys
import ctypes
import ctypes.wintypes

# Win32 DLL handles
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
advapi32 = ctypes.windll.advapi32
shell32 = ctypes.windll.shell32
comdlg32 = ctypes.windll.comdlg32

try:
    shcore = ctypes.windll.shcore
except Exception:
    shcore = None

try:
    dwmapi = ctypes.windll.dwmapi
except Exception:
    dwmapi = None

try:
    comctl32 = ctypes.windll.comctl32
except Exception:
    comctl32 = None

# ---------------------------------------------------------------------------
GWL_STYLE = -16
GWL_EXSTYLE = -20
GWL_WNDPROC = -4
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_TABSTOP = 0x00010000
WS_HSCROLL = 0x00100000
WS_VSCROLL = 0x00200000
SW_RESTORE = 9
SW_SHOWNORMAL = 1
SW_SHOW = 5
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
HWND_TOP = 0
HWND_BOTTOM = 1
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
ASFW_ANY = 0xFFFFFFFF
WPF_SETMINPOSITION = 0x0001
WPF_RESTORETOMAXIMIZED = 0x0002
WPF_ASYNCWINDOWPLACEMENT = 0x0004
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION_CLASS = 20
TOKEN_INTEGRITY_LEVEL_CLASS = 25
TOKEN_UIACCESS_CLASS = 26
SECURITY_MANDATORY_UNTRUSTED_RID = 0x00000000
SECURITY_MANDATORY_LOW_RID = 0x00001000
SECURITY_MANDATORY_MEDIUM_RID = 0x00002000
SECURITY_MANDATORY_MEDIUM_PLUS_RID = 0x00002100
SECURITY_MANDATORY_HIGH_RID = 0x00003000
SECURITY_MANDATORY_SYSTEM_RID = 0x00004000
SECURITY_MANDATORY_PROTECTED_PROCESS_RID = 0x00005000
UOI_NAME = 2
DESKTOP_READOBJECTS = 0x0001
MAX_PATH = 265
MEM_COMMIT = 0x00001000
MEM_RESERVE = 0x00002000
MEM_RELEASE = 0x00008000
PAGE_READWRITE = 0x04
PW_RENDERFULLCONTENT = 0x00000002
CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_DIB = 8
CF_PALETTE = 9
CF_UNICODETEXT = 13
CF_ENHMETAFILE = 14
CF_HDROP = 15
CF_LOCALE = 16
CF_DIBV5 = 17
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
LR_CREATEDIBSECTION = 0x00002000
CLIPBOARD_RETRY_TIMEOUT = 1.5
CLIPBOARD_RETRY_INTERVAL = 0.03
CLIPBOARD_HANDLE_FORMATS = {CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE}
CLIPBOARD_DUPLICABLE_HANDLE_FORMATS = {CF_BITMAP, CF_ENHMETAFILE}
SRCCOPY = 0x00CC0020
WHEEL_DELTA = 120
GA_ROOT = 2
GA_ROOTOWNER = 3
GW_OWNER = 4
MONITOR_DEFAULTTONEAREST = 2
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_SYSCOMMAND = 0x0112
WM_USER = 0x0400
WM_HSCROLL = 0x0114
WM_VSCROLL = 0x0115
WM_NOTIFY = 0x004E
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_CHAR = 0x0102
MK_LBUTTON = 0x0001
IDOK = 1
IDCANCEL = 2
IDABORT = 3
IDRETRY = 4
IDIGNORE = 5
IDYES = 6
IDNO = 7
IDCLOSE = 8
IDHELP = 9
IDTRYAGAIN = 10
IDCONTINUE = 11
OFN_READONLY = 0x00000001
OFN_OVERWRITEPROMPT = 0x00000002
OFN_HIDEREADONLY = 0x00000004
OFN_NOCHANGEDIR = 0x00000008
OFN_SHOWHELP = 0x00000010
OFN_ENABLEHOOK = 0x00000020
OFN_NOVALIDATE = 0x00000100
OFN_ALLOWMULTISELECT = 0x00000200
OFN_EXTENSIONDIFFERENT = 0x00000400
OFN_PATHMUSTEXIST = 0x00000800
OFN_FILEMUSTEXIST = 0x00001000
OFN_CREATEPROMPT = 0x00002000
OFN_SHAREAWARE = 0x00004000
OFN_NOREADONLYRETURN = 0x00008000
OFN_NOTESTFILECREATE = 0x00010000
OFN_NONETWORKBUTTON = 0x00020000
OFN_NOLONGNAMES = 0x00040000
OFN_EXPLORER = 0x00080000
OFN_NODEREFERENCELINKS = 0x00100000
OFN_LONGNAMES = 0x00200000
BM_CLICK = 0x00F5
BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BN_CLICKED = 0
BST_CHECKED = 1
BST_UNCHECKED = 0
BST_INDETERMINATE = 2
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_AUTOHSCROLL = 0x0080
CBS_SIMPLE = 0x0001
CBS_DROPDOWN = 0x0002
CBS_DROPDOWNLIST = 0x0003
CBS_HASSTRINGS = 0x0200
SBS_HORZ = 0x0000
SBS_VERT = 0x0001
SBS_SIZEBOX = 0x0008
SB_LINEUP = 0
SB_LINELEFT = 0
SB_LINEDOWN = 1
SB_LINERIGHT = 1
SB_PAGEUP = 2
SB_PAGELEFT = 2
SB_PAGEDOWN = 3
SB_PAGERIGHT = 3
SB_THUMBPOSITION = 4
SB_THUMBTRACK = 5
SB_TOP = 6
SB_LEFT = 6
SB_BOTTOM = 7
SB_RIGHT = 7
SB_ENDSCROLL = 8
SB_CTL = 2
SIF_RANGE = 0x0001
SIF_PAGE = 0x0002
SIF_POS = 0x0004
SIF_DISABLENOSCROLL = 0x0008
SIF_TRACKPOS = 0x0010
SIF_ALL = SIF_RANGE | SIF_PAGE | SIF_POS | SIF_TRACKPOS
CB_GETEDITSEL = 0x0140
CB_SETEDITSEL = 0x0142
CB_ADDSTRING = 0x0143
CB_GETCOUNT = 0x0146
CB_GETCURSEL = 0x0147
CB_GETLBTEXT = 0x0148
CB_GETLBTEXTLEN = 0x0149
CB_SETCURSEL = 0x014E
CBN_SELCHANGE = 1
CBN_EDITCHANGE = 5
CBN_EDITUPDATE = 6
CBEM_INSERTITEMW = WM_USER + 11
CBEM_SETITEMW = WM_USER + 12
CBEM_GETITEMW = WM_USER + 13
CBEM_GETCOMBOCONTROL = WM_USER + 6
CBEM_GETEDITCONTROL = WM_USER + 7
CBEIF_TEXT = 0x00000001
CBEIF_IMAGE = 0x00000002
CBEIF_SELECTEDIMAGE = 0x00000004
CBEIF_OVERLAY = 0x00000008
CBEIF_INDENT = 0x00000010
CBEIF_LPARAM = 0x00000020
CBEIF_DI_SETITEM = 0x10000000
LBS_NOTIFY = 0x0001
LB_ADDSTRING = 0x0180
LB_SETSEL = 0x0185
LB_SETCURSEL = 0x0186
LB_GETSEL = 0x0187
LB_GETCURSEL = 0x0188
LB_GETTEXT = 0x0189
LB_GETTEXTLEN = 0x018A
LB_GETCOUNT = 0x018B
LB_GETITEMRECT = 0x0198
LBN_SELCHANGE = 1
LBN_DBLCLK = 2
BS_CHECKBOX = 0x0002
BS_AUTOCHECKBOX = 0x0003
BS_RADIOBUTTON = 0x0004
BS_3STATE = 0x0005
BS_AUTO3STATE = 0x0006
BS_AUTORADIOBUTTON = 0x0009
LVS_REPORT = 0x0001
LVS_EX_CHECKBOXES = 0x00000004
TVS_HASBUTTONS = 0x0001
TVS_HASLINES = 0x0002
TVS_LINESATROOT = 0x0004
TVS_CHECKBOXES = 0x0100
SMTO_ABORTIFHUNG = 0x0002
PM_REMOVE = 0x0001
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
EVENT_MIN = 0x00000001
EVENT_MAX = 0x7FFFFFFF
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MENUSTART = 0x0004
EVENT_SYSTEM_MENUEND = 0x0005
EVENT_SYSTEM_DIALOGSTART = 0x0010
EVENT_SYSTEM_DIALOGEND = 0x0011
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_REORDER = 0x8004
EVENT_OBJECT_FOCUS = 0x8005
EVENT_OBJECT_SELECTION = 0x8006
EVENT_OBJECT_VALUECHANGE = 0x800E
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_NAMECHANGE = 0x800C
CWP_SKIPINVISIBLE = 0x0001
CWP_SKIPDISABLED = 0x0002
CWP_SKIPTRANSPARENT = 0x0004
OBJID_CLIENT_SIGNED = -4
OBJID_CLIENT = OBJID_CLIENT_SIGNED & 0xFFFFFFFF
MF_STRING = 0x0000
MF_GRAYED = 0x0001
MF_DISABLED = 0x0002
MF_CHECKED = 0x0008
MF_POPUP = 0x0010
MF_SEPARATOR = 0x0800
MF_BYCOMMAND = 0x0000
MF_BYPOSITION = 0x0400
MENU_ID_INVALID = 0xFFFFFFFF
MESSAGE_RESULT_ERROR = ctypes.c_size_t(-1).value
LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETNEXTITEM = LVM_FIRST + 12
LVM_GETITEMRECT = LVM_FIRST + 14
LVM_ENSUREVISIBLE = LVM_FIRST + 19
LVM_SETITEMSTATE = LVM_FIRST + 43
LVM_GETITEMSTATE = LVM_FIRST + 44
LVM_GETCOLUMNWIDTH = LVM_FIRST + 29
LVM_SETCOLUMNWIDTH = LVM_FIRST + 30
LVM_GETHEADER = LVM_FIRST + 31
LVM_SETEXTENDEDLISTVIEWSTYLE = LVM_FIRST + 54
LVM_GETEXTENDEDLISTVIEWSTYLE = LVM_FIRST + 55
LVM_INSERTITEMW = LVM_FIRST + 77
LVM_GETCOLUMNW = LVM_FIRST + 95
LVM_INSERTCOLUMNW = LVM_FIRST + 97
LVM_GETITEMTEXTW = LVM_FIRST + 115
LVM_SETITEMTEXTW = LVM_FIRST + 116
LVIF_TEXT = 0x0001
LVIF_STATE = 0x0008
LVIS_FOCUSED = 0x0001
LVIS_SELECTED = 0x0002
LVIS_STATEIMAGEMASK = 0xF000
LVNI_SELECTED = 0x0002
LVIR_BOUNDS = 0
LVIR_ICON = 1
LVIR_LABEL = 2
LVIR_SELECTBOUNDS = 3
LVCF_FMT = 0x0001
LVCF_WIDTH = 0x0002
LVCF_TEXT = 0x0004
LVCF_SUBITEM = 0x0008
LVCFMT_LEFT = 0x0000
HDM_FIRST = 0x1200
HDM_GETITEMCOUNT = HDM_FIRST + 0
HDM_INSERTITEMW = HDM_FIRST + 10
HDM_GETITEMW = HDM_FIRST + 11
HDM_SETITEMW = HDM_FIRST + 12
HDM_GETITEMRECT = HDM_FIRST + 7
HDM_GETORDERARRAY = HDM_FIRST + 17
HDM_SETORDERARRAY = HDM_FIRST + 18
HDI_WIDTH = 0x0001
HDI_TEXT = 0x0002
HDI_FORMAT = 0x0004
HDI_LPARAM = 0x0008
HDI_IMAGE = 0x0020
HDI_ORDER = 0x0080
HDI_STATE = 0x0200
HDF_LEFT = 0x0000
HDF_STRING = 0x4000
HDS_BUTTONS = 0x0002
TCM_FIRST = 0x1300
TCM_GETITEMCOUNT = TCM_FIRST + 4
TCM_GETITEMW = TCM_FIRST + 60
TCM_INSERTITEMW = TCM_FIRST + 62
TCM_SETCURSEL = TCM_FIRST + 12
TCM_GETCURSEL = TCM_FIRST + 11
TCN_FIRST = -550
TCN_SELCHANGE = TCN_FIRST - 1
TCN_SELCHANGING = TCN_FIRST - 2
TCIF_TEXT = 0x0001
TB_ENABLEBUTTON = 0x0401
TB_CHECKBUTTON = 0x0402
TB_PRESSBUTTON = 0x0403
TB_BUTTONSTRUCTSIZE = 0x041E
TB_ADDBUTTONSW = 0x0444
TB_ADDSTRINGW = 0x044D
TB_BUTTONCOUNT = 0x0418
TB_COMMANDTOINDEX = 0x0419
TB_GETBUTTON = 0x0417
TB_GETITEMRECT = 0x041D
TB_GETBUTTONTEXTW = 0x044B
TB_GETTOOLTIPS = 0x0423
TB_SETTOOLTIPS = 0x0424
TBSTATE_CHECKED = 0x01
TBSTATE_PRESSED = 0x02
TBSTATE_ENABLED = 0x04
TBSTATE_HIDDEN = 0x08
TBSTYLE_BUTTON = 0x0000
TBSTYLE_SEP = 0x0001
TTS_ALWAYSTIP = 0x01
TTS_NOPREFIX = 0x02
TTF_IDISHWND = 0x0001
TTF_SUBCLASS = 0x0010
TTM_ACTIVATE = WM_USER + 1
TTM_ADDTOOLW = WM_USER + 50
TTM_DELTOOLW = WM_USER + 51
TTM_GETTEXTW = WM_USER + 56
TTM_UPDATETIPTEXTW = WM_USER + 57
TTM_GETTOOLCOUNT = WM_USER + 13
TTM_ENUMTOOLW = WM_USER + 58
TTM_GETTOOLINFOW = WM_USER + 53
SB_SETPARTS = WM_USER + 4
SB_GETPARTS = WM_USER + 6
SB_GETRECT = WM_USER + 10
SB_SETTEXTW = WM_USER + 11
SB_GETTEXTLENGTHW = WM_USER + 12
SB_GETTEXTW = WM_USER + 13
SBT_NOBORDERS = 0x0100
SBT_POPOUT = 0x0200
SBT_RTLREADING = 0x0400
SBT_OWNERDRAW = 0x1000
TBM_GETPOS = WM_USER
TBM_GETRANGEMIN = WM_USER + 1
TBM_GETRANGEMAX = WM_USER + 2
TBM_SETPOS = WM_USER + 5
TBM_SETRANGE = WM_USER + 6
TBM_SETRANGEMIN = WM_USER + 7
TBM_SETRANGEMAX = WM_USER + 8
TBM_GETLINESIZE = WM_USER + 24
TBM_GETPAGESIZE = WM_USER + 22
TBS_VERT = 0x0002
TB_THUMBPOSITION = 4
TB_ENDTRACK = 8
UDS_SETBUDDYINT = 0x0002
UDM_SETBUDDY = WM_USER + 105
UDM_GETBUDDY = WM_USER + 106
UDM_SETRANGE32 = WM_USER + 111
UDM_GETRANGE32 = WM_USER + 112
UDM_SETPOS32 = WM_USER + 113
UDM_GETPOS32 = WM_USER + 114
PBM_SETRANGE32 = WM_USER + 6
PBM_GETRANGE = WM_USER + 7
PBM_GETPOS = WM_USER + 8
PBM_SETPOS = WM_USER + 2
PBM_DELTAPOS = WM_USER + 3
PBM_SETSTEP = WM_USER + 4
PBM_STEPIT = WM_USER + 5
DTM_FIRST = 0x1000
DTM_GETSYSTEMTIME = DTM_FIRST + 1
DTM_SETSYSTEMTIME = DTM_FIRST + 2
MCM_FIRST = 0x1000
MCM_GETCURSEL = MCM_FIRST + 1
MCM_SETCURSEL = MCM_FIRST + 2
GDT_VALID = 0
GDT_NONE = 1
GDT_ERROR = -1
IPM_CLEARADDRESS = WM_USER + 100
IPM_SETADDRESS = WM_USER + 101
IPM_GETADDRESS = WM_USER + 102
IPM_ISBLANK = WM_USER + 105
SS_LEFT = 0x0000
SS_CENTER = 0x0001
SS_RIGHT = 0x0002
SS_ICON = 0x0003
SS_BLACKRECT = 0x0004
SS_GRAYRECT = 0x0005
SS_WHITERECT = 0x0006
SS_BLACKFRAME = 0x0007
SS_GRAYFRAME = 0x0008
SS_WHITEFRAME = 0x0009
SS_USERITEM = 0x000A
SS_SIMPLE = 0x000B
SS_LEFTNOWORDWRAP = 0x000C
SS_OWNERDRAW = 0x000D
SS_BITMAP = 0x000E
SS_ENHMETAFILE = 0x000F
SS_ETCHEDHORZ = 0x0010
SS_ETCHEDVERT = 0x0011
SS_ETCHEDFRAME = 0x0012
SS_TYPEMASK = 0x001F
SS_NOTIFY = 0x0100
STM_SETIMAGE = 0x0172
STM_GETIMAGE = 0x0173
STN_CLICKED = 0
IMAGE_BITMAP = 0
IMAGE_ICON = 1
IMAGE_CURSOR = 2
IMAGE_ENHMETAFILE = 3
HKM_SETHOTKEY = WM_USER + 1
HKM_GETHOTKEY = WM_USER + 2
HKM_SETRULES = WM_USER + 3
HOTKEYF_SHIFT = 0x01
HOTKEYF_CONTROL = 0x02
HOTKEYF_ALT = 0x04
HOTKEYF_EXT = 0x08
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_MENU = 0x12
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_INSERT = 0x2D
VK_DELETE = 0x2E
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
L_MAX_URL_LENGTH = 2084
MAX_LINKID_TEXT = 48
LIF_ITEMINDEX = 0x00000001
LIF_STATE = 0x00000002
LIF_ITEMID = 0x00000004
LIF_URL = 0x00000008
LIS_FOCUSED = 0x00000001
LIS_ENABLED = 0x00000002
LIS_VISITED = 0x00000004
LIS_HOTTRACK = 0x00000008
LIS_DEFAULTCOLORS = 0x00000010
LM_HITTEST = WM_USER + 0x300
LM_GETIDEALHEIGHT = WM_USER + 0x301
LM_SETITEM = WM_USER + 0x302
LM_GETITEM = WM_USER + 0x303
EM_GETSEL = 0x00B0
EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2
EM_GETLINECOUNT = 0x00BA
EM_GETLIMITTEXT = WM_USER + 37
EM_EXGETSEL = WM_USER + 52
EM_EXSETSEL = WM_USER + 55
EM_SETLIMITTEXT = WM_USER + 53
EN_CHANGE = 0x0300
TV_FIRST = 0x1100
TVM_EXPAND = TV_FIRST + 2
TVM_GETITEMRECT = TV_FIRST + 4
TVM_GETNEXTITEM = TV_FIRST + 10
TVM_SELECTITEM = TV_FIRST + 11
TVM_ENSUREVISIBLE = TV_FIRST + 20
TVM_INSERTITEMW = TV_FIRST + 50
TVM_GETITEMW = TV_FIRST + 62
TVM_SETITEMW = TV_FIRST + 63
TVGN_ROOT = 0x0000
TVGN_NEXT = 0x0001
TVGN_CHILD = 0x0004
TVGN_CARET = 0x0009
TVE_COLLAPSE = 0x0001
TVE_EXPAND = 0x0002
TVIF_TEXT = 0x0001
TVIF_STATE = 0x0008
TVIS_SELECTED = 0x0002
TVIS_EXPANDED = 0x0020
TVIS_STATEIMAGEMASK = 0xF000
TVI_ROOT = ctypes.c_void_p(ctypes.c_size_t(-0x10000).value).value
TVI_LAST = ctypes.c_void_p(ctypes.c_size_t(-0x0FFFE).value).value
ICC_LISTVIEW_CLASSES = 0x00000001
ICC_TREEVIEW_CLASSES = 0x00000002
ICC_TAB_CLASSES = 0x00000008
ICC_BAR_CLASSES = 0x00000004
ICC_UPDOWN_CLASS = 0x00000010
ICC_PROGRESS_CLASS = 0x00000020
ICC_DATE_CLASSES = 0x00000100
ICC_INTERNET_CLASSES = 0x00000800
ICC_HOTKEY_CLASS = 0x00000040
ICC_LINK_CLASS = 0x00008000
ICC_USEREX_CLASSES = 0x00000200

MSAA_SELF = 0
MSAA_SELECT_TAKEFOCUS = 0x00000001
MSAA_SELECT_TAKESELECTION = 0x00000002
MSAA_SELECT_EXTENDSELECTION = 0x00000004
MSAA_SELECT_ADDSELECTION = 0x00000008
MSAA_SELECT_REMOVESELECTION = 0x00000010


def _dedupe_preserve_order(items: List[Any]) -> List[Any]:
    result: List[Any] = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _coerce_bool(value: Any, default: bool = False) -> bool:
    """Parse bool-like CLI/MCP values without treating every non-empty string as true."""
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on", "enable", "enabled"):
        return True
    if text in ("0", "false", "no", "n", "off", "disable", "disabled", "none", "null"):
        return False
    return bool(default)


def _dict_get_any(data: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return _coerce_bool(value, False)


UIA_PATTERN_IDS = {
    "Invoke": 10000,
    "Selection": 10001,
    "Value": 10002,
    "RangeValue": 10003,
    "Scroll": 10004,
    "ExpandCollapse": 10005,
    "Grid": 10006,
    "GridItem": 10007,
    "MultipleView": 10008,
    "Window": 10009,
    "SelectionItem": 10010,
    "Dock": 10011,
    "Table": 10012,
    "TableItem": 10013,
    "Text": 10014,
    "Toggle": 10015,
    "Transform": 10016,
    "ScrollItem": 10017,
    "LegacyIAccessible": 10018,
    "ItemContainer": 10019,
    "VirtualizedItem": 10020,
    "SynchronizedInput": 10021,
    "ObjectModel": 10022,
    "Annotation": 10023,
    "Text2": 10024,
    "Styles": 10025,
    "Spreadsheet": 10026,
    "SpreadsheetItem": 10027,
    "Transform2": 10028,
    "TextChild": 10029,
    "Drag": 10030,
    "DropTarget": 10031,
    "TextEdit": 10032,
    "CustomNavigation": 10033,
    "Selection2": 10034,
}

UIA_PROPERTY_IDS = {
    "control_type": 30003,
    "controltype": 30003,
    "localized_control_type": 30004,
    "localizedcontroltype": 30004,
    "type": 30004,
    "name": 30005,
    "automation_id": 30011,
    "automationid": 30011,
    "id": 30011,
    "class_name": 30012,
    "classname": 30012,
    "class": 30012,
    "help_text": 30013,
    "helptext": 30013,
    "access_key": 30007,
    "accesskey": 30007,
    "accelerator_key": 30006,
    "acceleratorkey": 30006,
    "item_type": 30021,
    "itemtype": 30021,
    "is_offscreen": 30022,
    "isoffscreen": 30022,
    "framework_id": 30024,
    "frameworkid": 30024,
    "item_status": 30026,
    "itemstatus": 30026,
    "value": 30045,
    "legacy_name": 30092,
    "legacy_value": 30093,
    "legacy_description": 30094,
}

UIA_CONTROL_TYPE_IDS = {
    "button": 50000,
    "calendar": 50001,
    "checkbox": 50002,
    "combo_box": 50003,
    "combobox": 50003,
    "edit": 50004,
    "hyperlink": 50005,
    "image": 50006,
    "list_item": 50007,
    "listitem": 50007,
    "list": 50008,
    "menu": 50009,
    "menu_bar": 50010,
    "menubar": 50010,
    "menu_item": 50011,
    "menuitem": 50011,
    "progress_bar": 50012,
    "progressbar": 50012,
    "radio_button": 50013,
    "radiobutton": 50013,
    "scroll_bar": 50014,
    "scrollbar": 50014,
    "slider": 50015,
    "spinner": 50016,
    "status_bar": 50017,
    "statusbar": 50017,
    "tab": 50018,
    "tab_item": 50019,
    "tabitem": 50019,
    "text": 50020,
    "tool_bar": 50021,
    "toolbar": 50021,
    "tool_tip": 50022,
    "tooltip": 50022,
    "tree": 50023,
    "tree_item": 50024,
    "treeitem": 50024,
    "custom": 50025,
    "group": 50026,
    "thumb": 50027,
    "data_grid": 50028,
    "datagrid": 50028,
    "data_item": 50029,
    "dataitem": 50029,
    "document": 50030,
    "split_button": 50031,
    "splitbutton": 50031,
    "window": 50032,
    "pane": 50033,
    "header": 50034,
    "header_item": 50035,
    "headeritem": 50035,
    "table": 50036,
    "title_bar": 50037,
    "titlebar": 50037,
    "separator": 50038,
    "semantic_zoom": 50039,
    "semanticzoom": 50039,
    "app_bar": 50040,
    "appbar": 50040,
}

UIA_SCROLL_NO_AMOUNT = 2
UIA_SCROLL_AMOUNT_VALUES = {
    "large_decrement": 0,
    "largedecrement": 0,
    "large-decrement": 0,
    "page_up": 0,
    "page-up": 0,
    "page_left": 0,
    "page-left": 0,
    "small_decrement": 1,
    "smalldecrement": 1,
    "small-decrement": 1,
    "line_up": 1,
    "line-up": 1,
    "line_left": 1,
    "line-left": 1,
    "no_amount": 2,
    "noamount": 2,
    "no-amount": 2,
    "none": 2,
    "large_increment": 3,
    "largeincrement": 3,
    "large-increment": 3,
    "page_down": 3,
    "page-down": 3,
    "page_right": 3,
    "page-right": 3,
    "small_increment": 4,
    "smallincrement": 4,
    "small-increment": 4,
    "line_down": 4,
    "line-down": 4,
    "line_right": 4,
    "line-right": 4,
}

UIA_TEXT_ENDPOINT_START = 0
UIA_TEXT_ENDPOINT_END = 1
UIA_TEXT_UNIT_VALUES = {
    "character": 0,
    "char": 0,
    "format": 1,
    "word": 2,
    "line": 3,
    "paragraph": 4,
    "page": 5,
    "document": 6,
}

UIA_ZOOM_UNIT_VALUES = {
    "no_amount": 0,
    "noamount": 0,
    "no-amount": 0,
    "large_decrement": 1,
    "largedecrement": 1,
    "large-decrement": 1,
    "small_decrement": 2,
    "smalldecrement": 2,
    "small-decrement": 2,
    "large_increment": 3,
    "largeincrement": 3,
    "large-increment": 3,
    "small_increment": 4,
    "smallincrement": 4,
    "small-increment": 4,
}

UIA_SYNC_INPUT_TYPE_VALUES = {
    "keyup": 1,
    "key_up": 1,
    "key-up": 1,
    "keydown": 2,
    "key_down": 2,
    "key-down": 2,
    "leftmouseup": 4,
    "left_mouse_up": 4,
    "left-mouse-up": 4,
    "leftmousedown": 8,
    "left_mouse_down": 8,
    "left-mouse-down": 8,
    "rightmouseup": 16,
    "right_mouse_up": 16,
    "right-mouse-up": 16,
    "rightmousedown": 32,
    "right_mouse_down": 32,
    "right-mouse-down": 32,
}

UIA_NAVIGATION_DIRECTION_VALUES = {
    "parent": 0,
    "next_sibling": 1,
    "next-sibling": 1,
    "next": 1,
    "previous_sibling": 2,
    "previous-sibling": 2,
    "previous": 2,
    "prev": 2,
    "first_child": 3,
    "first-child": 3,
    "first": 3,
    "last_child": 4,
    "last-child": 4,
    "last": 4,
}

UIA_DOCK_POSITION_VALUES = {
    "top": 0,
    "left": 1,
    "bottom": 2,
    "right": 3,
    "fill": 4,
    "none": 5,
}

UIA_DOCK_POSITION_NAMES = {
    0: "top",
    1: "left",
    2: "bottom",
    3: "right",
    4: "fill",
    5: "none",
}

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000

# ---------------------------------------------------------------------------
# Windows API handles
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
advapi32 = ctypes.windll.advapi32
gdi32 = ctypes.windll.gdi32
comdlg32 = ctypes.windll.comdlg32

# ---------------------------------------------------------------------------
# Function prototypes
# ---------------------------------------------------------------------------
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.CreateWindowExW.argtypes = [
    ctypes.c_ulong,
    ctypes.c_wchar_p,
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
user32.CreateWindowExW.restype = ctypes.c_void_p
user32.DestroyWindow.argtypes = [ctypes.c_void_p]
user32.DestroyWindow.restype = ctypes.c_bool
user32.UpdateWindow.argtypes = [ctypes.c_void_p]
user32.UpdateWindow.restype = ctypes.c_bool
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.IsWindow.argtypes = [ctypes.c_void_p]
user32.IsWindow.restype = ctypes.c_bool
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetGUIThreadInfo.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
user32.GetGUIThreadInfo.restype = ctypes.c_bool
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
if ctypes.sizeof(ctypes.c_void_p) == 8:
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
else:
    user32.GetWindowLongPtrW = user32.GetWindowLongW
    user32.SetWindowLongPtrW = user32.SetWindowLongW
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool
user32.SetWindowPos.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = ctypes.c_bool
user32.GetWindowPlacement.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetWindowPlacement.restype = ctypes.c_bool
user32.SetWindowPlacement.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.SetWindowPlacement.restype = ctypes.c_bool
user32.MoveWindow.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_bool,
]
user32.MoveWindow.restype = ctypes.c_bool
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_bool
try:
    user32.AllowSetForegroundWindow.argtypes = [ctypes.c_ulong]
    user32.AllowSetForegroundWindow.restype = ctypes.c_bool
except Exception:
    pass
try:
    user32.SwitchToThisWindow.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    user32.SwitchToThisWindow.restype = None
except Exception:
    pass
user32.GetProcessWindowStation.argtypes = []
user32.GetProcessWindowStation.restype = ctypes.c_void_p
user32.GetThreadDesktop.argtypes = [ctypes.c_ulong]
user32.GetThreadDesktop.restype = ctypes.c_void_p
user32.GetUserObjectInformationW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
user32.GetUserObjectInformationW.restype = ctypes.c_bool
user32.OpenInputDesktop.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
user32.OpenInputDesktop.restype = ctypes.c_void_p
user32.CloseDesktop.argtypes = [ctypes.c_void_p]
user32.CloseDesktop.restype = ctypes.c_bool
user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
user32.BringWindowToTop.restype = ctypes.c_bool
user32.SetFocus.argtypes = [ctypes.c_void_p]
user32.SetFocus.restype = ctypes.c_void_p
user32.GetFocus.argtypes = []
user32.GetFocus.restype = ctypes.c_void_p
user32.SetActiveWindow.argtypes = [ctypes.c_void_p]
user32.SetActiveWindow.restype = ctypes.c_void_p
user32.GetActiveWindow.argtypes = []
user32.GetActiveWindow.restype = ctypes.c_void_p
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetWindow.restype = ctypes.c_void_p
user32.GetCursorPos.argtypes = [ctypes.POINTER(ctypes.wintypes.POINT)]
user32.GetCursorPos.restype = ctypes.c_bool
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetParent.argtypes = [ctypes.c_void_p]
user32.GetParent.restype = ctypes.c_void_p
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetDlgCtrlID.argtypes = [ctypes.c_void_p]
user32.GetDlgCtrlID.restype = ctypes.c_int
user32.IsWindowEnabled.argtypes = [ctypes.c_void_p]
user32.IsWindowEnabled.restype = ctypes.c_bool
user32.IsIconic.argtypes = [ctypes.c_void_p]
user32.IsIconic.restype = ctypes.c_bool
user32.IsZoomed.argtypes = [ctypes.c_void_p]
user32.IsZoomed.restype = ctypes.c_bool
user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetClientRect.restype = ctypes.c_bool
user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.POINT)]
user32.ClientToScreen.restype = ctypes.c_bool
user32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.POINT)]
user32.ScreenToClient.restype = ctypes.c_bool
user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.ChildWindowFromPointEx.argtypes = [ctypes.c_void_p, ctypes.wintypes.POINT, ctypes.c_uint]
user32.ChildWindowFromPointEx.restype = ctypes.c_void_p
user32.RealChildWindowFromPoint.argtypes = [ctypes.c_void_p, ctypes.wintypes.POINT]
user32.RealChildWindowFromPoint.restype = ctypes.c_void_p
user32.EnumChildWindows.argtypes = [ctypes.c_void_p, ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p), ctypes.c_void_p]
user32.EnumChildWindows.restype = ctypes.c_bool
user32.SendMessageTimeoutW.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
    ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = ctypes.c_void_p
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.PostMessageW.restype = ctypes.c_bool
comdlg32.GetOpenFileNameW.argtypes = [ctypes.c_void_p]
comdlg32.GetOpenFileNameW.restype = ctypes.c_bool
comdlg32.CommDlgExtendedError.argtypes = []
comdlg32.CommDlgExtendedError.restype = ctypes.c_ulong
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.CallWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.PeekMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
user32.PeekMessageW.restype = ctypes.c_bool
user32.TranslateMessage.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
user32.TranslateMessage.restype = ctypes.c_bool
user32.DispatchMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_long,
    ctypes.c_long,
    ctypes.c_ulong,
    ctypes.c_ulong,
)
user32.SetWinEventHook.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, WinEventProcType, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_uint]
user32.SetWinEventHook.restype = ctypes.c_void_p
user32.UnhookWinEvent.argtypes = [ctypes.c_void_p]
user32.UnhookWinEvent.restype = ctypes.c_bool
user32.GetMenu.argtypes = [ctypes.c_void_p]
user32.GetMenu.restype = ctypes.c_void_p
user32.GetSystemMenu.argtypes = [ctypes.c_void_p, ctypes.c_bool]
user32.GetSystemMenu.restype = ctypes.c_void_p
user32.GetMenuItemCount.argtypes = [ctypes.c_void_p]
user32.GetMenuItemCount.restype = ctypes.c_int
user32.GetSubMenu.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetSubMenu.restype = ctypes.c_void_p
user32.GetMenuItemID.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetMenuItemID.restype = ctypes.c_uint
user32.GetMenuStringW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint]
user32.GetMenuStringW.restype = ctypes.c_int
user32.GetMenuState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
user32.GetMenuState.restype = ctypes.c_uint
user32.CreateMenu.argtypes = []
user32.CreateMenu.restype = ctypes.c_void_p
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = ctypes.c_void_p
user32.AppendMenuW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_wchar_p]
user32.AppendMenuW.restype = ctypes.c_bool
user32.SetMenu.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.SetMenu.restype = ctypes.c_bool
user32.DrawMenuBar.argtypes = [ctypes.c_void_p]
user32.DrawMenuBar.restype = ctypes.c_bool
user32.DestroyMenu.argtypes = [ctypes.c_void_p]
user32.DestroyMenu.restype = ctypes.c_bool
user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
user32.AttachThreadInput.restype = ctypes.c_bool
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.c_bool
user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
user32.PrintWindow.restype = ctypes.c_bool
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetScrollInfo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
user32.GetScrollInfo.restype = ctypes.c_bool
user32.SetScrollInfo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_bool]
user32.SetScrollInfo.restype = ctypes.c_int
user32.OpenClipboard.argtypes = [ctypes.c_void_p]
user32.OpenClipboard.restype = ctypes.c_bool
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.c_bool
user32.EnumClipboardFormats.argtypes = [ctypes.c_uint]
user32.EnumClipboardFormats.restype = ctypes.c_uint
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.c_bool
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = ctypes.c_bool
user32.mouse_event.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
user32.mouse_event.restype = None
user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint
user32.CopyImage.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.CopyImage.restype = ctypes.c_void_p
kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = ctypes.c_ulong
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.restype = ctypes.c_uint

# DWM Frame Bounds API
try:
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
except Exception:
    pass

kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_bool
kernel32.VirtualAllocEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
kernel32.VirtualFreeEx.restype = ctypes.c_bool
kernel32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = ctypes.c_bool
kernel32.WriteProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = ctypes.c_bool
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)
]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_bool
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype = ctypes.c_void_p
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = ctypes.c_void_p
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = ctypes.c_ulong
kernel32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
kernel32.LoadLibraryW.restype = ctypes.c_void_p
advapi32.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
advapi32.OpenProcessToken.restype = ctypes.c_bool
advapi32.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
advapi32.GetTokenInformation.restype = ctypes.c_bool
advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
advapi32.GetLengthSid.restype = ctypes.c_ulong
advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
advapi32.GetSidSubAuthority.restype = ctypes.POINTER(ctypes.c_ulong)
shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = ctypes.c_bool

gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = ctypes.c_bool
gdi32.CopyEnhMetaFileW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
gdi32.CopyEnhMetaFileW.restype = ctypes.c_void_p
gdi32.DeleteEnhMetaFile.argtypes = [ctypes.c_void_p]
gdi32.DeleteEnhMetaFile.restype = ctypes.c_bool
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = ctypes.c_bool
gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.BitBlt.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong,
]
gdi32.BitBlt.restype = ctypes.c_bool
try:
    comctl32 = ctypes.windll.comctl32
except Exception:
    comctl32 = None

# ---------------------------------------------------------------------------
# Structures
# ---------------------------------------------------------------------------

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", ctypes.wintypes.RECT),
    ]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("showCmd", ctypes.c_uint),
        ("ptMinPosition", ctypes.wintypes.POINT),
        ("ptMaxPosition", ctypes.wintypes.POINT),
        ("rcNormalPosition", ctypes.wintypes.RECT),
    ]


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", ctypes.c_uint),
        ("hwndOwner", ctypes.c_void_p),
        ("hInstance", ctypes.c_void_p),
        ("lpstrFilter", ctypes.c_wchar_p),
        ("lpstrCustomFilter", ctypes.c_wchar_p),
        ("nMaxCustFilter", ctypes.c_uint),
        ("nFilterIndex", ctypes.c_uint),
        ("lpstrFile", ctypes.c_wchar_p),
        ("nMaxFile", ctypes.c_uint),
        ("lpstrFileTitle", ctypes.c_wchar_p),
        ("nMaxFileTitle", ctypes.c_uint),
        ("lpstrInitialDir", ctypes.c_wchar_p),
        ("lpstrTitle", ctypes.c_wchar_p),
        ("Flags", ctypes.c_uint),
        ("nFileOffset", ctypes.c_ushort),
        ("nFileExtension", ctypes.c_ushort),
        ("lpstrDefExt", ctypes.c_wchar_p),
        ("lCustData", ctypes.c_ssize_t),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", ctypes.c_wchar_p),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", ctypes.c_uint),
        ("FlagsEx", ctypes.c_uint),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", ctypes.c_ulong),
    ]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [
        ("Label", SID_AND_ATTRIBUTES),
    ]


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [
        ("TokenIsElevated", ctypes.c_ulong),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]


class INITCOMMONCONTROLSEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("dwICC", ctypes.c_ulong),
    ]


class SCROLLINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("fMask", ctypes.c_uint),
        ("nMin", ctypes.c_int),
        ("nMax", ctypes.c_int),
        ("nPage", ctypes.c_uint),
        ("nPos", ctypes.c_int),
        ("nTrackPos", ctypes.c_int),
    ]


class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint),
        ("iItem", ctypes.c_int),
        ("iSubItem", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("stateMask", ctypes.c_uint),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", ctypes.c_ssize_t),
        ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int),
        ("cColumns", ctypes.c_uint),
        ("puColumns", ctypes.c_void_p),
        ("piColFmt", ctypes.c_void_p),
        ("iGroup", ctypes.c_int),
    ]


class LVCOLUMNW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint),
        ("fmt", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iSubItem", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("iOrder", ctypes.c_int),
        ("cxMin", ctypes.c_int),
        ("cxDefault", ctypes.c_int),
        ("cxIdeal", ctypes.c_int),
    ]


class HDITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint),
        ("cxy", ctypes.c_int),
        ("pszText", ctypes.c_void_p),
        ("hbm", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("fmt", ctypes.c_int),
        ("lParam", ctypes.c_ssize_t),
        ("iImage", ctypes.c_int),
        ("iOrder", ctypes.c_int),
        ("type", ctypes.c_uint),
        ("pvFilter", ctypes.c_void_p),
        ("state", ctypes.c_uint),
    ]


class TCITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint),
        ("dwState", ctypes.c_uint),
        ("dwStateMask", ctypes.c_uint),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", ctypes.c_ssize_t),
    ]


class TBBUTTON(ctypes.Structure):
    _fields_ = [
        ("iBitmap", ctypes.c_int),
        ("idCommand", ctypes.c_int),
        ("fsState", ctypes.c_ubyte),
        ("fsStyle", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte * (6 if ctypes.sizeof(ctypes.c_void_p) == 8 else 2)),
        ("dwData", ctypes.c_size_t),
        ("iString", ctypes.c_ssize_t),
    ]


class TOOLINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("hwnd", ctypes.c_void_p),
        ("uId", ctypes.c_size_t),
        ("rect", ctypes.wintypes.RECT),
        ("hinst", ctypes.c_void_p),
        ("lpszText", ctypes.c_void_p),
        ("lParam", ctypes.c_ssize_t),
        ("lpReserved", ctypes.c_void_p),
    ]


class NMHDR(ctypes.Structure):
    _fields_ = [
        ("hwndFrom", ctypes.c_void_p),
        ("idFrom", ctypes.c_size_t),
        ("code", ctypes.c_int),
    ]


class NMHEADERW(ctypes.Structure):
    _fields_ = [
        ("hdr", NMHDR),
        ("iItem", ctypes.c_int),
        ("iButton", ctypes.c_int),
        ("pitem", ctypes.c_void_p),
    ]


class LITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint),
        ("iLink", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("stateMask", ctypes.c_uint),
        ("szID", ctypes.c_wchar * MAX_LINKID_TEXT),
        ("szUrl", ctypes.c_wchar * L_MAX_URL_LENGTH),
    ]


class COMBOBOXEXITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint),
        ("iItem", ctypes.c_ssize_t),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("iSelectedImage", ctypes.c_int),
        ("iOverlay", ctypes.c_int),
        ("iIndent", ctypes.c_int),
        ("lParam", ctypes.c_ssize_t),
    ]


class COMBOBOXINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("rcItem", ctypes.wintypes.RECT),
        ("rcButton", ctypes.wintypes.RECT),
        ("stateButton", ctypes.c_uint),
        ("hwndCombo", ctypes.c_void_p),
        ("hwndItem", ctypes.c_void_p),
        ("hwndList", ctypes.c_void_p),
    ]


try:
    user32.GetComboBoxInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(COMBOBOXINFO)]
    user32.GetComboBoxInfo.restype = ctypes.c_bool
except Exception:
    pass


class PBRANGE(ctypes.Structure):
    _fields_ = [
        ("iLow", ctypes.c_int),
        ("iHigh", ctypes.c_int),
    ]


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", ctypes.c_ushort),
        ("wMonth", ctypes.c_ushort),
        ("wDayOfWeek", ctypes.c_ushort),
        ("wDay", ctypes.c_ushort),
        ("wHour", ctypes.c_ushort),
        ("wMinute", ctypes.c_ushort),
        ("wSecond", ctypes.c_ushort),
        ("wMilliseconds", ctypes.c_ushort),
    ]


class CHARRANGE(ctypes.Structure):
    _fields_ = [
        ("cpMin", ctypes.c_long),
        ("cpMax", ctypes.c_long),
    ]


class TVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", ctypes.c_uint),
        ("hItem", ctypes.c_void_p),
        ("state", ctypes.c_uint),
        ("stateMask", ctypes.c_uint),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("iSelectedImage", ctypes.c_int),
        ("cChildren", ctypes.c_int),
        ("lParam", ctypes.c_ssize_t),
    ]


class TVINSERTSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hParent", ctypes.c_void_p),
        ("hInsertAfter", ctypes.c_void_p),
        ("item", TVITEMW),
    ]


class _RemoteBuffer:
    def __init__(self, hwnd: int, size: int):
        self.hwnd = int(hwnd)
        self.size = max(int(size), 1)
        self.process = 0
        self.address = 0

    def __enter__(self):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
        self.process = int(kernel32.OpenProcess(
            PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid.value,
        ) or 0)
        if not self.process:
            raise RuntimeError(f"OpenProcess failed for pid {pid.value}")
        self.address = int(kernel32.VirtualAllocEx(
            self.process,
            None,
            self.size,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_READWRITE,
        ) or 0)
        if not self.address:
            raise RuntimeError("VirtualAllocEx failed")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.address and self.process:
            try:
                kernel32.VirtualFreeEx(self.process, ctypes.c_void_p(self.address), 0, MEM_RELEASE)
            except Exception:
                pass
        if self.process:
            try:
                kernel32.CloseHandle(self.process)
            except Exception:
                pass

    def write_bytes(self, offset: int, data: bytes) -> None:
        written = ctypes.c_size_t()
        buf = ctypes.create_string_buffer(data)
        if not kernel32.WriteProcessMemory(
            self.process,
            ctypes.c_void_p(self.address + int(offset)),
            buf,
            len(data),
            ctypes.byref(written),
        ):
            raise RuntimeError("WriteProcessMemory failed")

    def write_struct(self, offset: int, struct_value: ctypes.Structure) -> None:
        self.write_bytes(offset, ctypes.string_at(ctypes.byref(struct_value), ctypes.sizeof(struct_value)))

    def read_bytes(self, offset: int, size: int) -> bytes:
        read = ctypes.c_size_t()
        buf = ctypes.create_string_buffer(size)
        if not kernel32.ReadProcessMemory(
            self.process,
            ctypes.c_void_p(self.address + int(offset)),
            buf,
            int(size),
            ctypes.byref(read),
        ):
            raise RuntimeError("ReadProcessMemory failed")
        return bytes(buf.raw[: int(read.value)])

    def read_wstring(self, offset: int, max_chars: int) -> str:
        data = self.read_bytes(offset, max_chars * ctypes.sizeof(ctypes.c_wchar))
        return data.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]

