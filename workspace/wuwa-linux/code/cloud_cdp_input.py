"""March7th-style CDP keyboard/mouse events exposed as the OK-WW adapter API."""
import asyncio
from cloud_keymap import KEY_ALIAS_MAP, SPECIAL_KEY_MAP, CHAR_KEY_MAP


def key_info(key):
    name = str(key).lower()
    name = {'lshift':'shiftleft','rshift':'shiftright','lctrl':'ctrlleft',
            'rctrl':'ctrlright','controlleft':'ctrlleft','controlright':'ctrlright',
            'lalt':'altleft','ralt':'altright',' ':'space'}.get(name, name)
    name = KEY_ALIAS_MAP.get(name, name)
    info = SPECIAL_KEY_MAP.get(name) or CHAR_KEY_MAP.get(name)
    if info is None or info.get('modifier') == 4:
        raise ValueError(f'Unsupported game key: {key}')
    return info


class CdpKeyboard:
    def __init__(self, page):
        self.page = page
        self.held = {}

    async def event(self, key, down):
        info = key_info(key)
        held = dict(self.held)
        if down:
            held[info['code']] = info
        else:
            held.pop(info['code'], None)
        modifiers = 0
        for item in held.values():
            modifiers |= item.get('modifier', 0)
        payload = dict(type='keyDown' if down else 'keyUp',key=info['key'],code=info['code'],
                       windowsVirtualKeyCode=info['vk'],nativeVirtualKeyCode=info['vk'],
                       modifiers=modifiers,text='')
        if 'location' in info:
            payload['location'] = info['location']
        if down:
            # M7 refreshes the last game mouse position before key down.
            await self.page.mouse.move(self.page.mouse.x, self.page.mouse.y)
            self.held = held  # Track even if the response is lost after dispatch.
        await self.page.send('Input.dispatchKeyEvent', payload, release=not down)
        self.held = held

    async def down(self, key):
        await self.event(key, True)

    async def up(self, key):
        await self.event(key, False)

    async def press(self, key, delay=20):
        try:
            await self.down(key)
            # Linux direct CDP has no extension-poll latency to stretch a 10ms tap.
            await asyncio.sleep(max(60, delay)/1000)
        finally:
            await self.up(key)

    async def type(self, text):
        if not isinstance(text,str) or len(text)>256:
            raise ValueError('Invalid game text')
        await self.page.send('Input.insertText', {'text':text})


class CdpMouse:
    def __init__(self, page):
        self.page = page
        self.x, self.y = 640, 360
        self.buttons = set()

    async def event(self, event, button='none', **extra):
        bits = sum({'left':1,'right':2,'middle':4}[b] for b in self.buttons)
        modifiers = 0
        for info in self.page.keyboard.held.values():
            modifiers |= info.get('modifier', 0)
        await self.page.send('Input.dispatchMouseEvent', dict(type=event,x=self.x,y=self.y,
            button=button,buttons=bits,pointerType='mouse',modifiers=modifiers,**extra),
            release=event=='mouseReleased')

    async def move(self, x, y):
        self.x, self.y = x, y
        await self.event('mouseMoved')

    async def down(self, button='left'):
        if button not in ('left','right','middle'):
            raise ValueError('Unknown mouse button')
        self.buttons.add(button)
        await self.event('mousePressed',button,clickCount=1)

    async def up(self, button='left'):
        self.buttons.discard(button)
        await self.event('mouseReleased',button,clickCount=1)

    async def wheel(self, dx, dy):
        await self.event('mouseWheel',deltaX=dx,deltaY=dy)


class BridgePage:
    def __init__(self, capture):
        self.capture = capture
        self.keyboard = CdpKeyboard(self)
        self.mouse = CdpMouse(self)

    async def send(self, method, params, release=False):
        if (self.capture.block_input or getattr(self.capture,'recovering',False)) and not release:
            raise RuntimeError('Cloud input stopped')
        try:
            return await self.capture.request('input',dict(method=method,params=params))
        except BaseException:
            self.capture.block_input = True
            raise

    def is_closed(self):
        return not self.capture.bridge.connected()
