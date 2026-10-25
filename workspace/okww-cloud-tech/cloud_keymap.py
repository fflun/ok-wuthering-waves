# Derived from March7thAssistant module/automation/cdp_input.py.
# Upstream: moesnow/March7thAssistant, commit 881e90b4ce50611d26ecdcb06ee6ecd07cc76b6e.
# SPDX-License-Identifier: GPL-3.0-only
# See THIRD_PARTY_CLOUD.md and licenses/March7thAssistant-GPL-3.0.txt.

KEY_ALIAS_MAP = {
        "escape": "esc",
        "return": "enter",
        "control": "ctrl",
        "option": "alt",
        "win": "windows",
        "command": "windows",
        "left shift": "shiftleft",
        "right shift": "shiftright",
        "left ctrl": "ctrlleft",
        "right ctrl": "ctrlright",
        "left control": "ctrlleft",
        "right control": "ctrlright",
        "left alt": "altleft",
        "right alt": "altright",
        "left win": "windowsleft",
        "right win": "windowsright",
        "left windows": "windowsleft",
        "right windows": "windowsright",
    }

SPECIAL_KEY_MAP = {
        "esc": {"key": "Escape", "code": "Escape", "vk": 27},
        "enter": {"key": "Enter", "code": "Enter", "vk": 13},
        "space": {"key": " ", "code": "Space", "vk": 32},
        "tab": {"key": "Tab", "code": "Tab", "vk": 9},
        "backspace": {"key": "Backspace", "code": "Backspace", "vk": 8},
        "delete": {"key": "Delete", "code": "Delete", "vk": 46},
        "shift": {"key": "Shift", "code": "ShiftLeft", "vk": 16, "modifier": 8, "location": 1},
        "shiftleft": {"key": "Shift", "code": "ShiftLeft", "vk": 16, "modifier": 8, "location": 1},
        "shiftright": {"key": "Shift", "code": "ShiftRight", "vk": 16, "modifier": 8, "location": 2},
        "ctrl": {"key": "Control", "code": "ControlLeft", "vk": 17, "modifier": 2, "location": 1},
        "ctrlleft": {"key": "Control", "code": "ControlLeft", "vk": 17, "modifier": 2, "location": 1},
        "ctrlright": {"key": "Control", "code": "ControlRight", "vk": 17, "modifier": 2, "location": 2},
        "alt": {"key": "Alt", "code": "AltLeft", "vk": 18, "modifier": 1, "location": 1},
        "altleft": {"key": "Alt", "code": "AltLeft", "vk": 18, "modifier": 1, "location": 1},
        "altright": {"key": "Alt", "code": "AltRight", "vk": 18, "modifier": 1, "location": 2},
        "windows": {"key": "Meta", "code": "MetaLeft", "vk": 91, "modifier": 4, "location": 1},
        "windowsleft": {"key": "Meta", "code": "MetaLeft", "vk": 91, "modifier": 4, "location": 1},
        "windowsright": {"key": "Meta", "code": "MetaRight", "vk": 92, "modifier": 4, "location": 2},
        "arrowup": {"key": "ArrowUp", "code": "ArrowUp", "vk": 38},
        "arrowdown": {"key": "ArrowDown", "code": "ArrowDown", "vk": 40},
        "arrowleft": {"key": "ArrowLeft", "code": "ArrowLeft", "vk": 37},
        "arrowright": {"key": "ArrowRight", "code": "ArrowRight", "vk": 39},
    }

for i in range(1, 13):
        SPECIAL_KEY_MAP[f"f{i}"] = {
            "key": f"F{i}",
            "code": f"F{i}",
            "vk": 111 + i
        }

CHAR_KEY_MAP = {
        # a-z
        **{chr(i): {
            "key": chr(i).upper(),
            "code": f"Key{chr(i).upper()}",
            "vk": ord(chr(i).upper())
        } for i in range(97, 123)},
        # 0-9
        **{str(i): {
            "key": str(i),
            "code": f"Digit{str(i)}",
            "vk": 48 + i
        } for i in range(0, 10)},
    }
