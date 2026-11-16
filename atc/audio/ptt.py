"""Push-to-talk bindings (Milestone 5, R5): any keyboard key, a side mouse button, or a joystick / yoke button.

A binding is stored in settings.toml as text:
    "right ctrl"     one of the old names (PTT_KEYS), still accepted
    "key:0xA3"       a Windows virtual-key code
    "joy:0:5"        joystick 0 (the first one), button 5
Keys are read with GetAsyncKeyState, so push-to-talk works while MSFS has the focus. Joysticks are read with
winmm's joyGetPosEx: simple and built into Windows, but it sees at most 16 devices and 32 buttons each, so a
button numbered higher on a big yoke or throttle can't be bound this way.
The Settings page binds a key by capture(): "press the key or button you want".
"""
import ctypes
import re
import time
from dataclasses import dataclass
from typing import Callable

PTT_KEYS = {"right ctrl": 0xA3, "left ctrl": 0xA2, "right shift": 0xA1, "right alt": 0xA5, "caps lock": 0x14,
            "scroll lock": 0x91, "pause": 0x13, "insert": 0x2D}
JOYSTICKS, JOY_BUTTONS = 16, 32

# Names for the Settings page. Codes from the Windows virtual-key list.
KEY_NAMES = {
    0x05: "Mouse button 4", 0x06: "Mouse button 5", 0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause",
    0x14: "Caps Lock", 0x1B: "Esc", 0x20: "Space", 0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2D: "Insert", 0x2E: "Delete", 0x5B: "Left Windows",
    0x5C: "Right Windows", 0x5D: "Menu", 0x6A: "Numpad *", 0x6B: "Numpad +", 0x6D: "Numpad -", 0x6E: "Numpad .",
    0x6F: "Numpad /", 0x90: "Num Lock", 0x91: "Scroll Lock", 0xA0: "Left Shift", 0xA1: "Right Shift",
    0xA2: "Left Ctrl", 0xA3: "Right Ctrl", 0xA4: "Left Alt", 0xA5: "Right Alt",
    **{0x30 + i: str(i) for i in range(10)}, **{0x41 + i: chr(0x41 + i) for i in range(26)},
    **{0x60 + i: f"Numpad {i}" for i in range(10)}, **{0x70 + i: f"F{i + 1}" for i in range(24)},
}
# Never bound: the left/right/middle mouse buttons (you click with them) and the "either side" codes for shift,
# ctrl and alt (Windows reports those together with the left or right one, which is the one we keep)
NOT_BINDABLE = {0x01, 0x02, 0x04, 0x10, 0x11, 0x12}


@dataclass(frozen=True)
class Binding:
    kind: str  # "key" or "joy"
    code: int  # the virtual-key code, or the joystick number (0 = the first)
    button: int = 0  # joystick button, 1..32

    @property
    def text(self) -> str:
        return f"key:0x{self.code:02X}" if self.kind == "key" else f"joy:{self.code}:{self.button}"

    @property
    def name(self) -> str:
        if self.kind == "joy":
            return f"Joystick {self.code + 1} button {self.button}"
        return KEY_NAMES.get(self.code, f"Key 0x{self.code:02X}")


def parse(text: str) -> Binding:
    """A binding from settings.toml; ValueError with what is allowed."""
    value = text.strip().lower()
    if value in PTT_KEYS:
        return Binding("key", PTT_KEYS[value])
    if m := re.fullmatch(r"key:(0x[0-9a-f]{1,2}|\d{1,3})", value):
        code = int(m[1], 0)
        if 0 < code < 0xFF and code not in NOT_BINDABLE:
            return Binding("key", code)
    if m := re.fullmatch(r"joy:(\d{1,2}):(\d{1,2})", value):
        device, button = int(m[1]), int(m[2])
        if device < JOYSTICKS and 1 <= button <= JOY_BUTTONS:
            return Binding("joy", device, button)
    raise ValueError(f"unknown push-to-talk binding {text!r}: use one of {', '.join(PTT_KEYS)}, "
                     "or set it in the Settings page (key:0xA3, joy:0:5)")


