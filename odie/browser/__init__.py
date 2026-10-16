"""Odie's own browser: the Chrome, Edge, Chromium or Brave already on the computer, driven over the DevTools protocol
in a profile of its own (never the user's), reaching only public web addresses."""
from __future__ import annotations

# The flags the render browser adds so three.js gets WebGL headless: Metal through ANGLE on a Mac, with SwiftShader
# (software) as the fallback the browser picks when the GPU path isn't there.
GL_ARGS = ("--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader")

# The flags that cut the render browser off from the network. Its sealed tabs refuse HTTP requests through request
# interception, but that never sees a WebSocket, nor anything a worker opens. So every connection is sent to a proxy
# that isn't there (port 9 on this computer, where nothing listens), this computer included (<-loopback> takes away
# the proxy's usual exception for localhost), and WebRTC may not go around the proxy. Only the render browser gets
# these: it only ever draws sealed pages, while the browsing browser has to reach the web.
NO_NETWORK_ARGS = ("--proxy-server=socks5://127.0.0.1:9", "--proxy-bypass-list=<-loopback>",
                   "--force-webrtc-ip-handling-policy=disable_non_proxied_udp")

# Everything the render browser adds: WebGL, and no network.
RENDER_ARGS = GL_ARGS + NO_NETWORK_ARGS

_shared = None
_render = None


def shared():
    """The app's one browser (its profile in <data>/browser), made on first use."""
    global _shared
    if _shared is None:
        from odie import config
        from odie.browser.engine import Browser
        _shared = Browser(config.settings.data_dir / "browser")
    return _shared


def render_browser():
    """The browser videos are drawn in: its own profile, the GL flags and no network at all (RENDER_ARGS), so
    rendering never changes the browsing one."""
    global _render
    if _render is None:
        from odie import config
        from odie.browser.engine import Browser
        _render = Browser(config.settings.data_dir / "browser-render", extra_args=RENDER_ARGS)
    return _render


async def close_shared() -> None:
    global _shared, _render
    if _shared is not None:
        await _shared.close()
        _shared = None
    if _render is not None:
        await _render.close()
        _render = None
