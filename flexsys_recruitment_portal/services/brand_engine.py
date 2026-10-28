"""Offline logo-derived brand palette. Pure Python/Pillow for deterministic unit tests."""
import hashlib
import io
import json
import re
from collections import Counter
from colorsys import rgb_to_hsv
from PIL import Image, UnidentifiedImageError

MAX_LOGO_BYTES = 3 * 1024 * 1024
MAX_PIXELS = 10_000_000
DEFAULT_PRIMARY = '#254b70'
TOKENS = ('primary', 'secondary', 'accent', 'background', 'surface', 'text',
          'text_secondary', 'on_primary', 'button_hover', 'border', 'focus',
          'success', 'error')

class InvalidLogo(ValueError):
    pass


def rgb(hexcolor):
    if not isinstance(hexcolor, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', hexcolor):
        raise ValueError('Invalid CSS hex color')
    return tuple(int(hexcolor[n:n+2], 16) for n in (1, 3, 5))


def hx(color):
    return '#%02x%02x%02x' % tuple(round(max(0, min(255, c))) for c in color)


def luminance(hexcolor):
    def linear(n):
        n = n / 255
        return n / 12.92 if n <= 0.04045 else ((n + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in rgb(hexcolor))
    return 0.2126*r + 0.7152*g + 0.0722*b


def contrast(a, b):
    x, y = sorted((luminance(a), luminance(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def mix(a, b, amount):
    x, y = rgb(a), rgb(b)
    return hx(tuple((1-amount)*v + amount*w for v, w in zip(x, y)))


def readable(bg):
    return '#ffffff' if contrast('#ffffff', bg) >= contrast('#18212d', bg) else '#18212d'


def ensure_contrast(fg, bg, minimum=4.5):
    rgb(fg)
    rgb(bg)
    if contrast(fg, bg) >= minimum:
        return fg.lower()
    target = readable(bg)
    for i in range(1, 101):
        proposed = mix(fg, target, i/100)
        if contrast(proposed, bg) >= minimum:
            return proposed
    return target


def extract_primary(blob):
    if not blob or len(blob) > MAX_LOGO_BYTES:
        raise InvalidLogo('Logo is empty or too large.')
    try:
        with Image.open(io.BytesIO(blob)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > MAX_PIXELS:
                raise InvalidLogo('Unsupported image or unsafe dimensions.')
            image = source.convert('RGBA')
            image.thumbnail((160, 160))
            counts = Counter()
            pixels = image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()
            for r, g, b, alpha in pixels:
                if alpha < 128:
                    continue
                h, s, v = rgb_to_hsv(r/255, g/255, b/255)
                if s < 0.14 or v > 0.96 and s < 0.28 or v < 0.09:
                    continue
                quantized = tuple((c//24)*24 + 12 for c in (r, g, b))
                counts[quantized] += max(1, round(s * 4))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidLogo('Invalid image data.') from exc
    if not counts:
        return DEFAULT_PRIMARY
    # Favour conspicuous coloured features, not wide pale backgrounds.
    chosen = max(counts.items(), key=lambda item: item[1])[0]
    chosen_hex = hx(chosen)
    return ensure_contrast(chosen_hex, '#ffffff', 4.5)


def generate_palette(blob):
    primary = extract_primary(blob)
    return {
        'primary': primary,
        'secondary': mix(primary, '#ffffff', .87),
        'accent': mix(primary, '#101820', .26),
        'background': '#ffffff',
        'surface': '#f6f8fb',
        'text': '#17202c',
        'text_secondary': '#4c5664',
        'on_primary': readable(primary),
        'button_hover': mix(primary, '#000000', .16),
        'border': '#737f8b',
        'focus': primary,
        'success': '#166534',
        'error': '#b42318',
    }


def apply_overrides(palette, overrides):
    result = dict(palette)
    for key, value in (overrides or {}).items():
        if key not in TOKENS:
            raise ValueError('Unknown brand token')
        rgb(value)
        result[key] = value.lower()
    result['on_primary'] = ensure_contrast(result['on_primary'], result['primary'])
    result['text'] = ensure_contrast(result['text'], result['background'])
    result['text_secondary'] = ensure_contrast(result['text_secondary'], result['background'])
    return result


def logo_fingerprint(blob):
    return hashlib.sha256(blob).hexdigest()


def safe_css(palette):
    # Token/value allowlist prevents injecting CSS via admin-configurable colors.
    for key in TOKENS:
        rgb(palette[key])
    return ';'.join('--fs-brand-%s:%s' % (key.replace('_', '-'), palette[key]) for key in TOKENS) + ';'


def to_json(palette):
    return json.dumps(palette, sort_keys=True)
