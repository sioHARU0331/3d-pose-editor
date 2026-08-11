"""
vsf_controller.py
VMC 繝励Ο繝医さ繝ｫ縺ｧ VSeeFace 縺ｫ菴薙・鬪ｨ繝・・繧ｿ繧帝∽ｿ｡縺吶ｋ縲・
譁ｹ驥・
- 鬘・/ 逶ｮ / 蜿｣ / Jaw / Head / 繝悶Ξ繝ｳ繝峨す繧ｧ繧､繝・縺ｯ荳蛻・√ｉ縺ｪ縺・ｼ亥哨繝代け菫晁ｭｷ・・- Hips 縺ｯ騾√ｉ縺ｪ縺・ｼ・osition(0,0,0) 縺ｧ繧ｭ繝｣繝ｩ縺梧ｶ医∴繧具ｼ・- Root/Pos 縺ｯ騾√ｉ縺ｪ縺・ｼ亥酔荳奇ｼ・- 繧｢繧ｯ繧ｷ繝ｧ繝ｳ讖溯・: vsf_state.json 縺ｮ action 繝輔ぅ繝ｼ繝ｫ繝峨ｒ逶｣隕悶＠縺ｦ繧｢繝九Γ繧堤匱轣ｫ
"""

import ctypes, json, math, pathlib, random, subprocess, sys, time, traceback, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pythonosc import udp_client
from pythonosc.osc_message_builder import OscMessageBuilder

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VSF_HOST = "127.0.0.1"
VSF_PORT = 39539
VSF_ACTION_PORT = 8766
LOOP_INTERVAL = 1.0 / 30.0
ENABLE_IDLE_MOTION = True

VSF_STATE_PATH = pathlib.Path(__file__).parent / "vsf_state.json"
VSF_LOG_PATH = pathlib.Path(__file__).parent / "vsf_controller.log"
FORTUNE_POSE_PATH = pathlib.Path(__file__).parent / "fortune_think_pose.json"
VSF_SPEECH_LEASE_PATHS = [
    pathlib.Path(__file__).parent / "vsf_speaking_pattern1.json",
    pathlib.Path(__file__).parent / "vsf_speaking_pattern2.json",
]

# HTTP 経由で受け取ったアクション・表情を格納するグローバル変数
_pending_action     = None
_pending_expression = None
_pending_lock       = threading.Lock()
_stop_action_requested = False
_motion_mode        = "scripted"  # scripted: idle/action on, mocap: VSeeFace webcam priority
_normal_recovery_until = 0.0
_last_valid_vsf_state = {}
_current_speaking = False
_current_action_name = None
_fortune_pose_preview_active = False
_fortune_pose_test_bones = set()

# The external 3D editor authors this JSON. The existing management tool and
# live action both consume the same seven-bone pose.
_FORTUNE_POSE_FALLBACK = {
    "RightShoulder": [0.0, 0.0, -5.0],
    "RightUpperArm": [-21.0, -32.0, 20.0],
    "RightLowerArm": [-5.0, 77.0, -140.0],
    "RightHand": [26.0, 56.0, -28.0],
    "RightThumbProximal": [15.0, -10.0, 30.0],
    "RightThumbIntermediate": [0.0, 5.0, 60.0],
    "RightThumbDistal": [0.0, 0.0, 40.0],
}


def _load_fortune_pose():
    try:
        loaded = json.loads(FORTUNE_POSE_PATH.read_text(encoding="utf-8"))
        return {
            bone: [float(value) for value in loaded[bone]]
            for bone in _FORTUNE_POSE_FALLBACK
        }
    except Exception as exc:
        print(f"[vsf] fortune pose JSON fallback: {exc}", flush=True)
        return {bone: list(values) for bone, values in _FORTUNE_POSE_FALLBACK.items()}


FORTUNE_POSE_BASE = _load_fortune_pose()
_fortune_pose_preview = {
    bone: list(values) for bone, values in FORTUNE_POSE_BASE.items()
}
# Minimal B direction checks: permit the three explicitly tested bones.
for _test_bone in ('RightHand', 'RightIndexProximal', 'RightThumbProximal'):
    _fortune_pose_preview.setdefault(_test_bone, [0.0, 0.0, 0.0])

# VSeeFace expression hotkeys.
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

EXPRESSION_HOTKEYS = {
    "neutral":  ("Neutral",  [VK_CONTROL, VK_SHIFT, 0x70]),  # Ctrl+Shift+F1
    "normal":   ("Neutral",  [VK_CONTROL, VK_SHIFT, 0x70]),  # Ctrl+Shift+F1
    "smile":    ("Joy",      [VK_CONTROL, VK_SHIFT, 0x73]),  # Ctrl+Shift+F4
    "joy":      ("Joy",      [VK_CONTROL, VK_SHIFT, 0x73]),  # Ctrl+Shift+F4
    "fun":      ("Fun",      [VK_CONTROL, VK_SHIFT, 0x71]),  # Ctrl+Shift+F2
    "angry":    ("Angry",    [VK_CONTROL, VK_SHIFT, 0x72]),  # Ctrl+Shift+F3
    "serious":  ("Angry",    [VK_CONTROL, VK_SHIFT, 0x72]),  # Ctrl+Shift+F3
    "sorrow":   ("Sorrow",   [VK_CONTROL, VK_SHIFT, 0x74]),  # Ctrl+Shift+F5
    "sad":      ("Sorrow",   [VK_CONTROL, VK_SHIFT, 0x74]),  # Ctrl+Shift+F5
    "worry":    ("Sorrow",   [VK_CONTROL, VK_SHIFT, 0x74]),  # Ctrl+Shift+F5
    "surprise": ("Surprise", [VK_CONTROL, VK_SHIFT, 0x75]),  # Ctrl+Shift+F6
}

EXPRESSION_BLEND_CANDIDATES = {
    "neutral":  [],
    "normal":   [],
    "smile":    ["Joy", "Fun"],
    "joy":      ["Joy", "Fun"],
    "fun":      ["Fun", "Joy"],
    "angry":    ["Angry"],
    "serious":  ["Angry"],
    "sorrow":   ["Sorrow"],
    "sad":      ["Sorrow"],
    "worry":    ["Sorrow"],
    "surprise": ["Surprised", "Surprise"],
}

# Subtle expressions are sent only through VMC. They deliberately avoid the
# strong VSeeFace preset hotkeys that can close the avatar's eyes.
EXPRESSION_BLEND_VALUES = {
    # Keep Joy restrained because this avatar closes its eyes at high values.
    "soft_smile": {"Joy": 0.34, "Fun": 0.05},
    # Make worry visible without turning it into an exaggerated sad face.
    "concerned": {"Sorrow": 0.54, "Angry": 0.04},
    # Lowered brows with a trace of Sorrow reads as focused, not angry.
    "focused": {"Angry": 0.38, "Sorrow": 0.02},
    "attentive": {"Surprised": 0.12, "Surprise": 0.12},
}

KNOWN_BLENDSHAPES = ["Joy", "Fun", "Angry", "Sorrow", "Surprised", "Surprise", "Blink"]


