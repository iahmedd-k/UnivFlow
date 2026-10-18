import logging
import re
import html
import base64
import zlib
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


def _is_light_color(hex_color: str) -> bool:
    try:
        c = hex_color.lstrip("#")
        if len(c) == 3:
            c = "".join([x * 2 for x in c])
        if len(c) == 6:
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            return (0.299 * r + 0.587 * g + 0.114 * b) > 135
    except Exception:
        pass
    return False


def _parse_label_lines(raw_val: str) -> List[str]:
    """Parse HTML/text label into clean lines, removing tags while preserving breaks."""
    if not raw_val:
        return []
    # Replace breaks and div closures with newline marker
    text = re.sub(r"<br\s*/?>", "\n", raw_val, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<hr\s*/?>", "\n---\n", text, flags=re.IGNORECASE)
    text = re.sub(r"&bull;", "• ", text, flags=re.IGNORECASE)
    text = html.unescape(text)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return lines


def _render_single_diagram_model(model_elem: ET.Element, title: str = "") -> Optional[str]:
    """Render a single mxGraphModel or diagram root into an SVG string."""
    cells = model_elem.findall(".//mxCell")
    if not cells:
        return None

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    for cell in cells:
        cid = cell.get("id")
        if cid in ("0", "1") and not cell.get("value"):
            continue

        raw_val = cell.get("value") or ""
        lines = _parse_label_lines(raw_val)
        style = cell.get("style") or ""
        geom = cell.find("mxGeometry")

        # Parse style properties
        fill = "#1e293b"
        stroke = "#38bdf8"
        font_color = None
        stroke_width = "2"
        is_title = "text;" in style or "fontSize=16" in style

        for s in style.split(";"):
            s_clean = s.strip()
            if s_clean.startswith("fillColor="):
                fill = s_clean.split("=")[1]
            elif s_clean.startswith("strokeColor="):
                stroke = s_clean.split("=")[1]
            elif s_clean.startswith("fontColor="):
                font_color = s_clean.split("=")[1]
            elif s_clean.startswith("strokeWidth="):
                stroke_width = s_clean.split("=")[1]

        if not font_color:
            font_color = "#0f172a" if _is_light_color(fill) else "#f8fafc"

        if cell.get("vertex") == "1" and geom is not None:
            try:
                x = float(geom.get("x", 0))
                y = float(geom.get("y", 0))
                w = float(geom.get("width", 160))
                h = float(geom.get("height", 70))
                nodes[cid] = {
                    "id": cid,
                    "lines": lines,
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "fill": fill,
                    "stroke": stroke,
                    "stroke_width": stroke_width,
                    "font_color": font_color,
                    "is_title": is_title,
                }
            except Exception:
                pass
        elif cell.get("edge") == "1":
            label_text = " ".join(lines) if lines else ""
            edges.append({
                "source": cell.get("source"),
                "target": cell.get("target"),
                "label": label_text,
                "stroke": stroke if stroke != "#38bdf8" else ("#f87171" if "CC0000" in style.upper() else "#38bdf8"),
                "stroke_width": stroke_width if stroke_width != "2" else ("3.5" if "4" in stroke_width else "2"),
            })

    if not nodes:
        return None

    min_x = min(n["x"] for n in nodes.values())
    min_y = min(n["y"] for n in nodes.values())
    max_x = max(n["x"] + n["w"] for n in nodes.values())
    max_y = max(n["y"] + n["h"] for n in nodes.values())

    pad = 40
    width = max(700, int(max_x - min_x + pad * 2))
    height = max(350, int(max_y - min_y + pad * 2))
    shift_x = pad - min_x
    shift_y = pad - min_y

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        '  <defs>',
        '    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="#38bdf8" />',
        '    </marker>',
        '    <marker id="arrow-red" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="#f87171" />',
        '    </marker>',
        '    <marker id="arrow-dark" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748b" />',
        '    </marker>',
        '    <filter id="shadow" x="-5%" y="-5%" width="110%" height="115%">',
        '      <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000000" flood-opacity="0.35"/>',
        '    </filter>',
        '  </defs>',
        f'  <rect width="{width}" height="{height}" fill="#0f172a" rx="14"/>',
    ]

    # Draw edge lines
    for edge in edges:
        s_node = nodes.get(edge["source"])
        t_node = nodes.get(edge["target"])
        if s_node and t_node:
            sx = s_node["x"] + shift_x + s_node["w"] / 2
            sy = s_node["y"] + shift_y + s_node["h"] / 2
            tx = t_node["x"] + shift_x + t_node["w"] / 2
            ty = t_node["y"] + shift_y + t_node["h"] / 2
            edge_color = edge["stroke"]
            marker_id = "arrow-red" if "#F87171" in edge_color.upper() or "CC0000" in edge_color.upper() else "arrow"
            svg_parts.append(
                f'  <line x1="{sx}" y1="{sy}" x2="{tx}" y2="{ty}" stroke="{edge_color}" stroke-width="{edge["stroke_width"]}" marker-end="url(#{marker_id})"/>'
            )
            if edge["label"]:
                mx = (sx + tx) / 2
                my = (sy + ty) / 2 - 8
                svg_parts.append(
                    f'  <rect x="{mx - 80}" y="{my - 12}" width="160" height="20" fill="#0f172a" fill-opacity="0.8" rx="4"/>'
                )
                svg_parts.append(
                    f'  <text x="{mx}" y="{my + 2}" fill="{edge_color}" font-family="Segoe UI, sans-serif" font-size="11" font-weight="600" text-anchor="middle">{html.escape(edge["label"])}</text>'
                )

    # Draw nodes
    for n in nodes.values():
        nx = n["x"] + shift_x
        ny = n["y"] + shift_y
        nw = n["w"]
        nh = n["h"]

        if n["is_title"]:
            title_text = " ".join(n["lines"])
            svg_parts.append(
                f'  <text x="{nx + nw/2}" y="{ny + nh/2 + 6}" fill="#f8fafc" font-family="Segoe UI, sans-serif" font-size="16" font-weight="bold" text-anchor="middle">{html.escape(title_text)}</text>'
            )
            continue

        svg_parts.append(
            f'  <rect x="{nx}" y="{ny}" width="{nw}" height="{nh}" rx="8" fill="{n["fill"]}" stroke="{n["stroke"]}" stroke-width="{n["stroke_width"]}" filter="url(#shadow)"/>'
        )

        lines = n["lines"]
        if not lines:
            continue

        # Header / first line
        header_line = lines[0]
        has_divider = len(lines) > 1 and (lines[1] == "---" or len(lines) > 2)
        start_y = ny + 24 if len(lines) > 1 else ny + nh / 2 + 5

        svg_parts.append(
            f'  <text x="{nx + 14 if len(lines) > 1 else nx + nw/2}" y="{start_y}" fill="{n["font_color"]}" font-family="Segoe UI, sans-serif" font-size="13" font-weight="bold" text-anchor="{"start" if len(lines) > 1 else "middle"}">{html.escape(header_line)}</text>'
        )

        curr_y = start_y + 8
        if has_divider:
            curr_y += 6
            svg_parts.append(
                f'  <line x1="{nx + 10}" y1="{curr_y}" x2="{nx + nw - 10}" y2="{curr_y}" stroke="{n["stroke"]}" stroke-opacity="0.4" stroke-width="1"/>'
            )
            curr_y += 14

        for body_line in lines[1:]:
            if body_line == "---":
                continue
            svg_parts.append(
                f'  <text x="{nx + 14}" y="{curr_y}" fill="{n["font_color"]}" fill-opacity="0.9" font-family="Segoe UI, sans-serif" font-size="11" text-anchor="start">{html.escape(body_line)}</text>'
            )
            curr_y += 16
            if curr_y > ny + nh - 8:
                break

    svg_parts.append('</svg>')
    return "\n".join(svg_parts)


