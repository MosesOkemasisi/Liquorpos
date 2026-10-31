"""Server-side photo optimisation: crop to a fixed shape, shrink, fix rotation and compress."""
import io
import os

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

PRODUCT_ASPECT = (4, 3)      # same shape as the picture frame in the shop
PRODUCT_MAX = (800, 600)     # plenty for the shop, cart and POS tiles
WEBP_QUALITY = 82
MAX_PIXELS = 50_000_000      # refuse absurdly large images (decompression-bomb guard)
MAX_UPLOAD = 20 * 1024 * 1024


def optimise_image(uploaded, aspect=PRODUCT_ASPECT, max_size=PRODUCT_MAX):
    """Return a small WebP ContentFile made from an uploaded image.

    The picture is cropped (from the centre) to `aspect` so it fills its frame with no bars,
    then shrunk to fit inside `max_size`. Small photos are never enlarged.
    Raises ValueError if the file is not a readable image.
    """
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        uploaded.seek(0)
        img = Image.open(uploaded)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("That file could not be read as an image. Please use a JPG, PNG or WebP photo.")

    img = ImageOps.exif_transpose(img)  # phone photos often store rotation in EXIF
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "transparency" in img.info or img.mode in ("LA", "PA") else "RGB")

    w, h = img.size
    target = aspect[0] / aspect[1]
    if w / h > target:            # too wide: trim left and right
        new_w = int(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    elif w / h < target:          # too tall: trim top and bottom
        new_h = int(w / target)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    img.thumbnail(max_size, Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=6)
    base = os.path.splitext(os.path.basename(getattr(uploaded, "name", "photo")))[0] or "photo"
    return ContentFile(buffer.getvalue(), name=f"{base[:60]}.webp")


def process_form_image(image, **kwargs):
    """For form clean_<field>() methods.

    A freshly uploaded file is optimised. An existing stored image, an empty value or a
    "clear" request is returned untouched. Raises ValueError with a message fit to show users.
    """
    if isinstance(image, UploadedFile):
        if image.size > MAX_UPLOAD:
            raise ValueError("Photo is too large (over 20 MB). Please pick a smaller one.")
        return optimise_image(image, **kwargs)
    return image
