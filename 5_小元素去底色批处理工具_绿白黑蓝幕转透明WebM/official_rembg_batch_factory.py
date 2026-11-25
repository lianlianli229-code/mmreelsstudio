#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reels 工作室 · 官方工业级小元素抠像与封装批处理工厂 (`official_rembg_batch_factory.py`)

完整集成官方 `vn-subtitle-element-studio` (`fast_element_factory.py`) 四大核心工序：
1. `rembg (isnet-general-use)` 深度神经网络主体分割 + 四色幕（白幕/绿幕/黑幕/蓝幕）专属抠像器
2. `remove_small_components` 8-连通域孤立悬浮黑灰噪点清洗 + `unpremul_and_bright_lift` 直通道反预乘亮底提纯
3. 全帧并集包围盒 (`All-Frame Union BBox`) + `512×512` 画布内 `[46, 466]` (`420×420`) 安全盒居中封装 (`enforce_safe_bounds`)
4. `dilate_rgb_4px` (`cv2.distanceTransformWithLabels` 4.5px 前景 RGB 边缘扩散，远端归零，彻底消灭 VP9 yuva420p 亮底黑灰边与白底框)
5. 支持视频 (`.mp4`, `.mov`, `.webm`, `.mkv`, `.avi` -> 输出 `512×512` VP9 Alpha `.webm` + 亮底预览图 `.jpg`)
   与图片 (`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp` -> 输出 `512×512` 真透明 `.png`)，100% 保留原素材。
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CENTRAL_MODELS_HOME = Path(r"C:\Users\Clara\reels-studio\资源管理中心\5_小元素去底色批处理工具_绿白黑蓝幕转透明WebM\models")
MODELS_HOME = CENTRAL_MODELS_HOME if CENTRAL_MODELS_HOME.exists() else (HERE / "models")
MODELS_HOME.mkdir(parents=True, exist_ok=True)
os.environ["U2NET_HOME"] = str(MODELS_HOME)
os.environ["REMBG_HOME"] = str(MODELS_HOME)

import cv2
import numpy as np
from PIL import Image

SAFE_MIN = 46
SAFE_MAX = 466  # 420x420 safe box inside 512x512
CANVAS_SIZE = 512
SAFE_BOX_SIZE = SAFE_MAX - SAFE_MIN  # 420
FPS_OUT = 24

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".flv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

_REMBG_SESS = None
_KERN_3 = np.ones((3, 3), np.uint8)
_KERN_5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
_KERN_7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
_KERN_9 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
_KERN_11 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
_YY512, _XX512 = np.mgrid[0:512, 0:512].astype(np.float32)

DEFAULT_STAGE_PHOTO = Path(r"C:\Users\Clara\reels-studio\public\stage-photo.jpg")


