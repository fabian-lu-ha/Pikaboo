from playwright.async_api import Browser, Playwright, async_playwright

_pw: Playwright | None = None
_browser: Browser | None = None


async def start() -> None:
    global _pw, _browser
    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(headless=True)


async def stop() -> None:
    global _pw, _browser
    if _browser is not None:
        await _browser.close()
    if _pw is not None:
        await _pw.stop()
    _pw = None
    _browser = None


def get_browser() -> Browser:
    if _browser is None:
        raise RuntimeError("Playwright browser is not running")
    return _browser
