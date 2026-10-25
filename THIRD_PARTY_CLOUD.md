# Cloud adapter sources

Keyboard maps in `cloud_keymap.py` are derived from **moesnow/March7thAssistant**,
`module/automation/cdp_input.py`, commit
`881e90b4ce50611d26ecdcb06ee6ecd07cc76b6e`, under GPL-3.0.
Full upstream license: `licenses/March7thAssistant-GPL-3.0.txt`.

https://github.com/moesnow/March7thAssistant/blob/881e90b4ce50611d26ecdcb06ee6ecd07cc76b6e/module/automation/cdp_input.py

The adapter also follows its CDP screenshot, key-code/modifier and focus-refresh
approach. It changes transport to an explicitly paired Chrome extension, so the
existing normal Chrome profile can be used. It changes error handling to propagate
failures and release held keys. No Star Rail daily task or account data is copied.

The existing OK-WW license still applies to OK-WW and its changes. This source
attribution must accompany the derived keyboard maps when redistributed.

Important differences: M7's own profile/ChromeDriver startup, game-specific queue
selectors, login detection, and tasks are not portable to cloud Wuwa. Its pointer
lock camera movement has an explicit upstream TODO; automatic Wuwa combat has not
been validated by this port.
