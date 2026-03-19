# -*- coding: utf-8 -*-
"""程序化底纹生成器 - wave / scroll / cloud

设计原则：
  wave  : 紧密叠浪，行间距极小，每行带卷曲峰头，整体无空白
  scroll: 缠枝纹，茎蔓稀疏留白，波峰处有卷头+叶片，不满铺
  cloud : 如意云头，错位排列，云朵之间有自然间距

画布形状感知：
  generate() params 可传 shape='disc'|'rect'
  disc  : 极坐标辐射方式（同心/螺旋）
  rect  : 笛卡尔坐标行扫描方式（水平条带）
"""
from __future__ import annotations

import math
import numpy as np
import cv2


# ─────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────

def _draw_wave_row(
    canvas: np.ndarray,
    y_center: float,
    w: int,
    amp: float,
    freq: float,
    phase: float,
    thickness: int,
    curl_r: int,
    curl_spacing: int,
) -> None:
    pts = []
    for x in range(w):
        wy = int(y_center + amp * math.sin(2 * math.pi * freq * x / w + phase))
        pts.append((x, wy))
    cv2.polylines(canvas, [np.array(pts, dtype=np.int32)], False, 255, thickness, cv2.LINE_AA)
    for cx in range(curl_r * 2, w - curl_r, curl_spacing):
        sin_val = math.sin(2 * math.pi * freq * cx / w + phase)
        if sin_val > 0.6:
            wy = int(y_center + amp * sin_val)
            cv2.ellipse(canvas, (cx, wy - curl_r // 2),
                        (max(1, curl_r), max(1, curl_r // 2)),
                        0, 180, 360, 255, max(1, thickness - 1), cv2.LINE_AA)


# ─────────────────────────────────────────────
# WaveGenerator  海水波浪纹
# ─────────────────────────────────────────────

class WaveGenerator:
    """海水波浪：紧密叠浪（row_overlap 0.88），每行带卷曲峰头。
    disc 模式：同心圆波纹，从圆心向外扩散。
    """

    def generate(self, w: int, h: int, params: dict) -> np.ndarray:
        if str(params.get("shape", "rect")).lower() == "disc":
            return self._disc(w, h, params)
        return self._rect(w, h, params)

    def _rect(self, w: int, h: int, params: dict) -> np.ndarray:
        density         = int(params.get("density", 22))
        thickness_ratio = float(params.get("line_thickness_ratio", 0.005))
        curl_size       = float(params.get("curl_size", 0.30))
        row_overlap     = float(params.get("row_overlap", 0.88))

        canvas    = np.zeros((h, w), dtype=np.uint8)
        thickness = max(1, int(min(w, h) * thickness_ratio))
        row_h     = max(6, h // max(1, density))
        step      = max(1, int(row_h * (1.0 - row_overlap)))
        curl_r    = max(2, int(row_h * curl_size))
        curl_sp   = max(curl_r * 3, w // max(1, density))

        y, idx = 0.0, 0
        while y < h + row_h:
            freq  = 2.5 + (idx % 3) * 0.4
            amp   = row_h * 0.28
            phase = (idx % 2) * math.pi * 0.5
            _draw_wave_row(canvas, y, w, amp, freq, phase, thickness, curl_r, curl_sp)
            y += step
            idx += 1
        return canvas

    def _disc(self, w: int, h: int, params: dict) -> np.ndarray:
        """同心圆波纹"""
        density         = int(params.get("density", 20))
        thickness_ratio = float(params.get("line_thickness_ratio", 0.005))
        curl_size       = float(params.get("curl_size", 0.25))

        canvas    = np.zeros((h, w), dtype=np.uint8)
        thickness = max(1, int(min(w, h) * thickness_ratio))
        cx, cy    = w // 2, h // 2
        max_r     = int(math.hypot(w, h) * 0.6)
        step      = max(3, max_r // max(1, density))
        curl_r    = max(2, int(step * curl_size))

        for ring in range(1, density + 3):
            r = ring * step
            if r > max_r:
                break
            n_pts      = max(64, r * 3)
            wave_amp   = step * 0.18
            wave_freq  = 6 + (ring % 3) * 2
            pts = []
            for i in range(n_pts + 1):
                theta = 2 * math.pi * i / n_pts
                rr    = r + wave_amp * math.sin(wave_freq * theta)
                pts.append((int(cx + rr * math.cos(theta)),
                             int(cy + rr * math.sin(theta))))
            cv2.polylines(canvas, [np.array(pts, dtype=np.int32)], False,
                          255, thickness, cv2.LINE_AA)
            # 波峰处画卷头
            n_curls = max(4, ring * 2)
            for k in range(n_curls):
                theta = 2 * math.pi * k / n_curls
                sv    = math.sin(wave_freq * theta)
                if sv > 0.55:
                    rr  = r + wave_amp * sv
                    px  = int(cx + rr * math.cos(theta))
                    py  = int(cy + rr * math.sin(theta))
                    if 0 <= px < w and 0 <= py < h:
                        cv2.circle(canvas, (px, py), curl_r,
                                   255, max(1, thickness - 1), cv2.LINE_AA)
        return canvas


# ─────────────────────────────────────────────
# ScrollGenerator  缠枝纹
# ─────────────────────────────────────────────

class ScrollGenerator:
    """缠枝纹：茎蔓行少（density=5）有留白，波峰处卷头+双叶。
    disc 模式：螺旋茎蔓从圆心旋出，沿途带卷头叶片。
    """

    def generate(self, w: int, h: int, params: dict) -> np.ndarray:
        if str(params.get("shape", "rect")).lower() == "disc":
            return self._disc(w, h, params)
        return self._rect(w, h, params)

    def _rect(self, w: int, h: int, params: dict) -> np.ndarray:
        density         = int(params.get("density", 5))
        thickness_ratio = float(params.get("line_thickness_ratio", 0.006))
        curl_size       = float(params.get("curl_size", 0.35))
        row_overlap     = float(params.get("row_overlap", 0.50))  # 稀疏留白

        canvas    = np.zeros((h, w), dtype=np.uint8)
        thickness = max(1, int(min(w, h) * thickness_ratio))
        row_h     = max(24, h // max(1, density))
        step      = max(1, int(row_h * (1.0 - row_overlap)))
        curl_r    = max(8, int(row_h * curl_size))
        spacing   = max(curl_r * 4, w // max(1, density * 2))

        y, row_idx = float(curl_r), 0
        while y < h - curl_r:
            phase = (row_idx % 2) * math.pi
            freq, amp = 1.5, row_h * 0.22
            # 主茎线
            pts = []
            for x in range(w):
                wy = int(y + amp * math.sin(2 * math.pi * freq * x / w + phase))
                pts.append((x, wy))
            cv2.polylines(canvas, [np.array(pts, dtype=np.int32)],
                          False, 255, thickness, cv2.LINE_AA)
            # 波峰 → 卷头 + 双叶
            for cx in range(spacing // 2, w - curl_r, spacing):
                sv = math.sin(2 * math.pi * freq * cx / w + phase)
                wy = int(y + amp * sv)
                if sv > 0.4:
                    cv2.circle(canvas, (cx, wy - curl_r),
                               curl_r, 255, thickness, cv2.LINE_AA)
                    lrx = max(3, curl_r // 2)
                    lry = max(2, curl_r // 3)
                    cv2.ellipse(canvas,
                                (cx - int(curl_r * 1.4), wy - curl_r),
                                (lrx, lry), -30, 0, 360,
                                255, thickness, cv2.LINE_AA)
                    cv2.ellipse(canvas,
                                (cx + int(curl_r * 1.4), wy - curl_r),
                                (lrx, lry), 30, 0, 360,
                                255, thickness, cv2.LINE_AA)
                elif sv < -0.4:
                    cv2.circle(canvas, (cx, wy + curl_r // 2),
                               curl_r // 2, 255,
                               max(1, thickness - 1), cv2.LINE_AA)
            y += step
            row_idx += 1
        return canvas

    def _disc(self, w: int, h: int, params: dict) -> np.ndarray:
        """圆盘形缠枝：多条 Archimedean 螺旋，沿途插卷头叶片"""
        density         = int(params.get("density", 4))
        thickness_ratio = float(params.get("line_thickness_ratio", 0.006))
        curl_size       = float(params.get("curl_size", 0.28))

        canvas    = np.zeros((h, w), dtype=np.uint8)
        thickness = max(1, int(min(w, h) * thickness_ratio))
        cx, cy    = w // 2, h // 2
        max_r     = min(w, h) * 0.48
        curl_r    = max(6, int(max_r * curl_size / density))
        n_arms    = max(2, density)  # 螺旋臂数

        for arm in range(n_arms):
            start_angle = arm * (2 * math.pi / n_arms)
            pts = []
            n_pts = 300
            for i in range(n_pts):
                t     = i / n_pts
                theta = start_angle + t * 3 * math.pi  # 1.5圈
                r     = t * max_r
                # 叠加正弦波使茎蔓弯曲
                r += max_r * 0.04 * math.sin(8 * theta)
                x = int(cx + r * math.cos(theta))
                y = int(cy + r * math.sin(theta))
                pts.append((x, y))
            arr = np.array(pts, dtype=np.int32)
            cv2.polylines(canvas, [arr], False, 255, thickness, cv2.LINE_AA)
            # 每隔若干点画卷头
            interval = max(20, n_pts // (density * 3))
            for i in range(interval, n_pts - interval, interval):
                t     = i / n_pts
                theta = start_angle + t * 3 * math.pi
                r     = t * max_r
                r    += max_r * 0.04 * math.sin(8 * theta)
                px = int(cx + r * math.cos(theta))
                py = int(cy + r * math.sin(theta))
                if 0 <= px < w and 0 <= py < h:
                    cv2.circle(canvas, (px, py), curl_r,
                               255, thickness, cv2.LINE_AA)
                    # 叶片（垂直于螺旋方向）
                    leaf_angle = math.degrees(theta) + 90
                    lrx = max(2, curl_r // 2)
                    lry = max(2, curl_r // 3)
                    off_x = int(curl_r * 1.3 * math.cos(theta + math.pi / 2))
                    off_y = int(curl_r * 1.3 * math.sin(theta + math.pi / 2))
                    cv2.ellipse(canvas, (px + off_x, py + off_y),
                                (lrx, lry), leaf_angle, 0, 360,
                                255, thickness, cv2.LINE_AA)
                    cv2.ellipse(canvas, (px - off_x, py - off_y),
                                (lrx, lry), leaf_angle, 0, 360,
                                255, thickness, cv2.LINE_AA)
        return canvas


# ─────────────────────────────────────────────
# CloudGenerator  祥云纹
# ─────────────────────────────────────────────

class CloudGenerator:
    """祥云：如意云头（三叠椭圆），错位排列，云朵间留自然间距。
    disc 模式：沿同心圆环排布云头。
    """

    def generate(self, w: int, h: int, params: dict) -> np.ndarray:
        if str(params.get("shape", "rect")).lower() == "disc":
            return self._disc(w, h, params)
        return self._rect(w, h, params)

    def _draw_cloud_head(self, canvas, cx, cy, rx, ry, thickness):
        """一朵如意云头：主体椭圆 + 左右上角各一小椭圆"""
        cv2.ellipse(canvas, (cx, cy), (max(1, rx), max(1, ry)),
                    0, 0, 360, 255, thickness, cv2.LINE_AA)
        srx, sry = max(1, rx // 2), max(1, ry // 2)
        cv2.ellipse(canvas, (cx - rx // 2, cy - ry // 2),
                    (srx, sry), 0, 0, 360, 255, thickness, cv2.LINE_AA)
        cv2.ellipse(canvas, (cx + rx // 2, cy - ry // 2),
                    (srx, sry), 0, 0, 360, 255, thickness, cv2.LINE_AA)
        cv2.line(canvas, (cx - rx, cy), (cx + rx, cy),
                 255, max(1, thickness - 1), cv2.LINE_AA)

    def _rect(self, w: int, h: int, params: dict) -> np.ndarray:
        density         = int(params.get("density", 5))
        thickness_ratio = float(params.get("line_thickness_ratio", 0.005))

        canvas    = np.zeros((h, w), dtype=np.uint8)
        thickness = max(1, int(min(w, h) * thickness_ratio))
        cols      = max(2, density)
        rows      = max(2, int(density * h / max(1, w)))
        cell_w    = w // cols
        cell_h    = h // rows
        rx        = max(4, cell_w // 3)
        ry        = max(3, cell_h // 3)

        for row in range(rows + 1):
            for col in range(cols + 1):
                cx = int((col + 0.5) * cell_w)
                cy = int((row + 0.5) * cell_h)
                if row % 2 == 1:
                    cx += cell_w // 2
                self._draw_cloud_head(canvas, cx, cy, rx, ry, thickness)
        return canvas

    def _disc(self, w: int, h: int, params: dict) -> np.ndarray:
        """圆盘形：沿同心圆环均匀分布云头"""
        density         = int(params.get("density", 5))
        thickness_ratio = float(params.get("line_thickness_ratio", 0.005))

        canvas    = np.zeros((h, w), dtype=np.uint8)
        thickness = max(1, int(min(w, h) * thickness_ratio))
        cx, cy    = w // 2, h // 2
        max_r     = min(w, h) * 0.46
        n_rings   = max(2, density // 2)

        for ring in range(1, n_rings + 1):
            r       = ring * max_r / n_rings
            rx      = max(4, int(r * 0.12))
            ry      = max(3, int(r * 0.08))
            n_heads = max(4, ring * 4)
            for k in range(n_heads):
                theta = 2 * math.pi * k / n_heads
                px    = int(cx + r * math.cos(theta))
                py    = int(cy + r * math.sin(theta))
                if 0 <= px < w and 0 <= py < h:
                    self._draw_cloud_head(canvas, px, py, rx, ry, thickness)
        return canvas


# ─────────────────────────────────────────────
# NullGenerator
# ─────────────────────────────────────────────
# SpiralVineGenerator - S形/螺旋骨架线，用于缠枝纹引导
# ─────────────────────────────────────────────

class SpiralVineGenerator:
    """生成程序化S形贝塞尔曲线骨架，作为缠枝纹ControlNet引导信号。

    原理：在底纹区域内画若干条S形曲线（正弦骨架线），
    轻度模糊后以低权重送入ControlNet，让SDXL沿骨架幻觉卷草细节。
    不追求精确的纹样，只提供走势方向场。
    """

    def generate(self, w: int, h: int, params: dict) -> np.ndarray:
        canvas = np.zeros((h, w), dtype=np.uint8)
        n_waves     = int(params.get("n_waves", 3))       # S形曲线条数
        amplitude   = float(params.get("amplitude", 0.18)) # 振幅比例（相对画布高）
        thickness   = int(params.get("thickness", 2))
        phase_shift = float(params.get("phase_shift", math.pi))  # 相邻线相位差

        amp_px = max(8, int(h * amplitude))
        row_gap = max(16, h // max(1, n_waves))

        for i in range(n_waves):
            y_center = int((i + 0.5) * row_gap)
            if y_center >= h:
                break
            phase = i * phase_shift
            pts = []
            for x in range(0, w, 2):
                # 正弦骨架线，形成S形走势
                y = int(y_center + amp_px * math.sin(2 * math.pi * x / w + phase))
                y = max(0, min(h - 1, y))
                pts.append((x, y))
            if len(pts) >= 2:
                cv2.polylines(
                    canvas,
                    [np.array(pts, dtype=np.int32)],
                    False, 200, thickness, cv2.LINE_AA
                )
            # 在波峰/波谷处加小圆圈，模拟卷头位置提示
            for x in range(w // 6, w, w // 4):
                y = int(y_center + amp_px * math.sin(2 * math.pi * x / w + phase))
                y = max(4, min(h - 5, y))
                curl_r = max(3, int(min(w, h) * 0.018))
                cv2.circle(canvas, (x, y), curl_r, 180, max(1, thickness - 1), cv2.LINE_AA)

        # 轻度模糊：软化骨架，让边界柔和，但保留走势
        k = 9
        canvas = cv2.GaussianBlur(canvas, (k, k), sigmaX=3, sigmaY=3)
        return canvas


# ─────────────────────────────────────────────

class NullGenerator:
    """找不到生成器时的降级：返回全空画布"""
    def generate(self, w: int, h: int, params: dict) -> np.ndarray:
        return np.zeros((h, w), dtype=np.uint8)


_REGISTRY: dict[str, object] = {
    "wave":         WaveGenerator(),
    "scroll":       ScrollGenerator(),
    "cloud":        CloudGenerator(),
    "spiral_vine":  SpiralVineGenerator(),
}


def get_pattern_generator(name: str | None) -> object:
    """按名称获取生成器实例，未知名称返回 NullGenerator"""
    if not name:
        return NullGenerator()
    return _REGISTRY.get(str(name).lower(), NullGenerator())  