#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
9-Gate Subtitle / Overlay / AE Typography Pre-Flight Linter + Anti-Homogenization Dedup
+ Fast Skia 1-Line & 2-Line Preview Contact Sheet Generator.
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _load_ui_font(size: int = 13) -> ImageFont.ImageFont:
    for cand in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ):
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size=size)
            except Exception:
                pass
    return ImageFont.load_default()

HERE = Path(__file__).resolve().parent
RENDER_TILES_MJS = HERE / "render_sub_preview_tiles.mjs"
DEFAULT_BASE_URL = "https://vn-subtitle-cloud.fb-muse-dad32d.workers.dev"

# Authoritative 56 Vietnamese-verified fonts + exact R2 paths (synced with src/worker.js)
FONT_REGISTRY_56 = {
    "Alfa Slab One": ["fonts/AlfaSlabOne-Regular.ttf"],
    "Allura": ["fonts/Allura-Regular.ttf"],
    "Anton": ["fonts/Anton-Regular.ttf"],
    "Archivo": ["fonts/Archivo-VariableFont-wght-Regular.ttf"],
    "Arimo": ["fonts/Arimo-Bold.ttf"],
    "Asap Condensed": ["fonts/AsapCondensed-Bold.ttf"],
    "Bad Script": ["fonts/BadScript-Regular.ttf"],
    "Barlow Condensed": ["fonts/BarlowCondensed-Bold.ttf"],
    "Be Vietnam Pro": ["fonts/BeVietnamPro-Bold.ttf"],
    "Bricolage Grotesque": ["fonts/BricolageGrotesque-VariableFont_opsz,wdth,wght.ttf"],
    "Calistoga": ["fonts/Calistoga-Regular.ttf"],
    "Carattere": ["fonts/Carattere-Regular.ttf"],
    "Cormorant Garamond": ["fonts/CormorantGaramond-VariableFont-wght-Regular.ttf"],
    "Dancing Script": ["fonts/DancingScript-VariableFont_wght.ttf"],
    "Fira Sans": ["fonts/FiraSans-Bold.ttf"],
    "Fjalla One": ["fonts/FjallaOne-Regular.ttf"],
    "Francois One": ["fonts/FrancoisOne-Regular.ttf"],
    "Gelasio": ["fonts/Gelasio-VariableFont_wght.ttf"],
    "Great Vibes": ["fonts/GreatVibes-Regular.ttf"],
    "Inter": ["fonts/Inter-VariableFont-wght-Regular.ttf"],
    "Josefin Sans": ["fonts/JosefinSans-VariableFont-wght-Regular.ttf"],
    "Lato": ["fonts/Lato-Bold.ttf"],
    "League Gothic": ["fonts/LeagueGothic-Regular-VariableFont_wdth.ttf"],
    "League Spartan": ["fonts/LeagueSpartan-VariableFont-wght-Regular.ttf"],
    "LiberationSans": ["fonts/LiberationSans-Bold.ttf"],
    "Lobster": ["fonts/Lobster-Regular.ttf"],
    "Lora": ["fonts/Lora-Bold.ttf"],
    "Manrope": ["fonts/Manrope-VariableFont_wght-Regular.ttf"],
    "Merienda": ["fonts/Merienda-VariableFont_wght.ttf"],
    "Merriweather": ["fonts/Merriweather-VariableFont-wght-Regular.ttf"],
    "Montserrat": ["fonts/Montserrat-Bold.ttf"],
    "Noto Sans": ["fonts/NotoSans-VariableFont-wght-Regular.ttf"],
    "Noto Serif": ["fonts/NotoSerif-VariableFont_wdth,wght.ttf"],
    "Nunito": ["fonts/Nunito-VariableFont-wght-Regular.ttf"],
    "Open Sans": ["fonts/OpenSans-Bold.ttf"],
    "Oswald": ["fonts/Oswald-Bold.ttf"],
    "Pacifico": ["fonts/Pacifico-Regular.ttf"],
    "Pinyon Script": ["fonts/PinyonScript-Regular.ttf"],
    "Playfair Display": ["fonts/PlayfairDisplay-VariableFont_wght.ttf"],
    "Playwrite AT": ["fonts/PlaywriteAT-VariableFont_wght.ttf"],
    "Playwrite NZ Basic": ["fonts/PlaywriteNZBasic-VariableFont_wght.ttf"],
    "Prata": ["fonts/Prata-Regular.ttf"],
    "Quicksand": ["fonts/Quicksand-VariableFont_wght-Regular.ttf"],
    "Raleway": ["fonts/Raleway-VariableFont-wght-Regular.ttf"],
    "Road Rage": ["fonts/RoadRage-Regular.ttf"],
    "Roboto": ["fonts/Roboto-Bold.ttf"],
    "Roboto Condensed": ["fonts/RobotoCondensed-VariableFont_wght.ttf"],
    "Roboto Slab": ["fonts/RobotoSlab-VariableFont_wght.ttf"],
    "Rowdies": ["fonts/Rowdies-Bold.ttf"],
    "SN Pro": ["fonts/SNPro-VariableFont_wght.ttf"],
    "Source Serif 4 Variable": ["fonts/SourceSerif4Variable-VariableFont_wght-Regular.ttf"],
    "SourceCodeVF": ["fonts/SourceCodeVF-VariableFont-wght-Regular.ttf"],
    "SourceSans3VF": ["fonts/SourceSans3VF-VariableFont-wght-Regular.ttf"],
    "Tapestry": ["fonts/Tapestry-Regular.ttf"],
    "TikTok Sans": ["fonts/TikTokSans-VariableFont-wght-Regular.ttf"],
    "Yeseva One": ["fonts/YesevaOne-Regular.ttf"],
}

