"""MW Sound Optimizer v3 - Tactical Audio HUD
Egaliseur + outils audio pour Call of Duty MW / Warzone (ecouteurs).
- Equalizer APO : EQ, largeur stereo, coupe-explosions, niveau, balance
- Voicemeeter   : detection, VU-metre, EQ natif (Banana / Potato), commandes
- Warzone / COD : detection du jeu et activation automatique
Le logiciel ne touche jamais au jeu : il lit seulement la liste des processus.
"""
import array
import cmath
import ctypes
import json
import math
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import wave
import winreg
import winsound
from ctypes import wintypes
from tkinter import messagebox, simpledialog

APP_NAME = "MW Sound Optimizer"
VERSION = "3.0"
PF = os.environ.get("ProgramFiles", r"C:\Program Files")
PF86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
APO_DIR = os.path.join(PF, "EqualizerAPO")
APO_CFG_DIR = os.path.join(APO_DIR, "config")
APO_MAIN = os.path.join(APO_CFG_DIR, "config.txt")
APO_OUT = os.path.join(APO_CFG_DIR, "MW_optimizer.txt")
APO_INCLUDE = "Include: MW_optimizer.txt"
SETTINGS_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MWSoundOptimizer")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
TEST_WAV = os.path.join(SETTINGS_DIR, "test.wav")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "MWSoundOptimizer"

# ---------------------------------------------------------------- theme
BG = "#05070d"
PANEL = "#0a0f1e"
PANEL2 = "#111a33"
LINE = "#1b2a4d"
TXT = "#eaf2ff"
MUTED = "#6c7da6"
ACC = "#00e5ff"
MAG = "#ff2bd6"
LIME = "#a6ff3d"
BAD = "#ff4d6d"
WARN = "#ffc247"
HEAD = "Bahnschrift"
FONT = "Segoe UI"


def F(px, bold=False, head=False):
    return (HEAD if head else FONT, -px, "bold" if bold else "normal")


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# nom, frequence, type APO, Q, (min Hz, max Hz), couleur
BANDS = [
    ("Graves", 100, "LSC", 0.7, (40, 250), "#ff5fa8"),
    ("Bas-medium", 250, "PK", 1.0, (150, 500), "#ff9a3d"),
    ("Voix", 1200, "PK", 1.2, (700, 2000), "#ffd23d"),
    ("Pas", 2500, "PK", 1.4, (1500, 3500), LIME),
    ("Recharge", 4000, "PK", 1.5, (2500, 6000), ACC),
    ("Aigus", 7500, "PK", 2.0, (5000, 12000), "#b08cff"),
]
NB = len(BANDS)
PRESETS = {
    "Pas / competitif": [-5, -3, 2, 4, 3, -3],
    "Equilibre": [-2, -1, 1, 2, 1, -1],
    "Pas extreme": [-8, -5, 3, 6, 4, -4],
    "Immersion": [3, 1, -1, -1, 0, 1],
    "Voix / chat": [-4, -1, 3, 2, 0, -2],
    "Neutre": [0] * NB,
}
FS = 48000.0
GMAX = 12.0
NBAR = 72
PEAK_FREQS = [20 * (1000 ** (k / 70)) for k in range(71)]
GAME_RE = re.compile(r"^(cod|cod\d\d-cod|sp\d\d-cod|cod-?hq|modernwarfare|warzone|blackops\w*|vanguard)\.exe$", re.I)


# ---------------------------------------------------------------- DSP
def biquad(kind, f0, gain, q):
    a = 10 ** (gain / 40.0)
    w0 = 2 * math.pi * f0 / FS
    cw, sw = math.cos(w0), math.sin(w0)
    al = sw / (2 * q)
    if kind == "LSC":
        sa = math.sqrt(a)
        b0 = a * ((a + 1) - (a - 1) * cw + 2 * sa * al)
        b1 = 2 * a * ((a - 1) - (a + 1) * cw)
        b2 = a * ((a + 1) - (a - 1) * cw - 2 * sa * al)
        a0 = (a + 1) + (a - 1) * cw + 2 * sa * al
        a1 = -2 * ((a - 1) + (a + 1) * cw)
        a2 = (a + 1) + (a - 1) * cw - 2 * sa * al
    elif kind == "HP":
        b0, b1, b2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
        a0, a1, a2 = 1 + al, -2 * cw, 1 - al
    elif kind == "BP":
        b0, b1, b2 = al, 0.0, -al
        a0, a1, a2 = 1 + al, -2 * cw, 1 - al
    else:
        b0, b1, b2 = 1 + al * a, -2 * cw, 1 - al * a
        a0, a1, a2 = 1 + al / a, -2 * cw, 1 - al / a
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def resp_db(c, f):
    b0, b1, b2, a1, a2 = c
    z = cmath.exp(-1j * 2 * math.pi * f / FS)
    h = (b0 + b1 * z + b2 * z * z) / (1 + a1 * z + a2 * z * z)
    return 20 * math.log10(max(abs(h), 1e-9))


# ---------------------------------------------------------------- sons de test
def make_test_wav(kind):
    sr = 48000
    fr = []
    if kind == "lr":
        for side in (0, 1, 0, 1):
            n = int(0.5 * sr)
            f0 = 660 if side == 0 else 880
            for k in range(n):
                env = min(1.0, k / 480, (n - k) / 480)
                s = int(0.22 * 32767 * env * math.sin(2 * math.pi * f0 * k / sr))
                fr.extend((s, 0) if side == 0 else (0, s))
            fr.extend([0, 0] * int(0.25 * sr))
    elif kind == "steps":
        b0, b1, b2, a1, a2 = biquad("BP", 2200, 0, 0.9)
        rnd = random.Random(7)
        for step in range(9):
            pan = step / 8.0
            gl, gr = math.cos(pan * math.pi / 2), math.sin(pan * math.pi / 2)
            x1 = x2 = y1 = y2 = 0.0
            for k in range(int(0.42 * sr)):
                t = k / sr
                if t < 0.12:
                    x = rnd.uniform(-1, 1) * math.exp(-t * 45)
                    th = 0.5 * math.sin(2 * math.pi * 110 * t) * math.exp(-t * 60)
                else:
                    x = th = 0.0
                y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
                x2, x1, y2, y1 = x1, x, y1, y
                s = max(-1.0, min(1.0, 0.9 * y + 0.25 * th)) * 0.5 * 32767
                fr.append(int(s * gl))
                fr.append(int(s * gr))
    else:  # balayage
        n = 6 * sr
        ph = 0.0
        for k in range(n):
            ph += 2 * math.pi * 20 * (1000 ** (k / n)) / sr
            env = min(1.0, k / 2400, (n - k) / 2400)
            s = int(0.16 * 32767 * env * math.sin(ph))
            fr.append(s)
            fr.append(s)
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with wave.open(TEST_WAV, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(array.array("h", fr).tobytes())


# ---------------------------------------------------------------- detection du jeu
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


def find_game(extra=()):
    """Retourne le nom de l'exe du jeu s'il tourne (lecture seule de la liste des processus)."""
    h = _k32.CreateToolhelp32Snapshot(2, 0)
    if not h or h == ctypes.c_void_p(-1).value:
        return None
    found = None
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _k32.Process32FirstW(h, ctypes.byref(pe))
        extra = {e.lower() for e in extra}
        while ok:
            name = pe.szExeFile
            if GAME_RE.match(name) or name.lower() in extra:
                found = name
                break
            ok = _k32.Process32NextW(h, ctypes.byref(pe))
    finally:
        _k32.CloseHandle(h)
    return found


# ---------------------------------------------------------------- Equalizer APO
def apo_devices():
    """Sorties audio sur lesquelles Equalizer APO est installe : [(guid, nom)]."""
    res = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EqualizerAPO\Child APOs") as k:
            guids = []
            i = 0
            while True:
                try:
                    guids.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        return res
    for g in guids:
        try:
            p = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render" + "\\" + g + r"\Properties"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, p) as k:
                desc = winreg.QueryValueEx(k, "{a45c254e-df1c-4efd-8020-67d146a850e0},2")[0]
                try:
                    iface = winreg.QueryValueEx(k, "{b3f8fa53-0004-438e-9003-51a46e139bfc},6")[0]
                except OSError:
                    iface = ""
            res.append((g.strip("{}").lower(), f"{desc} ({iface})" if iface else str(desc)))
        except OSError:
            continue
    return res


def other_apo_configs():
    try:
        with open(APO_MAIN, "r", encoding="utf-8", errors="ignore") as f:
            c = f.read().lower()
    except OSError:
        return []
    out = []
    if "yousound" in c:
        out.append("YouSound")
    if "hesuvi" in c:
        out.append("HeSuVi")
    if "peace.txt" in c:
        out.append("Peace")
    return out


# ---------------------------------------------------------------- sortie Windows par defaut
class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def set_default_output(dev_id):
    """Definit la sortie audio par defaut de Windows (meme reglage que Parametres > Son).
    La sortie "communications" n'est pas modifiee. Retourne "" si tout va bien, sinon l'erreur."""
    ole = ctypes.OleDLL("ole32")
    inited = False
    try:
        try:
            ole.CoInitializeEx(None, 0)
            inited = True
        except OSError:
            pass  # COM deja initialise autrement sur ce thread
        clsid, iid = _GUID(), _GUID()
        ole.CLSIDFromString(ctypes.c_wchar_p("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"), ctypes.byref(clsid))
        ole.CLSIDFromString(ctypes.c_wchar_p("{f8679f50-850a-41cf-9c72-430f290290c8}"), ctypes.byref(iid))
        p = ctypes.c_void_p()
        ole.CoCreateInstance(ctypes.byref(clsid), None, 23, ctypes.byref(iid), ctypes.byref(p))
        vt = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        set_ep = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)(vt[13])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
        try:
            for role in (0, 1):  # console + multimedia
                set_ep(p, dev_id, role)
        finally:
            release(p)
        return ""
    except OSError as e:
        return str(e)
    finally:
        if inited:
            ole.CoUninitialize()


