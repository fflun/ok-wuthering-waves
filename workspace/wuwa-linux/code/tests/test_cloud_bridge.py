import asyncio
import json
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from cloud_bridge import ChromeBridge, game_rect, pixel_crop
from cloud_cdp_input import CdpKeyboard, CdpMouse


def surface(**extra):
    return dict(ready=True,kind='canvas',rect=[0,0,1280,720],source=[1920,1080],
                fit='fill',position='50% 50%',viewport=[1280,720],**extra)


class GeometryTests(unittest.TestCase):
    def test_local_crop_hidpi(self):
        self.assertEqual(pixel_crop(dict(x=10,y=20,width=100,height=80),
                                    [1280,720],[2560,1440]),(20,40,220,200))

    def test_crop_rejects_resized_screenshot(self):
        with self.assertRaises(RuntimeError):
            pixel_crop(dict(x=0,y=0,width=1280,height=720),[1280,720],[1309,1208])

    def test_canvas_mapping(self):
        self.assertEqual(game_rect(surface()),dict(x=0,y=0,width=1280,height=720))

    def test_letterbox(self):
        m=surface(); m.update(rect=[0,0,1280,1000],fit='contain',viewport=[1280,1000])
        self.assertEqual(game_rect(m),dict(x=0,y=140,width=1280,height=720))

    def test_unsafe_layouts(self):
        for changes in ({'ready':False},{'rect':[0,0,1309,1208]},
                        {'rect':[-2,0,1280,720]},{'source':[0,0]},
                        {'fit':'contain','position':'0% 0%'}):
            m=surface(); m.update(changes)
            with self.subTest(changes=changes), self.assertRaises(RuntimeError): game_rect(m)


class BridgeTests(unittest.TestCase):
    def setUp(self): self.bridge=ChromeBridge(port=0)
    def tearDown(self): self.bridge.close()

    def post(self,path,body,token=None):
        req=Request(f'http://127.0.0.1:{self.bridge.port}'+path,
                    data=json.dumps(body).encode(),headers={
                    'Authorization':'Bearer '+(token or self.bridge.token),
                    'Content-Type':'application/json'})
        with urlopen(req,timeout=2) as response: return json.load(response)

    def test_auth(self):
        with self.assertRaises(HTTPError) as error: self.post('/poll',{},'wrong')
        self.assertEqual(error.exception.code,403)
        self.assertFalse(self.bridge.connected())

    def test_automatic_extension_handshake(self):
        for origin in ('chrome-extension://' + 'a'*32, 'https://example.com', 'null', ''):
            req=Request(f'http://127.0.0.1:{self.bridge.port}/connect', data=b'{}',
                        headers={'Origin':origin,'Content-Type':'application/json'})
            if origin.startswith('chrome-extension:'):
                with urlopen(req,timeout=2) as response:
                    self.assertEqual(json.load(response)['token'],self.bridge.token)
            else:
                with self.assertRaises(HTTPError) as error: urlopen(req,timeout=2)
                self.assertEqual(error.exception.code,403)

    def test_round_trip(self):
        result=[]
        t=threading.Thread(target=lambda:result.append(self.bridge.request('metrics')))
        t.start()
        for _ in range(30):
            cmd=self.post('/poll',{})['command']
            if cmd: break
            time.sleep(.01)
        self.post('/result',dict(id=cmd['id'],result={'ready':True}))
        t.join(2)
        self.assertEqual(result,[{'ready':True}])

    def test_expired_not_delivered(self):
        with self.assertRaises(TimeoutError): self.bridge.request('input',timeout=.01)
        self.assertIsNone(self.post('/poll',{})['command'])

    def test_no_arbitrary_cdp(self):
        with self.assertRaises(ValueError): self.bridge.request('Runtime.evaluate')


class InputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events=[]
        class Page: pass
        self.page=Page()
        async def send(method,params,release=False): self.events.append((method,params,release))
        self.page.send=send
        self.page.keyboard=CdpKeyboard(self.page)
        self.page.mouse=CdpMouse(self.page)

    async def test_focus_key_payload_and_release(self):
        await self.page.keyboard.press('w',delay=0)
        self.assertEqual([x[1]['type'] for x in self.events],['mouseMoved','keyDown','keyUp'])
        self.assertEqual(self.events[1][1]['windowsVirtualKeyCode'],87)
        self.assertEqual(self.events[1][1]['code'],'KeyW')
        self.assertEqual(self.page.keyboard.held,{})

    async def test_both_shifts_release_one(self):
        k=self.page.keyboard
        await k.down('ShiftLeft'); await k.down('ShiftRight'); await k.up('ShiftLeft')
        self.assertEqual(self.events[-1][1]['modifiers'],8)
        await k.up('ShiftRight')
        self.assertEqual(self.events[-1][1]['modifiers'],0)

    async def test_mouse_release_buttons_zero(self):
        await self.page.mouse.down(); await self.page.mouse.up()
        self.assertEqual(self.events[-1][1]['buttons'],0)
        self.assertTrue(self.events[-1][2])

    async def test_cancel_releases_key(self):
        task=asyncio.create_task(self.page.keyboard.press('w',delay=10000))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(self.events[-1][1]['type'],'keyUp')

    async def test_unknown_key_is_error(self):
        with self.assertRaises(ValueError): await self.page.keyboard.down('made-up-key')
        self.assertFalse(self.events)


if __name__=='__main__': unittest.main()
