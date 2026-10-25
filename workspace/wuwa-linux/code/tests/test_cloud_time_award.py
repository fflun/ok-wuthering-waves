import unittest
from unittest.mock import AsyncMock,Mock,patch
from cloud_background_startup import dismiss_received_time_award

class TimeAwardTests(unittest.IsolatedAsyncioTestCase):
    def page(self,text='购买\n×畅玩7天\n点击空白区域关闭'):
        page=Mock();award=page.locator.return_value
        award.count=AsyncMock(return_value=1);award.inner_text=AsyncMock(return_value=text)
        award.bounding_box=AsyncMock(return_value={'x':0,'y':0,'width':1280,'height':720})
        award.click=AsyncMock()
        close=award.get_by_text.return_value;close.count=AsyncMock(return_value=1);close.click=AsyncMock()
        return page,award,close
    async def test_two_matching_receipt_frames_then_blank_overlay_only(self):
        page,award,close=self.page()
        self.assertTrue(await dismiss_received_time_award(page))
        self.assertEqual(award.inner_text.await_count,2)
        award.get_by_text.assert_called_once_with('点击空白区域关闭',exact=True)
        close.click.assert_not_awaited()
        award.click.assert_awaited_once_with(position={'x':20,'y':20},timeout=5000)
    async def test_purchase_or_unrelated_overlay_never_clicked(self):
        for text in ('购买\n畅玩7天\n确认购买\n点击空白区域关闭',
                     '购买\n畅玩7天\n支付\n点击空白区域关闭',
                     '购买\n畅玩30天\n点击空白区域关闭','点击空白区域关闭'):
            page,award,close=self.page(text)
            self.assertFalse(await dismiss_received_time_award(page));close.click.assert_not_awaited()
    async def test_changed_receipt_stops(self):
        page,award,close=self.page();award.inner_text.side_effect=['购买×畅玩7天点击空白区域关闭','购买×畅玩30天点击空白区域关闭']
        with self.assertRaisesRegex(RuntimeError,'changed'):await dismiss_received_time_award(page)
        close.click.assert_not_awaited()
    async def test_duplicate_overlays_or_close_labels_rejected(self):
        page,award,close=self.page();award.count.return_value=2
        self.assertFalse(await dismiss_received_time_award(page));close.click.assert_not_awaited()
        page,award,close=self.page();close.count.return_value=2
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):await dismiss_received_time_award(page)
        close.click.assert_not_awaited()
    async def test_small_overlay_never_clicked(self):
        page,award,close=self.page();award.bounding_box.return_value={'x':1,'y':1,'width':100,'height':100}
        with self.assertRaisesRegex(RuntimeError,'size is unverified'):await dismiss_received_time_award(page)
        award.click.assert_not_awaited()

if __name__=='__main__':unittest.main()