# ---------------------------------------------------------------- Voicemeeter
class Voicemeeter:
    TYPES = {1: "Voicemeeter Standard", 2: "Voicemeeter Banana", 3: "Voicemeeter Potato"}

    def __init__(self):
        self.dll = None
        self.logged = False
        self.vtype = 0
        self.install_dir = None
        for base in (PF86, PF):
            d = os.path.join(base, "VB", "Voicemeeter")
            for name in ("VoicemeeterRemote64.dll", "VoicemeeterRemote.dll"):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    try:
                        self.dll = ctypes.WinDLL(p)
                        self.install_dir = d
                        break
                    except OSError:
                        continue
            if self.dll:
                break
        if self.dll:
            d = self.dll
            d.VBVMR_Login.restype = ctypes.c_long
            d.VBVMR_Logout.restype = ctypes.c_long
            d.VBVMR_RunVoicemeeter.argtypes = [ctypes.c_long]
            d.VBVMR_GetVoicemeeterType.argtypes = [ctypes.POINTER(ctypes.c_long)]
            d.VBVMR_GetVoicemeeterType.restype = ctypes.c_long
            d.VBVMR_SetParameters.argtypes = [ctypes.c_char_p]
            d.VBVMR_SetParameters.restype = ctypes.c_long
            d.VBVMR_IsParametersDirty.restype = ctypes.c_long
            d.VBVMR_GetLevel.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.POINTER(ctypes.c_float)]
            d.VBVMR_GetLevel.restype = ctypes.c_long

    @property
    def available(self):
        return self.dll is not None

    def login(self):
        if self.dll and not self.logged and self.dll.VBVMR_Login() >= 0:
            self.logged = True

    def logout(self):
        if self.dll and self.logged:
            self.dll.VBVMR_Logout()
            self.logged = False

    def refresh(self):
        self.vtype = 0
        if self.dll:
            self.login()
            t = ctypes.c_long(0)
            if self.logged and self.dll.VBVMR_GetVoicemeeterType(ctypes.byref(t)) == 0:
                self.vtype = t.value
        return self.vtype

    def run(self):
        if not self.dll:
            return
        self.login()
        d = self.install_dir
        for code, exe in ((3, "voicemeeter8.exe"), (2, "voicemeeterpro.exe"), (1, "voicemeeter.exe")):
            if os.path.isfile(os.path.join(d, exe)):
                self.dll.VBVMR_RunVoicemeeter(code)
                return

    def script(self, text):
        if not self.dll or not self.logged or not self.vtype:
            return False
        ok, chunk, size = True, [], 0
        for p in text.split(";"):
            chunk.append(p)
            size += len(p) + 1
            if size > 1800:
                ok &= self.dll.VBVMR_SetParameters(";".join(chunk).encode("ascii")) >= 0
                chunk, size = [], 0
        if chunk:
            ok &= self.dll.VBVMR_SetParameters(";".join(chunk).encode("ascii")) >= 0
        return ok

    def levels(self):
        """Niveau de sortie du bus A1 (gauche, droite), lineaire."""
        if not self.dll or not self.logged or not self.vtype:
            return None
        self.dll.VBVMR_IsParametersDirty()
        out = []
        for ch in (0, 1):
            v = ctypes.c_float(0)
            if self.dll.VBVMR_GetLevel(3, ch, ctypes.byref(v)) != 0:
                return None
            out.append(v.value)
        return out