def drawio_xml_to_all_svgs(xml_text: str) -> List[Tuple[str, str]]:
    """
    Parse Draw.io XML (<mxfile> or <mxGraphModel>) and return a list of
    (diagram_name_or_id, svg_content) tuples for every diagram page.
    """
    if not xml_text or not isinstance(xml_text, str):
        return []

    target_xml = xml_text.strip()
    try:
        root = ET.fromstring(target_xml)
    except Exception as err:
        logger.debug(f"Could not parse Draw.io XML root: {err}")
        return []

    results: List[Tuple[str, str]] = []
    diagram_nodes = root.findall(".//diagram")

    if diagram_nodes:
        for idx, diag in enumerate(diagram_nodes, 1):
            diag_name = diag.get("name") or diag.get("id") or f"diagram_{idx}"
            # Check if diagram content is compressed
            mx_model = diag.find(".//mxGraphModel")
            if mx_model is not None:
                svg = _render_single_diagram_model(mx_model, title=diag_name)
                if svg:
                    results.append((diag_name, svg))
            else:
                raw_inner = (diag.text or "").strip()
                if raw_inner:
                    try:
                        raw_bytes = base64.b64decode(raw_inner)
                        decompressed = urllib.parse.unquote(zlib.decompress(raw_bytes, -15).decode("utf-8"))
                        inner_root = ET.fromstring(decompressed)
                        svg = _render_single_diagram_model(inner_root, title=diag_name)
                        if svg:
                            results.append((diag_name, svg))
                    except Exception as dec_err:
                        logger.debug(f"Decompress diagram failed: {dec_err}")
    else:
        # Single mxGraphModel without <diagram> wrapper
        svg = _render_single_diagram_model(root, title="Architecture Diagram")
        if svg:
            results.append(("diagram", svg))

    return results