AE_ENGINES_8 = {
    "particle_morph_gold",
    "extruded_3d_gold",
    "saber_light_trace",
    "liquid_molten_gold",
    "magnetic_wave_karaoke",
    "gold_foil_emboss_card",
    "motion_blur_whip_slam",
    "underline_brush_draw",
}

ALLOWED_ANIM_TYPES = {
    "default", "none", "fade", "slide_up", "slide_down", "slide_left", "slide_right",
    "pop", "zoom_bounce", "typewriter", "char_bounce", "letter_jump",
    "char_float_up", "char_pop_elastic", "char_wave", "char_drop_bounce",
    "char_squash_bounce", "char_center_spread", "word_pop_random",
    "word_pop_random_pulse", "metronome", "blur_sharp", "holy_glow",
    "floating", "bullet_reveal", "box_wipe", "zoom_typewriter", "line_focus",
    "underline_sweep", "feather_wipe", "speech_feather_wipe", "pulse",
    "three_word_focus_stack", "rolling_rainbow_karaoke", "rolling_quill_karaoke",
    "flash_highlight", "kinetic_glow_stack",
    # AE engines & aliases supported by reels-ae-typography.js
    "particle_morph_gold", "ae_particle_sparkle",
    "extruded_3d_gold", "extruded_3d_flip", "ae_3d_extrude",
    "saber_light_trace", "ae_saber_glow",
    "liquid_molten_gold", "ae_gold_sweep",
    "magnetic_wave_karaoke", "ae_magnetic_karaoke",
    "gold_foil_emboss_card",
    "motion_blur_whip_slam", "ae_whip_slam",
    "underline_brush_draw", "ae_brush_reveal", "ae_holy_rays",
    # Overlay modes
    "scroll_sync", "scroll_tw", "focus_flow",
}

EXPANDING_ANIMS = {
    "letter_jump", "word_pop_random", "word_pop_random_pulse",
    "scatter_pop", "magnetic_wave_karaoke", "ae_magnetic_karaoke",
}

SACRED_KEYWORDS = (
    "天主", "耶稣", "圣", "灵修", "祈祷", "福音", "圣母", "神父",
    "chúa", "giê-su", "ki-tô", "thiên chúa", "đức mẹ", "amen", "lời chúa",
)