def log_vsf(message):
    line = f"[vsf] {message}"
    print(line, flush=True)
    try:
        with VSF_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class _ActionHandler(BaseHTTPRequestHandler):
    """POST /action  {"action": "wave"} を受けて _pending_action に積む。"""

    def do_OPTIONS(self):
        self._cors(204)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/fortune_pose_adjust":
            with _pending_lock:
                self._json(200, {
                    "ok": True,
                    "active": _fortune_pose_preview_active,
                    "values": {bone: list(values) for bone, values in _fortune_pose_preview.items()},
                    "base": {bone: list(values) for bone, values in FORTUNE_POSE_BASE.items()},
                })
            return
        if path not in {"/motion_mode", "/status"}:
            self._json(404, {"ok": False, "error": "not_found"})
            return
        with _pending_lock:
            mode = _motion_mode
        payload = {"ok": True, "mode": mode}
        if path == "/status":
            payload["speaking"] = bool(_current_speaking)
            payload["action"] = _current_action_name
        self._json(200, payload)

    def do_POST(self):
        global _pending_action, _pending_expression, _stop_action_requested
        global _motion_mode, _normal_recovery_until, _fortune_pose_preview_active
        global _fortune_pose_test_bones
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", errors="ignore").strip()
        try:
            data       = json.loads(raw) if raw else {}
            action     = data.get("action", "").strip()
            expression = data.get("expression", "").strip()
            mode       = data.get("mode", "").strip().lower()
            with _pending_lock:
                if self.path.split("?", 1)[0] == "/fortune_pose_adjust":
                    active = bool(data.get("active", True))
                    values = data.get("values", {})
                    if not isinstance(values, dict):
                        raise ValueError("values must be an object")
                    for bone, axes in values.items():
                        if bone not in _fortune_pose_preview or not isinstance(axes, list) or len(axes) != 3:
                            raise ValueError(f"invalid bone values: {bone}")
                        _fortune_pose_preview[bone] = [
                            max(-180.0, min(180.0, float(value))) for value in axes
                        ]
                    _fortune_pose_test_bones = set(values) if data.get("test_only") else set()
                    _fortune_pose_preview_active = active
                    if active:
                        if _motion_mode == "mocap":
                            _motion_mode = "scripted"
                        if _current_action_name != "fortune_pose_preview":
                            _pending_action = "fortune_pose_preview"
                    else:
                        if _pending_action == "fortune_pose_preview":
                            _pending_action = None
                        if _current_action_name == "fortune_pose_preview":
                            _stop_action_requested = True
                    self._json(200, {
                        "ok": True,
                        "active": _fortune_pose_preview_active,
                        "values": {bone: list(axes) for bone, axes in _fortune_pose_preview.items()},
                    })
                    return
                if mode in ("scripted", "normal"):
                    _motion_mode = "scripted"
                    _pending_action = None
                    _normal_recovery_until = time.monotonic() + 3.0
                    print("[vsf] motion mode -> scripted", flush=True)
                elif mode in ("mocap", "webcam"):
                    _motion_mode = "mocap"
                    _pending_action = None
                    print("[vsf] motion mode -> mocap", flush=True)
                if action:
                    if _motion_mode == "mocap":
                        print(f"[vsf] HTTP action ignored in mocap mode: {action}", flush=True)
                    elif action == "fortune_think_stop":
                        _stop_action_requested = True
                        if _pending_action == "fortune_think":
                            _pending_action = None
                        print("[vsf] HTTP fortune thinking stop requested", flush=True)
                    else:
                        _pending_action = action
                        print(f"[vsf] HTTP action queued: {action}", flush=True)
                if expression:
                    _pending_expression = expression
                    log_vsf(f"HTTP expression queued: {expression}")
                current_mode = _motion_mode
            self._json(200, {"ok": True, "mode": current_mode})
        except Exception as e:
            print(f"[vsf] HTTP action error: {e}", flush=True)
            self._json(400, {"ok": False, "error": str(e)})

    def _cors(self, status):
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass  # HTTPアクセスログは不要


def _start_action_server():
    try:
        server = HTTPServer(("127.0.0.1", VSF_ACTION_PORT), _ActionHandler)
        print(f"[vsf] action HTTP server -> 127.0.0.1:{VSF_ACTION_PORT}", flush=True)
        server.serve_forever()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()

_I  = (0.0, 0.0,  0.0,    1.0)
_LA = (0.0, 0.0, +0.3827, 0.9239)   # LeftUpperArm  +45deg Z
_RA = (0.0, 0.0, -0.3827, 0.9239)   # RightUpperArm -45deg Z

# 送信する骨。Hips / Head は除外
BODY_BONES = [
    # torso
    ("Spine",      _I),
    ("Chest",      _I),
    ("UpperChest", _I),
    ("Neck",       _I),
    # left arm
    ("LeftShoulder",  _I),
    ("LeftUpperArm",  _LA),
    ("LeftLowerArm",  _I),
    ("LeftHand",      _I),
    ("LeftThumbProximal",      _I),
    ("LeftThumbIntermediate",  _I),
    ("LeftThumbDistal",        _I),
    ("LeftIndexProximal",      _I),
    ("LeftIndexIntermediate",  _I),
    ("LeftIndexDistal",        _I),
    ("LeftMiddleProximal",     _I),
    ("LeftMiddleIntermediate", _I),
    ("LeftMiddleDistal",       _I),
    ("LeftRingProximal",       _I),
    ("LeftRingIntermediate",   _I),
    ("LeftRingDistal",         _I),
    ("LeftLittleProximal",     _I),
    ("LeftLittleIntermediate", _I),
    ("LeftLittleDistal",       _I),
    # right arm
    ("RightShoulder",  _I),
    ("RightUpperArm",  _RA),
    ("RightLowerArm",  _I),
    ("RightHand",      _I),
    ("RightThumbProximal",      _I),
    ("RightThumbIntermediate",  _I),
    ("RightThumbDistal",        _I),
    ("RightIndexProximal",      _I),
    ("RightIndexIntermediate",  _I),
    ("RightIndexDistal",        _I),
    ("RightMiddleProximal",     _I),
    ("RightMiddleIntermediate", _I),
    ("RightMiddleDistal",       _I),
    ("RightRingProximal",       _I),
    ("RightRingIntermediate",   _I),
    ("RightRingDistal",         _I),
    ("RightLittleProximal",     _I),
    ("RightLittleIntermediate", _I),
    ("RightLittleDistal",       _I),
    # legs
    ("LeftUpperLeg",  _I),
    ("LeftLowerLeg",  _I),
    ("LeftFoot",      _I),
    ("LeftToes",      _I),
    ("RightUpperLeg", _I),
    ("RightLowerLeg", _I),
    ("RightFoot",     _I),
    ("RightToes",     _I),
]

# action duration
ACTION_DURATION = {
    "wave":        1.5,
    "nod":         1.5,
    "small_nod":   1.25,
    "head_tilt":   2.0,
    "head_tilt_left": 2.0,
    "bow":         2.5,
    "explain":     2.8,
    "listen":      2.6,
    "think":       2.8,
    "fortune_think": 8.0,
    "fortune_pose_preview": 60.0 * 60.0,
}

