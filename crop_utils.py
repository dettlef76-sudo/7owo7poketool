"""
crop_utils.py
--------------
Automatischer Zuschnitt von Karte/Slab.

Neuer Hauptansatz "Hintergrund lernen": Die Farbe des Hintergrunds wird
aus den Bildraendern gelernt (dort ist praktisch nie die Karte). Alles,
was deutlich von dieser Farbe abweicht, gilt als Vordergrund - davon
wird die Bounding-Box genommen. Vorteil: schneidet nie IN den Slab
hinein (Label-Ausbuchtung, transparente Ecken etc. bleiben drin), weil
einfach alles Nicht-Hintergrund eingeschlossen wird.

Fallback: bisherige Kontur-Methode, falls der Rand-Ansatz nichts
Plausibles findet.

Voraussetzung bleibt: halbwegs einfarbiger Hintergrund. Bei wildem
Hintergrund hilft die manuelle Nachjustierung in der App.
"""

import cv2
import numpy as np


# ---------- Hauptansatz: Hintergrundfarbe von den Raendern lernen ----------

def _crop_by_background_color(image_bgr: np.ndarray, padding_px: int):
    h, w = image_bgr.shape[:2]
    border = max(4, int(min(h, w) * 0.02))

    # Randpixel einsammeln (oben, unten, links, rechts)
    strips = [
        image_bgr[:border, :].reshape(-1, 3),
        image_bgr[-border:, :].reshape(-1, 3),
        image_bgr[:, :border].reshape(-1, 3),
        image_bgr[:, -border:].reshape(-1, 3),
    ]
    border_pixels = np.vstack(strips).astype(np.float32)
    bg_color = np.median(border_pixels, axis=0)

    # Wie einheitlich ist der Rand? Bei buntem Hintergrund -> Ansatz ablehnen
    spread = np.mean(np.std(border_pixels, axis=0))
    if spread > 45:
        return None

    # Abstand jedes Pixels zur Hintergrundfarbe
    dist = np.linalg.norm(image_bgr.astype(np.float32) - bg_color, axis=2)
    mask = (dist > 42).astype(np.uint8) * 255

    # Rauschen entfernen, Luecken schliessen
    kernel = np.ones((9, 9), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None

    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()

    area_ratio = ((x1 - x0) * (y1 - y0)) / float(w * h)
    if not (0.08 <= area_ratio <= 0.98):
        return None

    x0 = max(0, x0 - padding_px)
    y0 = max(0, y0 - padding_px)
    x1 = min(w, x1 + padding_px)
    y1 = min(h, y1 + padding_px)
    return image_bgr[y0:y1, x0:x1]


# ---------- Fallback: Kontur-Methode ----------

def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _rectangularity_score(contour, img_area):
    area = cv2.contourArea(contour)
    if area < 0.1 * img_area or area > 0.97 * img_area:
        return -1
    rect = cv2.minAreaRect(contour)
    (w, h) = rect[1]
    if w == 0 or h == 0:
        return -1
    fill_ratio = area / (w * h)
    if fill_ratio < 0.7:
        return -1
    return area / img_area  # groesste plausible Kontur gewinnt (= Slab)


def _crop_by_contour(image_bgr: np.ndarray, padding_px: int):
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    img_area = h * w
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, otsu_inv = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    edges = cv2.Canny(blur, 30, 120)
    edges = cv2.dilate(edges, np.ones((7, 7), np.uint8), iterations=2)

    best, best_score = None, -1
    for mask in (otsu, otsu_inv, edges):
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            score = _rectangularity_score(c, img_area)
            if score > best_score:
                best, best_score = c, score

    if best is None:
        return None

    x, y, bw, bh = cv2.boundingRect(best)
    x0 = max(0, x - padding_px)
    y0 = max(0, y - padding_px)
    x1 = min(w, x + bw + padding_px)
    y1 = min(h, y + bh + padding_px)
    return image_bgr[y0:y1, x0:x1]


def crop_card_or_slab(image_bgr: np.ndarray, padding_px: int = 10) -> np.ndarray:
    """Zuschnitt: erst Hintergrundfarben-Ansatz, dann Kontur-Fallback,
    sonst Original unveraendert zurueck."""
    result = _crop_by_background_color(image_bgr, padding_px)
    if result is not None:
        return result
    result = _crop_by_contour(image_bgr, padding_px)
    if result is not None:
        return result
    return image_bgr
