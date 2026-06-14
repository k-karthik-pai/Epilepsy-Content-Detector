from __future__ import annotations

from collections.abc import Iterable

from .models import Monitor, ScreenFrame


SYNTHETIC_MONITOR = Monitor("synthetic", 0, 0, 160, 90, True)


def solid_frame(timestamp: float, rgb: tuple[int, int, int], width: int = 160, height: int = 90) -> ScreenFrame:
    r, g, b = rgb
    pixel = bytes((b, g, r, 255))
    return ScreenFrame(SYNTHETIC_MONITOR, timestamp, width, height, pixel * width * height)


def browser_like_frame(timestamp: float, width: int = 160, height: int = 90) -> ScreenFrame:
    data = bytearray(bytes((255, 255, 255, 255)) * width * height)
    toolbar = bytes((225, 225, 225, 255))
    text = bytes((45, 45, 45, 255))
    accent = bytes((190, 95, 30, 255))

    for y in range(0, 12):
        for x in range(width):
            offset = (y * width + x) * 4
            data[offset : offset + 4] = toolbar

    for y in range(20, 76, 10):
        for x in range(12, 118):
            if (x // 7) % 3 == 0:
                offset = (y * width + x) * 4
                data[offset : offset + 4] = text

    for y in range(30, 76, 20):
        for x in range(14, 82):
            if (x // 9) % 2 == 0:
                offset = (y * width + x) * 4
                data[offset : offset + 4] = accent

    return ScreenFrame(SYNTHETIC_MONITOR, timestamp, width, height, bytes(data))


def partial_stripes_frame(
    timestamp: float,
    inverted: bool = False,
    width: int = 160,
    height: int = 90,
) -> ScreenFrame:
    data = bytearray()
    patterned_height = height // 4
    for y in range(height):
        for x in range(width):
            if y < patterned_height:
                stripe_on = (x // 8) % 2 == 0
                if inverted:
                    stripe_on = not stripe_on
                value = 255 if stripe_on else 0
            else:
                value = 245
            data.extend((value, value, value, 255))
    return ScreenFrame(SYNTHETIC_MONITOR, timestamp, width, height, bytes(data))


def stripes_frame(timestamp: float, width: int = 160, height: int = 90) -> ScreenFrame:
    data = bytearray()
    for _y in range(height):
        for x in range(width):
            value = 255 if (x // 8) % 2 == 0 else 0
            data.extend((value, value, value, 255))
    return ScreenFrame(SYNTHETIC_MONITOR, timestamp, width, height, bytes(data))


def scenario_frames(name: str, sample_fps: float = 12.0) -> Iterable[ScreenFrame]:
    step = 1.0 / sample_fps
    if name == "safe-browser":
        yield solid_frame(0.0, (32, 80, 128))
        yield solid_frame(step, (245, 245, 245))
        yield browser_like_frame(step * 2)
        yield browser_like_frame(step * 3)
        yield solid_frame(step * 4, (250, 250, 250))
        return

    if name == "partial-pattern":
        yield solid_frame(0.0, (34, 34, 34))
        yield partial_stripes_frame(step)
        yield partial_stripes_frame(step * 2, inverted=True)
        return

    if name == "general-flash":
        colors = [(0, 0, 0), (255, 255, 255)] * 6
        for index, color in enumerate(colors):
            yield solid_frame(index * step, color)
        return

    if name == "red-flash":
        colors = [(0, 0, 0), (255, 0, 0)] * 6
        for index, color in enumerate(colors):
            yield solid_frame(index * step, color)
        return

    if name == "regular-pattern":
        yield stripes_frame(0.0)
        return

    raise ValueError(f"Unknown synthetic scenario: {name}")


def scenario_names() -> tuple[str, ...]:
    return ("safe-browser", "partial-pattern", "general-flash", "red-flash", "regular-pattern")