# prebuilt OSC packets
_ok_dgram    = None
_bone_dgrams = []
_bone_dgram_map = {}  # bone蜷・-> dgram (繧｢繧ｯ繧ｷ繝ｧ繝ｳ譎ゅ・繧ｪ繝ｼ繝舌・繝ｩ繧､繝臥畑)


def z_quat_from_degrees(degrees):
    half_rad = math.radians(degrees) * 0.5
    return (0.0, 0.0, math.sin(half_rad), math.cos(half_rad))


def quat_from_euler_degrees(x_deg=0.0, y_deg=0.0, z_deg=0.0):
    x = math.radians(x_deg) * 0.5
    y = math.radians(y_deg) * 0.5
    z = math.radians(z_deg) * 0.5
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    qw = cx * cy * cz + sx * sy * sz
    qx = sx * cy * cz - cx * sy * sz
    qy = cx * sy * cz + sx * cy * sz
    qz = cx * cy * sz - sx * sy * cz
    return (qx, qy, qz, qw)


def quat_multiply(left, right):
    """Compose two quaternions as left * right."""
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def quat_from_editor_xyz_degrees(x_deg=0.0, y_deg=0.0, z_deg=0.0):
    """Match the editor's matrix order: Rx * Ry * Rz."""
    qx = quat_from_euler_degrees(x_deg, 0.0, 0.0)
    qy = quat_from_euler_degrees(0.0, y_deg, 0.0)
    qz = quat_from_euler_degrees(0.0, 0.0, z_deg)
    return quat_multiply(quat_multiply(qx, qy), qz)


def fortune_pose_bone_quat(bone, euler):
    """Convert an editor-local delta onto VSeeFace's neutral arm pose."""
    delta = quat_from_editor_xyz_degrees(*euler)
    if bone in IDLE_EULER:
        return quat_multiply(idle_quat(bone), delta)
    return delta


def quat_slerp(start, end, t):
    """Shortest-path spherical interpolation for a smooth pose handoff."""
    t = max(0.0, min(1.0, t))
    dot = sum(a * b for a, b in zip(start, end))
    if dot < 0.0:
        end = tuple(-value for value in end)
        dot = -dot
    if dot > 0.9995:
        blended = tuple(a + (b - a) * t for a, b in zip(start, end))
        length = math.sqrt(sum(value * value for value in blended)) or 1.0
        return tuple(value / length for value in blended)
    theta_0 = math.acos(max(-1.0, min(1.0, dot)))
    sin_theta_0 = math.sin(theta_0)
    theta = theta_0 * t
    scale_start = math.sin(theta_0 - theta) / sin_theta_0
    scale_end = math.sin(theta) / sin_theta_0
    return tuple(scale_start * a + scale_end * b for a, b in zip(start, end))


def build_bone_dgram(bone, quat):
    qx, qy, qz, qw = quat
    b = OscMessageBuilder(address="/VMC/Ext/Bone/Pos")
    b.add_arg(bone, arg_type="s")
    for v in (0.0, 0.0, 0.0, qx, qy, qz, qw):
        b.add_arg(float(v), arg_type="f")
    return b.build().dgram


def build_blend_val_dgram(name, value):
    b = OscMessageBuilder(address="/VMC/Ext/Blend/Val")
    b.add_arg(name, arg_type="s")
    b.add_arg(float(value), arg_type="f")
    return b.build().dgram


def build_blend_apply_dgram():
    return OscMessageBuilder(address="/VMC/Ext/Blend/Apply").build().dgram


def send_lip_sync(sock, addr, speaking, now, gain=1.0):
    vowel_names = ("A", "I", "U", "E", "O", "aa", "ih", "ou", "ee", "oh")
    gain = max(0.0, min(1.0, float(gain)))
    if speaking or gain > 0.001:
        wave = 0.5 + 0.5 * math.sin(now * 18.0)
        main = (0.22 + 0.72 * wave) * gain
        sub = (0.10 + 0.20 * (1.0 - wave)) * gain
        values = {
            "A": main,
            "aa": main,
            "I": sub * 0.55,
            "ih": sub * 0.55,
            "U": sub * 0.35,
            "ou": sub * 0.35,
            "E": sub * 0.45,
            "ee": sub * 0.45,
            "O": sub * 0.30,
            "oh": sub * 0.30,
        }
        for name in vowel_names:
            sock.sendto(build_blend_val_dgram(name, values.get(name, 0.0)), addr)
    else:
        for name in vowel_names:
            sock.sendto(build_blend_val_dgram(name, 0.0), addr)
    sock.sendto(build_blend_apply_dgram(), addr)


if sys.platform == "win32":
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetActiveWindow.argtypes = [wintypes.HWND]
    user32.SetActiveWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def get_window_text(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def get_window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def process_image_path(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
    finally:
        kernel32.CloseHandle(handle)
    return ""


def list_vseeface_pids():
    if sys.platform != "win32":
        return set()
    pids = set()
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process VSeeFace -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
    except Exception as e:
        log_vsf(f"list_vseeface_pids failed: {e}")
    return pids


def find_vseeface_windows():
    if sys.platform != "win32":
        return []
    matches = []
    pid_matches = list_vseeface_pids()
    log_vsf(f"VSeeFace process ids: {sorted(pid_matches)}")

    @EnumWindowsProc
    def enum_proc(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        image = process_image_path(pid.value)
        title = get_window_text(hwnd)
        cls = get_window_class(hwnd)
        image_lower = image.lower()
        title_lower = title.lower().strip()
        looks_like_vsf = (
            pid.value in pid_matches
            or
            image_lower.endswith("\\vseeface.exe")
            or title_lower == "vseeface"
            or title_lower.startswith("vseeface ")
            or "vseeface v" in title_lower
        )
        if looks_like_vsf:
            matches.append((hwnd, pid.value, bool(user32.IsWindowVisible(hwnd)), cls, title))
        return True

    user32.EnumWindows(enum_proc, 0)
    matches.sort(key=lambda item: (item[1] not in pid_matches, not item[2], item[4] == ""))
    return matches


def activate_vseeface_window():
    if sys.platform != "win32":
        return False
    windows = find_vseeface_windows()
    if windows:
        hwnd, pid, visible, cls, title = windows[0]
        log_vsf(f"VSeeFace window found: hwnd={int(hwnd)} pid={pid} visible={visible} class={cls} title={title!r}")
        focused = False
        for attempt in range(3):
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
            time.sleep(0.08)
            foreground = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
            target_thread = user32.GetWindowThreadProcessId(hwnd, None)
            current_thread = kernel32.GetCurrentThreadId()
            attached = False
            if foreground_thread and target_thread and foreground_thread != current_thread:
                attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
            try:
                ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
                time.sleep(0.03)
                ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                ok = bool(user32.SetForegroundWindow(hwnd))
                time.sleep(0.15)
                foreground = user32.GetForegroundWindow()
                focused = foreground == hwnd
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            log_vsf(
                f"VSeeFace focus attempt={attempt + 1} hwnd={int(hwnd)} "
                f"pid={pid} title={title!r} set_foreground={ok} focused={focused}"
            )
            if ok or focused:
                return True
            time.sleep(0.05)

    try:
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$ok = $ws.AppActivate('VSeeFace'); "
            "if (-not $ok) { "
            "  $p=Get-Process VSeeFace -ErrorAction SilentlyContinue | Select-Object -First 1; "
            "  if ($p) { $ok = $ws.AppActivate($p.Id) } "
            "} "
            "$ok"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=2,
        )
        ok = "True" in result.stdout
        log_vsf(
            f"VSeeFace focus fallback=AppActivate ok={ok} "
            f"stdout={result.stdout.strip()!r} stderr={result.stderr.strip()!r}"
        )
        time.sleep(0.2)
        return ok
    except Exception as e:
        log_vsf(f"VSeeFace focus failed: {e}")
        return False


def send_hotkey(keys):
    if sys.platform != "win32":
        log_vsf("expression hotkey skipped: hotkeys are only implemented on Windows")
        return False
    focused = activate_vseeface_window()
    log_vsf(f"expression hotkey prepare: keys={format_hotkey(keys)} focused={focused}")
    time.sleep(0.1)
    for vk in keys:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.015)
    time.sleep(0.08)
    for vk in reversed(keys):
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.015)
    log_vsf(f"hotkey sent: {format_hotkey(keys).lower()}")
    return True