def key_down(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class _JoyInfoEx(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "size", "flags", "x", "y", "z", "r", "u", "v", "buttons", "button_number", "pov", "reserved1", "reserved2")]


JOY_RETURNBUTTONS = 0x80


def joystick_buttons(device: int) -> int:
    """The pressed buttons of a joystick as bits (bit 0 = button 1); 0 when there is no such joystick."""
    info = _JoyInfoEx(size=ctypes.sizeof(_JoyInfoEx), flags=JOY_RETURNBUTTONS)
    try:
        if ctypes.windll.winmm.joyGetPosEx(device, ctypes.byref(info)) != 0:
            return 0
    except OSError:
        return 0
    return info.buttons


def is_held(binding: Binding, keys: Callable[[int], bool] = key_down,
            joysticks: Callable[[int], int] = joystick_buttons) -> bool:
    if binding.kind == "key":
        return keys(binding.code)
    return bool(joysticks(binding.code) & (1 << (binding.button - 1)))


def pressed(keys: Callable[[int], bool] = key_down, joysticks: Callable[[int], int] = joystick_buttons,
            devices: list[int] | None = None) -> Binding | None:
    """The first bindable key or joystick button that is down right now, if any."""
    for vk in range(1, 0xFF):
        if vk not in NOT_BINDABLE and keys(vk):
            return Binding("key", vk)
    for device in devices if devices is not None else range(JOYSTICKS):
        if buttons := joysticks(device):
            return Binding("joy", device, (buttons & -buttons).bit_length())  # the lowest pressed button
    return None


def held_now(keys: Callable[[int], bool] = key_down, joysticks: Callable[[int], int] = joystick_buttons,
             devices: list[int] | None = None) -> set[Binding]:
    """Every bindable key and joystick button that is down right now."""
    found = {Binding("key", vk) for vk in range(1, 0xFF) if vk not in NOT_BINDABLE and keys(vk)}
    for device in devices if devices is not None else range(JOYSTICKS):
        buttons = joysticks(device)
        found |= {Binding("joy", device, b + 1) for b in range(JOY_BUTTONS) if buttons & (1 << b)}
    return found


SETTLE_S = 0.3  # how long capture() watches first, to learn what is down already


def capture(timeout: float = 10, keys: Callable[[int], bool] = key_down,
            joysticks: Callable[[int], int] = joystick_buttons, clock=time.monotonic,
            sleep=time.sleep) -> Binding | None:
    """Wait for the pilot to press a key or button, and return it; None after `timeout` seconds.
    Only a NEW press counts: what is down while capture starts (a key still held from typing, or a switch on a yoke
    or throttle that Windows reports as a button held all the time, found on the user's PC) is learned first and
    ignored until it is let go."""
    devices = [d for d in range(JOYSTICKS) if _connected(d, joysticks)]
    deadline = clock() + timeout
    settled = clock() + SETTLE_S
    already: set[Binding] = set()
    while clock() < settled:
        already |= held_now(keys, joysticks, devices)
        sleep(0.02)
    while clock() < deadline:
        now = held_now(keys, joysticks, devices)
        if new := now - already:
            return min(new, key=lambda b: (b.kind, b.code, b.button))
        already &= now  # let go: pressing it again counts
        sleep(0.02)
    return None


def _connected(device: int, joysticks: Callable[[int], int]) -> bool:
    """Only for the real winmm reader: skip joystick numbers with no device, so polling stays quick."""
    if joysticks is not joystick_buttons:
        return True
    info = _JoyInfoEx(size=ctypes.sizeof(_JoyInfoEx), flags=JOY_RETURNBUTTONS)
    try:
        return ctypes.windll.winmm.joyGetPosEx(device, ctypes.byref(info)) == 0
    except OSError:
        return False