def drawio_xml_to_svg(xml_text: str, diagram_index: int = 0) -> Optional[str]:
    """Parse Draw.io XML and generate an SVG for the specified diagram page (default 0)."""
    svg_list = drawio_xml_to_all_svgs(xml_text)
    if not svg_list:
        return None
    if 0 <= diagram_index < len(svg_list):
        return svg_list[diagram_index][1]
    return svg_list[0][1]


def render_svg_to_png(svg_content: str, width: int = 1200, scale: int = 2, page=None) -> Optional[bytes]:
    """
    Render SVG markup to high-definition PNG bytes using Playwright headless Chromium.
    If an existing Playwright page is provided, reuses it for instant zero-overhead capture.
    """
    if not svg_content or not isinstance(svg_content, str):
        return None

    clean_svg = svg_content.strip()
    if not clean_svg.startswith("<svg") and "<svg" in clean_svg:
        match = re.search(r"<svg.*?</svg>", clean_svg, re.DOTALL | re.IGNORECASE)
        if match:
            clean_svg = match.group(0)

    if not clean_svg.startswith("<svg"):
        return None

    html_page = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        f"<body style='margin:0;padding:20px;background:#0f172a;display:inline-block;'>{clean_svg}</body></html>"
    )

    if page is not None:
        try:
            page.set_content(html_page)
            svg_el = page.locator("svg").first
            return svg_el.screenshot(type="png")
        except Exception as reuse_err:
            logger.debug(f"Could not reuse existing page for SVG render: {reuse_err}")

    try:
        from playwright.sync_api import sync_playwright
        flags = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ]
        with sync_playwright() as p:
            browser = None
            try:
                browser = p.chromium.launch(channel="chrome", headless=True, args=flags)
            except Exception:
                try:
                    browser = p.chromium.launch(headless=True, args=flags)
                except Exception as launch_err:
                    logger.warning(f"Playwright chromium launch failed: {launch_err}")
                    return None

            p_page = browser.new_page(
                viewport={"width": width, "height": 800},
                device_scale_factor=scale,
            )
            p_page.set_content(html_page)
            svg_el = p_page.locator("svg").first
            png_bytes = svg_el.screenshot(type="png")
            browser.close()
            return png_bytes
    except Exception as err:
        logger.warning(f"SVG to PNG rendering failed: {err}")
        return None


def render_diagrams_to_png_list(content: str, language: str = "drawio", page=None) -> List[Tuple[str, bytes]]:
    """
    Universal diagram renderer that handles single or multi-page diagram specifications.
    Returns list of (suggested_filename, png_bytes).
    """
    if not content or not isinstance(content, str):
        return []

    stripped = content.strip()
    lang = (language or "").lower()
    results: List[Tuple[str, bytes]] = []

    # 1. Direct SVG content
    if "<svg" in stripped:
        png = render_svg_to_png(stripped, page=page)
        if png:
            results.append(("diagram.png", png))
            return results

    # 2. Draw.io XML (<mxfile> or <mxGraphModel>)
    is_drawio = (
        lang in ("drawio", "drawio.xml", "mxfile", "xml")
        or "<mxfile" in stripped
        or "<mxGraphModel" in stripped
    )
    if is_drawio:
        svg_pairs = drawio_xml_to_all_svgs(stripped)
        for idx, (diag_name, svg_code) in enumerate(svg_pairs, 1):
            clean_name = re.sub(r"[^A-Za-z0-9_-]", "_", diag_name).strip("_") or f"diagram_{idx}"
            png = render_svg_to_png(svg_code, page=page)
            if png:
                results.append((f"{clean_name}.png", png))

    return results


def render_diagram_to_png(content: str, language: str = "drawio", page=None) -> Optional[bytes]:
    """Universal diagram renderer returning the primary PNG bytes."""
    png_list = render_diagrams_to_png_list(content, language=language, page=page)
    if png_list:
        return png_list[0][1]
    return None
