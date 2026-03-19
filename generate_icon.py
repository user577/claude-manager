"""Generate app_icon.ico — a 2x2 grid of terminal windows on a dark background."""
import struct
import io
import zlib


def create_rgba_image(size: int) -> bytes:
    """Create a 2x2 grid icon as raw RGBA bytes."""
    pixels = bytearray(size * size * 4)

    bg = (30, 30, 46, 255)          # dark background
    grid_color = (137, 180, 250, 255)  # blue windows
    gap = max(size // 16, 1)
    pad = max(size // 8, 2)
    mid_x = size // 2
    mid_y = size // 2

    def set_pixel(x, y, rgba):
        if 0 <= x < size and 0 <= y < size:
            offset = (y * size + x) * 4
            pixels[offset:offset+4] = bytes(rgba)

    # Fill background with rounded-ish rect
    for y in range(size):
        for x in range(size):
            # Simple rounded corner check
            corner_r = max(size // 6, 2)
            in_corner = False
            for cx, cy in [(0, 0), (size-1, 0), (0, size-1), (size-1, size-1)]:
                dx = abs(x - cx)
                dy = abs(y - cy)
                if dx < corner_r and dy < corner_r:
                    if (corner_r - dx)**2 + (corner_r - dy)**2 > corner_r**2:
                        in_corner = True
            if not in_corner:
                set_pixel(x, y, bg)

    # Draw 4 quadrant rectangles
    quads = [
        (pad, pad, mid_x - gap, mid_y - gap),
        (mid_x + gap, pad, size - pad, mid_y - gap),
        (pad, mid_y + gap, mid_x - gap, size - pad),
        (mid_x + gap, mid_y + gap, size - pad, size - pad),
    ]
    for x1, y1, x2, y2 in quads:
        for y in range(y1, y2):
            for x in range(x1, x2):
                set_pixel(x, y, grid_color)

        # Add a tiny "prompt" indicator in each quad (top-left area)
        prompt_y = y1 + max((y2 - y1) // 4, 1)
        prompt_x_start = x1 + max((x2 - x1) // 6, 1)
        prompt_x_end = prompt_x_start + max((x2 - x1) // 3, 2)
        prompt_color = (30, 30, 46, 255)
        for y in range(prompt_y, min(prompt_y + max((y2 - y1) // 8, 1), y2)):
            for x in range(prompt_x_start, min(prompt_x_end, x2)):
                set_pixel(x, y, prompt_color)

    return bytes(pixels)


def create_png(size: int) -> bytes:
    """Create a minimal PNG from RGBA data."""
    rgba = create_rgba_image(size)

    # Build raw image data for PNG (filter byte 0 per row)
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter: none
        offset = y * size * 4
        raw.extend(rgba[offset:offset + size * 4])

    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8bit RGBA
    compressed = zlib.compress(bytes(raw))

    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')


def create_ico(sizes=(16, 32, 48, 256)) -> bytes:
    """Create a multi-resolution .ico file."""
    images = []
    for s in sizes:
        images.append((s, create_png(s)))

    # ICO header
    header = struct.pack("<HHH", 0, 1, len(images))

    offset = 6 + 16 * len(images)  # header + entries
    entries = bytearray()
    data = bytearray()

    for size, png_data in images:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries.extend(struct.pack("<BBBBHHII",
            w, h, 0, 0, 1, 32, len(png_data), offset))
        data.extend(png_data)
        offset += len(png_data)

    return header + bytes(entries) + bytes(data)


if __name__ == "__main__":
    ico_data = create_ico()
    with open("app_icon.ico", "wb") as f:
        f.write(ico_data)
    print(f"Created app_icon.ico ({len(ico_data)} bytes)")
