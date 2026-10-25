"""Linux cloud keyboard delivery; preserve native key codes and task timings."""
import sys


class ProviderKeys:
    def __init__(self, driver):
        self.driver = driver
        self.held = {}

    async def send(self, payload):
        self.driver.ensure_page()
        kind = payload.get('type')
        code = payload.get('code')
        vk = payload.get('windowsVirtualKeyCode')
        if kind not in ('keyDown', 'keyUp') or not isinstance(code, str):
            raise ValueError('Unsupported keyboard event')
        if type(vk) is not int or not 1 <= vk <= 255:
            raise ValueError('Invalid virtual key')
        saved = self.held.get(code)
        if saved and saved[1] != vk:
            raise RuntimeError('Held key identity changed')
        route = saved[0] if saved else 'cdp'
        if not saved and sys.platform == 'linux':
            supported = await self.driver.page.evaluate("""() =>
                !window.tencentGamePlayer
                && typeof window.WLCG?.onKeyBoardEvent === 'function'
                && typeof window.WLCG.KEY_DOWN === 'number'
                && typeof window.WLCG.KEY_UP === 'number'""")
            if supported is True:
                route = 'welink'
        if kind == 'keyDown':
            # Retain on transport failure so cleanup still releases the same key.
            self.held[code] = (route, vk)
        if route == 'welink':
            await self.driver.page.evaluate("""({vk, down}) => {
                const s = window.WLCG;
                if (typeof s?.onKeyBoardEvent !== 'function')
                    throw Error('Owned Welink keyboard disappeared');
                if (down && s.isOnPause === true)
                    throw Error('Owned Welink session paused');
                s.onKeyBoardEvent(vk, down ? s.KEY_DOWN : s.KEY_UP);
            }""", {'vk': vk, 'down': kind == 'keyDown'})
        else:
            await self.driver.cdp.send('Input.dispatchKeyEvent', payload)
        if kind == 'keyUp':
            self.held.pop(code, None)