def find_working_ffmpeg() -> str:
    candidates = [
        os.environ.get("FFMPEG_BIN", ""),
        r"C:\Users\Clara\AppData\Local\Programs\videokit\resources\vendor\ffmpeg\bin\ffmpeg.exe",
        shutil.which("ffmpeg") or "",
        r"C:\Users\Clara\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\Softdeluxe\Free Download Manager\ffmpeg.exe",
    ]
    for bin_path in candidates:
        if not bin_path:
            continue
        try:
            cp = subprocess.run([bin_path, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=5)
            if cp.returncode == 0 and "libvpx-vp9" in (cp.stdout or ""):
                return bin_path
        except Exception:
            pass
    for bin_path in candidates:
        if not bin_path:
            continue
        try:
            cp = subprocess.run([bin_path, "-version"], capture_output=True, text=True, timeout=5)
            if cp.returncode == 0:
                return bin_path
        except Exception:
            pass
    raise RuntimeError("未找到可用的 ffmpeg.exe，请确认已安装 FFmpeg 或 VideoKit。")


def get_rembg_session():
    global _REMBG_SESS
    if _REMBG_SESS is None:
        from rembg import new_session
        _REMBG_SESS = new_session("isnet-general-use")
    return _REMBG_SESS


# ============================================================================
# 官方四大后期核心算子 (1:1 源自 fast_element_factory.py)
# ============================================================================

def dilate_rgb_4px(rgba: np.ndarray, radius: float = 4.5) -> np.ndarray:
    """Fill alpha <= 5 pixels within ~4.5px of alpha > 20 with nearest foreground RGB (alpha stays 0); far background RGB -> 0."""
    out = rgba.copy()
    a = out[:, :, 3]
    fg = a > 20
    if not np.any(fg):
        out[:, :, :3] = 0
        return out
    inv = (~fg).astype(np.uint8)
    dist, labels = cv2.distanceTransformWithLabels(inv, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys_fg, xs_fg = np.where(fg)
    lut_y = np.zeros(int(labels.max()) + 1, dtype=np.int32)
    lut_x = np.zeros(int(labels.max()) + 1, dtype=np.int32)
    fg_lbl = labels[ys_fg, xs_fg]
    lut_y[fg_lbl] = ys_fg
    lut_x[fg_lbl] = xs_fg

    fill_mask = (a <= 5) & (dist > 0.0) & (dist <= radius)
    fy_idx, fx_idx = np.where(fill_mask)
    fl = labels[fy_idx, fx_idx]
    out[fy_idx, fx_idx, :3] = out[lut_y[fl], lut_x[fl], :3]
    far = (a <= 5) & (dist > radius)
    out[far, :3] = 0
    return out


def enforce_safe_bounds(rgba: np.ndarray) -> np.ndarray:
    """强制锁定 512x512 画布内的 [46, 466] (420x420) 安全盒，外围 46px 净空区强制归零。"""
    out = rgba.copy()
    mask_out = (_XX512 < SAFE_MIN) | (_XX512 >= SAFE_MAX) | (_YY512 < SAFE_MIN) | (_YY512 >= SAFE_MAX)
    out[mask_out] = 0
    return out


def remove_small_components(alpha_f: np.ndarray, min_area: int = 40, thresh: float = 0.06) -> np.ndarray:
    """8-连通域分析清除孤立悬浮噪点与灰黑碎渣。"""
    vis = (alpha_f > thresh).astype(np.uint8)
    nc, lbl, st, _ = cv2.connectedComponentsWithStats(vis, connectivity=8)
    if nc <= 1:
        return alpha_f
    keep = np.zeros_like(vis, dtype=bool)
    for k in range(1, nc):
        if int(st[k, cv2.CC_STAT_AREA]) >= min_area:
            keep |= lbl == k
    keep_dil = cv2.dilate(keep.astype(np.uint8), _KERN_3) > 0
    return np.where(keep_dil, alpha_f, 0.0)


def unpremul_and_bright_lift(
    rgba: np.ndarray,
    lift_white: bool = False,
    lift_warm_fire: bool = False,
    despill_green: bool = False,
    despill_blue: bool = False,
    bg_rgb: tuple[float, float, float] | None = None,
) -> np.ndarray:
    """直通道反预乘亮底提纯：剥离半透明边缘混入的背景色，消除白边/黑边/绿溢/蓝溢，并将透明区 RGB 强制归 0。"""
    a = rgba[:, :, 3].astype(np.float32) / 255.0
    arr = rgba[:, :, :3].astype(np.float32)
    semi = (a > 0.02) & (a < 0.96)

    if bg_rgb is not None:
        # 对带背景色的半透明边缘做精确背景色反混合: C_fg = (C - (1 - a) * C_bg) / max(a, 0.28)
        bg_arr = np.array(bg_rgb, dtype=np.float32).reshape((1, 1, 3))
        safe_a = np.maximum(a[:, :, None], 0.28)
        unp = np.clip((arr - (1.0 - a[:, :, None]) * bg_arr) / safe_a, 0.0, 255.0)
    else:
        unp = np.clip(arr / np.maximum(a[:, :, None], 0.30), 0.0, 255.0)

    rgb = np.where(semi[:, :, None], unp, arr)

    if despill_green:
        rb_max = np.maximum(rgb[:, :, 0], rgb[:, :, 2])
        g_exc = rgb[:, :, 1] - rb_max
        spill = (a > 0.02) & ((g_exc > 3.0) | (semi & (rgb[:, :, 1] > rb_max)))
        rgb[:, :, 1] = np.where(spill, np.minimum(rgb[:, :, 1], rb_max), rgb[:, :, 1])

    if despill_blue:
        rg_max = np.maximum(rgb[:, :, 0], rgb[:, :, 1])
        b_exc = rgb[:, :, 2] - rg_max
        spill = (a > 0.02) & ((b_exc > 3.0) | (semi & (rgb[:, :, 2] > rg_max)))
        rgb[:, :, 2] = np.where(spill, np.minimum(rgb[:, :, 2], rg_max), rgb[:, :, 2])

    if lift_white:
        r2, g2, b2 = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        mx2 = np.max(rgb, axis=2)
        white_tip = (a > 0.02) & (a < 0.94) & (np.abs(r2 - b2) < 38.0) & (mx2 < 220.0) & (mx2 > 50.0)
        t_alpha = np.clip((0.94 - a) / 0.65, 0.0, 1.0)
        t_luma = np.clip((224.0 - mx2) / 145.0, 0.0, 1.0)
        t = np.where(white_tip, 0.72 * t_alpha * t_luma, 0.0)
        rgb[:, :, 0] = rgb[:, :, 0] * (1.0 - t) + 255.0 * t
        rgb[:, :, 1] = rgb[:, :, 1] * (1.0 - t) + 252.0 * t
        rgb[:, :, 2] = rgb[:, :, 2] * (1.0 - t) + 246.0 * t

    if lift_warm_fire:
        r2, _, b2 = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        mx2 = np.max(rgb, axis=2)
        warm_edge = (a > 0.02) & (a < 0.90) & (r2 >= b2 + 16.0)
        if lift_white:
            warm_edge = warm_edge & (np.abs(r2 - b2) >= 38.0)
        t_f = np.where(warm_edge, np.clip((0.90 - a) / 0.70, 0.0, 1.0), 0.0)
        r_new = np.where(warm_edge, rgb[:, :, 0] * (1.0 - 0.80 * t_f) + 255.0 * (0.80 * t_f), rgb[:, :, 0])
        g_target = np.minimum(r_new * 0.58, np.maximum(rgb[:, :, 1], 115.0))
        g_new = np.where(warm_edge, rgb[:, :, 1] * (1.0 - 0.70 * t_f) + g_target * (0.70 * t_f), rgb[:, :, 1])
        rgb[:, :, 0] = r_new
        rgb[:, :, 1] = g_new
        core = mx2 > 225.0
        rgb = np.where(core[:, :, None] & (~semi[:, :, None]), arr, rgb)

    out = np.zeros_like(rgba)
    vis = a > 0.015
    out[:, :, :3] = np.where(vis[:, :, None], np.clip(rgb, 0.0, 255.0), 0.0).astype(np.uint8)
    out[:, :, 3] = np.where(vis, np.clip(a * 255.0, 0.0, 255.0), 0.0).astype(np.uint8)
    return out


# ============================================================================
# 四色幕智能识别与官方 rembg (isnet-general-use) 融合抠像器
# ============================================================================

def detect_corner_background(rgb: np.ndarray, forced_mode: str = "auto") -> dict:
    h, w = rgb.shape[:2]
    p = max(4, min(24, h // 20, w // 20))
    corners = np.concatenate([
        rgb[:p, :p].reshape(-1, 3),
        rgb[:p, -p:].reshape(-1, 3),
        rgb[-p:, :p].reshape(-1, 3),
        rgb[-p:, -p:].reshape(-1, 3),
    ], axis=0).astype(np.float32)
    c_med = np.median(corners, axis=0)
    c_std = float(np.mean(np.std(corners, axis=0)))
    r, g, b = float(c_med[0]), float(c_med[1]), float(c_med[2])
    g_exc = g - max(r, b)
    b_exc = b - max(r, g)
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    sat = 0.0 if max_c == 0 else (max_c - min_c) / max_c

    if forced_mode and forced_mode != "auto":
        bg_type = forced_mode
    elif g_exc > 32.0 and g > 80.0:
        bg_type = "green"
    elif b_exc > 30.0 and b > 80.0:
        bg_type = "blue"
    elif luma >= 145.0 and sat < 0.28:
        bg_type = "white"
    elif luma <= 75.0:
        bg_type = "black"
    elif g >= r and g >= b and sat >= 0.22:
        bg_type = "green"
    elif b >= r and b >= g and sat >= 0.22:
        bg_type = "blue"
    elif luma >= 128.0:
        bg_type = "white"
    else:
        bg_type = "black"

    hex_str = f"#{int(round(r)):02X}{int(round(g)):02X}{int(round(b)):02X}"
    label_map = {"white": "白幕", "green": "绿幕", "black": "黑幕", "blue": "蓝幕"}
    return {
        "type": bg_type,
        "c_med": c_med,
        "c_std": c_std,
        "rgb_tuple": (r, g, b),
        "hex": hex_str,
        "label": f"{label_map.get(bg_type, bg_type)} ({hex_str})",
    }


def predict_rembg_alpha(rgb: np.ndarray) -> np.ndarray:
    """运行官方 rembg (isnet-general-use) 获取 [0.0, 1.0] 主体显著性 Alpha 掩码。"""
    from rembg import remove
    seg = np.array(remove(Image.fromarray(rgb), session=get_rembg_session()))
    return seg[:, :, 3].astype(np.float32) / 255.0


def compute_border_floodfill_bg_mask(rgb: np.ndarray, bg_info: dict, ai_raw: np.ndarray) -> np.ndarray:
    """
    从画布四条外边界（及面积 ≥36 像素的纯背景色内部镂空洞）做连通域泛洪，返回 `is_flooded_bg` 布尔掩码。
    凡是被 rembg (isnet-general-use) 高置信度判定为主体内部且带有纹理/色彩梯度（非纯平背景色洞）的区域，禁止泛洪穿过！
    """
    h, w = rgb.shape[:2]
    bg_type = bg_info["type"]
    c_med = bg_info["c_med"]
    arr = rgb.astype(np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mx = np.max(arr, axis=2)
    mn = np.min(arr, axis=2)
    chroma = mx - mn
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    diff_bg = np.max(np.abs(arr - c_med[None, None, :]), axis=2)

    if bg_type == "white":
        exact_core = (diff_bg <= 7.0) & (chroma <= 5.0)
        # Neutral white/off-white background, neutral gray bottom drop-shadow (chroma <= 15 & luma >= 95),
        # or very pale background haze (luma >= 236 & chroma <= 26)
        can_flood = ((diff_bg <= 22.0) & (chroma <= 18.0)) | ((luma >= 95.0) & (chroma <= 15.0)) | ((luma >= 236.0) & (chroma <= 26.0))
        # AI 强保护锁：凡是 rembg 认为是主体内部 (ai_raw >= 0.45) 且不是纯平背景色核心或中性灰底影的（例如小耶稣的带褶皱白色襁褓、圣母白纱），禁止泛洪进入！
        ai_subject_lock = (ai_raw >= 0.45) & (~exact_core) & (~((luma >= 95.0) & (chroma <= 12.0) & (diff_bg <= 36.0) & (ai_raw < 0.72)))
        can_flood = can_flood & (~ai_subject_lock)
    elif bg_type == "black":
        exact_core = (diff_bg <= 8.0) & (mx <= 18.0)
        can_flood = ((diff_bg <= 26.0) & (chroma <= 22.0)) | ((mx <= 36.0) & (chroma <= 20.0))
        ai_subject_lock = (ai_raw >= 0.50) & (~exact_core)
        can_flood = can_flood & (~ai_subject_lock)
    elif bg_type == "green":
        g_exc = g - np.maximum(r, b)
        exact_core = (g > 85.0) & (g_exc > 36.0)
        can_flood = ((g > 60.0) & (g_exc > 18.0)) | (diff_bg <= 28.0)
        ai_subject_lock = (ai_raw >= 0.55) & (g_exc < 24.0)
        can_flood = can_flood & (~ai_subject_lock)
    else:  # blue
        b_exc = b - np.maximum(r, g)
        exact_core = (b > 85.0) & (b_exc > 36.0)
        can_flood = ((b > 60.0) & (b_exc > 18.0)) | (diff_bg <= 28.0)
        ai_subject_lock = (ai_raw >= 0.55) & (b_exc < 24.0)
        can_flood = can_flood & (~ai_subject_lock)

    # 使用 OpenCV connectedComponentsWithStats 在 can_flood 上一步完成外边界连通 + 内部大块纯背景洞 (≥36px) 泛洪！
    cf_u8 = can_flood.astype(np.uint8)
    nc, labels, stats, _ = cv2.connectedComponentsWithStats(cf_u8, connectivity=4)
    if nc <= 1:
        return np.zeros((h, w), dtype=bool)

    border_labels = set()
    border_labels.update(np.unique(labels[0, :]).tolist())
    border_labels.update(np.unique(labels[-1, :]).tolist())
    border_labels.update(np.unique(labels[:, 0]).tolist())
    border_labels.update(np.unique(labels[:, -1]).tolist())
    border_labels.discard(0)

    # 内部面积 ≥36 像素的纯平背景色镂空洞（如圣母与约瑟之间的白底镂空区、空十字内部镂空区）
    min_pocket = 16 if bg_type in ("green", "blue") else 36
    nc_core, lbl_core, st_core, _ = cv2.connectedComponentsWithStats(exact_core.astype(np.uint8), connectivity=4)
    for k in range(1, nc_core):
        if int(st_core[k, cv2.CC_STAT_AREA]) >= min_pocket:
            ys_c, xs_c = np.where(lbl_core == k)
            if len(ys_c) > 0:
                cf_lbl = int(labels[ys_c[0], xs_c[0]])
                if cf_lbl > 0:
                    border_labels.add(cf_lbl)

    lut = np.zeros(nc, dtype=bool)
    for bl in border_labels:
        lut[bl] = True
    return lut[labels]


def key_frame_with_ai_and_screen(rgb: np.ndarray, bg_info: dict, ai_raw: np.ndarray) -> np.ndarray:
    """
    结合官方 rembg (isnet-general-use) 神经网络掩码 `ai_raw` + 四边连通泛洪 + 四幕色彩物理学修边：
    - 既保留底部红花绿叶花环、金铃铛、顶部伯利恒金星等所有非背景装饰元素（解决单纯 rembg 漏掉底座花环的问题），
    - 又由 rembg 100% 锁死保护人物内部白色襁褓、圣母白头纱、白鸽羽毛不被抠穿，
    - 并彻底剥离外围白幕/黑幕/绿幕/蓝幕、底部灰白阴影与人物之间的镂空背景区。
    """
    bg_type = bg_info["type"]
    c_med = bg_info["c_med"]
    bg_tuple = bg_info["rgb_tuple"]

    arr = rgb.astype(np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mx = np.max(arr, axis=2)
    mn = np.min(arr, axis=2)
    chroma = mx - mn
    diff_bg = np.max(np.abs(arr - c_med[None, None, :]), axis=2)

    is_bg = compute_border_floodfill_bg_mask(rgb, bg_info, ai_raw)
    fg_mask = ~is_bg

    # 计算前景边缘到背景的欧氏距离场，用于 1~3px 抗锯齿柔化与退晕
    fg_u8 = fg_mask.astype(np.uint8)
    dist_from_bg = cv2.distanceTransform(fg_u8, cv2.DIST_L2, 3)

    if bg_type == "black":
        ai_closed = cv2.morphologyEx(ai_raw, cv2.MORPH_CLOSE, _KERN_7)
        ai_eroded = cv2.erode(ai_closed, _KERN_5, iterations=1)
        wing_ivory = np.clip((mx - 102.0) / 68.0, 0.0, 1.0) * np.clip((b - 56.0) / 36.0, 0.0, 1.0)
        flame_color = (r > b + 30.0) & (g > b + 10.0)
        glow = np.where(fg_mask | flame_color, np.clip((mx - 36.0) / 138.0, 0.0, 1.0) ** 1.15, 0.0)
        alpha = np.where(fg_mask, 1.0, glow * 0.65)
        edge_band = (dist_from_bg > 0) & (dist_from_bg <= 2.5)
        edge_a = np.clip(np.maximum(mx - 24.0, chroma * 1.8) / 95.0, 0.0, 1.0)
        alpha = np.where(edge_band & (ai_eroded < 0.8), np.minimum(alpha, np.maximum(edge_a, ai_raw)), alpha)
        alpha = remove_small_components(np.clip(alpha, 0.0, 1.0), min_area=40, thresh=0.06)

        rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
        rgba[:, :, :3] = rgb
        rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
        return unpremul_and_bright_lift(rgba, lift_white=True, lift_warm_fire=True, despill_green=False)

    if bg_type == "green":
        rb_max = np.maximum(r, b)
        g_exc = g - rb_max
        alpha = np.where(fg_mask, 1.0, 0.0).astype(np.float32)
        edge_band = (dist_from_bg > 0) & (dist_from_bg <= 3.0)
        edge_a = 1.0 - np.clip((g_exc - 6.0) / 36.0, 0.0, 1.0)
        alpha = np.where(edge_band, np.minimum(alpha, edge_a), alpha)
        alpha = remove_small_components(np.clip(alpha, 0.0, 1.0), min_area=40, thresh=0.06)

        rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
        rgba[:, :, :3] = rgb
        rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
        return unpremul_and_bright_lift(rgba, lift_white=True, lift_warm_fire=True, despill_green=True)

    if bg_type == "blue":
        rg_max = np.maximum(r, g)
        b_exc = b - rg_max
        alpha = np.where(fg_mask, 1.0, 0.0).astype(np.float32)
        edge_band = (dist_from_bg > 0) & (dist_from_bg <= 3.0)
        edge_a = 1.0 - np.clip((b_exc - 6.0) / 36.0, 0.0, 1.0)
        alpha = np.where(edge_band, np.minimum(alpha, edge_a), alpha)
        alpha = remove_small_components(np.clip(alpha, 0.0, 1.0), min_area=40, thresh=0.06)

        rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
        rgba[:, :, :3] = rgb
        rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
        return unpremul_and_bright_lift(rgba, lift_white=True, lift_warm_fire=False, despill_blue=True)

    # 白幕 (`white`): fg_mask 已经完整保留了人物+襁褓+底层红花绿叶花环+金铃铛+顶部金星，同时清除了外围白底、底部灰影和人物中间白洞
    alpha = np.where(fg_mask, 1.0, 0.0).astype(np.float32)
    edge_band = (dist_from_bg > 0) & (dist_from_bg <= 3.0)
    color_signal = np.maximum(diff_bg * 1.25, chroma * 2.4)
    ramp_a = np.clip((color_signal - 14.0) / 42.0, 0.0, 1.0)
    d1 = (dist_from_bg > 0) & (dist_from_bg <= 1.2)
    d2 = (dist_from_bg > 1.2) & (dist_from_bg <= 2.2)
    d3 = (dist_from_bg > 2.2) & (dist_from_bg <= 3.2)
    alpha = np.where(d1, np.minimum(0.88, ramp_a), alpha)
    alpha = np.where(d2, np.maximum(ramp_a, 0.56), alpha)
    alpha = np.where(d3, np.maximum(ramp_a, 0.84), alpha)

    alpha = remove_small_components(np.clip(alpha, 0.0, 1.0), min_area=40, thresh=0.06)
    rgba = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb
    rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    return unpremul_and_bright_lift(rgba, lift_white=False, lift_warm_fire=False, despill_green=False, bg_rgb=bg_tuple)


def fit_frames_into_512_safe_box(frames_rgba: list[np.ndarray]) -> list[np.ndarray]:
    """
    官方工序 1 + 工序 4：
    计算全帧并集包围盒 (`All-Frame Union BBox`)，留 ~2% 外扩后用 Lanczos 居中缩放到
    512×512 画布的 [46, 466] (420×420) 安全盒内，并执行 `enforce_safe_bounds` + `dilate_rgb_4px`！
    """
    if not frames_rgba:
        return []
    h, w = frames_rgba[0].shape[:2]
    y0, y1, x0, x1 = h, 0, w, 0
    for rgba in frames_rgba:
        fg = rgba[:, :, 3] > 24
        xs = np.where(fg.sum(axis=0) >= 2)[0]
        ys = np.where(fg.sum(axis=1) >= 2)[0]
        if len(xs) and len(ys):
            x0 = min(x0, int(xs.min()))
            x1 = max(x1, int(xs.max()) + 1)
            y0 = min(y0, int(ys.min()))
            y1 = max(y1, int(ys.max()) + 1)

    if x1 <= x0 or y1 <= y0:
        x0, y0, x1, y1 = 0, 0, w, h

    pad = max(8, int(round(max(x1 - x0, y1 - y0) * 0.02)))
    x0p, x1p = max(0, x0 - pad), min(w, x1 + pad)
    y0p, y1p = max(0, y0 - pad), min(h, y1 + pad)
    bw, bh = max(8, x1p - x0p), max(8, y1p - y0p)

    sc = min(float(SAFE_BOX_SIZE) / float(bw), float(SAFE_BOX_SIZE) / float(bh))
    tw = max(2, min(SAFE_BOX_SIZE, int(round(bw * sc))))
    th = max(2, min(SAFE_BOX_SIZE, int(round(bh * sc))))
    ox = (CANVAS_SIZE - tw) // 2
    oy = (CANVAS_SIZE - th) // 2

    out_frames = []
    for rgba in frames_rgba:
        crop = rgba[y0p:y1p, x0p:x1p]
        resized = np.array(Image.fromarray(crop, "RGBA").resize((tw, th), Image.Resampling.LANCZOS))
        canvas = np.zeros((CANVAS_SIZE, CANVAS_SIZE, 4), dtype=np.uint8)
        canvas[oy : oy + th, ox : ox + tw] = resized
        bounded = enforce_safe_bounds(canvas)
        dilated = dilate_rgb_4px(bounded, radius=4.5)
        out_frames.append(dilated)

    return out_frames


def process_single_image(in_path: Path, out_dir: Path, forced_mode: str) -> dict:
    im = Image.open(in_path).convert("RGBA")
    arr = np.array(im)
    rgb = arr[:, :, :3]
    bg_info = detect_corner_background(rgb, forced_mode)

    # 若原图已有完整透明通道 (四角 Alpha < 15 且无白框残留)
    corners_a = [arr[0, 0, 3], arr[0, -1, 3], arr[-1, 0, 3], arr[-1, -1, 3]]
    if forced_mode == "auto" and all(a < 15 for a in corners_a) and np.any(arr[:, :, 3] > 200):
        rgba = unpremul_and_bright_lift(arr)
    else:
        ai_raw = predict_rembg_alpha(rgb)
        rgba = key_frame_with_ai_and_screen(rgb, bg_info, ai_raw)

    fitted = fit_frames_into_512_safe_box([rgba])[0]
    out_png = out_dir / f"{in_path.stem}.png"
    Image.fromarray(fitted, "RGBA").save(out_png)
    return {
        "bg_label": bg_info["label"],
        "frames": 1,
        "out_path": out_png,
    }


def probe_video_dimensions(ffmpeg_bin: str, in_path: Path) -> tuple[int, int]:
    cmd = [ffmpeg_bin, "-hide_banner"]
    if in_path.suffix.lower() == ".webm":
        cmd += ["-c:v", "libvpx-vp9"]
    cmd += ["-i", str(in_path)]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    text = f"{cp.stdout or ''}\n{cp.stderr or ''}"
    import re
    m = re.search(r"Stream #0:\d+.*Video:.*?\s(\d{2,5})x(\d{2,5})(?:[\s,\[])", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1280, 720


def process_single_video(ffmpeg_bin: str, in_path: Path, out_dir: Path, forced_mode: str) -> dict:
    src_w, src_h = probe_video_dimensions(ffmpeg_bin, in_path)
    max_side = max(src_w, src_h)
    if max_side > 960:
        sc = 960.0 / float(max_side)
        dec_w = max(64, int(round(src_w * sc)) & ~1)
        dec_h = max(64, int(round(src_h * sc)) & ~1)
        vf = f"fps={FPS_OUT},scale={dec_w}:{dec_h}"
    else:
        dec_w, dec_h = src_w, src_h
        vf = f"fps={FPS_OUT}"

    dec_cmd = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
    if in_path.suffix.lower() == ".webm":
        dec_cmd += ["-c:v", "libvpx-vp9"]
    dec_cmd += ["-i", str(in_path), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    raw_bytes = subprocess.run(dec_cmd, capture_output=True, check=True).stdout
    fb = dec_w * dec_h * 3
    n_fr = len(raw_bytes) // fb
    if n_fr < 1:
        raise RuntimeError(f"未能从视频解码出任何帧: {in_path}")

    first_rgb = np.frombuffer(raw_bytes[:fb], dtype=np.uint8).reshape((dec_h, dec_w, 3)).copy()
    bg_info = detect_corner_background(first_rgb, forced_mode)

    # 智能帧间 AI 掩码复用：若相邻帧画面差异极小 (微光/静止雕像/微动元素, L1 diff < 2.2)，直接复用上一关键帧的 rembg 神经网络掩码并按当前帧 RGB 精修！
    # 若画面有明显动作 (如白鸽扇翅/旋转)，则自动对当前帧重新运行 rembg (isnet-general-use)！
    frames_rgba = []
    prev_key_rgb = None
    prev_ai_raw = None
    ai_calls = 0

    for fi in range(n_fr):
        fr_rgb = np.frombuffer(raw_bytes[fi * fb : (fi + 1) * fb], dtype=np.uint8).reshape((dec_h, dec_w, 3)).copy()
        need_new_ai = False
        if prev_ai_raw is None or prev_key_rgb is None:
            need_new_ai = True
        else:
            mean_diff = float(np.mean(np.abs(fr_rgb[::4, ::4].astype(np.float32) - prev_key_rgb[::4, ::4].astype(np.float32))))
            if mean_diff > 4.5:
                need_new_ai = True

        if need_new_ai:
            prev_ai_raw = predict_rembg_alpha(fr_rgb)
            prev_key_rgb = fr_rgb
            ai_calls += 1

        rgba = key_frame_with_ai_and_screen(fr_rgb, bg_info, prev_ai_raw)
        frames_rgba.append(rgba)

    # 执行官方全帧并集包围盒 [46, 466] 安全盒缩放 + enforce_safe_bounds + dilate_rgb_4px
    fitted_frames = fit_frames_into_512_safe_box(frames_rgba)

    out_webm = out_dir / f"{in_path.stem}.webm"
    out_poster = out_dir / f"{in_path.stem}_亮底预览.jpg"

    enc_proc = subprocess.Popen(
        [
            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{CANVAS_SIZE}x{CANVAS_SIZE}", "-r", str(FPS_OUT), "-i", "-",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", "22", "-b:v", "0",
            "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "4", "-an",
            str(out_webm),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    backdrop = (
        Image.open(DEFAULT_STAGE_PHOTO).convert("RGBA").resize((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.LANCZOS)
        if DEFAULT_STAGE_PHOTO.exists()
        else Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (225, 228, 232, 255))
    )
    mid_idx = len(fitted_frames) // 2

    assert enc_proc.stdin is not None
    for idx, frame_512 in enumerate(fitted_frames):
        enc_proc.stdin.write(frame_512.tobytes())
        if idx == mid_idx:
            Image.alpha_composite(backdrop.copy(), Image.fromarray(frame_512, "RGBA")).convert("RGB").save(out_poster, quality=92)

    enc_proc.stdin.close()
    _, err_bytes = enc_proc.communicate()
    if enc_proc.returncode != 0:
        raise RuntimeError(f"FFmpeg VP9 Alpha 编码失败: {err_bytes.decode(errors='replace')}")

    return {
        "bg_label": bg_info["label"],
        "frames": len(fitted_frames),
        "ai_keyframes": ai_calls,
        "out_path": out_webm,
        "poster_path": out_poster,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Reels 工作室 · 官方 rembg(isnet-general-use) + 4px扩散 + 512x512 [46,466] 安全盒 批量抠像工厂")
    ap.add_argument("target", nargs="?", default="", help="待处理的文件夹或单个视频/图片路径")
    ap.add_argument("--default-dir", default="", help="双击启动时的默认目录")
    ap.add_argument("--interactive", action="store_true", help="启用交互式中文引导菜单（供 .bat 双击调用）")
    ap.add_argument("--mode", default="auto", choices=["auto", "white", "green", "black", "blue"], help="幕布类型 (默认 auto 自动识别)")
    ap.add_argument("--out-subdir", default="透明成品_512标准WebM与PNG", help="输出子文件夹名称")
    args = ap.parse_args()

    default_base = Path(args.default_dir).resolve() if args.default_dir else HERE
    raw_target = (args.target or "").strip().strip('"').strip("'")
    mode = args.mode

    if args.interactive:
        print("================================================================================")
        print("  Reels 工作室 · 官方工业级小元素抠像与 512×512 [46,466] 安全盒封装批处理")
        print("  - 核心管线：rembg (isnet-general-use) + unpremul_and_bright_lift + dilate_rgb_4px")
        print("  - 标准画幅：全帧并集包围盒自动居中缩放入 512×512 画布的 [46,466] (420×420) 安全盒")
        print("  - 支持格式：视频 (.mp4 / .mov / .webm) & 图片 (.jpg / .png / .webp)")
        print("  - 安全保护：100% 保留原素材不修改，透明成品输出至 [透明成品_512标准WebM与PNG]")
        print("================================================================================\n")

        if not raw_target:
            local_media = [
                p for p in default_base.iterdir()
                if p.is_file() and p.suffix.lower() in (VIDEO_EXTS | IMAGE_EXTS)
            ] if default_base.exists() and default_base.is_dir() else []

            if local_media:
                print(f"✅ 已自动锁定当前文件夹（共检测到 {len(local_media)} 个视频/图片素材）：")
                print(f"   📂 {default_base}")
                print("   （直接按回车处理当前文件夹；如需改处理其它目录，请直接将文件夹拖入下方）\n")
                try:
                    user_in = input("请直接按【回车键】确认当前文件夹（或拖入其它路径）: ").strip().strip('"').strip("'")
                except EOFError:
                    user_in = ""
                raw_target = user_in if user_in else str(default_base)
            else:
                print(f"[提示] 当前目录 [{default_base}] 下暂无视频/图片素材。")
                print("       请把要处理的【文件夹】或【单个视频/图片】直接拖进此窗口：\n")
                try:
                    user_in = input("请拖入要处理的文件夹或视频/图片路径后按回车: ").strip().strip('"').strip("'")
                except EOFError:
                    user_in = ""
                raw_target = user_in if user_in else str(default_base)

        print(f"\n当前待处理目标: {raw_target}\n")
        print("请选择去底色模式：")
        print("  [1] 智能自动识别（默认推荐：自动识别白幕/绿幕/黑幕/蓝幕 + rembg isnet-general-use 主体分割）")
        print("  [2] 强制按【白幕】抠像（AI主体分割 + 去白底与底部灰影，保护内部白色衣物/白鸽）")
        print("  [3] 强制按【绿幕】抠像（AI主体保护 + Vlahos去绿溢 + 白羽/花环提纯）")
        print("  [4] 强制按【黑幕】抠像（AI主体核心锁死 + 圣光/火焰亮度融合提亮）")
        print("  [5] 强制按【蓝幕】抠像（AI主体保护 + 去蓝溢）\n")
        try:
            m_choice = input("请输入模式编号 [1-5，直接按回车默认选 1]: ").strip()
        except EOFError:
            m_choice = "1"
        mode_map = {"1": "auto", "2": "white", "3": "green", "4": "black", "5": "blue"}
        mode = mode_map.get(m_choice, "auto")
        print("")

    if not raw_target:
        raw_target = str(default_base)

    ffmpeg_bin = find_working_ffmpeg()
    target_path = Path(raw_target).resolve()
    if not target_path.exists():
        print(f"❌ 找不到路径: {target_path}")
        sys.exit(1)

    if target_path.is_file():
        base_dir = target_path.parent
        files = [target_path]
    else:
        base_dir = target_path
        files = sorted([
            p for p in base_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (VIDEO_EXTS | IMAGE_EXTS)
        ])

    if not files:
        print(f"⚠️ 在 [{base_dir}] 中未找到支持的视频 (.mp4/.mov/.webm) 或图片 (.jpg/.png/.webp)。")
        sys.exit(0)

    out_dir = base_dir / args.out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    print("================================================================================")
    print("🎬 Reels 工作室 · 官方工业级小元素抠像与 512×512 [46,466] 安全盒封装批处理")
    print(f"🧠 AI 分割模型      : rembg (isnet-general-use.onnx 本地离线推理)")
    print(f"🛠️ 官方四大标准工序 : unpremul_and_bright_lift + All-Frame Union BBox [46,466] + dilate_rgb_4px")
    print(f"📂 源素材目录(保留) : {base_dir}")
    print(f"✨ 透明成品输出目录 : {out_dir}")
    print(f"🎞️ 待处理素材数量   : {len(files)} 个")
    print("================================================================================\n")

    # 预热一次本地 ISNet 模型
    print("⏳ 正在加载本地 isnet-general-use 神经网络模型...", flush=True)
    get_rembg_session()
    print("✅ 模型加载就绪，开始批量抠像封装！\n", flush=True)

    ok_cnt = 0
    fail_cnt = 0
    for idx, fpath in enumerate(files, start=1):
        ext = fpath.suffix.lower()
        is_img = ext in IMAGE_EXTS
        kind_str = "🖼️ 图片" if is_img else "🎞️ 视频"
        print(f"[{idx}/{len(files)}] 正在处理 {kind_str}: {fpath.name} ...", flush=True)
        t0 = time.time()
        try:
            if is_img:
                res = process_single_image(fpath, out_dir, mode)
            else:
                res = process_single_video(ffmpeg_bin, fpath, out_dir, mode)
            dt = time.time() - t0
            kb = round(res["out_path"].stat().st_size / 1024)
            extra = f" | AI关键帧分割: {res.get('ai_keyframes', 1)}次" if not is_img else ""
            print(f"   ├─ 识别底色: {res['bg_label']} | 总帧数: {res['frames']}帧{extra} | 规格: 512×512 [46,466]安全盒")
            print(f"   └─ ✅ 成功 ({dt:.1f}s, {kb} KB) -> {res['out_path']}\n", flush=True)
            ok_cnt += 1
        except Exception as e:
            print(f"   └─ ❌ 失败: {e}\n", flush=True)
            fail_cnt += 1

    print("================================================================================")
    print(f"🎉 批量制作完成：成功 {ok_cnt} 个，失败 {fail_cnt} 个（原素材 100% 保留未改动）")
    print(f"📁 成品目录：{out_dir}")
    print("💡 注意：在其它软件或 FFmpeg 中调用透明 .webm 时，请确保将 -c:v libvpx-vp9 放在 -i 之前！")
    print("================================================================================")


if __name__ == "__main__":
    main()
