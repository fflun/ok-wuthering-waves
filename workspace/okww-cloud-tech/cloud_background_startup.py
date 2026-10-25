"""Observe two fresh frames without restarting or sending game input."""
import asyncio
import math
import re
import time


async def dismiss_received_time_award(page):
    """A completed seven-day time receipt; never a purchase/payment control."""
    award=page.locator('.award')
    if await award.count()!=1:return False
    def received(text):
        compact=''.join(text.split())
        return ('点击空白区域关闭' in compact and '购买' in compact
                and re.search(r'[×xX]?畅玩7天',compact) is not None
                and not any(word in compact for word in ('确认购买','立即购买','支付','充值','验证码')))
    first=await award.inner_text()
    if not received(first):return False
    await asyncio.sleep(.3)
    if await award.count()!=1:return False
    second=await award.inner_text()
    if not received(second) or ''.join(first.split())!=''.join(second.split()):
        raise RuntimeError('Cloud time receipt changed before dismissal')
    close=award.get_by_text('点击空白区域关闭',exact=True)
    if await close.count()!=1:raise RuntimeError('Cloud time receipt close label is ambiguous')
    rect=await award.bounding_box()
    if not rect or rect['width']<640 or rect['height']<360:
        raise RuntimeError('Cloud time receipt overlay size is unverified')
    # The observed label has pointer-events:none. The receipt explicitly says
    # to click blank space; click its verified full overlay, never underlying UI.
    await award.click(position={'x':20,'y':20},timeout=5000)
    return True


def explicit_start_failure(text):
    # The observed cloud-client dialog, not a gameplay/capture failure or login gate.
    compact=''.join(text.split())
    return ('开始游戏失败，请稍后重试，若仍无法解决请重启客户端或寻求客服支持。' in compact
            and '提示' in compact and '好的' in compact
            and not any(word in compact for word in ('登录','购买','支付','充值','时长不足')))


class BackgroundFrameError(RuntimeError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__('Background game frames unavailable; ' + str(diagnostics))


def frame_stamp(frame):
    if frame.get('gameSurface') is not True or not frame.get('data'):
        raise RuntimeError('No fresh game surface frame')
    metrics = frame.get('metrics', {})
    source = metrics.get('source', [])
    if (metrics.get('kind') not in ('video', 'canvas') or not metrics.get('ready')
            or len(source) != 2 or any(not isinstance(n, (int,float)) or n <= 0 for n in source)):
        raise RuntimeError('No fresh game surface frame')
    fresh = frame.get('freshness', {}) or {}
    media, count = fresh.get('mediaTime'), fresh.get('presentedFrames')
    if any(isinstance(n, bool) or not isinstance(n, (int,float)) or not math.isfinite(n)
           for n in (media, count)) or media < 0 or count <= 0:
        raise RuntimeError('No fresh game surface frame')
    return (metrics['kind'], tuple(source)), (media, count)


async def wait_fresh_surface(browser, timeout=120, *, clock=time.monotonic, pause=asyncio.sleep):
    deadline = clock() + timeout
    previous = None
    diagnostics = dict(ready=False, kind=None, fresh_frames=0, frame_stalls=0)
    while clock() < deadline:
        metrics = await asyncio.wait_for(browser.metrics(), timeout=max(.01, deadline-clock()))
        diagnostics.update(ready=metrics.get('ready') is True, kind=metrics.get('kind'))
        if metrics.get('ready') and metrics.get('kind') in ('canvas', 'video'):
            try:
                frame = await asyncio.wait_for(browser.frame(), timeout=max(.01, deadline-clock()))
                surface, stamp = frame_stamp(frame)
                # Transport/size changes reset the pair; frozen or rewinded
                # counters cannot qualify as a continuing stream.
                if previous and previous[0] == surface:
                    if stamp[0] > previous[1][0] and stamp[1] > previous[1][1]:
                        return frame['metrics']
                previous = surface, stamp
                diagnostics['fresh_frames'] += 1
            except Exception as exc:
                # page.evaluate wraps JavaScript rejection in Playwright Error,
                # not RuntimeError. Only the exact observed frame-stall message
                # may follow the existing bounded read-only wait path.
                canvas_stall = str(exc).partition('\n')[0] == 'Page.evaluate: Error: Canvas video stalled'
                native_stall = isinstance(exc, RuntimeError) and any(token in str(exc).lower()
                        for token in ('stalled', 'no fresh', 'disappeared', 'not ready', '尚未就绪'))
                if not isinstance(exc, TimeoutError) and not canvas_stall and not native_stall:
                    raise
                previous = None
                diagnostics['frame_stalls'] += 1
        else:
            previous = None
        remaining = deadline - clock()
        if remaining > 0: await pause(min(.2 if metrics.get('ready') else 1, remaining))
    raise BackgroundFrameError(diagnostics)
