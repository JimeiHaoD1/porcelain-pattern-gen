import math

import cv2
import numpy as np

DEFAULT_SIZE = (1024, 768)  # (width, height)


def _canvas(size):
    w, h = size
    return np.zeros((h, w), dtype=np.uint8)


def _soften_mask(mask, sigma=8, thresh=60):
    blurred = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return (blurred > thresh).astype(np.uint8) * 255


def _apply_color(image, mask, color, alpha=1.0):
    idx = mask > 0
    if not idx.any():
        return image
    if alpha >= 1.0:
        image[idx] = color
        return image
    blended = image.astype(np.float32)
    color_arr = np.array(color, dtype=np.float32)
    blended[idx] = blended[idx] * (1.0 - alpha) + color_arr * alpha
    image[:] = blended.astype(np.uint8)
    return image


def get_border_mask(size=DEFAULT_SIZE, pos='both', h_ratio=0.12):
    mask = _canvas(size)
    h, w = mask.shape
    t = max(1, int(h * h_ratio))

    if pos in ('top', 'both', 'top_bottom'):
        mask[:t, :] = 255
    if pos in ('bottom', 'both', 'top_bottom'):
        mask[h - t :, :] = 255
    return mask


def get_central_mask(size=DEFAULT_SIZE, center_y=0.5, r_ratio=0.28):
    mask = _canvas(size)
    h, w = mask.shape
    r = max(1, int(min(h, w) * r_ratio))
    cx = w // 2
    cy = int(h * center_y)
    cy = max(r, min(h - r - 1, cy))
    cv2.circle(mask, (cx, cy), r, 255, thickness=-1)
    return mask


def get_allover_mask(size=DEFAULT_SIZE):
    w, h = size
    return np.full((h, w), 255, dtype=np.uint8)


