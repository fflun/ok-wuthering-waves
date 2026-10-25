import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

from cloud_background_browser import BackgroundBrowser, GAME_URL


class BackgroundBrowserTests(unittest.IsolatedAsyncioTestCase):
    def make_browser(self):
        browser=BackgroundBrowser(tempfile.gettempdir())
        browser.page=Mock()
        browser.page.is_closed.return_value=False
        browser.page.url=GAME_URL+'#/'
        browser.cdp=Mock(send=AsyncMock())
        return browser

    async def test_disabled_input_does_not_dispatch_or_hold_keys(self):
        browser=self.make_browser()
        with self.assertRaisesRegex(RuntimeError,'disabled'):
            await browser.key('KeyW','w',87,True)
        browser.cdp.send.assert_not_awaited()
        self.assertEqual(browser.keys,set())

    async def test_navigation_stops_input_before_dispatch(self):
        browser=self.make_browser()
        browser.input_enabled=True
        browser.page.url='https://example.com/'
        with self.assertRaisesRegex(RuntimeError,'Unexpected page'):
            await browser.key('KeyW','w',87,True)
        browser.cdp.send.assert_not_awaited()
        self.assertFalse(browser.input_enabled)

    async def test_release_remains_possible_after_input_disabled(self):
        browser=self.make_browser()
        browser.input_enabled=True
        await browser.key('KeyW','w',87,True)
        browser.input_enabled=False
        await browser.release()
        self.assertEqual(browser.keys,set())
        self.assertEqual(browser.cdp.send.await_args.args[1]['type'],'keyUp')

    async def test_close_cleans_owned_browser_even_if_key_release_fails(self):
        browser=self.make_browser()
        browser.keys.add(('KeyW','w',87))
        browser.cdp.send.side_effect=RuntimeError('transport lost')
        context=browser.context=Mock(close=AsyncMock())
        playwright=browser.playwright=Mock(stop=AsyncMock())
        with self.assertRaisesRegex(RuntimeError,'transport lost'):
            await browser.close()
        context.close.assert_awaited_once()
        playwright.stop.assert_awaited_once()
        self.assertIsNone(browser.page)


if __name__=='__main__':unittest.main()
