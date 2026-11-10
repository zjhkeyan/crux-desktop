"""Image utilities for multimodal prompt construction.

Provides compression and resizing of base64-encoded images to keep
LLM prompts within token/size limits. These operations are applied
at prompt construction time, not at evaluation time, so full-quality
images are preserved for frontend display.
"""

import base64
import io


def compress_image_base64(base64_str: str, max_kb: int = 512) -> str:
    """Compress a base64-encoded image to fit within a size limit.

    Iteratively reduces JPEG quality until the image fits within
    ``max_kb`` kilobytes. If the input is already small enough it is
    returned unchanged.

    Args:
        base64_str: Base64-encoded image data (PNG or JPEG).
        max_kb: Maximum size in kilobytes.

    Returns:
        Base64-encoded JPEG image within the size limit, or the
        original string if compression is unavailable.
    """
    try:
        from PIL import Image
    except ImportError:
        return base64_str

    raw = base64.b64decode(base64_str)
    if len(raw) <= max_kb * 1024:
        return base64_str

    img: Image.Image = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    quality = 85
    while quality >= 10:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= max_kb * 1024:
            return base64.b64encode(buf.getvalue()).decode()
        quality -= 10

    # Last resort: return at lowest quality
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=10)
    return base64.b64encode(buf.getvalue()).decode()


def resize_image_base64(
    base64_str: str,
    max_width: int = 1024,
    max_height: int = 1024,
) -> str:
    """Resize a base64-encoded image to fit within maximum dimensions.

    Maintains aspect ratio. If the image already fits, it is returned
    unchanged.

    Args:
        base64_str: Base64-encoded image data.
        max_width: Maximum width in pixels.
        max_height: Maximum height in pixels.

    Returns:
        Base64-encoded PNG image within the size constraints, or the
        original string if resizing is unavailable.
    """
    try:
        from PIL import Image
    except ImportError:
        return base64_str

    raw = base64.b64decode(base64_str)
    img: Image.Image = Image.open(io.BytesIO(raw))

    if img.width <= max_width and img.height <= max_height:
        return base64_str

    resample = getattr(Image, "Resampling", Image).LANCZOS
    img.thumbnail((max_width, max_height), resample)
    buf = io.BytesIO()
    fmt = "PNG" if img.mode == "RGBA" else "JPEG"
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()
