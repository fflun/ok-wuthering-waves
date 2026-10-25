"""Lazy backend exports: importing the browser must not import Windows capture."""
import importlib
_EXPORTS = {'ADBInteraction': ('ok.device.interaction_methods.adb', 'ADBInteraction'), 'BaseInteraction': ('ok.device.interaction_methods.base', 'BaseInteraction'), 'BrowserInteraction': ('ok.device.interaction_methods.browser', 'BrowserInteraction'), 'DoNothingInteraction': ('ok.device.interaction_methods.do_nothing', 'DoNothingInteraction'), 'ForegroundPostMessageInteraction': ('ok.device.interaction_methods.foreground_post_message', 'ForegroundPostMessageInteraction'), 'GenshinInteraction': ('ok.device.interaction_methods.genshin', 'GenshinInteraction'), 'INPUT': ('ok.device.interaction_methods.genshin', 'INPUT'), 'MOUSEINPUT': ('ok.device.interaction_methods.genshin', 'MOUSEINPUT'), 'SendInput': ('ok.device.interaction_methods.genshin', 'SendInput'), 'ADB_KEY_MAP': ('ok.device.interaction_methods.keys', 'ADB_KEY_MAP'), 'PYDIRECT_KEY_MAP': ('ok.device.interaction_methods.keys', 'PYDIRECT_KEY_MAP'), 'normalize_pydirect_key': ('ok.device.interaction_methods.keys', 'normalize_pydirect_key'), 'vk_key_dict': ('ok.device.interaction_methods.keys', 'vk_key_dict'), 'PostMessageInteraction': ('ok.device.interaction_methods.post_message', 'PostMessageInteraction'), 'PyDirectInteraction': ('ok.device.interaction_methods.pydirect', 'PyDirectInteraction'), 'PynputInteraction': ('ok.device.interaction_methods.pynput', 'PynputInteraction'), 'insert_swipe': ('ok.device.interaction_methods.swipe', 'insert_swipe')}
__all__ = list(_EXPORTS)
def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    value = getattr(importlib.import_module(module), attribute)
    globals()[name] = value
    return value
