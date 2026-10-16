import html
import base64
import urllib.parse
import textwrap
from io import BytesIO
from typing import Optional, List, Dict, Any


class TerminalCardRenderer:
    """
    Renders high-definition, dark-mode terminal window images (SVG / Data-URI / HTML)
    for embedding directly into university lab reports and assignment Google Docs.
    """

    DARK_THEME = {
        "bg": "#0f172a",          # Deep navy slate
        "header_bg": "#1e293b",   # Title bar background
        "border": "#334155",      # Border outline
        "dot_red": "#ef4444",     # Close button
        "dot_yellow": "#f59e0b",  # Minimize button
        "dot_green": "#10b981",   # Maximize button
        "text_prompt": "#38bdf8", # Sky blue prompt
        "text_cmd": "#f8fafc",    # White command text
        "text_output": "#cbd5e1", # Crisp light slate output text
        "text_success": "#4ade80",# Green success highlights
        "text_dim": "#64748b",    # Dim gray comments/meta
    }

    @classmethod
    def _get_fonts(cls):
        from PIL import ImageFont
        font = None
        title_font = None
        for font_path in [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/consolab.ttf",
            "C:/Windows/Fonts/lucon.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "DejaVuSansMono.ttf"
        ]:
            try:
                font = ImageFont.truetype(font_path, 20)
                break
            except Exception:
                continue

        for tfont_path in [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "DejaVuSans.ttf"
        ]:
            try:
                title_font = ImageFont.truetype(tfont_path, 16)
                break
            except Exception:
                continue

        if not font:
            font = ImageFont.load_default()
        if not title_font:
            title_font = font
        return font, title_font

    @classmethod
    def generate_single_card_png(cls, command: str, raw_lines: List[str], title: str = "Assignment code run", is_continuation: bool = False) -> bytes:
        """Render a single high-definition terminal card PNG from a given list of wrapped lines."""
        from PIL import Image, ImageDraw

        width = 1280
        font, title_font = cls._get_fonts()

        cmd_prefix = "$ " if not is_continuation else "$ ... (continued) "
        lines = [f"{cmd_prefix}{command or 'run solution file'}"] + (raw_lines or ["No output."])

        line_height = 26
        header_height = 48
        height = max(170, header_height + 28 + line_height * len(lines) + 24)
        image = Image.new("RGB", (width, height), cls.DARK_THEME["bg"])
        draw = ImageDraw.Draw(image)

        def image_text(value: str) -> str:
            return "".join(char if 32 <= ord(char) < 127 else " " for char in str(value))

        draw.rounded_rectangle((2, 2, width - 3, height - 3), radius=14, fill=cls.DARK_THEME["bg"], outline=cls.DARK_THEME["border"], width=2)
        draw.rounded_rectangle((3, 3, width - 4, header_height), radius=13, fill=cls.DARK_THEME["header_bg"])
        draw.rectangle((3, header_height - 10, width - 4, header_height), fill=cls.DARK_THEME["header_bg"])
        for x, color in ((24, cls.DARK_THEME["dot_red"]), (46, cls.DARK_THEME["dot_yellow"]), (68, cls.DARK_THEME["dot_green"])):
            draw.ellipse((x - 7, 18, x + 7, 32), fill=color)
        draw.text((96, 15), image_text(title[:100]), font=title_font, fill="#cbd5e1")

        y = header_height + 24
        for index, line in enumerate(lines):
            if index == 0:
                color = cls.DARK_THEME["text_prompt"]
            elif any(word in line.lower() for word in ("error", "failed", "traceback", "exception")):
                color = cls.DARK_THEME["dot_red"]
            elif any(word in line.lower() for word in ("success", "passed", "complete", "ok")):
                color = cls.DARK_THEME["text_success"]
            else:
                color = cls.DARK_THEME["text_output"]
            draw.text((24, y), image_text(line), font=font, fill=color)
            y += line_height

        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    @classmethod
    def generate_terminal_pngs(cls, command: str, output_text: str, title: str = "Terminal Output", max_lines_per_card: int = 24) -> List[bytes]:
        """
        Render terminal output into one or multiple high-definition PNG screenshots.
        If output is large, splits cleanly into Part 1, Part 2 (half-and-half / multi-part)
        so 100% of the terminal evidence is preserved and visible.
        """
        source_lines = (output_text or "").strip().splitlines() or ["No output."]
        wrapped_lines: List[str] = []
        for line in source_lines:
            wrapped_lines.extend(textwrap.wrap(line, width=104, replace_whitespace=False, drop_whitespace=False) or [""])

        total_lines = len(wrapped_lines)
        if total_lines <= max_lines_per_card:
            # Single card is sufficient
            png_bytes = cls.generate_single_card_png(command, wrapped_lines, title=title, is_continuation=False)
            return [png_bytes]

        # Multiple cards needed (split half and half or into chunks of max_lines_per_card)
        num_parts = (total_lines + max_lines_per_card - 1) // max_lines_per_card
        chunk_size = (total_lines + num_parts - 1) // num_parts

        png_list: List[bytes] = []
        for part_idx in range(num_parts):
            start = part_idx * chunk_size
            end = min(start + chunk_size, total_lines)
            chunk = wrapped_lines[start:end]
            part_title = f"{title} (Part {part_idx + 1}/{num_parts})"
            is_cont = part_idx > 0
            png_bytes = cls.generate_single_card_png(command, chunk, title=part_title, is_continuation=is_cont)
            png_list.append(png_bytes)

        return png_list

    @classmethod
    def generate_terminal_png(cls, command: str, output_text: str, title: str = "Assignment code run") -> bytes:
        """Render captured terminal output into a single PNG image."""
        pngs = cls.generate_terminal_pngs(command, output_text, title=title, max_lines_per_card=80)
        return pngs[0] if pngs else b""

    @classmethod
    def generate_terminal_svg(
        cls,
        command: str,
        output_text: str,
        title: str = "bash — student@air-university: ~/lab-tasks",
        width: int = 760,
    ) -> str:
        """
        Generate a standalone, scalable vector SVG of a macOS/Linux terminal window.
        """
        theme = cls.DARK_THEME
        
        # Format output lines
        source_lines = (output_text or "").strip().splitlines() or ["No output."]
        raw_lines = []
        for line in source_lines:
            wrapped = textwrap.wrap(line, width=88, replace_whitespace=False, drop_whitespace=False) or [""]
            raw_lines.extend(wrapped)
        if len(raw_lines) > 48:
            raw_lines = ["… earlier output omitted …", *raw_lines[-47:]]
        escaped_command = html.escape(command or "python solution.py")
        
        # Calculate height dynamically based on output line count
        line_height = 22
        header_height = 42
        top_padding = 24
        bottom_padding = 24
        content_lines_count = max(len(raw_lines), 1) + 1  # +1 for the command line
        total_height = header_height + top_padding + (content_lines_count * line_height) + bottom_padding
        
        # Build SVG text elements for lines
        rendered_lines = []
        y_pos = header_height + top_padding

        # Line 0: Command prompt line
        rendered_lines.append(
            f'<text x="24" y="{y_pos}" font-family="Consolas, \'Fira Code\', Monaco, monospace" font-size="13" font-weight="600">'
            f'<tspan fill="{theme["text_prompt"]}">user@air-uni:~$ </tspan>'
            f'<tspan fill="{theme["text_cmd"]}">{escaped_command}</tspan>'
            f'</text>'
        )
        y_pos += line_height

        # Subsequent lines: Output
        for line in raw_lines:
            escaped_line = html.escape(line)
            fill_color = theme["text_output"]
            
            # Syntax highlights for typical terminal outputs
            if any(k in line.lower() for k in ["[+]", "[ok]", "success", "passed", "complete", "accuracy"]):
                fill_color = theme["text_success"]
            elif any(k in line.lower() for k in ["[-]", "error", "failed", "warning", "traceback"]):
                fill_color = theme["dot_red"]
            elif line.startswith("#") or line.startswith("//"):
                fill_color = theme["text_dim"]

            rendered_lines.append(
                f'<text x="24" y="{y_pos}" font-family="Consolas, \'Fira Code\', Monaco, monospace" font-size="13" fill="{fill_color}">'
                f'{escaped_line}'
                f'</text>'
            )
            y_pos += line_height

        lines_svg = "\n    ".join(rendered_lines)
        escaped_title = html.escape(title)

        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total_height}" width="{width}" height="{total_height}">
  <defs>
    <filter id="card-shadow" x="-5%" y="-5%" width="110%" height="115%" filterUnits="userSpaceOnUse">
      <feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#000000" flood-opacity="0.35"/>
    </filter>
  </defs>

  <!-- Terminal Window Background -->
  <rect x="2" y="2" width="{width - 4}" height="{total_height - 4}" rx="12" fill="{theme["bg"]}" stroke="{theme["border"]}" stroke-width="1.5" filter="url(#card-shadow)" />

  <!-- Terminal Header Bar -->
  <path d="M 2 14 Q 2 2 14 2 L {width - 14} 2 Q {width - 2} 2 {width - 2} 14 L {width - 2} {header_height} L 2 {header_height} Z" fill="{theme["header_bg"]}" />
  <line x1="2" y1="{header_height}" x2="{width - 2}" y2="{header_height}" stroke="{theme["border"]}" stroke-width="1" />

  <!-- Window Control Buttons (Red, Yellow, Green) -->
  <circle cx="20" cy="21" r="6" fill="{theme["dot_red"]}" />
  <circle cx="38" cy="21" r="6" fill="{theme["dot_yellow"]}" />
  <circle cx="56" cy="21" r="6" fill="{theme["dot_green"]}" />

  <!-- Window Header Title -->
  <text x="{width / 2}" y="25" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="500" fill="#94a3b8">
    {escaped_title}
  </text>

  <!-- Terminal Output Content -->
  <g>
    {lines_svg}
  </g>
