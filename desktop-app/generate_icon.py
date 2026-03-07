"""Generate macOS .icns icon for Thalamus.app"""

import struct
import zlib
import subprocess
import shutil
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"


def make_png(w, h, pixels):
    def chunk(ctype, cdata):
        c = ctype + cdata
        return struct.pack(">I", len(cdata)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def generate_icon_png(size=1024):
    W = H = size
    pixels = bytearray()

    for y in range(H):
        pixels.append(0)
        for x in range(W):
            cx, cy = W / 2, H / 2
            corner_r = int(W * 0.22)

            dx = max(0, abs(x - cx) - (cx - corner_r))
            dy = max(0, abs(y - cy) - (cy - corner_r))
            dist = (dx * dx + dy * dy) ** 0.5

            if dist > corner_r:
                pixels.extend([0, 0, 0, 0])
                continue

            t = (x + y) / (W + H)
            r = int(108 + (162 - 108) * t)
            g = int(92 + (155 - 92) * t)
            b = int(231 + (254 - 231) * t)

            nx = (x - cx) / (W * 0.35)
            ny = (y - cy) / (H * 0.4)
            bolt = False
            if -0.15 <= nx <= 0.25 and -1.0 <= ny <= 0.0:
                if nx <= 0.25 - 0.4 * (ny + 1.0):
                    bolt = True
            if -0.25 <= nx <= 0.15 and 0.0 <= ny <= 1.0:
                if nx >= -0.25 + 0.4 * ny:
                    bolt = True
            if bolt:
                r, g, b = 255, 255, 255

            pixels.extend([r, g, b, 255])

    return make_png(W, H, pixels)


def main():
    ASSETS.mkdir(exist_ok=True)
    png_1024 = ASSETS / "icon_1024.png"

    with open(png_1024, "wb") as f:
        f.write(generate_icon_png(1024))
    print("Generated 1024x1024 PNG")

    iconset = ASSETS / "icon.iconset"
    iconset.mkdir(exist_ok=True)

    for size in [16, 32, 64, 128, 256, 512]:
        subprocess.run(
            ["sips", "-z", str(size), str(size), str(png_1024),
             "--out", str(iconset / f"icon_{size}x{size}.png")],
            capture_output=True,
        )
        double = size * 2
        subprocess.run(
            ["sips", "-z", str(double), str(double), str(png_1024),
             "--out", str(iconset / f"icon_{size}x{size}@2x.png")],
            capture_output=True,
        )

    shutil.copy2(png_1024, iconset / "icon_512x512@2x.png")

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "icon.icns")],
        check=True,
    )

    shutil.rmtree(iconset)
    png_1024.unlink()
    print(f"Generated {ASSETS / 'icon.icns'}")


if __name__ == "__main__":
    main()
