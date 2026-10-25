"""Linux owned-session compositor activity; native fresh-frame capture stays intact."""
import asyncio
import sys

class CompositorLease:
    def __init__(self, cdp):
        self.cdp = cdp
        self.active = False
        self.error = None
        self.acknowledged = 0

    async def _ack(self, event):
        # Image payload is deliberately neither retained nor used by OCR.
        try:
            await self.cdp.send('Page.screencastFrameAck', {'sessionId': event['sessionId']})
            self.acknowledged += 1
        except Exception as exc:
            self.error = type(exc).__name__

    async def start(self):
        if sys.platform != 'linux':
            raise RuntimeError('Compositor lease is restricted to the Linux owned session')
        if self.active:
            raise RuntimeError('Compositor lease already active')
        self.cdp.on('Page.screencastFrame', self._ack)
        try:
            await self.cdp.send('Page.startScreencast', {
                'format': 'jpeg', 'quality': 0, 'maxWidth': 16,
                'maxHeight': 9, 'everyNthFrame': 60})
            self.active = True
        except BaseException:
            self.cdp.remove_listener('Page.screencastFrame', self._ack)
            raise

    def assert_healthy(self):
        if not self.active or self.error:
            raise RuntimeError('Compositor lease unavailable: ' + str(self.error))

    async def close(self):
        try:
            if self.active:
                await self.cdp.send('Page.stopScreencast')
        finally:
            self.active = False
            self.cdp.remove_listener('Page.screencastFrame', self._ack)

async def verify_fresh_capture(driver, count=12):
    """Measure original full PNG capture; reject repeated presentation metadata."""
    import statistics
    import time
    if count < 8:
        raise ValueError('At least eight fresh samples are required')
    timings, freshness, sources = [], [], []
    for _ in range(count):
        began = time.perf_counter()
        result = await driver.frame()
        timings.append((time.perf_counter() - began) * 1000)
        current = result.get('freshness') or {}
        metrics = result.get('metrics') or {}
        if (not result.get('data') or result.get('gameSurface') is not True
                or not isinstance(current.get('presentedFrames'), (int, float))
                or not isinstance(current.get('mediaTime'), (int, float))
                or current['presentedFrames'] <= 0
                or metrics.get('source') not in ([1280,720], [1920,1080])):
            raise RuntimeError('Original capture has no verified fresh video presentation')
        if freshness and (current['presentedFrames'] <= freshness[-1]['presentedFrames']
                          or current['mediaTime'] <= freshness[-1]['mediaTime']):
            raise RuntimeError('Original capture returned a repeated video presentation')
        freshness.append(current)
        sources.append(metrics['source'])
    if any(source != sources[0] for source in sources):
        raise RuntimeError('Capture source changed during measurement')
    ordered = sorted(timings)
    median, p95 = statistics.median(timings), ordered[int(.95*(len(ordered)-1))]
    if median >= 350 or p95 >= 600:
        raise RuntimeError('Fresh capture is still too slow: median=%.1f p95=%.1f ms' % (median,p95))
    return dict(verified=True, samples=len(timings), median_ms=median, p95_ms=p95,
                source=sources[0], freshness=freshness, samples_ms=timings)