def trigger_expression_hotkey(expression):
    log_vsf(f"expression request: {expression}")
    hotkey = EXPRESSION_HOTKEYS.get(expression)
    if not hotkey:
        log_vsf(f"unknown expression hotkey: {expression}")
        return
    label, keys = hotkey
    sent = send_hotkey(keys)
    log_vsf(
        f"expression result: request={expression} target={label} "
        f"keys={format_hotkey(keys)} sent={sent}"
    )


def expression_blend_values(expression):
    candidates = EXPRESSION_BLEND_CANDIDATES.get(expression)
    subtle_values = EXPRESSION_BLEND_VALUES.get(expression)
    if candidates is None and subtle_values is None:
        log_vsf(f"unknown expression blendshape: {expression}")
        return None

    activated = set(candidates or [])
    values = {}
    for blend_name in KNOWN_BLENDSHAPES:
        if subtle_values is not None:
            value = float(subtle_values.get(blend_name, 0.0))
        else:
            # Strong presets are intentionally softened so the face can return
            # naturally without closing the eyes or snapping between states.
            value = 0.62 if blend_name in activated else 0.0
        values[blend_name] = value
    return values


def send_expression_values(values, sock, addr):
    sent_names = []
    for blend_name in KNOWN_BLENDSHAPES:
        value = float(values.get(blend_name, 0.0))
        sock.sendto(build_blend_val_dgram(blend_name, value), addr)
        sent_names.append(f"{blend_name}={value:.2f}")
    sock.sendto(build_blend_apply_dgram(), addr)
    return sent_names


def natural_blink_value(now, blink_started_at):
    if blink_started_at is None:
        return 0.0
    elapsed = now - blink_started_at
    if elapsed < 0.09:
        return _smooth(elapsed / 0.09)
    if elapsed < 0.14:
        return 1.0
    if elapsed < 0.34:
        return 1.0 - _smooth((elapsed - 0.14) / 0.20)
    return 0.0


def trigger_expression(expression, sock, addr):
    values = expression_blend_values(expression)
    log_vsf(f"expression queued for smooth VMC transition: request={expression}")
    return values


def format_hotkey(keys):
    names = {
        VK_CONTROL: "Ctrl",
        VK_SHIFT: "Shift",
        0x70: "F1",
        0x71: "F2",
        0x72: "F3",
        0x73: "F4",
        0x74: "F5",
        0x75: "F6",
    }
    return "+".join(names.get(vk, hex(vk)) for vk in keys)


def prebuild():
    global _ok_dgram, _bone_dgrams, _bone_dgram_map
    b = OscMessageBuilder(address="/VMC/Ext/OK")
    b.add_arg(3, arg_type="i")
    _ok_dgram = b.build().dgram

    for bone, quat in BODY_BONES:
        dgram = build_bone_dgram(bone, quat)
        _bone_dgrams.append(dgram)
        _bone_dgram_map[bone] = dgram


# ===== vsf_state.json 縺ｮ隱ｭ縺ｿ譖ｸ縺・=====

