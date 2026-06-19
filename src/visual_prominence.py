"""Visual Prominence — spectral-residual saliency on an ad creative image.

Honest label: this shows what POPS (contrast / edges / colour structure), NOT
where humans provably look. It is NOT eye-tracking and must never be labelled
as such. Pure numpy + Pillow — no GPU, no scipy, no new heavy deps. Computed at
low resolution and gc'd, so it's cheap and Railway-OOM-safe.

Public: ``analyze_visual_prominence(image_path) -> dict``. Never raises;
returns ``{"found": False}`` on any failure so the caller just hides the card.
"""
from __future__ import annotations

import base64
import gc
import io

import numpy as np
from PIL import Image, ImageFilter

__all__ = ["analyze_visual_prominence"]

_WORK = 128            # saliency compute resolution (low res by design)
_MAX_OVERLAY_W = 720   # overlay display width cap — keeps the base64 small


def _box3(a: np.ndarray) -> np.ndarray:
    """3x3 mean filter, pure numpy (no scipy)."""
    p = np.pad(a, 1, mode="edge")
    return (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] +
            p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:] +
            p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 9.0


def _saliency(pil_img: Image.Image) -> np.ndarray:
    """0..1 saliency at the image's size, via Hou & Zhang 2007 spectral residual."""
    g = pil_img.convert("L").resize((_WORK, _WORK))
    f = np.fft.fft2(np.asarray(g, dtype=np.float64))
    log_amp = np.log(np.abs(f) + 1e-8)
    phase = np.angle(f)
    spectral_residual = log_amp - _box3(log_amp)
    recon = np.fft.ifft2(np.exp(spectral_residual + 1j * phase))
    sal = np.abs(recon) ** 2
    sal_img = Image.fromarray((255 * (sal / (sal.max() + 1e-8))).astype(np.uint8))
    sal_img = sal_img.filter(ImageFilter.GaussianBlur(2)).resize(pil_img.size)
    sal = np.asarray(sal_img, dtype=np.float64)
    return (sal - sal.min()) / (sal.max() - sal.min() + 1e-8)


def _heat_rgba(sal: np.ndarray) -> Image.Image:
    """0..1 saliency -> jet-ish RGBA heat; alpha grows with prominence."""
    r = np.clip(1.5 - np.abs(4 * sal - 3), 0, 1)
    g = np.clip(1.5 - np.abs(4 * sal - 2), 0, 1)
    b = np.clip(1.5 - np.abs(4 * sal - 1), 0, 1)
    a = np.clip(sal ** 0.8 * 1.15, 0, 1)
    rgba = (np.stack([r, g, b, a], axis=-1) * 255).astype(np.uint8)
    return Image.fromarray(rgba)


def _read(sal: np.ndarray) -> dict:
    """Plain-English 'where the attention lands' read (the text half)."""
    h, w = sal.shape
    total = float(sal.sum()) + 1e-8
    py, px = np.unravel_index(int(np.argmax(sal)), sal.shape)
    v = ["top", "middle", "bottom"][min(2, int(py / h * 3))]
    hb = ["left", "centre", "right"][min(2, int(px / w * 3))]
    thirds = [round(float(sal[int(i * h / 3):int((i + 1) * h / 3)].sum()) / total * 100)
              for i in range(3)]
    insight = (f"Most attention lands {v}-{hb} — {thirds[0]}% of the visual pull sits in the "
               "top third. If your key message or CTA falls outside the hot zones, it risks "
               "being skipped.")
    return {
        "focal_point": f"{v}-{hb}",
        "focal_xy_pct": [round(px / w * 100), round(py / h * 100)],
        "top_third_pct": thirds[0],
        "middle_third_pct": thirds[1],
        "bottom_third_pct": thirds[2],
        "insight": insight,
    }


def analyze_visual_prominence(image_path: str) -> dict:
    """Saliency heatmap overlay (JPEG data-URI) + a plain read for an image.

    Returns ``{"found": False}`` on any failure — never raises.
    """
    try:
        with Image.open(image_path) as im:
            img = im.convert("RGB")
        if img.width > _MAX_OVERLAY_W:
            img = img.resize((_MAX_OVERLAY_W,
                              round(img.height * _MAX_OVERLAY_W / img.width)))
        sal = _saliency(img)
        overlay = Image.alpha_composite(img.convert("RGBA"), _heat_rgba(sal)).convert("RGB")
        buf = io.BytesIO()
        overlay.save(buf, format="JPEG", quality=80)
        data_uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        read = _read(sal)
        gc.collect()
        return {"found": True, "label": "Visual Prominence", "overlay": data_uri, **read}
    except Exception:                                     # noqa: BLE001
        gc.collect()
        return {"found": False}