NARROW_FONTS = {"Oswald", "Anton", "League Gothic", "Barlow Condensed", "Asap Condensed"}
R2_FONT_PATH_RE = re.compile(r"^fonts/[A-Za-z0-9._,-]+\.(?:ttf|otf|woff2?)$", re.I)


def _parse_hex_rgb(val: str) -> tuple[int, int, int] | None:
    s = str(val or "").strip().lstrip("#")
    if len(s) == 6 and re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    if len(s) == 3 and re.fullmatch(r"[0-9a-fA-F]{3}", s):
        return int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16)
    return None


def _rel_luminance(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def _is_near_black(val: str) -> bool:
    rgb = _parse_hex_rgb(val)
    if rgb is None:
        return False
    return max(rgb) < 42 or _rel_luminance(rgb) < 0.04


def _rgb_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _fetch_online_catalog(base_url: str) -> tuple[dict, list[dict]]:
    fonts_map = dict(FONT_REGISTRY_56)
    items = []
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/v1/fonts", headers={"User-Agent": "vn-sub-pack-manager/2.0"})
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        for fam, info in (resp.get("fonts") or {}).items():
            ttfs = info.get("all_ttfs") or ([info["web_ttf"]] if info.get("web_ttf") else [])
            if ttfs:
                fonts_map[fam] = ttfs
    except Exception:
        pass
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/v1/items?limit=5000", headers={"User-Agent": "vn-sub-pack-manager/2.0"})
        resp = json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8"))
        items = resp.get("items") or []
    except Exception:
        pass
    return fonts_map, items


def _unpack_raw_items(file_path: Path) -> list[dict]:
    data = json.loads(file_path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        for k in ("items", "presets", "ae_8_templates"):
            if isinstance(data.get(k), list):
                raw_list = data[k]
                break
        else:
            raw_list = [data]
    elif isinstance(data, list):
        raw_list = data
    else:
        raise SystemExit("Unsupported JSON pack structure")

    entries = []
    for raw in raw_list:
        row_meta = None
        if isinstance(raw, dict) and isinstance(raw.get("row"), dict):
            row_meta = raw["row"]
            style_payload = json.loads(raw.get("json_text") or "{}") if raw.get("json_text") else (row_meta.get("style") or {})
            base = dict(row_meta)
            base.update(style_payload if isinstance(style_payload, dict) else {})
        else:
            base = dict(raw)

        kind = base.get("kind") or ("overlay" if "layers" in base else "subtitle")
        title = str(base.get("title") or base.get("name") or "未命名").strip()
        item_id = str(base.get("id") or "").strip().upper()
        stage_bg = base.get("stage_bg") or "photo"

        if kind == "overlay":
            layers = base.get("layers") or (base.get("style") or {}).get("layers") or []
            fam = str(base.get("font_family") or (layers[0].get("font_family") if layers else "") or "Lora").strip()
            style_obj = {
                "schema": "universal-overlay-style/1.0",
                "title": title,
                "kind": "overlay",
                "canvas": {"width": 1080, "height": 1920},
                "layers": layers,
            }
            raw_p = {}
        else:
            if isinstance(base.get("raw_style_params"), dict):
                raw_p = dict(base["raw_style_params"])
            elif isinstance(base.get("style"), dict) and isinstance(base["style"].get("raw_style_params"), dict):
                raw_p = dict(base["style"]["raw_style_params"])
            else:
                skip = {"id", "title", "name", "kind", "category", "stage_bg", "sort_weight", "sample_text_vi", "ae_engine_ref", "font_keys_json"}
                raw_p = {k: v for k, v in base.items() if k not in skip}
            if base.get("ae_engine_ref") and "ae_engine_ref" not in raw_p:
                raw_p["ae_engine_ref"] = base["ae_engine_ref"]
            fam = str(raw_p.get("font_family") or base.get("font_family") or "Be Vietnam Pro").strip()
            raw_p["font_family"] = fam
            style_obj = {
                "schema": "universal-subtitle-style/1.0",
                "title": title,
                "kind": "subtitle",
                "canvas": {"width": 1080, "height": 1920},
                "raw_style_params": raw_p,
                "sample_text_vi": base.get("sample_text_vi") or "Đức Chúa Giê-su luôn nâng đỡ bạn",
            }

        entries.append({
            "id": item_id,
            "title": title,
            "kind": kind,
            "stage_bg": stage_bg,
            "font_family": fam,
            "sample_text_vi": str(base.get("sample_text_vi") or style_obj.get("sample_text_vi") or ""),
            "font_keys_json": row_meta.get("font_keys_json") if row_meta else base.get("font_keys_json"),
            "ae_engine_ref": base.get("ae_engine_ref") or raw_p.get("ae_engine_ref") or "",
            "raw_p": raw_p,
            "style_obj": style_obj,
        })
    return entries


def lint_entry(idx: int, ent: dict, fonts_map: dict) -> dict:
    fails = []
    warns = []
    kind = ent["kind"]
    title = ent["title"]
    fam = ent["font_family"]
    p = ent["raw_p"]
    sample = ent["sample_text_vi"]

    # S01: 56-Font Whitelist
    if fam not in fonts_map:
        fails.append("S01_FONT_WHITELIST")
        warns.append(f"font `{fam}` not in 56-font VN whitelist")
    if kind == "overlay":
        for lay in ent["style_obj"].get("layers") or []:
            for fk in ("font_family", "scroll_title_font_family", "title_font_family", "body_font_family", "footer_font_family"):
                lf = lay.get(fk)
                if lf and lf not in fonts_map:
                    fails.append("S01_FONT_WHITELIST")
                    warns.append(f"overlay layer {fk}=`{lf}` not in whitelist")

    # S02: font_keys_json must store R2 paths ("fonts/..."), never font family names
    fk_raw = ent.get("font_keys_json")
    if fk_raw is not None:
        try:
            fk_list = json.loads(fk_raw) if isinstance(fk_raw, str) else list(fk_raw)
            if not fk_list or any(not R2_FONT_PATH_RE.match(str(x)) for x in fk_list):
                fails.append("S02_FONT_KEYS_PATH")
                warns.append(f"invalid font_keys_json={fk_raw} (must be R2 fonts/*.ttf path)")
        except Exception:
            fails.append("S02_FONT_KEYS_PATH")

    # Sacred detection
    text_blob = f"{title} {sample}".lower()
    is_sacred = any(kw in text_blob for kw in SACRED_KEYWORDS) or bool(ent.get("ae_engine_ref"))

    if kind == "subtitle":
        # S03: Sacred no pure/near black
        if is_sacred:
            stroke_on = p.get("use_stroke", True) is not False and float(p.get("border_width", 4) or 0) > 0
            out_c = str(p.get("color_outline") or p.get("stroke_color") or "")
            shd_c = str(p.get("color_shadow") or "")
            shd_op = float(p.get("opacity_shadow") or 0)
            shd_bl = float(p.get("shadow_blur") or 0)
            ext_cs = [x.strip() for x in str(p.get("extrude_3d_colors") or "").split(",") if x.strip()]
            if stroke_on and _is_near_black(out_c):
                fails.append("S03_SACRED_NO_BLACK")
                warns.append(f"sacred outline cannot be black ({out_c})")
            if shd_op > 20 and shd_bl > 0 and _is_near_black(shd_c):
                fails.append("S03_SACRED_NO_BLACK")
                warns.append(f"sacred shadow cannot be black ({shd_c})")
            if p.get("extrude_3d_enabled") and any(_is_near_black(c) for c in ext_cs):
                fails.append("S03_SACRED_NO_BLACK")
                warns.append("sacred 3D extrusion color cannot be black")

        # S04: Box separation & pixel line_spacing
        if p.get("use_box") and p.get("box_adaptive_width") and p.get("box_connected") is True:
            warns.append("box_connected=true explicitly set; verify 2-line spacing >=38px")
        elif p.get("use_box") and p.get("box_adaptive_width") and p.get("box_connected") is not False:
            fails.append("S04_BOX_AND_SPACING")
            warns.append("two-line adaptive box must explicitly set box_connected=false")

        ls = p.get("line_spacing")
        if ls is None:
            fails.append("S04_BOX_AND_SPACING")
            warns.append("missing pixel line_spacing (>=34)")
        elif isinstance(ls, (int, float)) and (0 < float(ls) <= 4.0 or float(ls) < 34):
            fails.append("S04_BOX_AND_SPACING")
            warns.append(f"line_spacing={ls} invalid (must be pixel >=34, never 1.2 multiplier)")

        # S05: Safe bounds & fontsize
        fs = float(p.get("fontsize") or 84)
        wrap_pct = float(p.get("wrap_width_percent") or 84)
        anim = str(p.get("anim_in_type") or "fade").strip()
        if fs < 72:
            fails.append("S05_SAFE_BOUNDS_AND_SIZE")
            warns.append(f"fontsize={fs} < 72 minimum for 1080x1920")
        if wrap_pct > 86:
            fails.append("S05_SAFE_BOUNDS_AND_SIZE")
            warns.append(f"wrap_width_percent={wrap_pct} > 86 risk edge clip")
        if anim in EXPANDING_ANIMS and wrap_pct > 80:
            fails.append("S05_SAFE_BOUNDS_AND_SIZE")
            warns.append(f"expanding anim `{anim}` requires wrap_width_percent <= 80 (got {wrap_pct})")

        # S06: AE & Animation whitelist sync
        if anim and anim not in ALLOWED_ANIM_TYPES:
            fails.append("S06_AE_WHITELIST_SYNC")
            warns.append(f"unknown anim_in_type `{anim}`")
        ae_ref = str(ent.get("ae_engine_ref") or "").strip()
        if ae_ref and ae_ref not in AE_ENGINES_8:
            fails.append("S06_AE_WHITELIST_SYNC")
            warns.append(f"unknown ae_engine_ref `{ae_ref}`")

        # S07: Vietnamese orthography NFC & Giê-su / Ki-tô
        if sample:
            if unicodedata.normalize("NFC", sample) != sample:
                fails.append("S07_VN_ORTHOGRAPHY_NFC")
                warns.append("sample_text_vi is not NFC normalized")
            if re.search(r"\bGiê\s*su\b", sample, re.I) or re.search(r"\bKi\s*tô\b", sample, re.I):
                fails.append("S07_VN_ORTHOGRAPHY_NFC")
                warns.append("missing hyphen in Giê-su or Ki-tô")
        if fam in NARROW_FONTS:
            warns.append(f"narrow font `{fam}` needs extra letter_spacing >= 2.2 for VN diacritics")
        if p.get("uppercase"):
            warns.append("uppercase=true risks clipping stacked VN diacritics")

        # S08: Readability contrast
        txt_rgb = _parse_hex_rgb(p.get("color_text") or "#FFFFFF")
        if txt_rgb:
            if p.get("use_box") and _parse_hex_rgb(p.get("color_bg")):
                bg_rgb = _parse_hex_rgb(p.get("color_bg"))
                if _rgb_dist(txt_rgb, bg_rgb) < 120:
                    fails.append("S08_CONTRAST_READABILITY")
                    warns.append("low text-vs-box color contrast (<120 RGB dist)")
            elif p.get("use_stroke", True) and _parse_hex_rgb(p.get("color_outline")):
                out_rgb = _parse_hex_rgb(p.get("color_outline"))
                if _rgb_dist(txt_rgb, out_rgb) < 120:
                    fails.append("S08_CONTRAST_READABILITY")
                    warns.append("low text-vs-outline contrast (<120 RGB dist)")

    else:  # overlay
        for lay in ent["style_obj"].get("layers") or []:
            t = lay.get("type")
            if t == "scroll":
                if float(lay.get("fontsize") or 0) < 44:
                    fails.append("S05_SAFE_BOUNDS_AND_SIZE")
                    warns.append(f"scroll fontsize={lay.get('fontsize')} too small for seniors (<44)")
                if lay.get("content") and unicodedata.normalize("NFC", lay["content"]) != lay["content"]:
                    fails.append("S07_VN_ORTHOGRAPHY_NFC")
            elif t == "textcard":
                if lay.get("title_text") and float(lay.get("title_fontsize") or 0) < 52:
                    fails.append("S05_SAFE_BOUNDS_AND_SIZE")
                    warns.append("textcard title_fontsize < 52")

    fails = sorted(set(fails))
    return {
        "index": idx,
        "id": ent["id"] or f"NEW-{idx:02d}",
        "title": title,
        "kind": kind,
        "font_family": fam,
        "stage_bg": ent["stage_bg"],
        "status": "PASS" if not fails else "FAIL",
        "failed_gates": fails,
        "notes": warns,
    }


def check_dedup_and_anti_homogenization(entries: list[dict], reports: list[dict], online_items: list[dict]) -> None:
    """S09: Block intra-batch color-swap clones & warn against online near-duplicates."""
    seen_struct = {}
    for idx, ent in enumerate(entries):
        p = ent["raw_p"]
        if ent["kind"] == "subtitle":
            sig = (
                "subtitle",
                ent["font_family"],
                str(p.get("anim_in_type") or "fade"),
                bool(p.get("use_box")),
                str(p.get("box_brush_style") or "rect"),
                bool(p.get("dynamic_box")),
                bool(p.get("extrude_3d_enabled")),
                bool(p.get("stroke_expand_enabled")),
                round(float(p.get("fontsize") or 84) / 8.0),
            )
        else:
            layers = ent["style_obj"].get("layers") or []
            sig = ("overlay", ent["font_family"], len(layers), tuple(l.get("type") for l in layers))

        if sig in seen_struct:
            prev_i = seen_struct[sig]
            reports[idx]["failed_gates"] = sorted(set(reports[idx]["failed_gates"] + ["S09_ANTI_HOMOGENIZATION_DEDUP"]))
            reports[idx]["status"] = "FAIL"
            reports[idx]["notes"].append(f"structural clone / color-swap duplicate of item #{prev_i + 1}")
        else:
            seen_struct[sig] = idx

    # Online catalog soft-check (warning only, does not block re-checking published items)
    if online_items:
        online_sigs = {}
        for oi in online_items:
            if oi.get("kind") != "subtitle":
                continue
            op = ((oi.get("style") or {}).get("raw_style_params")) or {}
            osig = (
                oi.get("font_family"),
                str(op.get("anim_in_type") or ""),
                bool(op.get("use_box")),
                str(op.get("color_text") or "").upper(),
                str(op.get("color_outline") or "").upper(),
                str(op.get("color_bg") or "").upper(),
            )
            online_sigs[osig] = oi.get("id")
        for idx, ent in enumerate(entries):
            if ent["kind"] != "subtitle" or ent["id"]:
                continue
            p = ent["raw_p"]
            esig = (
                ent["font_family"],
                str(p.get("anim_in_type") or ""),
                bool(p.get("use_box")),
                str(p.get("color_text") or "").upper(),
                str(p.get("color_outline") or "").upper(),
                str(p.get("color_bg") or "").upper(),
            )
            if esig in online_sigs:
                reports[idx]["notes"].append(f"matches online item {online_sigs[esig]}")


def generate_preview_sheet(entries: list[dict], reports: list[dict], fonts_map: dict, out_sheet: Path) -> dict:
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("node binary not found for Skia preview sheet")

    with tempfile.TemporaryDirectory(prefix="vnsub_qa_sheet_") as td:
        tmp_dir = Path(td)
        job_path = tmp_dir / "job.json"
        used_fonts = {}
        for ent in entries:
            fam = ent["font_family"]
            if fam in fonts_map:
                used_fonts[fam] = fonts_map[fam]
        job = {
            "out_dir": str(tmp_dir),
            "font_map": used_fonts,
            "items": [
                {
                    "title": e["title"],
                    "kind": e["kind"],
                    "stage_bg": e["stage_bg"],
                    "sample_text_vi": e["sample_text_vi"],
                    "style_obj": e["style_obj"],
                }
                for e in entries
            ],
        }
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([node_bin, str(RENDER_TILES_MJS), "--job", str(job_path)], capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(f"render_sub_preview_tiles.mjs failed:\n{proc.stderr}\n{proc.stdout}")
        render_res = json.loads(proc.stdout)

        tile_w, tile_h = 270, 480
        info_w = 340
        font_body = _load_ui_font(13)
        font_hdr = _load_ui_font(12)
        max_cols = max((len(r["tiles"]) for r in render_res["results"]), default=2)
        sheet_w = info_w + max_cols * (tile_w + 8) + 8
        sheet_h = len(entries) * (tile_h + 26) + 8
        sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 22, 32))
        dr = ImageDraw.Draw(sheet)

        for row_i, item_res in enumerate(render_res["results"]):
            rep = reports[row_i]
            if item_res.get("clipped_any"):
                rep["failed_gates"] = sorted(set(rep["failed_gates"] + ["S05_SAFE_BOUNDS_AND_SIZE"]))
                rep["status"] = "FAIL"
                rep["notes"].append("Skia rendered pixels touched canvas border")

            y0 = row_i * (tile_h + 26) + 6
            col = (74, 222, 128) if rep["status"] == "PASS" else (248, 113, 113)
            fail_str = ", ".join(rep["failed_gates"]) or "NONE"
            wrapped_title = textwrap.wrap(rep["title"], width=22)[:2]
            wrapped_fail = textwrap.wrap(f"Fail: {fail_str}", width=34)[:3]
            txt = "\n".join([
                f"{rep['status']} | #{row_i+1} {rep['id']}",
                *wrapped_title,
                f"Font: {rep['font_family']}",
                f"Stage: {rep['stage_bg']}",
                f"Anim: {entries[row_i]['raw_p'].get('anim_in_type','overlay')}",
                *wrapped_fail,
            ])
            dr.text((10, y0 + 14), txt, fill=col, font=font_body)

            for c_i, tile in enumerate(item_res["tiles"]):
                x0 = info_w + c_i * (tile_w + 8)
                im = Image.open(tile["path"]).convert("RGB").resize((tile_w, tile_h), Image.Resampling.LANCZOS)
                sheet.paste(im, (x0, y0 + 18))
                dr.text((x0 + 4, y0 + 2), f"{tile['tag']} clip={tile['clipped']}", fill=(203, 213, 225), font=font_hdr)

        out_sheet.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out_sheet, quality=92)
        return render_res


def main():
    ap = argparse.ArgumentParser(description="9-Gate Subtitle/Overlay Pre-Flight QA + Skia Preview Sheet")
    ap.add_argument("--file", required=True)
    ap.add_argument("--catalog-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--preview-sheet", default=None)
    ap.add_argument("--skip-online", action="store_true")
    args = ap.parse_args()

    if args.skip_online:
        fonts_map, online_items = dict(FONT_REGISTRY_56), []
    else:
        fonts_map, online_items = _fetch_online_catalog(args.catalog_url)

    entries = _unpack_raw_items(Path(args.file))
    reports = [lint_entry(i + 1, ent, fonts_map) for i, ent in enumerate(entries)]
    check_dedup_and_anti_homogenization(entries, reports, online_items)

    if args.preview_sheet:
        generate_preview_sheet(entries, reports, fonts_map, Path(args.preview_sheet))

    failed = sum(1 for r in reports if r["status"] == "FAIL")
    out = {
        "ok": failed == 0,
        "total": len(reports),
        "passed": len(reports) - failed,
        "failed": failed,
        "preview_sheet": str(args.preview_sheet) if args.preview_sheet else None,
        "reports": reports,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