def read_vsf_state():
    global _last_valid_vsf_state
    try:
        if VSF_STATE_PATH.exists():
            state = json.loads(VSF_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(state, dict):
                _last_valid_vsf_state = state
                return state
    except Exception:
        pass
    return dict(_last_valid_vsf_state)


def clear_vsf_action():
    try:
        state = read_vsf_state()
        if "action" in state:
            del state["action"]
            temp_path = VSF_STATE_PATH.with_name(f"{VSF_STATE_PATH.name}.controller.tmp")
            temp_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(VSF_STATE_PATH)
    except Exception:
        pass


def has_active_speech_lease(now_wall):
    for path in VSF_SPEECH_LEASE_PATHS:
        try:
            lease = json.loads(path.read_text(encoding="utf-8"))
            if bool(lease.get("active")) and float(lease.get("expiresAt", 0.0)) >= now_wall:
                return True
        except Exception:
            continue
    return False


# ===== 繧｢繧ｯ繧ｷ繝ｧ繝ｳ: 謇九ｒ謖ｯ繧・=====

def _lerp(a, b, t):
    return a + (b - a) * t


def _smooth(t):
    """Ease both ends so scripted poses do not start or stop abruptly."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _pose_phase(t, enter, hold_end, exit_end):
    if t < enter:
        return _smooth(t / enter)
    if t < hold_end:
        return 1.0
    if t < exit_end:
        return 1.0 - _smooth((t - hold_end) / (exit_end - hold_end))
    return 0.0


IDLE_EULER = {
    "LeftShoulder":  (0.0, 0.0, 0.0),
    "LeftUpperArm":  (-4.0, 6.0, 74.0),
    "LeftLowerArm":  (-30.0, 2.0, -26.0),
    "LeftHand":      (3.0, -4.0, 3.0),
    "RightShoulder": (0.0, 0.0, 0.0),
    "RightUpperArm": (-4.0, -6.0, -74.0),
    "RightLowerArm": (-30.0, -2.0, 26.0),
    "RightHand":     (3.0, 4.0, -3.0),
}

ARM_KEEPALIVE_BONES = [
    "LeftShoulder", "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightShoulder", "RightUpperArm", "RightLowerArm", "RightHand",
]


def idle_quat(bone):
    return quat_from_euler_degrees(*IDLE_EULER[bone])


def get_idle_overrides(now, speaking=False):
    breathe = math.sin(now * math.pi * 2 / 4.8)
    sway = math.sin(now * math.pi * 2 / 7.0)
    drift = math.sin(now * math.pi * 2 / 11.0 + 0.7)
    g = 1.4 if speaking else 1.0
    return {
        "Spine":      quat_from_euler_degrees(0.8 * breathe * g, 0.0, 1.2 * sway * g),
        "Chest":      quat_from_euler_degrees(1.0 * breathe * g, 0.0, 0.8 * sway * g),
        "UpperChest": quat_from_euler_degrees(0.5 * breathe * g, 0.0, 0.6 * drift * g),
        "Neck":       quat_from_euler_degrees(0.4 * breathe * g, 0.6 * drift * g, -0.5 * sway * g),
        "LeftShoulder":  idle_quat("LeftShoulder"),
        "LeftUpperArm":  idle_quat("LeftUpperArm"),
        "LeftLowerArm":  idle_quat("LeftLowerArm"),
        "LeftHand":      idle_quat("LeftHand"),
        "RightShoulder": idle_quat("RightShoulder"),
        "RightUpperArm": idle_quat("RightUpperArm"),
        "RightLowerArm": idle_quat("RightLowerArm"),
        "RightHand":     idle_quat("RightHand"),
    }


def get_wave_overrides(t):
    """Natural small wave near the face."""
    overrides = {}
    idle_upper = IDLE_EULER["RightUpperArm"]
    idle_lower = IDLE_EULER["RightLowerArm"]
    idle_hand = IDLE_EULER["RightHand"]
    if t < 0.22:
        progress = _smooth(t / 0.22)
        upper_x = _lerp(idle_upper[0], -8, progress)
        upper_y = _lerp(idle_upper[1], -46, progress)
        upper_z = _lerp(idle_upper[2], -14, progress)
        lower_x = _lerp(idle_lower[0], -26, progress)
        lower_y = _lerp(idle_lower[1], -5, progress)
        lower_z = _lerp(idle_lower[2], 108, progress)
        hand_x = _lerp(idle_hand[0], 10, progress)
        hand_y = _lerp(idle_hand[1], -25, progress)
        hand_z = _lerp(idle_hand[2], -8, progress)
        overrides["RightUpperArm"] = quat_from_euler_degrees(upper_x, upper_y, upper_z)
        overrides["RightLowerArm"] = quat_from_euler_degrees(lower_x, lower_y, lower_z)
        overrides["RightHand"] = quat_from_euler_degrees(hand_x, hand_y, hand_z)
    elif t < 0.82:
        wave_phase = (t - 0.22) / 0.60  # 0..1
        wrist = math.sin(wave_phase * math.pi * 2) * 14
        forearm = math.sin(wave_phase * math.pi * 2) * 2
        overrides["RightUpperArm"] = quat_from_euler_degrees(-8, -46, -14)
        overrides["RightLowerArm"] = quat_from_euler_degrees(-26, -5, 108 + forearm)
        overrides["RightHand"] = quat_from_euler_degrees(10, -25 + wrist * 0.25, -8 + wrist * 0.6)
    elif t < 1.5:
        progress = _smooth((t - 0.82) / 0.68)
        upper_x = _lerp(-8, idle_upper[0], progress)
        upper_y = _lerp(-46, idle_upper[1], progress)
        upper_z = _lerp(-14, idle_upper[2], progress)
        lower_x = _lerp(-26, idle_lower[0], progress)
        lower_y = _lerp(-5, idle_lower[1], progress)
        lower_z = _lerp(108, idle_lower[2], progress)
        hand_x = _lerp(10, idle_hand[0], progress)
        hand_y = _lerp(-25, idle_hand[1], progress)
        hand_z = _lerp(-8, idle_hand[2], progress)
        overrides["RightUpperArm"] = quat_from_euler_degrees(upper_x, upper_y, upper_z)
        overrides["RightLowerArm"] = quat_from_euler_degrees(lower_x, lower_y, lower_z)
        overrides["RightHand"] = quat_from_euler_degrees(hand_x, hand_y, hand_z)
    else:
        overrides["RightUpperArm"] = idle_quat("RightUpperArm")
        overrides["RightLowerArm"] = idle_quat("RightLowerArm")
        overrides["RightHand"] = idle_quat("RightHand")
    return overrides


# ===== アクション: うなずく =====

def get_nod_overrides(t):
    """2回うなずく。"""
    if t >= 1.5:
        return {"Neck": _I}
    phase = t % 0.75
    if phase < 0.25:
        neck_x = _lerp(0, 16, _smooth(phase / 0.25))
    else:
        neck_x = _lerp(16, 0, _smooth((phase - 0.25) / 0.5))
    return {"Neck": quat_from_euler_degrees(neck_x, 0, 0)}


def get_small_nod_overrides(t):
    """会話中に使いやすい、控えめな1回だけのうなずき。"""
    amount = _pose_phase(t, 0.34, 0.46, 1.25)
    return {
        "Neck": quat_from_euler_degrees(9.0 * amount, 0, 0),
        "UpperChest": quat_from_euler_degrees(1.5 * amount, 0, 0),
    }


def get_head_tilt_overrides(t):
    """首を右にかしげて戻る。"""
    nz = 16 * _pose_phase(t, 0.45, 1.35, 2.0)
    return {"Neck": quat_from_euler_degrees(0, 0, nz)}


def get_head_tilt_left_overrides(t):
    """毎回同じ方向にならないための左向き首かしげ。"""
    nz = -14 * _pose_phase(t, 0.45, 1.35, 2.0)
    return {"Neck": quat_from_euler_degrees(0, 0, nz)}


def get_bow_overrides(t):
    """おじぎ。"""
    if t < 0.5:
        p = _smooth(t / 0.5)
        sx, cx = _lerp(0, 22, p), _lerp(0, 14, p)
    elif t < 1.5:
        sx, cx = 22, 14
    elif t < 2.5:
        p = _smooth((t - 1.5) / 1.0)
        sx, cx = _lerp(22, 0, p), _lerp(14, 0, p)
    else:
        return {"Spine": _I, "Chest": _I}
    return {
        "Spine": quat_from_euler_degrees(sx, 0, 0),
        "Chest": quat_from_euler_degrees(cx, 0, 0),
    }


def get_explain_overrides(t):
    """片手を軽く開き、落ち着いて説明している姿勢。"""
    amount = _pose_phase(t, 0.6, 1.9, 2.8)
    idle_upper = IDLE_EULER["LeftUpperArm"]
    idle_lower = IDLE_EULER["LeftLowerArm"]
    idle_hand = IDLE_EULER["LeftHand"]
    return {
        "Chest": quat_from_euler_degrees(0, -2.0 * amount, -1.2 * amount),
        "LeftUpperArm": quat_from_euler_degrees(
            _lerp(idle_upper[0], -8, amount),
            _lerp(idle_upper[1], 10, amount),
            _lerp(idle_upper[2], 62, amount),
        ),
        "LeftLowerArm": quat_from_euler_degrees(
            _lerp(idle_lower[0], -38, amount),
            _lerp(idle_lower[1], 5, amount),
            _lerp(idle_lower[2], -92, amount),
        ),
        "LeftHand": quat_from_euler_degrees(
            _lerp(idle_hand[0], 0, amount),
            _lerp(idle_hand[1], 14, amount),
            _lerp(idle_hand[2], 6, amount),
        ),
    }


def get_listen_overrides(t):
    """わずかに前へ入り、相手の話を聞いている姿勢。"""
    amount = _pose_phase(t, 0.65, 1.8, 2.6)
    return {
        "Spine": quat_from_euler_degrees(6.0 * amount, 0, -1.2 * amount),
        "Chest": quat_from_euler_degrees(4.5 * amount, 0, -1.8 * amount),
        "Neck": quat_from_euler_degrees(-3.0 * amount, 3.0 * amount, -7.0 * amount),
    }


def get_think_overrides(t):
    """返答を考える時の、控えめな視線・姿勢変化。"""
    amount = _pose_phase(t, 0.55, 1.9, 2.8)
    return {
        "UpperChest": quat_from_euler_degrees(3.0 * amount, -3.5 * amount, 1.8 * amount),
        "Neck": quat_from_euler_degrees(7.0 * amount, -12.0 * amount, 7.0 * amount),
    }


def get_fortune_think_overrides(t, pose_values=None):
    """Fold one arm across the chest and raise the other fist below the chin."""
    def progress(start, end):
        return _smooth((t - start) / (end - start))

    # Lead with the gaze and torso, then fold the supporting arm. The raised
    # arm follows later so the whole body does not start on a single frame.
    if t < 0.05:
        body_pose = 0.0
    elif t < 1.20:
        body_pose = progress(0.05, 1.20)
    elif t < 7.15:
        body_pose = 1.0
    elif t < 8.00:
        body_pose = 1.0 - progress(7.15, 8.00)
    else:
        body_pose = 0.0

    if t < 0.25:
        support_pose = 0.0
    elif t < 1.50:
        support_pose = progress(0.25, 1.50)
    elif t < 6.60:
        support_pose = 1.0
    elif t < 7.88:
        support_pose = 1.0 - progress(6.60, 7.88)
    else:
        support_pose = 0.0

    # Keep the upward "hmm" look for the whole thinking hold. It starts before
    # the arms and is the last part to settle back to neutral.
    if t < 0.08:
        look_up = 0.0
    elif t < 1.25:
        look_up = progress(0.08, 1.25)
    elif t < 7.25:
        look_up = 1.0
    elif t < 8.00:
        look_up = 1.0 - progress(7.25, 8.00)
    else:
        look_up = 0.0

    # Guide the fist through the centre of the chest before bringing it below
    # the chin. A single idle-to-final blend arcs past the shoulder and looks
    # like the arm is being pulled by the wrist.
    if t < 0.38:
        raised_phase = ("idle", 0.0)
    elif t < 1.65:
        raised_phase = ("entry", progress(0.38, 1.65))
    elif t < 2.65:
        raised_phase = ("lift", progress(1.65, 2.65))
    elif t < 6.08:
        raised_phase = ("hold", 1.0)
    elif t < 7.05:
        raised_phase = ("lower", progress(6.08, 7.05))
    elif t < 7.85:
        raised_phase = ("release", progress(7.05, 7.85))
    else:
        raised_phase = ("idle", 0.0)

    # Form the fist before lifting the arm and keep it closed until the arm is
    # back down. Interpolating finger curls with the arm exposed an open palm
    # halfway through both the raise and return transitions.
    if t < 0.08:
        visible_finger_pose = 0.0
    elif t < 0.38:
        visible_finger_pose = _smooth((t - 0.08) / 0.30)
    elif t < 7.72:
        visible_finger_pose = 1.0
    elif t < 8.00:
        visible_finger_pose = 1.0 - _smooth((t - 7.72) / 0.28)
    else:
        visible_finger_pose = 0.0

    # Close the fingers and pre-rotate the wrist while the hand is still low.
    # The chest waypoint uses a slightly side-on dorsal angle; the final
    # rotation happens only as the fist approaches the chin. Keeping the final
    # wrist angle throughout the lift makes the thumb look like a stray pinky.
    wrist_pose = visible_finger_pose

    nod = 0.0
    if 4.85 <= t < 5.85:
        nod = math.sin((t - 4.85) / 1.0 * math.pi) * 2.2
    thought_sway = math.sin((t - 1.0) * 1.05) * 0.55 * body_pose

    def arm(bone, target, amount):
        idle = IDLE_EULER[bone]
        return quat_from_euler_degrees(
            _lerp(idle[0], target[0], amount),
            _lerp(idle[1], target[1], amount),
            _lerp(idle[2], target[2], amount),
        )

    raised_target = {
        bone: tuple(values)
        for bone, values in (pose_values or FORTUNE_POSE_BASE).items()
    }

    # Form the fist at the centre of the chest before lifting it to the chin.
    # Keeping the upper arm closer to idle here prevents the fist from swinging
    # out toward the shoulder during both the raise and the return.
    raised_waypoint = {
        "RightShoulder": (-1.0, -2.0, -1.0),
        "RightUpperArm": (-10.0, -35.0, -78.0),
        "RightLowerArm": (-8.0, -6.0, -112.0),
        # Form the correct fist before it enters the visible chest area.
        "RightHand": (-95.0, -25.0, -20.0),
    }

    def between(start, end, amount):
        return quat_from_euler_degrees(
            _lerp(start[0], end[0], amount),
            _lerp(start[1], end[1], amount),
            _lerp(start[2], end[2], amount),
        )

    def raised_arm(bone):
        phase, amount = raised_phase
        idle = IDLE_EULER[bone]
        waypoint = raised_waypoint[bone]
        target = raised_target[bone]
        target_quat = fortune_pose_bone_quat(bone, target)
        waypoint_quat = quat_from_euler_degrees(*waypoint)
        if phase == "entry":
            if bone == "RightHand":
                return waypoint_quat
            return between(idle, waypoint, amount)
        if phase == "lift":
            return quat_slerp(waypoint_quat, target_quat, amount)
        if phase == "hold":
            return target_quat
        if phase == "lower":
            return quat_slerp(target_quat, waypoint_quat, amount)
        if phase == "release":
            return between(waypoint, idle, amount)
        if bone == "RightHand":
            return between(idle, waypoint, wrist_pose)
        return quat_from_euler_degrees(*idle)

    # Keep the motion phase available for the fist timing below.
    phase, phase_amount = raised_phase

    # The fist stays equally closed during travel and hold, preventing an open
    # palm or claw frame from appearing halfway through the motion.
    moving_curl_boost = 1.0
    if phase == "entry":
        finger_curl_boost = moving_curl_boost
    elif phase == "lift":
        settle = _smooth(max(0.0, (phase_amount - 0.65) / 0.35))
        finger_curl_boost = _lerp(moving_curl_boost, 1.0, settle)
    elif phase == "hold":
        finger_curl_boost = 1.0
    elif phase == "lower":
        close = _smooth(min(1.0, phase_amount / 0.35))
        finger_curl_boost = _lerp(1.0, moving_curl_boost, close)
    elif phase == "release":
        finger_curl_boost = moving_curl_boost
    else:
        finger_curl_boost = 1.0

    overrides = {
        "Spine": quat_from_euler_degrees(1.4 * body_pose, 0.0, -0.5 * body_pose),
        "Chest": quat_from_euler_degrees(2.4 * body_pose, -1.6 * body_pose, thought_sway),
        "UpperChest": quat_from_euler_degrees(2.0 * body_pose, -2.2 * body_pose, 0.7 * thought_sway),
        "Neck": quat_from_euler_degrees(
            -3.0 * body_pose - 20.5 * look_up + nod,
            -4.0 * body_pose + 14.0 * look_up,
            0.4 * body_pose - 3.5 * look_up + 0.7 * thought_sway,
        ),
        # Fold the opposite forearm across the lower chest to support the
        # raised elbow, matching a conventional thinking pose.
        "LeftShoulder": arm("LeftShoulder", (1.8, 3.0, 1.8), support_pose),
        "LeftUpperArm": arm("LeftUpperArm", (-4.0, 40.0, 64.0), support_pose),
        "LeftLowerArm": arm("LeftLowerArm", (-30.0, 20.0, 120.0), support_pose),
        # Hide the supporting fingers inside the sleeve. Exposing them creates
        # a disconnected skin-coloured nub beside the raised elbow.
        "LeftHand": arm("LeftHand", (0.0, -90.0, 0.0), support_pose),
        "RightShoulder": raised_arm("RightShoulder"),
        "RightUpperArm": raised_arm("RightUpperArm"),
        "RightLowerArm": raised_arm("RightLowerArm"),
        "RightHand": raised_arm("RightHand"),
    }

    # Curl the four fingers fully behind the back of the right hand. Shallower
    # curls exposed fingertips and made the fist look like the wrong hand.
    visible_finger_curls = {
        "Index": (-90.0, -105.0, -90.0),
        "Middle": (-91.5, -106.5, -91.5),
        "Ring": (-93.0, -108.0, -93.0),
        "Little": (-94.5, -109.5, -94.5),
    }
    for finger, (proximal, intermediate, distal) in visible_finger_curls.items():
        overrides[f"Right{finger}Proximal"] = quat_from_euler_degrees(
            0.0, 0.0, proximal * finger_curl_boost * visible_finger_pose
        )
        overrides[f"Right{finger}Intermediate"] = quat_from_euler_degrees(
            0.0, 0.0, intermediate * finger_curl_boost * visible_finger_pose
        )
        overrides[f"Right{finger}Distal"] = quat_from_euler_degrees(
            0.0, 0.0, distal * finger_curl_boost * visible_finger_pose
        )
    # Use the exact thumb chain authored in the external 3D editor.
    for bone in (
        "RightThumbProximal",
        "RightThumbIntermediate",
        "RightThumbDistal",
    ):
        target = raised_target[bone]
        overrides[bone] = quat_slerp(
            _I,
            fortune_pose_bone_quat(bone, target),
            visible_finger_pose,
        )
    # Keep the supporting hand compact so it reads as holding the opposite
    # elbow instead of presenting an open palm toward the camera.
    support_finger_curls = {
        "Index": (-30.2, -38.6, -28.6),
        "Middle": (-31.9, -41.2, -30.2),
        "Ring": (-33.6, -42.8, -31.9),
        "Little": (-35.3, -44.5, -33.6),
    }
    for finger, (proximal, intermediate, distal) in support_finger_curls.items():
        overrides[f"Left{finger}Proximal"] = quat_from_euler_degrees(
            0.0, 0.0, proximal * support_pose
        )
        overrides[f"Left{finger}Intermediate"] = quat_from_euler_degrees(
            0.0, 0.0, intermediate * support_pose
        )
        overrides[f"Left{finger}Distal"] = quat_from_euler_degrees(
            0.0, 0.0, distal * support_pose
        )
    overrides["LeftThumbProximal"] = quat_from_euler_degrees(
        0.0, -32.0 * support_pose, -8.0 * support_pose
    )
    overrides["LeftThumbIntermediate"] = quat_from_euler_degrees(
        0.0, 0.0, -58.0 * support_pose
    )
    overrides["LeftThumbDistal"] = quat_from_euler_degrees(
        0.0, 0.0, -38.0 * support_pose
    )
    return overrides


def get_action_overrides(action, t):
    if action == "wave":        return get_wave_overrides(t)
    if action == "nod":         return get_nod_overrides(t)
    if action == "small_nod":   return get_small_nod_overrides(t)
    if action == "head_tilt":   return get_head_tilt_overrides(t)
    if action == "head_tilt_left": return get_head_tilt_left_overrides(t)
    if action == "bow":         return get_bow_overrides(t)
    if action == "explain":     return get_explain_overrides(t)
    if action == "listen":      return get_listen_overrides(t)
    if action == "think":       return get_think_overrides(t)
    if action == "fortune_think": return get_fortune_think_overrides(t)
    if action == "fortune_pose_preview":
        if _fortune_pose_test_bones:
            return {
                bone: quat_from_euler_degrees(*_fortune_pose_preview[bone])
                for bone in _fortune_pose_test_bones
            }
        return get_fortune_think_overrides(3.0, _fortune_pose_preview)
    return {}


def build_pose_dgrams(overrides, base_overrides=None):
    dgrams = []
    base_overrides = base_overrides or {}
    for bone, _ in BODY_BONES:
        quat = overrides.get(bone)
        if quat is None:
            quat = base_overrides.get(bone)
        if quat is None:
            dgrams.append(_bone_dgram_map[bone])
        else:
            dgrams.append(build_bone_dgram(bone, quat))
    return dgrams


def build_selected_pose_dgrams(bones, overrides):
    dgrams = []
    for bone in bones:
        quat = overrides.get(bone)
        if quat is None:
            quat = idle_quat(bone) if bone in IDLE_EULER else _I
        dgrams.append(build_bone_dgram(bone, quat))
    return dgrams


def main():
    global _pending_action, _pending_expression, _current_speaking
    global _stop_action_requested, _current_action_name, _fortune_pose_preview_active

    # アクション受付 HTTP サーバーをバックグラウンドスレッドで起動
    threading.Thread(target=_start_action_server, daemon=True).start()

    prebuild()
    client = udp_client.SimpleUDPClient(VSF_HOST, VSF_PORT)
    sock   = client._sock
    addr   = (VSF_HOST, VSF_PORT)
    print(f"vsf_controller start -> {VSF_HOST}:{VSF_PORT}")
    print(f"bones: {len(BODY_BONES)} (face/Hips/Head 髯､螟・")
    sys.stdout.flush()

    tick = 0
    current_action    = None
    action_start      = 0.0
    recovery_from     = None
    recovery_start    = 0.0
    recovery_duration = 0.45
    last_motion_mode  = None
    last_speaking     = False
    lip_release_start = 0.0
    lip_release_end   = 0.0
    current_expression_values = {name: 0.0 for name in KNOWN_BLENDSHAPES}
    expression_from_values = dict(current_expression_values)
    expression_target_values = dict(current_expression_values)
    expression_transition_start = 0.0
    expression_transition_duration = 0.0
    expression_transition_active = False
    next_blink_at = time.monotonic() + random.uniform(2.6, 5.5)
    blink_started_at = None
    print("[vsf] expression mode: smooth VMC blendshape", flush=True)

    while True:
        try:
            now = time.monotonic()
            pending_expr = None
            pending = None
            stop_action = False
            state = read_vsf_state()
            speaking = bool(state.get("speaking")) or has_active_speech_lease(time.time())
            _current_speaking = speaking
            with _pending_lock:
                motion_mode = _motion_mode
                normal_recovery_until = _normal_recovery_until
                pending_expr = _pending_expression
                _pending_expression = None
                stop_action = _stop_action_requested
                _stop_action_requested = False
                if motion_mode == "scripted" and tick % 5 == 0:
                    pending = _pending_action if current_action is None else None
                    if current_action is None:
                        _pending_action = None
                elif motion_mode == "mocap":
                    _pending_action = None

            if motion_mode != last_motion_mode:
                print(f"[vsf] active motion mode: {motion_mode}", flush=True)
                if motion_mode == "mocap":
                    current_action = None
                    _current_action_name = None
                    _fortune_pose_preview_active = False
                    recovery_from = None
                last_motion_mode = motion_mode

            if stop_action and current_action in {"fortune_think", "fortune_pose_preview"}:
                elapsed = max(0.0, now - action_start)
                recovery_from = get_action_overrides(current_action, elapsed)
                recovery_start = now
                if current_action == "fortune_pose_preview":
                    _fortune_pose_preview_active = False
                current_action = None
                _current_action_name = None
                print("[vsf] fortune pose stopped", flush=True)

            # ---- 表情変更 ----
            if pending_expr is not None:
                target_values = trigger_expression(pending_expr, sock, addr)
                if target_values is not None:
                    expression_from_values = dict(current_expression_values)
                    expression_target_values = target_values
                    expression_transition_start = now
                    expression_transition_duration = 0.45 if pending_expr in {"neutral", "normal"} else 0.32
                    expression_transition_active = True

            if expression_transition_active:
                elapsed = now - expression_transition_start
                progress = _smooth(elapsed / expression_transition_duration)
                current_expression_values = {
                    name: expression_from_values[name]
                    + (expression_target_values[name] - expression_from_values[name]) * progress
                    for name in KNOWN_BLENDSHAPES
                }
                if elapsed >= expression_transition_duration:
                    current_expression_values = dict(expression_target_values)
                    expression_transition_active = False
                    log_vsf("expression smooth transition complete")

            if speaking != last_speaking:
                print(f"[vsf] speaking -> {speaking}", flush=True)
                if last_speaking and not speaking:
                    lip_release_start = now
                    lip_release_end = now + 0.16
                last_speaking = speaking

            if speaking:
                lip_gain = 1.0
            elif now < lip_release_end:
                lip_gain = 1.0 - _smooth((now - lip_release_start) / (lip_release_end - lip_release_start))
            else:
                lip_gain = 0.0

            # モーキャプモードでは、体の自動揺れ・アクション送信を止める。
            if motion_mode == "mocap":
                arm_dgrams = build_selected_pose_dgrams(ARM_KEEPALIVE_BONES, get_idle_overrides(now, speaking))
                sock.sendto(_ok_dgram, addr)
                for dgram in arm_dgrams:
                    sock.sendto(dgram, addr)
                send_lip_sync(sock, addr, speaking, now, lip_gain)
                tick += 1
                if tick % 40 == 1:
                    print(f"[vsf] mocap mode: scripted actions paused, arms kept idle -> {VSF_HOST}:{VSF_PORT}")
                    sys.stdout.flush()
                time.sleep(LOOP_INTERVAL)
                continue

            # ---- アクション検出 ----
            if current_action is None and tick % 5 == 0:
                if not pending:
                    state = read_vsf_state()
                    pending = state.get("action")
                    if pending:
                        clear_vsf_action()
                if pending:
                    current_action = pending
                    _current_action_name = pending
                    action_start   = time.monotonic()
                    print(f"[vsf] action start: {current_action}", flush=True)

            # ---- ボーン送信データ決定 ----
            if now < normal_recovery_until:
                current_action = None
                _current_action_name = None
                recovery_from = None
                dgrams_to_send = build_pose_dgrams({}, get_idle_overrides(now, speaking))
            elif current_action:
                t = now - action_start
                duration = ACTION_DURATION.get(current_action, 3.0)
                if t >= duration:
                    print(f"[vsf] action end: {current_action}")
                    sys.stdout.flush()
                    recovery_from = get_action_overrides(
                        current_action,
                        max(0.0, duration - LOOP_INTERVAL),
                    )
                    recovery_start = now
                    if current_action == "fortune_pose_preview":
                        _fortune_pose_preview_active = False
                    current_action = None
                    _current_action_name = None
                    if ENABLE_IDLE_MOTION:
                        idle_pose = get_idle_overrides(now, speaking)
                        blended = {
                            bone: quat_slerp(quat, idle_pose.get(bone, _I), 0.0)
                            for bone, quat in recovery_from.items()
                        }
                        dgrams_to_send = build_pose_dgrams(blended, idle_pose)
                    else:
                        dgrams_to_send = _bone_dgrams
                else:
                    overrides = get_action_overrides(current_action, t)
                    if ENABLE_IDLE_MOTION:
                        dgrams_to_send = build_pose_dgrams(overrides, get_idle_overrides(now, speaking))
                    elif overrides:
                        dgrams_to_send = build_pose_dgrams(overrides)
                    else:
                        dgrams_to_send = _bone_dgrams
            elif recovery_from and now - recovery_start < recovery_duration:
                idle_pose = get_idle_overrides(now, speaking)
                progress = _smooth((now - recovery_start) / recovery_duration)
                blended = {
                    bone: quat_slerp(quat, idle_pose.get(bone, _I), progress)
                    for bone, quat in recovery_from.items()
                }
                dgrams_to_send = build_pose_dgrams(blended, idle_pose)
            else:
                recovery_from = None
                if ENABLE_IDLE_MOTION:
                    dgrams_to_send = build_pose_dgrams({}, get_idle_overrides(now, speaking))
                else:
                    dgrams_to_send = _bone_dgrams

            # ---- VMC 送信 ----
            sock.sendto(_ok_dgram, addr)
            for dgram in dgrams_to_send:
                sock.sendto(dgram, addr)
            if blink_started_at is None and now >= next_blink_at:
                blink_started_at = now
            blink_value = natural_blink_value(now, blink_started_at)
            if blink_started_at is not None and now - blink_started_at >= 0.34:
                blink_started_at = None
                next_blink_at = now + random.uniform(2.6, 6.2)
            face_values = dict(current_expression_values)
            face_values["Blink"] = blink_value
            send_expression_values(face_values, sock, addr)
            send_lip_sync(sock, addr, speaking, now, lip_gain)
            tick += 1
            if tick % 40 == 1:
                status = f"action={current_action}" if current_action else "idle"
                print(f"[vsf] {status} expr=smooth-vmc {len(dgrams_to_send)} bones -> {VSF_HOST}:{VSF_PORT}")
                sys.stdout.flush()

        except Exception:
            print("[vsf] loop error:")
            traceback.print_exc()
            sys.stdout.flush()

        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[vsf] stopped")
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        input("Press Enter to close...")