</svg>"""
        return svg_content

    @classmethod
    def get_data_uri(cls, command: str, output_text: str, title: Optional[str] = None) -> str:
        """Return base64 Data URI for direct web / markdown display."""
        svg_code = cls.generate_terminal_svg(
            command=command,
            output_text=output_text,
            title=title or "bash — student@air-university: ~"
        )
        b64 = base64.b64encode(svg_code.encode("utf-8")).decode("utf-8")
        return f"data:image/svg+xml;base64,{b64}"


class TerminalRenderer:
    """Renderer interface for capturing and embedding code terminal execution output."""
    @staticmethod
    def render_terminal_screenshot(command: str = "", stdout: str = "", stderr: str = "", exit_code: int = 0) -> Optional[str]:
        output = stdout or ""
        if stderr:
            output = f"{output}\n[stderr]\n{stderr}" if output else stderr
        if not output.strip():
            output = f"[Process completed with exit code {exit_code}]"
        png_bytes = TerminalCardRenderer.generate_terminal_png(command=command, output_text=output)
        if png_bytes:
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            return f"data:image/png;base64,{b64}"
        return None


class DiagramRenderer:
    """
    Renders Mermaid.js and PlantUML diagrams into high-resolution images for lab report flowcharts.
    """

    @staticmethod
    def get_mermaid_image_url(mermaid_code: str, theme: str = "default") -> str:
        """
        Converts Mermaid syntax to an image URL via the Kroki / QuickChart diagram rendering gateway.
        """
        clean_code = (mermaid_code or "").strip()
        if not clean_code:
            return ""
        
        # Clean markdown code blocks if wrapped
        if clean_code.startswith("```mermaid"):
            clean_code = clean_code[10:]
        if clean_code.startswith("```"):
            clean_code = clean_code[3:]
        if clean_code.endswith("```"):
            clean_code = clean_code[:-3]
        clean_code = clean_code.strip()

        # URL safe encoding for Quickchart / Kroki
        encoded = urllib.parse.quote(clean_code)
        return f"https://quickchart.io/chart?chart={encoded}&format=png&width=800"

    @staticmethod
    def generate_flowchart_svg(nodes: List[Dict[str, str]], title: str = "Algorithm Flowchart") -> str:
        """
        Builds a clean, self-contained SVG flowchart for standard lab task steps.
        """
        width = 700
        step_height = 55
        gap = 40
        total_height = 60 + len(nodes) * (step_height + gap)
        
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total_height}" width="{width}" height="{total_height}">',
            '<defs>',
            '  <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '    <path d="M 0 0 L 10 5 L 0 10 z" fill="#4f46e5" />',
            '  </marker>',
            '</defs>',
            f'<rect width="{width}" height="{total_height}" rx="12" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1.5" />',
            f'<text x="{width/2}" y="32" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="700" fill="#1e293b">{html.escape(title)}</text>'
        ]

        y = 60
        box_w = 420
        box_x = (width - box_w) / 2

        for i, node in enumerate(nodes):
            label = html.escape(node.get("label", f"Step {i+1}"))
            desc = html.escape(node.get("desc", ""))
            node_type = node.get("type", "process") # start, process, decision, end
            
            rx = "24" if node_type in ["start", "end"] else "8"
            bg = "#e0e7ff" if node_type in ["start", "end"] else "#ffffff"
            stroke = "#4f46e5" if node_type in ["start", "end"] else "#94a3b8"

            svg_parts.append(
                f'<rect x="{box_x}" y="{y}" width="{box_w}" height="{step_height}" rx="{rx}" fill="{bg}" stroke="{stroke}" stroke-width="1.5" />'
            )
            svg_parts.append(
                f'<text x="{width/2}" y="{y + 24}" text-anchor="middle" font-family="sans-serif" font-size="13" font-weight="600" fill="#1e1b4b">{label}</text>'
            )
            if desc:
                svg_parts.append(
                    f'<text x="{width/2}" y="{y + 42}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#64748b">{desc}</text>'
                )

            # Arrow to next step
            if i < len(nodes) - 1:
                arrow_y1 = y + step_height
                arrow_y2 = y + step_height + gap - 5
                svg_parts.append(
                    f'<line x1="{width/2}" y1="{arrow_y1}" x2="{width/2}" y2="{arrow_y2}" stroke="#4f46e5" stroke-width="2" marker-end="url(#arrow)" />'
                )

            y += step_height + gap

        svg_parts.append('</svg>')
        return "\n".join(svg_parts)