def get_window_mask(size=DEFAULT_SIZE, n=8):
    mask = _canvas(size)
    h, w = mask.shape
    center = (w // 2, h // 2)
    rx = max(1, int(w * 0.38))
    ry = max(1, int(h * 0.38))
    inner_rx = max(1, int(rx * 0.3))
    inner_ry = max(1, int(ry * 0.3))

    sector = 360.0 / max(1, n)
    gap = sector * 0.2
    for i in range(n):
        start = i * sector + gap / 2
        end = (i + 1) * sector - gap / 2
        cv2.ellipse(mask, center, (rx, ry), 0, start, end, 255, thickness=-1)

    cv2.ellipse(mask, center, (inner_rx, inner_ry), 0, 0, 360, 0, thickness=-1)
    return mask


def get_satellite_mask(size=DEFAULT_SIZE, center_r=0.25):
    h, w = _canvas(size).shape
    cx, cy = w // 2, h // 2
    r = max(1, int(min(h, w) * center_r))

    mask_sun = _canvas(size)
    cv2.circle(mask_sun, (cx, cy), r, 255, thickness=-1)

    mask_stars = _canvas(size)
    sat_r = max(1, int(r * 0.35))
    margin = max(5, int(min(h, w) * 0.04))
    max_rx = max(1, w // 2 - sat_r - 1)
    max_ry = max(1, h // 2 - sat_r - 1)
    ring_rx = min(max_rx, max(r + sat_r + margin, int(w * 0.3)))
    ring_ry = min(max_ry, max(r + sat_r + margin, int(h * 0.25)))

    for i in range(6):
        theta = 2.0 * math.pi * i / 6.0
        x = int(cx + ring_rx * math.cos(theta))
        y = int(cy + ring_ry * math.sin(theta))
        cv2.circle(mask_stars, (x, y), sat_r, 255, thickness=-1)

    return {'center': mask_sun, 'satellites': mask_stars}


def get_narrative_masks(size=DEFAULT_SIZE):
    rng = np.random.default_rng(7)
    h, w = _canvas(size).shape

    side_left = rng.random() < 0.5
    mask_L = _canvas(size)

    points = []
    if side_left:
        points.append((0, 0))
        for y in np.linspace(0, h, 7)[1:-1]:
            x = rng.uniform(w * 0.1, w * 0.45)
            points.append((int(x), int(y)))
        points.append((0, h))
    else:
        points.append((w, 0))
        for y in np.linspace(0, h, 7)[1:-1]:
            x = rng.uniform(w * 0.55, w * 0.9)
            points.append((int(x), int(y)))
        points.append((w, h))

    cv2.fillPoly(mask_L, [np.array(points, dtype=np.int32)], 255)
    mask_L = _soften_mask(mask_L, sigma=8, thresh=50)

    mask_F = _canvas(size)
    if side_left:
        fx = int(w * 0.7)
    else:
        fx = int(w * 0.3)
    fy = int(h * 0.55)
    frx = max(1, int(w * 0.12))
    fry = max(1, int(h * 0.18))
    cv2.ellipse(mask_F, (fx, fy), (frx, fry), 0, 0, 360, 255, thickness=-1)

    mask_C = _canvas(size)
    amp = max(2, int(h * 0.03))
    thickness = max(2, int(h * 0.025))
    step = max(10, w // 40)

    for y_base in (0.22, 0.36, 0.5):
        phase = rng.uniform(0, 2 * math.pi)
        freq = rng.uniform(1.5, 2.5)
        pts = []
        for x in range(0, w, step):
            y = int(h * y_base + amp * math.sin(2 * math.pi * freq * x / w + phase))
            pts.append((x, y))
        cv2.polylines(mask_C, [np.array(pts, dtype=np.int32)], False, 255, thickness=thickness)

    mask_C = _soften_mask(mask_C, sigma=5, thresh=30)

    return {'landscape': mask_L, 'figures': mask_F, 'clouds': mask_C}


def get_scattered_mask(size, n=15, r=35, avoid_mask=None):
    mask = _canvas(size)
    h, w = mask.shape
    rng = np.random.default_rng()

    forbidden_zone = np.zeros((h, w), dtype=np.uint8)
    if avoid_mask is not None:
        avoid = (avoid_mask > 0).astype(np.uint8)
        dilate_r = max(1, int(r + 20))
        k = 2 * dilate_r + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        forbidden_zone = cv2.dilate(avoid, kernel, iterations=1)

    centers = []
    min_dist = max(1, int(2 * r))
    max_attempts = max(200, n * 200)
    attempts = 0

    while len(centers) < n and attempts < max_attempts:
        attempts += 1
        x = int(rng.integers(r, w - r))
        y = int(rng.integers(r, h - r))

        if forbidden_zone[y, x] > 0:
            continue
        if any((x - cx) ** 2 + (y - cy) ** 2 < min_dist ** 2 for cx, cy in centers):
            continue
        centers.append((x, y))

    for x, y in centers:
        cv2.circle(mask, (x, y), int(r), 255, thickness=-1)
    return mask


if __name__ == '__main__':
    import matplotlib.pyplot as plt

    size = DEFAULT_SIZE
    h, w = _canvas(size).shape

    # Elegant Style
    border = get_border_mask(size, pos='both', h_ratio=0.12)
    center = get_central_mask(size, center_y=0.5, r_ratio=0.28)
    vip = ((border > 0) | (center > 0)).astype(np.uint8) * 255
    scattered = get_scattered_mask(size, n=15, r=30, avoid_mask=vip)

    elegant = np.full((h, w, 3), 255, dtype=np.uint8)
    _apply_color(elegant, border, (220, 60, 60))
    _apply_color(elegant, center, (60, 90, 220))
    _apply_color(elegant, scattered, (60, 170, 80))

    # Satellite Style
    sat = get_satellite_mask(size, center_r=0.25)
    base = get_allover_mask(size)
    sat_block = ((sat['center'] > 0) | (sat['satellites'] > 0)).astype(np.uint8) * 255
    sat_base = cv2.bitwise_and(base, cv2.bitwise_not(sat_block))

    satellite = np.full((h, w, 3), 255, dtype=np.uint8)
    _apply_color(satellite, sat_base, (200, 200, 200))
    _apply_color(satellite, sat['satellites'], (130, 180, 230))
    _apply_color(satellite, sat['center'], (30, 60, 140))

    # Narrative Style
    nar = get_narrative_masks(size)
    narrative = np.full((h, w, 3), 255, dtype=np.uint8)
    _apply_color(narrative, nar['landscape'], (80, 160, 90))
    _apply_color(narrative, nar['figures'], (200, 60, 60))
    _apply_color(narrative, nar['clouds'], (255, 255, 255), alpha=0.5)

    # Windowed Style
    windows = get_window_mask(size, n=8)
    borders = get_border_mask(size, pos='both', h_ratio=0.12)
    base_full = get_allover_mask(size)
    window_block = ((windows > 0) | (borders > 0)).astype(np.uint8) * 255
    window_base = cv2.bitwise_and(base_full, cv2.bitwise_not(window_block))

    windowed = np.full((h, w, 3), 255, dtype=np.uint8)
    _apply_color(windowed, window_base, (200, 200, 200))
    _apply_color(windowed, windows, (80, 200, 200))
    _apply_color(windowed, borders, (220, 60, 60))

    fig, axes = plt.subplots(2, 2, figsize=(8, 6))
    axes[0, 0].imshow(elegant)
    axes[0, 0].set_title('Elegant Style')
    axes[0, 0].axis('off')

    axes[0, 1].imshow(satellite)
    axes[0, 1].set_title('Satellite Style')
    axes[0, 1].axis('off')

    axes[1, 0].imshow(narrative)
    axes[1, 0].set_title('Narrative Style')
    axes[1, 0].axis('off')

    axes[1, 1].imshow(windowed)
    axes[1, 1].set_title('Windowed Style')
    axes[1, 1].axis('off')

    fig.tight_layout()
    fig.savefig('layout_showcase.png', dpi=150)
    plt.close(fig)