# ---------------------------------------------------------------- spectre en direct
class Spectrum(threading.Thread):
    """Analyse en direct de ce qui sort sur le peripherique par defaut (capture loopback)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.bands = [0.0] * NBAR
        self.stamp = 0.0
        self.ok = False
        self.device = ""
        self.dev_id = ""
        self.outputs = []  # sorties Windows actives : [(id, nom)]
        self.err = ""

    def scan(self, sc):
        spk = sc.default_speaker()
        self.outputs = [(str(s.id), str(s.name)) for s in sc.all_speakers()]
        self.device, self.dev_id = spk.name, str(spk.id)
        return spk

    def run(self):
        try:
            import warnings
            import numpy as np
            import soundcard as sc
            warnings.filterwarnings("ignore")
        except Exception as e:  # modules absents : pas de spectre
            self.err = str(e)
            return
        n = 4096
        hop = 1024
        win = np.hanning(n)
        edges = [20 * (1000 ** (k / NBAR)) * n / 48000.0 for k in range(NBAR + 1)]
        rng = []
        for k in range(NBAR):
            lo = max(1, int(edges[k]))
            rng.append((lo, max(lo + 1, int(math.ceil(edges[k + 1])))))
        tilt = [3.0 * math.log2(max(20 * (1000 ** ((k + 0.5) / NBAR)), 20) / 1000.0) for k in range(NBAR)]
        buf = np.zeros(n, dtype=np.float32)
        while True:
            try:
                spk = self.scan(sc)
                mic = sc.get_microphone(id=str(spk.id), include_loopback=True)
                with mic.recorder(samplerate=48000, channels=2, blocksize=hop) as rec:
                    self.ok = True
                    self.err = ""
                    last = time.time()
                    while True:
                        data = rec.record(numframes=hop)
                        buf = np.concatenate((buf[hop:], data.mean(axis=1).astype(np.float32)))
                        db = 20 * np.log10(np.abs(np.fft.rfft(buf * win)) / (n / 4) + 1e-9)
                        self.bands = [min(1.0, max(0.0, (float(db[a:b].max()) + tilt[k] + 82.0) / 62.0))
                                      for k, (a, b) in enumerate(rng)]
                        self.stamp = time.time()
                        if self.stamp - last > 2:
                            last = self.stamp
                            if str(self.scan(sc).id) != str(spk.id):
                                break
            except Exception as e:
                self.ok = False
                self.err = str(e)
                time.sleep(3)


# ---------------------------------------------------------------- raccourcis globaux
class Hotkeys:
    """Ctrl+Alt+F9 : EQ on/off  -  Ctrl+Alt+F10 : preset suivant (API Windows RegisterHotKey)."""

    def __init__(self, q):
        self.q = q
        self.tid = None
        self.failed = False

    def start(self):
        if self.tid is None:
            threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        if self.tid:
            ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)

    def _run(self):
        u = ctypes.windll.user32
        self.tid = ctypes.windll.kernel32.GetCurrentThreadId()
        ok = [u.RegisterHotKey(None, i + 1, 0x4003, vk) for i, vk in enumerate((0x78, 0x79))]
        self.failed = not all(ok)
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:
                self.q.put(int(msg.wParam))
        for i in (1, 2):
            u.UnregisterHotKey(None, i)
        self.tid = None


# ---------------------------------------------------------------- widgets
def chamfer(c, x1, y1, x2, y2, cut, **kw):
    return c.create_polygon(x1 + cut, y1, x2, y1, x2, y2 - cut, x2 - cut, y2, x1, y2, x1, y1 + cut, **kw)


class Chip(tk.Label):
    def __init__(self, master, text, command=None, right=None, color=ACC, small=False, bg=PANEL2):
        super().__init__(master, text=text, font=F(12 if small else 13, True), cursor="hand2",
                         padx=9 if small else 14, pady=3 if small else 6, bg=bg, fg=TXT,
                         highlightthickness=1, highlightbackground=LINE)
        self.base, self.color, self.active = bg, color, False
        if command:
            self.bind("<Button-1>", lambda e: command())
        if right:
            self.bind("<Button-3>", lambda e: right())
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))

    def set_active(self, v):
        self.active = bool(v)
        self._paint(False)

    def _paint(self, hover):
        if self.active:
            self.config(bg=self.color, fg="#02141a", highlightbackground=self.color)
        else:
            self.config(bg=LINE if hover else self.base, fg=TXT,
                        highlightbackground=self.color if hover else LINE)


class BigCard(tk.Frame):
    """Grand bouton de profil du mode simple."""

    def __init__(self, master, title, sub, color, command):
        super().__init__(master, bg=PANEL, highlightthickness=2, highlightbackground=LINE, cursor="hand2")
        self.color = color
        tk.Frame(self, bg=color, height=3).pack(fill="x")
        self.t = tk.Label(self, text=title, font=F(19, True, True), fg=TXT, bg=PANEL, cursor="hand2")
        self.t.pack(pady=(14, 0))
        self.s = tk.Label(self, text=sub, font=F(11), fg=MUTED, bg=PANEL, cursor="hand2")
        self.s.pack(pady=(2, 14), padx=8)
        for w in (self, self.t, self.s):
            w.bind("<Button-1>", lambda e: command())

    def set_active(self, v):
        bg = mix(PANEL, self.color, 0.16) if v else PANEL
        self.config(bg=bg, highlightbackground=self.color if v else LINE)
        self.t.config(bg=bg, fg=self.color if v else TXT)
        self.s.config(bg=bg, fg=TXT if v else MUTED)


def style_menu(om, width):
    om.config(bg=PANEL2, fg=TXT, activebackground=LINE, activeforeground=TXT, highlightthickness=1,
              highlightbackground=LINE, bd=0, relief="flat", font=F(12), anchor="w", width=width)
    om["menu"].config(bg=PANEL2, fg=TXT, activebackground=ACC, activeforeground="#02141a", bd=0, font=F(12))


SIMPLE_CARDS = [
    ("COMPETITIF", "Pas / competitif", "Pas et recharges en avant", LIME),
    ("EQUILIBRE", "Equilibre", "Plus de detail, sans exces", ACC),
    ("PAS EXTREME", "Pas extreme", "Maximum sur les pas, moins de graves", MAG),
    ("IMMERSION", "Immersion", "Graves et ambiance", "#ff9a3d"),
]


class HSlider(tk.Canvas):
    def __init__(self, master, lo, hi, value, command, color=ACC, step=0.5, default=0.0, width=176, bg=PANEL):
        super().__init__(master, width=width, height=24, bg=bg, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.val, self.command = lo, hi, value, command
        self.color, self.step, self.default, self.w = color, step, default, width
        self.bind("<Button-1>", self._ev)
        self.bind("<B1-Motion>", self._ev)
        self.bind("<Double-Button-1>", lambda e: self._user(self.default))
        self.draw()

    def _x(self, v):
        return 10 + (v - self.lo) / (self.hi - self.lo) * (self.w - 20)

    def _ev(self, e):
        v = self.lo + (e.x - 10) / (self.w - 20) * (self.hi - self.lo)
        self._user(max(self.lo, min(self.hi, round(v / self.step) * self.step)))

    def _user(self, v):
        if v != self.val:
            self.val = v
            self.draw()
            self.command(v)

    def set(self, v):
        self.val = v
        self.draw()

    def draw(self):
        self.delete("all")
        y, x = 12, self._x(self.val)
        x0 = self._x(0 if self.lo < 0 < self.hi else self.lo)
        self.create_line(10, y, self.w - 10, y, fill=LINE, width=4, capstyle="round")
        self.create_line(x0, y, x, y, fill=self.color, width=4, capstyle="round")
        self.create_oval(x - 10, y - 10, x + 10, y + 10, fill=mix(BG, self.color, 0.25), outline="")
        self.create_oval(x - 6, y - 6, x + 6, y + 6, fill=self.color, outline=BG, width=2)


# ---------------------------------------------------------------- application
class App(tk.Tk):
    W = 1200

    def __init__(self, minimized=False):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.configure(bg=BG)
        self.geometry("1240x852")
        self.resizable(False, False)
        self.make_icon()

        self.gains = [float(x) for x in PRESETS["Pas / competitif"]]
        self.fcs = [float(b[1]) for b in BANDS]
        self.qs = [float(b[3]) for b in BANDS]
        self.cur_preset = "Pas / competitif"
        self.custom = {}
        self.enabled = True
        self.bypass = False
        self.intensity = 1.0
        self.level = 0.0
        self.balance = 0.0
        self.width = 0.0
        self.hp = 0
        self.swap = False
        self.mode = "apo"
        self.target = "auto"  # "auto" = sortie Windows par defaut, "all" = toutes, sinon GUID
        self.auto_guid = ""
        self.auto_game = False
        self.hotkeys_on = True
        self.buses = [1, 0, 0, 0, 0]
        self.extra_games = []
        self.simple = True        # mode simple par defaut
        self.win_allow = False    # le logiciel ne touche pas aux reglages son de Windows sans accord
        self.win_prev = ""        # sortie Windows d'origine, pour "Restaurer"
        self.win_default = ""
        self.outputs = []
        self.uiq = queue.Queue()
        self.load_settings()

        self.drag = None
        self.hover = None
        self._after = None
        self.game = None
        self.game_known = False
        self.hud = None
        self.sv = [0.0] * NBAR
        self.vu = [0.0, 0.0]
        self.scan_x = 0
        self.devices = apo_devices()

        self.vm = Voicemeeter()
        self.spec = Spectrum()
        self.spec.start()
        self.hkq = queue.Queue()
        self.hk = Hotkeys(self.hkq)
        if self.hotkeys_on:
            self.hk.start()

        self.build_ui()
        self.sync_all()
        self.redraw()
        self.tick_slow()
        self.tick_fast()
        self.apply()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if minimized:
            self.iconify()

    # ------------------------------------------------------------ icone / reglages
    def make_icon(self):
        try:  # logo fourni avec le programme (icon64.png), sinon pictogramme dessine
            here = os.path.dirname(os.path.abspath(__file__))
            base = getattr(sys, "_MEIPASS", None)
            path = os.path.join(base, "icon64.png") if base else os.path.join(here, "..", "assets", "icon64.png")
            self._icon = tk.PhotoImage(file=path)
            self.iconphoto(True, self._icon)
            return
        except (tk.TclError, OSError):
            pass
        img = tk.PhotoImage(width=32, height=32)
        img.put(BG, to=(0, 0, 32, 32))
        for i, (h, col) in enumerate(((10, "#ff5fa8"), (16, "#ffd23d"), (26, LIME), (20, ACC), (12, "#b08cff"))):
            img.put(col, to=(3 + i * 6, 29 - h, 7 + i * 6, 29))
        self._icon = img
        self.iconphoto(True, img)

    def load_settings(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            return
        try:
            self.gains = [float(x) for x in s.get("gains", self.gains)][:NB]
            self.fcs = [float(x) for x in s.get("fcs", self.fcs)][:NB]
            self.qs = [float(x) for x in s.get("qs", self.qs)][:NB]
            self.enabled = bool(s.get("enabled", True))
            self.mode = s.get("mode", "apo")
            self.buses = [int(x) for x in s.get("buses", self.buses)][:5]
            self.custom = dict(s.get("custom", {}))
            self.cur_preset = s.get("preset", "")
            self.intensity = float(s.get("intensity", 1.0))
            self.level = float(s.get("level", 0.0))
            self.balance = float(s.get("balance", 0.0))
            self.width = float(s.get("width", 0.0))
            self.hp = int(s.get("hp", 0))
            self.swap = bool(s.get("swap", False))
            self.target = s.get("target", "auto")
            self.auto_game = bool(s.get("auto_game", False))
            self.hotkeys_on = bool(s.get("hotkeys", True))
            self.extra_games = list(s.get("game_processes", []))
            self.simple = bool(s.get("simple", True))
            self.win_allow = bool(s.get("win_allow", False))
            self.win_prev = str(s.get("win_prev", ""))
        except Exception:
            pass

    def save_settings(self):
        try:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "gains": self.gains, "fcs": self.fcs, "qs": self.qs, "enabled": self.enabled,
                    "mode": self.mode, "buses": self.buses, "custom": self.custom, "preset": self.cur_preset,
                    "intensity": self.intensity, "level": self.level, "balance": self.balance,
                    "width": self.width, "hp": self.hp, "swap": self.swap, "target": self.target,
                    "auto_game": self.auto_game, "hotkeys": self.hotkeys_on,
                    "game_processes": self.extra_games, "simple": self.simple,
                    "win_allow": self.win_allow, "win_prev": self.win_prev,
                }, f, indent=1)
        except OSError:
            pass

    # ------------------------------------------------------------ interface
    def build_ui(self):
        W = self.W
        # --- en-tete
        hd = self.hd = tk.Canvas(self, width=W, height=74, bg=BG, highlightthickness=0)
        hd.pack(padx=20, pady=(12, 0))
        x = 0
        for txt, col in (("MW", ACC), ("//", MAG), ("SOUND OPTIMIZER", TXT)):
            hd.create_text(x, 28, text=txt, anchor="w", font=F(34, True, True), fill=col)
            x += tkfont.Font(font=F(34, True, True)).measure(txt) + 4
        hd.create_text(2, 58, anchor="w", font=F(11, True, True), fill=MUTED,
                       text=f"TACTICAL AUDIO HUD   //   V{VERSION}   //   WARZONE · MW   //   VOICEMEETER LINK")
        hd.create_line(0, 72, W, 72, fill=LINE)
        hd.create_line(0, 72, 260, 72, fill=ACC, width=2)
        hd.create_line(0, 72, 60, 72, fill=TXT, width=2, tags="scan")
        hd.tag_bind("sw", "<Button-1>", lambda e: self.toggle_enabled())
        # --- tuiles d'etat
        tl = self.tl = tk.Canvas(self, width=W, height=58, bg=BG, highlightthickness=0)
        tl.pack(padx=20, pady=(10, 0))
        tw = (W - 30) / 4
        for i, name in enumerate(("WARZONE / COD", "VOICEMEETER", "EQUALIZER APO", "PROFIL ACTIF")):
            x0 = i * (tw + 10)
            chamfer(tl, x0, 1, x0 + tw, 57, 12, fill=PANEL, outline=LINE, tags=f"box{i}")
            tl.create_oval(x0 + 16, 23, x0 + 28, 35, fill=MUTED, outline="", tags=f"led{i}")
            tl.create_text(x0 + 40, 18, anchor="w", text=name, font=F(10, True, True), fill=MUTED)
            tl.create_text(x0 + 40, 38, anchor="w", text="...", font=F(14, True), fill=TXT, tags=f"val{i}")
        # --- graphe
        self.gw, self.gh = W, 286
        self.gx0, self.gx1, self.gy0, self.gy1 = 48, W - 16, 28, self.gh - 26
        cv = self.cv = tk.Canvas(self, width=self.gw, height=self.gh, bg=PANEL, highlightthickness=1,
                                 highlightbackground=LINE)
        cv.pack(padx=20, pady=(10, 0))
        self.draw_static()
        cv.bind("<Button-1>", self.g_press)
        cv.bind("<B1-Motion>", self.g_move)
        cv.bind("<ButtonRelease-1>", lambda e: self.g_release())
        cv.bind("<Motion>", self.g_hover)
        cv.bind("<MouseWheel>", self.g_wheel)
        cv.bind("<Double-Button-1>", self.g_reset)
        self.build_winbar()
        self.build_simple()
        # --- presets + intensite (mode expert)
        pr = self.pr = tk.Frame(self, bg=BG)
        tk.Label(pr, text="PRESETS", font=F(11, True, True), fg=MUTED, bg=BG).pack(side="left", padx=(0, 10))
        self.chip_row = tk.Frame(pr, bg=BG)
        self.chip_row.pack(side="left")
        Chip(pr, "+ Enregistrer", self.save_preset, color=MAG).pack(side="right")
        self.int_lbl = tk.Label(pr, text="100 %", width=6, font=F(12, True), fg=TXT, bg=BG)
        self.int_lbl.pack(side="right", padx=(0, 10))
        self.int_sl = HSlider(pr, 0, 150, self.intensity * 100, self.on_intensity, MAG, 5, 100, 150, BG)
        self.int_sl.pack(side="right")
        tk.Label(pr, text="INTENSITE", font=F(11, True, True), fg=MUTED, bg=BG).pack(side="right", padx=(0, 4))
        self.chips = {}
        self.rebuild_chips()
        # --- bandes
        bd = self.bd = tk.Frame(self, bg=BG)
        self.b_gain, self.b_freq = [], []
        for i, b in enumerate(BANDS):
            card = tk.Frame(bd, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
            card.pack(side="left", expand=True, fill="both", padx=(0 if i == 0 else 8, 0))
            tk.Frame(card, bg=b[5], height=2).pack(fill="x")
            top = tk.Frame(card, bg=PANEL)
            top.pack(fill="x", padx=10, pady=(5, 0))
            tk.Label(top, text=b[0].upper(), font=F(11, True, True), fg=b[5], bg=PANEL).pack(side="left")
            fl = tk.Label(top, text="", font=F(11), fg=MUTED, bg=PANEL)
            fl.pack(side="right")
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", padx=8, pady=(2, 7))
            Chip(row, "\u2212", lambda k=i: self.bump(k, -0.5), color=b[5], small=True).pack(side="left")
            Chip(row, "+", lambda k=i: self.bump(k, 0.5), color=b[5], small=True).pack(side="right")
            gl = tk.Label(row, text="", font=F(18, True, True), fg=TXT, bg=PANEL)
            gl.pack(expand=True)
            self.b_gain.append(gl)
            self.b_freq.append(fl)
        # --- panneaux du bas
        bot = self.bot = tk.Frame(self, bg=BG)
        self.build_output(bot)
        self.build_tools(bot)
        self.build_vm(bot)
        self.status = tk.Label(self, text="Pret.", font=F(12), fg=MUTED, bg=BG, anchor="w")
        self.set_view()

    def set_view(self):
        """Mode simple : profils en un clic. Mode expert : tous les reglages."""
        for w in (self.simple_row, self.pr, self.bd, self.bot, self.status):
            w.pack_forget()
        if self.simple:
            self.simple_row.pack(fill="x", padx=20, pady=(8, 0))
        else:
            self.pr.pack(fill="x", padx=20, pady=(8, 0))
            self.bd.pack(fill="x", padx=20, pady=(8, 0))
            self.bot.pack(fill="x", padx=20, pady=(8, 0))
        self.status.pack(fill="x", padx=20, pady=(4, 6))
        self.view_chip.config(text="Mode expert  ▸" if self.simple else "◂  Mode simple")
        self.update_idletasks()
        self.geometry(f"1240x{self.winfo_reqheight()}")

    def toggle_view(self):
        self.simple = not self.simple
        self.set_view()
        self.save_settings()

    def build_winbar(self):
        f = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        f.pack(fill="x", padx=20, pady=(8, 0))
        r = tk.Frame(f, bg=PANEL)
        r.pack(fill="x", padx=10, pady=6)
        tk.Frame(r, bg=WARN, width=4, height=14).pack(side="left")
        tk.Label(r, text="WINDOWS", font=F(12, True, True), fg=TXT, bg=PANEL).pack(side="left", padx=(8, 14))
        tk.Label(r, text="Sortie par defaut", font=F(12), fg=MUTED, bg=PANEL).pack(side="left", padx=(0, 6))
        self.win_var = tk.StringVar(value="recherche...")
        self.win_menu = tk.OptionMenu(r, self.win_var, "")
        style_menu(self.win_menu, 42)
        self.win_menu.pack(side="left")
        self.t_win = Chip(r, "", self.toggle_win_allow, color=WARN, small=True)
        self.t_win.pack(side="left", padx=(8, 4))
        Chip(r, "Restaurer", self.win_restore, color=WARN, small=True).pack(side="left")
        self.view_chip = Chip(r, "", self.toggle_view, small=True)
        self.view_chip.pack(side="right")
        Chip(r, "Reglage automatique", self.auto_setup, color=LIME, small=True).pack(side="right", padx=(0, 6))

    def build_simple(self):
        f = self.simple_row = tk.Frame(self, bg=BG)
        self.cards = {}
        for i, (title, preset, sub, col) in enumerate(SIMPLE_CARDS):
            c = BigCard(f, title, sub, col, lambda p=preset: self.pick_simple(p))
            c.pack(side="left", fill="both", expand=True, padx=(0 if i == 0 else 8, 0))
            self.cards[preset] = c
        side = tk.Frame(f, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        side.pack(side="left", fill="y", padx=(8, 0))
        inner = tk.Frame(side, bg=PANEL)
        inner.pack(padx=12, pady=6)
        r = tk.Frame(inner, bg=PANEL)
        r.pack(fill="x")
        tk.Label(r, text="FORCE DE L'EFFET", font=F(11, True, True), fg=MUTED, bg=PANEL).pack(side="left")
        self.int_lbl2 = tk.Label(r, text="", font=F(12, True), fg=TXT, bg=PANEL)
        self.int_lbl2.pack(side="right")
        self.int_sl2 = HSlider(inner, 0, 150, self.intensity * 100, self.on_intensity, MAG, 5, 100, 230)
        self.int_sl2.pack()
        r = tk.Frame(inner, bg=PANEL)
        r.pack(fill="x", pady=(2, 0))
        self.t_auto2 = Chip(r, "Auto Warzone", self.toggle_auto, color=LIME, small=True)
        self.t_auto2.pack(side="left")
        Chip(r, "Configurator APO", self.open_configurator, small=True).pack(side="right")

    def pick_simple(self, preset):
        if not self.enabled:
            self.enabled = True
            self.draw_switch()
        self.set_preset(preset)

    def auto_setup(self):
        """Remet tout sur les reglages recommandes, sans toucher a Windows."""
        self.target, self.mode, self.enabled = "auto", "apo", True
        self.level = self.balance = self.width = 0.0
        self.hp, self.swap = 0, False
        for s, v in ((self.lvl_sl, 0.0), (self.bal_sl, 0.0), (self.wid_sl, 0.0)):
            s.set(v)
            s.label.config(text=s.fmt(v))
        self.show_intensity(100)
        self.fill_devices()
        self.sync_all()
        self.set_preset("Pas / competitif")
        if self._after:
            self.after_cancel(self._after)
        self.apply()
        if not os.path.isdir(APO_CFG_DIR):
            self.say("Equalizer APO n'est pas installe : rien ne peut etre applique.", BAD)
        elif self.auto_guid:
            name = next(nm for g, nm in self.devices if g == self.auto_guid)
            self.say(f"Reglage automatique termine : profil competitif sur {name}.", LIME)
        else:
            self.say("Reglage applique, mais ta sortie Windows par defaut n'a pas Equalizer APO : ouvre "
                     "« Configurator APO », coche-la, puis redemarre le PC.", WARN)

    def show_intensity(self, v):
        self.intensity = v / 100.0
        for s in (self.int_sl, self.int_sl2):
            s.set(v)
        for lab in (self.int_lbl, self.int_lbl2):
            lab.config(text=f"{v:.0f} %")

    # ------------------------------------------------------------ sortie Windows
    def fill_win(self):
        self.win_names = {}
        m = self.win_menu["menu"]
        m.delete(0, "end")
        for did, name in self.outputs:
            label = name[:54]
            self.win_names[label] = did
            m.add_command(label=label, command=lambda i=did, n=label: self.on_win_device(i, n))
        self.win_var.set(next((n for n, i in self.win_names.items() if i == self.win_default), "inconnue"))

    def win_change(self, did, ok_msg):
        def work():
            err = set_default_output(did)
            self.uiq.put((ok_msg, LIME) if not err else (f"Windows a refuse le changement : {err}", BAD))
        threading.Thread(target=work, daemon=True).start()

    def on_win_device(self, did, label):
        if did == self.win_default:
            return
        if not self.win_allow:
            self.say("« Modifier Windows » est sur NON : le logiciel ne change aucun reglage son de Windows.", WARN)
            return
        if not self.win_prev:
            self.win_prev = self.win_default
        self.save_settings()
        self.say(f"Changement de la sortie Windows vers {label}...")
        self.win_change(did, f"Sortie Windows par defaut : {label}")

    def win_restore(self):
        if not self.win_prev or self.win_prev == self.win_default:
            self.win_prev = ""
            self.say("Rien a restaurer : la sortie Windows n'a pas ete changee par le logiciel.")
        elif not self.win_allow:
            self.say("« Modifier Windows » est sur NON : passe-le sur OUI pour restaurer la sortie d'origine.", WARN)
        else:
            did, self.win_prev = self.win_prev, ""
            self.save_settings()
            self.win_change(did, "Sortie Windows d'origine restauree.")

    def toggle_win_allow(self):
        self.win_allow = not self.win_allow
        self.sync_all()
        self.save_settings()
        if self.win_allow:
            self.say("Le logiciel peut changer la sortie par defaut de Windows quand tu en choisis une dans la liste.",
                     WARN)
        else:
            self.say("Le logiciel ne touche plus aux reglages son de Windows.")

    def panel(self, parent, title, color, first=False):
        f = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        f.pack(side="left", fill="both", expand=True, padx=(0 if first else 8, 0))
        head = tk.Frame(f, bg=PANEL)
        head.pack(fill="x", padx=12, pady=(8, 4))
        tk.Frame(head, bg=color, width=4, height=14).pack(side="left")
        tk.Label(head, text=title, font=F(12, True, True), fg=TXT, bg=PANEL).pack(side="left", padx=8)
        body = tk.Frame(f, bg=PANEL)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        return body

    def srow(self, parent, label, lo, hi, val, cmd, fmt, color=ACC, step=0.5, default=0.0):
        r = tk.Frame(parent, bg=PANEL)
        r.pack(fill="x", pady=1)
        tk.Label(r, text=label, width=14, anchor="w", font=F(12), fg=MUTED, bg=PANEL).pack(side="left")
        lab = tk.Label(r, text=fmt(val), width=10, anchor="e", font=F(12, True), fg=TXT, bg=PANEL)

        def on(v):
            lab.config(text=fmt(v))
            cmd(v)
        s = HSlider(r, lo, hi, val, on, color, step, default)
        s.pack(side="left")
        lab.pack(side="right")
        s.label, s.fmt = lab, fmt
        return s

    def crow(self, parent, label=None):
        r = tk.Frame(parent, bg=PANEL)
        r.pack(fill="x", pady=2)
        if label:
            tk.Label(r, text=label, width=14, anchor="w", font=F(12), fg=MUTED, bg=PANEL).pack(side="left")
        return r

    def build_output(self, bot):
        b = self.panel(bot, "SORTIE", ACC, True)
        r = self.crow(b)
        self.mode_chips = {}
        for key, label in (("apo", "Equalizer APO"), ("vm", "Voicemeeter natif"), ("both", "Les deux")):
            c = Chip(r, label, lambda k=key: self.set_mode(k), small=True)
            c.pack(side="left", padx=(0, 5))
            self.mode_chips[key] = c
        r = self.crow(b, "Cible")
        self.dev_var = tk.StringVar()
        om = self.dev_menu = tk.OptionMenu(r, self.dev_var, "")
        om.config(bg=PANEL2, fg=TXT, activebackground=LINE, activeforeground=TXT, highlightthickness=1,
                  highlightbackground=LINE, bd=0, relief="flat", font=F(12), anchor="w", width=28)
        om["menu"].config(bg=PANEL2, fg=TXT, activebackground=ACC, activeforeground="#02141a", bd=0, font=F(12))
        om.pack(side="left")
        self.fill_devices()
        self.lvl_sl = self.srow(b, "Niveau de sortie", -12, 6, self.level, self.on_level,
                                lambda v: f"{v:+.1f} dB", ACC)
        self.bal_sl = self.srow(b, "Balance G / D", -6, 6, self.balance, self.on_balance,
                                lambda v: "centre" if v == 0 else (f"D +{v:.1f} dB" if v > 0 else f"G +{-v:.1f} dB"),
                                ACC)
        self.out_info = tk.Label(b, text="", font=F(11), fg=MUTED, bg=PANEL, justify="left", anchor="w",
                                 wraplength=350)
        self.out_info.pack(fill="x", pady=(4, 2))
        r = self.crow(b)
        Chip(r, "Configurator APO", self.open_configurator, small=True).pack(side="left", padx=(0, 5))
        Chip(r, "Appliquer", self.apply, small=True).pack(side="left")

    AUTO_LBL = "Auto : sortie Windows par defaut"
    ALL_LBL = "Toutes les sorties APO"

    def fill_devices(self):
        self.dev_names = {self.AUTO_LBL: "auto", self.ALL_LBL: "all"}
        for g, n in self.devices:
            self.dev_names[n[:34]] = g
        if self.target not in self.dev_names.values():
            self.target = "auto"
        m = self.dev_menu["menu"]
        m.delete(0, "end")
        for n in self.dev_names:
            m.add_command(label=n, command=lambda v=n: self.on_device(v))
        self.dev_var.set(next(n for n, g in self.dev_names.items() if g == self.target))

    def resolved(self):
        """GUID de la sortie visee ("" = toutes les sorties ou Equalizer APO est installe)."""
        if self.target == "auto":
            return self.auto_guid
        return "" if self.target == "all" else self.target

    def build_tools(self, bot):
        b = self.panel(bot, "OUTILS TACTIQUES", MAG)
        self.wid_sl = self.srow(b, "Largeur stereo", 0, 100, self.width, self.on_width,
                                lambda v: f"+{v:.0f} %", MAG, 5, 0)
        r = self.crow(b, "Coupe-explosions")
        self.hp_chips = {}
        for hz in (0, 60, 90, 120):
            c = Chip(r, "OFF" if hz == 0 else f"{hz} Hz", lambda h=hz: self.set_hp(h), color=MAG, small=True)
            c.pack(side="left", padx=(0, 4))
            self.hp_chips[hz] = c
        r = self.crow(b)
        self.t_swap = Chip(r, "Inverser G/D", self.toggle_swap, color=MAG, small=True)
        self.t_auto = Chip(r, "Auto Warzone", self.toggle_auto, color=LIME, small=True)
        self.t_hk = Chip(r, "Raccourcis", self.toggle_hotkeys, color=MAG, small=True)
        for c in (self.t_swap, self.t_auto, self.t_hk):
            c.pack(side="left", padx=(0, 4))
        r = self.crow(b)
        self.t_hud = Chip(r, "Mini HUD", self.toggle_hud, color=MAG, small=True)
        self.t_boot = Chip(r, "Demarrer avec Windows", self.toggle_autostart, color=MAG, small=True)
        ab = Chip(r, "A/B : maintenir", color=WARN, small=True)
        ab.bind("<ButtonPress-1>", lambda e: self.set_bypass(True))
        ab.bind("<ButtonRelease-1>", lambda e: self.set_bypass(False))
        for c in (self.t_hud, self.t_boot, ab):
            c.pack(side="left", padx=(0, 4))
        r = self.crow(b, "Tests audio")
        for label, kind in (("G / D", "lr"), ("Pas", "steps"), ("Balayage", "sweep")):
            Chip(r, label, lambda k=kind: self.play_test(k), color=MAG, small=True).pack(side="left", padx=(0, 4))
        Chip(r, "Stop", lambda: winsound.PlaySound(None, winsound.SND_PURGE), color=BAD, small=True).pack(side="left")
        tk.Label(b, text="Ctrl+Alt+F9 : EQ on/off   \u2022   Ctrl+Alt+F10 : preset suivant", font=F(11),
                 fg=MUTED, bg=PANEL, anchor="w").pack(fill="x", pady=(4, 0))

    def build_vm(self, bot):
        b = self.panel(bot, "VOICEMEETER LINK", LIME)
        self.vm_lbl = tk.Label(b, text="", font=F(13, True), fg=TXT, bg=PANEL, anchor="w")
        self.vm_lbl.pack(fill="x")
        self.vm_hint = tk.Label(b, text="", font=F(11), fg=MUTED, bg=PANEL, justify="left", anchor="w",
                                wraplength=350)
        self.vm_hint.pack(fill="x", pady=(0, 4))
        vu = self.vu_cv = tk.Canvas(b, width=350, height=40, bg=PANEL, highlightthickness=0)
        vu.pack(anchor="w")
        for k, name in enumerate(("G", "D")):
            y = 4 + k * 18
            vu.create_text(4, y + 6, text=name, anchor="w", font=F(10, True), fill=MUTED)
            vu.create_rectangle(20, y, 346, y + 12, fill=BG, outline=LINE)
            vu.create_rectangle(21, y + 1, 21, y + 11, fill=LIME, outline="", tags=f"vu{k}")
        r = self.crow(b, "Bus cibles (EQ)")
        self.bus_chips = []
        for i, n in enumerate(("A1", "A2", "A3", "A4", "A5")):
            c = Chip(r, n, lambda k=i: self.toggle_bus(k), color=LIME, small=True)
            c.pack(side="left", padx=(0, 4))
            self.bus_chips.append(c)
        r = self.crow(b)
        Chip(r, "Lancer", self.vm_launch, color=LIME, small=True).pack(side="left", padx=(0, 4))
        Chip(r, "Afficher", lambda: self.vm_cmd("Command.Show=1", "Voicemeeter affiche."), color=LIME,
             small=True).pack(side="left", padx=(0, 4))
        Chip(r, "Redemarrer le moteur audio", self.vm_restart, color=WARN, small=True).pack(side="left")

    def rebuild_chips(self):
        for w in self.chip_row.winfo_children():
            w.destroy()
        self.chips = {}
        for name in list(PRESETS) + list(self.custom):
            custom = name in self.custom
            c = Chip(self.chip_row, name, lambda n=name: self.set_preset(n),
                     right=(lambda n=name: self.delete_preset(n)) if custom else None,
                     color=MAG if custom else ACC)
            c.pack(side="left", padx=(0, 6))
            self.chips[name] = c
        self.mark_chips()

    def mark_chips(self):
        for n, c in self.chips.items():
            c.set_active(n == self.cur_preset)
        for n, c in self.cards.items():
            c.set_active(n == self.cur_preset and self.enabled)

    def sync_all(self):
        self.t_win.config(text="Modifier Windows : OUI" if self.win_allow else "Modifier Windows : NON")
        self.t_win.set_active(self.win_allow)
        self.t_auto2.set_active(self.auto_game)
        self.int_lbl2.config(text=f"{self.intensity * 100:.0f} %")
        for k, c in self.mode_chips.items():
            c.set_active(k == self.mode)
        for hz, c in self.hp_chips.items():
            c.set_active(hz == self.hp)
        self.t_swap.set_active(self.swap)
        self.t_auto.set_active(self.auto_game)
        self.t_hk.set_active(self.hotkeys_on)
        self.t_hud.set_active(self.hud is not None)
        self.t_boot.set_active(self.autostart_on())
        for i, c in enumerate(self.bus_chips):
            c.set_active(self.buses[i])
        self.int_lbl.config(text=f"{self.intensity * 100:.0f} %")
        self.draw_switch()

    def draw_switch(self):
        hd, W = self.hd, self.W
        hd.delete("sw")
        on = self.enabled
        col = LIME if on else MUTED
        hd.create_text(W - 96, 30, anchor="e", text="EQ ACTIF" if on else "EQ COUPE", font=F(15, True, True),
                       fill=col, tags="sw")
        chamfer(hd, W - 84, 12, W, 48, 10, fill=mix(BG, col, 0.25), outline=col, width=2, tags="sw")
        x = W - 30 if on else W - 62
        chamfer(hd, x - 14, 17, x + 22, 43, 7, fill=col, outline="", tags="sw")

    # ------------------------------------------------------------ graphe
    def x_of(self, f):
        return self.gx0 + (math.log10(f) - math.log10(20)) / 3.0 * (self.gx1 - self.gx0)

    def f_of(self, x):
        t = (x - self.gx0) / (self.gx1 - self.gx0)
        return 10 ** (math.log10(20) + max(0.0, min(1.0, t)) * 3.0)

    def y_of(self, db):
        return self.gy0 + (15 - db) / 30.0 * (self.gy1 - self.gy0)

    def db_of(self, y):
        return 15 - (y - self.gy0) / (self.gy1 - self.gy0) * 30.0

    def eff(self):
        return [max(-GMAX, min(GMAX, g * self.intensity)) for g in self.gains]

    def coefs(self):
        cs = []
        if self.hp:
            cs.append(biquad("HP", self.hp, 0, 0.7071))
        for i, g in enumerate(self.eff()):
            if abs(g) > 0.01:
                cs.append(biquad(BANDS[i][2], self.fcs[i], g, self.qs[i]))
        return cs

    def draw_static(self):
        c = self.cv
        x0, x1, y0, y1 = self.gx0, self.gx1, self.gy0, self.gy1
        zx0, zx1 = self.x_of(1500), self.x_of(4500)
        c.create_rectangle(zx0, y0, zx1, y1, fill="#0a1a12", outline="")
        c.create_line(zx0, y0, zx0, y1, fill="#1d4d2a", dash=(3, 4))
        c.create_line(zx1, y0, zx1, y1, fill="#1d4d2a", dash=(3, 4))
        c.create_text((zx0 + zx1) / 2, y0 + 10, text="ZONE DES PAS", fill="#5fbf3d", font=F(10, True, True))
        for db in range(-15, 16, 5):
            y = self.y_of(db)
            c.create_line(x0, y, x1, y, fill="#2b3d6b" if db == 0 else "#131d38")
            c.create_text(x0 - 8, y, text=f"{db:+d}" if db else "0", fill=MUTED, font=F(10), anchor="e")
        for f in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
            x = self.x_of(f)
            c.create_line(x, y0, x, y1, fill="#131d38")
            c.create_text(x, y1 + 12, text=f"{f // 1000}k" if f >= 1000 else str(f), fill=MUTED, font=F(10))
        bw = (x1 - x0) / NBAR
        self.bar_x = []
        for k in range(NBAR):
            bx = x0 + k * bw
            fmid = 20 * (1000 ** ((k + 0.5) / NBAR))
            zone = 1500 <= fmid <= 4500
            c.create_rectangle(bx + 1, y1, bx + bw - 1, y1, fill="#1f5c1a" if zone else "#0c3f55", outline="",
                               tags=f"bar{k}")
            c.create_line(bx + 1, y1, bx + bw - 1, y1, fill=LIME if zone else ACC, tags=f"cap{k}", state="hidden")
            self.bar_x.append((bx + 1, bx + bw - 1))
        c.create_text(x1 - 4, y0 + 10, anchor="e", text="", fill=MUTED, font=F(10, True, True), tags="spec_lbl")
        # coins facon HUD
        for (cx, cy, dx, dy) in ((4, 4, 1, 1), (self.gw - 4, 4, -1, 1), (4, self.gh - 4, 1, -1),
                                 (self.gw - 4, self.gh - 4, -1, -1)):
            c.create_line(cx, cy + 14 * dy, cx, cy, cx + 14 * dx, cy, fill=ACC, width=2)

    def redraw(self):
        c = self.cv
        c.delete("dyn")
        on = self.enabled and not self.bypass
        cs = self.coefs() if on else []
        pts = []
        n = 240
        for k in range(n + 1):
            f = 20 * (1000 ** (k / n))
            db = sum(resp_db(co, f) for co in cs)
            pts.extend((self.x_of(f), self.y_of(max(-15.0, min(15.0, db)))))
        col = ACC if on else MUTED
        y0 = self.y_of(0)
        c.create_polygon([pts[0], y0] + pts + [pts[-2], y0], fill=col, outline="", stipple="gray12", tags="dyn")
        for wd, t in ((11, 0.14), (6, 0.38)):
            c.create_line(pts, fill=mix(PANEL, col, t), width=wd, tags="dyn", capstyle="round", joinstyle="round")
        c.create_line(pts, fill=col, width=2.5, tags="dyn")
        eg = self.eff()
        for i, b in enumerate(BANDS):
            x, y = self.x_of(self.fcs[i]), self.y_of(eg[i] if on else 0)
            hot = self.drag == i or self.hover == i
            r = 10 if hot else 7
            c.create_oval(x - r - 6, y - r - 6, x + r + 6, y + r + 6, fill="", outline=mix(PANEL, b[5], 0.45),
                          tags="dyn")
            c.create_oval(x - r, y - r, x + r, y + r, fill=b[5], outline=BG, width=2, tags="dyn")
            c.create_text(x, y - r - 14, text=b[0].upper(), fill=b[5] if hot else mix(PANEL, b[5], 0.7),
                          font=F(10, True, True), tags="dyn")
        i = self.drag if self.drag is not None else self.hover
        if i is not None:
            txt = f"{BANDS[i][0].upper()}   {self.fcs[i]:.0f} Hz   {eg[i]:+.1f} dB   Q {self.qs[i]:.2f}"
            c.create_text(self.gx0 + 4, 14, anchor="w", fill=TXT, font=F(12, True, True), text=txt, tags="dyn")
        else:
            c.create_text(self.gx0 + 4, 14, anchor="w", fill=MUTED, font=F(11), tags="dyn",
                          text="Glisse les points   \u2022   molette = finesse (Q)   \u2022   double-clic = remise a zero")
        for k in range(NB):
            self.b_gain[k].config(text=f"{eg[k]:+.1f}")
            self.b_freq[k].config(text=f"{self.fcs[k]:.0f} Hz")

    def nearest(self, x, y, maxd=26):
        eg = self.eff()
        best, bd = None, maxd
        for i in range(NB):
            d = math.hypot(self.x_of(self.fcs[i]) - x, self.y_of(eg[i]) - y)
            if d < bd:
                best, bd = i, d
        return best

    def changed(self):
        if self.cur_preset:
            self.cur_preset = ""
            self.mark_chips()
        self.redraw()
        self.schedule_apply()

    def g_press(self, e):
        self.drag = self.nearest(e.x, e.y)
        if self.drag is not None:
            self.g_move(e)

    def g_move(self, e):
        i = self.drag
        if i is None:
            return
        if self.intensity < 0.2:
            self.show_intensity(100)
        lo, hi = BANDS[i][4]
        target = round(max(-GMAX, min(GMAX, self.db_of(e.y))) * 2) / 2
        self.gains[i] = max(-GMAX, min(GMAX, target / self.intensity))
        self.fcs[i] = max(lo, min(hi, self.f_of(e.x)))
        self.changed()

    def g_release(self):
        self.drag = None
        self.redraw()

    def g_hover(self, e):
        h = self.nearest(e.x, e.y)
        if h != self.hover:
            self.hover = h
            self.cv.config(cursor="hand2" if h is not None else "")
            self.redraw()

    def g_wheel(self, e):
        i = self.nearest(e.x, e.y, 44)
        if i is not None:
            self.qs[i] = max(0.3, min(6.0, self.qs[i] * (1.12 if e.delta > 0 else 1 / 1.12)))
            self.changed()

    def g_reset(self, e):
        i = self.nearest(e.x, e.y)
        if i is not None:
            self.gains[i], self.fcs[i], self.qs[i] = 0.0, float(BANDS[i][1]), float(BANDS[i][3])
            self.changed()

    def bump(self, i, d):
        self.gains[i] = max(-GMAX, min(GMAX, self.gains[i] + d))
        self.changed()

    # ------------------------------------------------------------ presets
    def set_preset(self, name):
        if name in PRESETS:
            self.gains = [float(x) for x in PRESETS[name]]
            self.fcs = [float(b[1]) for b in BANDS]
            self.qs = [float(b[3]) for b in BANDS]
        elif name in self.custom:
            p = self.custom[name]
            self.gains, self.fcs, self.qs = list(p["gains"]), list(p["fcs"]), list(p["qs"])
        else:
            return
        self.cur_preset = name
        self.mark_chips()
        self.redraw()
        self.schedule_apply()

    def next_preset(self):
        names = list(PRESETS) + list(self.custom)
        i = names.index(self.cur_preset) if self.cur_preset in names else -1
        self.set_preset(names[(i + 1) % len(names)])

    def save_preset(self):
        name = simpledialog.askstring(APP_NAME, "Nom du preset :", parent=self)
        if not name or name in PRESETS:
            return
        self.custom[name] = {"gains": list(self.gains), "fcs": list(self.fcs), "qs": list(self.qs)}
        self.cur_preset = name
        self.rebuild_chips()
        self.save_settings()
        self.say(f"Preset \u00ab {name} \u00bb enregistre (clic droit pour le supprimer).", LIME)

    def delete_preset(self, name):
        if messagebox.askyesno(APP_NAME, f"Supprimer le preset \u00ab {name} \u00bb ?", parent=self):
            self.custom.pop(name, None)
            if self.cur_preset == name:
                self.cur_preset = ""
            self.rebuild_chips()
            self.save_settings()

    # ------------------------------------------------------------ commandes
    def toggle_enabled(self, beep=False):
        self.enabled = not self.enabled
        self.draw_switch()
        self.mark_chips()
        self.redraw()
        self.apply()
        if beep:
            f = 1300 if self.enabled else 500
            threading.Thread(target=lambda: winsound.Beep(f, 90), daemon=True).start()

    def set_bypass(self, v):
        self.bypass = v
        self.redraw()
        self.apply()
        if v:
            self.say("A/B : son d'origine (relache pour revenir a l'EQ)", WARN)

    def on_intensity(self, v):
        self.show_intensity(v)
        self.redraw()
        self.schedule_apply()

    def on_level(self, v):
        self.level = v
        self.schedule_apply()

    def on_balance(self, v):
        self.balance = v
        self.schedule_apply()

    def on_width(self, v):
        self.width = v
        self.schedule_apply()

    def set_hp(self, hz):
        self.hp = hz
        self.sync_all()
        self.redraw()
        self.schedule_apply()

    def toggle_swap(self):
        self.swap = not self.swap
        self.sync_all()
        self.schedule_apply()

    def toggle_auto(self):
        self.auto_game = not self.auto_game
        self.game_known = False
        self.sync_all()
        self.save_settings()
        self.say("Auto Warzone : l'EQ s'active quand le jeu tourne et se coupe quand il est ferme."
                 if self.auto_game else "Auto Warzone desactive.", LIME if self.auto_game else MUTED)

    def toggle_hotkeys(self):
        self.hotkeys_on = not self.hotkeys_on
        if self.hotkeys_on:
            self.hk.start()
        else:
            self.hk.stop()
        self.sync_all()
        self.save_settings()

    def toggle_bus(self, i):
        self.buses[i] = 0 if self.buses[i] else 1
        self.sync_all()
        self.schedule_apply()

    def set_mode(self, m):
        self.mode = m
        self.sync_all()
        self.apply()

    def on_device(self, name):
        self.dev_var.set(name)
        self.target = self.dev_names.get(name, "auto")
        self.apply()

    def on_hotkey(self, n):
        if not self.hotkeys_on:
            return
        if n == 1:
            self.toggle_enabled(beep=True)
        elif n == 2:
            self.next_preset()
            threading.Thread(target=lambda: winsound.Beep(900, 60), daemon=True).start()

    def play_test(self, kind):
        self.say("Generation du son de test...", MUTED)

        def work():
            try:
                make_test_wav(kind)
                winsound.PlaySound(TEST_WAV, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()
        label = {"lr": "gauche puis droite, deux fois", "steps": "des pas qui vont de gauche a droite",
                 "sweep": "balayage de 20 Hz a 20 kHz"}[kind]
        self.after(400, lambda: self.say(f"Test audio : {label}.", MAG))

    # ------------------------------------------------------------ demarrage auto
    def autostart_cmd(self):
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --minimized'
        return f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}" --minimized'

    def autostart_on(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, RUN_NAME)
            return True
        except OSError:
            return False

    def toggle_autostart(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if self.autostart_on():
                    winreg.DeleteValue(k, RUN_NAME)
                    self.say("Demarrage avec Windows desactive.")
                else:
                    winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, self.autostart_cmd())
                    self.say("Le logiciel demarrera avec Windows (reduit).", LIME)
        except OSError as e:
            self.say(f"Impossible de modifier le demarrage : {e}", BAD)
        self.sync_all()

    # ------------------------------------------------------------ mini HUD
    def toggle_hud(self):
        if self.hud is not None:
            self.hud.destroy()
            self.hud = None
        else:
            w = self.hud = tk.Toplevel(self)
            w.overrideredirect(True)
            w.attributes("-topmost", True)
            w.attributes("-alpha", 0.88)
            w.configure(bg=ACC)
            inner = tk.Frame(w, bg=BG)
            inner.pack(padx=1, pady=1)
            self.hud_a = tk.Label(inner, text="", font=F(13, True, True), bg=BG, fg=LIME, padx=12, anchor="w",
                                  width=30)
            self.hud_a.pack(pady=(6, 0))
            self.hud_b = tk.Label(inner, text="", font=F(11), bg=BG, fg=MUTED, padx=12, anchor="w", width=36)
            self.hud_b.pack(pady=(0, 6))
            w.geometry(f"+{self.winfo_screenwidth() - 330}+24")
            for wd in (inner, self.hud_a, self.hud_b):
                wd.bind("<Button-1>", lambda e: setattr(self, "_hd", (e.x_root - w.winfo_x(), e.y_root - w.winfo_y())))
                wd.bind("<B1-Motion>", lambda e: w.geometry(f"+{e.x_root - self._hd[0]}+{e.y_root - self._hd[1]}"))
            self.update_hud()
        self.sync_all()

    def update_hud(self):
        if self.hud is None:
            return
        on = self.enabled and not self.bypass
        self.hud_a.config(text=("EQ ON  \u2022  " if on else "EQ OFF  \u2022  ") + (self.cur_preset or "Personnalise"),
                          fg=LIME if on else MUTED)
        vm = Voicemeeter.TYPES.get(self.vm.vtype, "Voicemeeter off").replace("Voicemeeter ", "VM ")
        self.hud_b.config(text=f"{'JEU DETECTE' if self.game else 'jeu ferme'}  \u2022  {vm}")

    # ------------------------------------------------------------ application des reglages
    def schedule_apply(self):
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(140, self.apply)

    def apo_text(self):
        if not self.enabled or self.bypass:
            return "# MW Sound Optimizer : desactive\n"
        cs = self.coefs()
        peak = max(0.0, max(sum(resp_db(c, f) for c in cs) for f in PEAK_FREQS)) if cs else 0.0
        w = self.width / 100.0 * 0.5
        pre = self.level - peak - 20 * math.log10(1 + w)
        cond = ['(sizeof(regexSearch("capture", stage)) == 0)']
        dev = self.resolved()
        if dev:
            cond.insert(0, f'(sizeof(regexSearch("{dev}", tolower(deviceGuid))) > 0)')
        lines = [f"# {APP_NAME} {VERSION} - fichier genere automatiquement", "If: " + " and ".join(cond),
                 f"Preamp: {pre:.1f} dB"]
        n = 1
        if self.hp:
            lines.append(f"Filter {n}: ON HP Fc {self.hp} Hz")
            n += 1
        for i, g in enumerate(self.eff()):
            if abs(g) > 0.01:
                lines.append(f"Filter {n}: ON {BANDS[i][2]} Fc {self.fcs[i]:.0f} Hz Gain {g:.1f} dB Q {self.qs[i]:.2f}")
                n += 1
        sl, sr = ("R", "L") if self.swap else ("L", "R")
        if w > 0:
            lines.append(f"Copy: L={1 + w:.3f}*{sl}+{-w:.3f}*{sr} R={1 + w:.3f}*{sr}+{-w:.3f}*{sl}")
        elif self.swap:
            lines.append("Copy: L=R R=L")
        if self.balance:
            lines += [f"Channel: {'L' if self.balance > 0 else 'R'}", f"Preamp: {-abs(self.balance):.1f} dB",
                      "Channel: all"]
        lines.append("EndIf:")
        return "\n".join(lines) + "\n"

    def write_apo(self):
        if not os.path.isdir(APO_CFG_DIR):
            return False, "Equalizer APO introuvable"
        try:
            with open(APO_OUT, "w", encoding="utf-8") as f:
                f.write(self.apo_text())
            with open(APO_MAIN, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if APO_INCLUDE not in content:
                with open(APO_MAIN, "a", encoding="utf-8") as f:
                    f.write("\n" + APO_INCLUDE + "\n")
            return True, "Equalizer APO"
        except PermissionError:
            return False, "droits insuffisants sur le dossier d'Equalizer APO (lance en administrateur)"
        except OSError as e:
            return False, str(e)

    def write_vm(self):
        t = self.vm.refresh()
        if not self.vm.available:
            return False, "Voicemeeter introuvable"
        if t == 0:
            return False, "Voicemeeter n'est pas lance"
        if t == 1:
            return False, "Voicemeeter Standard n'a pas d'EQ natif (garde le mode Equalizer APO)"
        sel = [i for i, v in enumerate(self.buses) if v]
        if not sel:
            return False, "aucun bus Voicemeeter selectionne"
        on = 1 if (self.enabled and not self.bypass) else 0
        eg = self.eff()
        parts = []
        for bus in sel:
            parts.append(f"Bus[{bus}].EQ.on={on}")
            for ch in range(8):
                for k in range(NB):
                    base = f"Bus[{bus}].EQ.channel[{ch}].cell[{k}]"
                    qv = max(1, min(100, round(self.qs[k] * 10)))
                    parts.append(f"{base}.on={on};{base}.type=0;{base}.f={self.fcs[k]:.0f};"
                                 f"{base}.gain={eg[k]:.1f};{base}.q={qv}")
        ok = self.vm.script(";".join(parts))
        return ok, "Voicemeeter" if ok else "echec d'envoi a Voicemeeter"

    def apply(self):
        self._after = None
        done, fail = [], []
        if self.mode in ("apo", "both"):
            ok, msg = self.write_apo()
            (done if ok else fail).append(msg)
        if self.mode in ("vm", "both"):
            ok, msg = self.write_vm()
            (done if ok else fail).append(msg)
        if fail:
            self.say("Attention : " + "  |  ".join(fail) + (("   \u2022   OK : " + ", ".join(done)) if done else ""),
                     WARN if done else BAD)
        elif self.level > 0 and self.enabled:
            self.say("Applique : " + ", ".join(done) + "   \u2022   niveau positif : risque de saturation", WARN)
        else:
            self.say("Applique : " + ", ".join(done), LIME)
        self.set_tile(3, (self.cur_preset or "Personnalise") + ("" if self.enabled else "  (coupe)"),
                      LIME if self.enabled and not self.bypass else MUTED)
        self.update_hud()
        self.save_settings()

    def say(self, text, color=MUTED):
        self.status.config(text=text, fg=color)

    def set_tile(self, i, text, color):
        self.tl.itemconfig(f"val{i}", text=text, fill=TXT if color != MUTED else MUTED)
        self.tl.itemconfig(f"led{i}", fill=color)
        self.tl.itemconfig(f"box{i}", outline=mix(LINE, color, 0.55) if color != MUTED else LINE)

    # ------------------------------------------------------------ Voicemeeter
    def vm_launch(self):
        if not self.vm.available:
            self.say("Voicemeeter n'est pas installe.", BAD)
            return
        self.vm.run()
        self.say("Lancement de Voicemeeter...", LIME)

    def vm_cmd(self, script, msg):
        self.vm.refresh()
        if self.vm.script(script):
            self.say(msg, LIME)
        else:
            self.say("Voicemeeter n'est pas lance.", BAD)

    def vm_restart(self):
        self.vm_cmd("Command.Restart=1", "Moteur audio Voicemeeter redemarre (corrige craquements et coupures).")

    def open_configurator(self):
        p = os.path.join(APO_DIR, "Configurator.exe")
        if os.path.isfile(p):
            try:
                os.startfile(p)
            except OSError:
                pass
        else:
            self.say("Equalizer APO n'est pas installe.", BAD)

    # ------------------------------------------------------------ boucles
    def tick_slow(self):
        # Voicemeeter
        t = self.vm.refresh()
        if not self.vm.available:
            name, hint, col = "Non installe", "Voicemeeter n'a pas ete trouve sur ce PC.", BAD
        elif t == 0:
            name, hint, col = "Installe, ferme", "Clique sur \u00ab Lancer \u00bb pour le demarrer.", WARN
        elif t == 1:
            name, col = "Voicemeeter Standard", LIME
            hint = ("Connecte. Cette edition n'a pas d'EQ integre : l'EQ passe par Equalizer APO sur la sortie "
                    "choisie dans \u00ab Cible \u00bb.")
        else:
            name, col = Voicemeeter.TYPES.get(t, "Voicemeeter"), LIME
            hint = "Connecte. EQ parametrique natif disponible sur les bus coches."
        self.vm_lbl.config(text="\u25cf  " + name, fg=col)
        self.vm_hint.config(text=hint)
        self.set_tile(1, name.replace("Voicemeeter ", "") + ("  \u2022  connecte" if t else ""), col if t else MUTED)
        # jeu
        game = find_game(self.extra_games)
        if game != self.game or not self.game_known:
            first = not self.game_known
            self.game, self.game_known = game, True
            if self.auto_game and (self.enabled != bool(game)):
                self.enabled = bool(game)
                self.draw_switch()
                self.mark_chips()
                self.redraw()
                self.apply()
                if not first:
                    self.say("Jeu detecte : EQ active." if game else "Jeu ferme : EQ coupe.", LIME if game else MUTED)
        self.set_tile(0, f"EN JEU  \u2022  {game}" if game else "en attente du jeu", LIME if game else MUTED)
        # sorties Windows (lecture seule tant que "Modifier Windows" est sur NON)
        sp = self.spec
        if sp.outputs != self.outputs or sp.dev_id != self.win_default:
            self.outputs, self.win_default = list(sp.outputs), sp.dev_id
            self.fill_win()
        # Equalizer APO : la liste des sorties peut changer (Configurator), on la relit a chaque passage
        if os.path.isdir(APO_CFG_DIR):
            devs = apo_devices()
            dirty = devs != self.devices
            if dirty:
                self.devices = devs
                self.fill_devices()
            did = sp.dev_id.lower()
            ag = next((g for g, _ in self.devices if did and g in did), "")
            if ag != self.auto_guid:
                self.auto_guid, dirty = ag, True
            if dirty:
                self.apply()
            n = len(self.devices)
            if ag:
                self.set_tile(2, "actif sur ta sortie", LIME)
            elif n and did:
                self.set_tile(2, "pas sur ta sortie par defaut", WARN)
            else:
                self.set_tile(2, f"installe sur {n} sortie{'s' if n > 1 else ''}" if n else "aucune sortie cochee",
                              LIME if n else WARN)
            info, warn = [], False
            if not n:
                info.append("Aucune sortie n'a Equalizer APO : ouvre le Configurator et coche ta sortie.")
                warn = True
            elif self.target == "auto" and ag:
                info.append("Cible auto : " + next(nm for g, nm in self.devices if g == ag))
            elif self.target == "auto" and did:
                info.append("La sortie Windows par defaut n'a pas Equalizer APO : l'EQ vise toutes les sorties APO.")
                warn = True
            others = other_apo_configs()
            if others:
                info.append("Autre traitement actif dans Equalizer APO : " + ", ".join(others) +
                            ". Les effets se cumulent avec cet EQ.")
                warn = True
            self.out_info.config(text="\n".join(info), fg=WARN if warn else MUTED)
        else:
            self.set_tile(2, "introuvable", BAD)
            self.out_info.config(text="Equalizer APO n'est pas installe (sourceforge.net/projects/equalizerapo).",
                                 fg=BAD)
        # spectre
        if sp.ok:
            self.cv.itemconfig("spec_lbl", text="SPECTRE LIVE  \u2022  " + sp.device[:40], fill=mix(PANEL, ACC, 0.6))
        else:
            self.cv.itemconfig("spec_lbl", text="spectre indisponible", fill=MUTED)
        if self.hk.failed and self.hotkeys_on:
            self.say("Raccourcis Ctrl+Alt+F9/F10 deja pris par un autre logiciel.", WARN)
            self.hk.failed = False
        self.update_hud()
        self.after(2000, self.tick_slow)

    def tick_fast(self):
        try:
            while True:
                self.on_hotkey(self.hkq.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                self.say(*self.uiq.get_nowait())
        except queue.Empty:
            pass
        # spectre
        sp = self.spec
        tgt = sp.bands if (time.time() - sp.stamp) < 0.3 else None
        c, y1, hgt = self.cv, self.gy1, (self.gy1 - self.gy0) * 0.92
        for k in range(NBAR):
            cur = self.sv[k]
            v = tgt[k] if tgt else 0.0
            nv = v if v > cur else cur * 0.84
            if nv < 0.004:
                nv = 0.0
            if nv != cur:
                self.sv[k] = nv
                xa, xb = self.bar_x[k]
                top = y1 - nv * hgt
                c.coords(f"bar{k}", xa, top, xb, y1)
                c.coords(f"cap{k}", xa, top, xb, top)
                c.itemconfig(f"cap{k}", state="normal" if nv > 0 else "hidden")
        # VU-metre Voicemeeter
        lv = self.vm.levels()
        for k in (0, 1):
            v = 0.0
            if lv:
                v = max(0.0, min(1.0, (20 * math.log10(max(lv[k], 1e-6)) + 60) / 60))
            nv = v if v > self.vu[k] else self.vu[k] * 0.86
            if abs(nv - self.vu[k]) > 0.002:
                self.vu[k] = nv
                y = 4 + k * 18
                self.vu_cv.coords(f"vu{k}", 21, y + 1, 21 + nv * 324, y + 11)
                self.vu_cv.itemconfig(f"vu{k}", fill=BAD if nv > 0.97 else (WARN if nv > 0.85 else LIME))
        # animation de l'en-tete
        self.scan_x = (self.scan_x + 5) % 260
        self.hd.coords("scan", self.scan_x, 72, min(260, self.scan_x + 50), 72)
        self.after(40, self.tick_fast)

    def on_close(self):
        self.save_settings()
        self.hk.stop()
        self.vm.logout()
        self.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    ctypes.windll.kernel32.CreateMutexW(None, False, "MWSoundOptimizer_single_instance")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, f"{APP_NAME} est deja ouvert.", APP_NAME, 0x40)
        return
    App(minimized="--minimized" in sys.argv).mainloop()


if __name__ == "__main__":
    main()
