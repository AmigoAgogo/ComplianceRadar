from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "dist" / "demo_ppt_assets"
OUT = ROOT / "dist" / "ComplianceRadar_Global_Demo.pptx"

NAVY = RGBColor(9, 31, 47)
TEAL = RGBColor(0, 151, 167)
MINT = RGBColor(178, 235, 242)
WHITE = RGBColor(255, 255, 255)
INK = RGBColor(28, 42, 54)
MUTED = RGBColor(91, 111, 128)
PAPER = RGBColor(246, 249, 251)
AMBER = RGBColor(247, 181, 56)


def add_textbox(slide, x, y, w, h, text, size=20, color=INK, bold=False, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    frame.margin_left = 0
    frame.margin_right = 0
    frame.margin_top = 0
    frame.margin_bottom = 0
    p = frame.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    font = run.font
    font.name = "Aptos"
    font.size = Pt(size)
    font.bold = bold
    font.color.rgb = color
    return box


def add_title(slide, title, subtitle=None):
    add_textbox(slide, 0.55, 0.34, 9.4, 0.48, title, size=24, color=WHITE, bold=True)
    if subtitle:
        add_textbox(slide, 0.58, 0.83, 10.0, 0.3, subtitle, size=9.5, color=MINT)


def add_header_band(slide):
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(1.18))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(1.15), Inches(13.333), Inches(0.07))
    accent.fill.solid()
    accent.fill.fore_color.rgb = TEAL
    accent.line.fill.background()


def add_footer(slide, page):
    add_textbox(slide, 0.58, 7.14, 5.2, 0.22, "ComplianceRadar POC | Siemens China Compliance Demo", 7.5, MUTED)
    add_textbox(slide, 12.42, 7.14, 0.35, 0.22, str(page), 7.5, MUTED, align=PP_ALIGN.RIGHT)


def add_bullets(slide, x, y, w, h, bullets, size=15, color=INK):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for i, bullet in enumerate(bullets):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.text = bullet
        p.level = 0
        p.font.name = "Aptos"
        p.font.size = Pt(size)
        p.font.color.rgb = color
        p.space_after = Pt(7)
    return box


def add_card(slide, x, y, w, h, title, body, fill=PAPER):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = RGBColor(220, 229, 235)
    add_textbox(slide, x + 0.16, y + 0.13, w - 0.3, 0.22, title, size=12, color=NAVY, bold=True)
    add_textbox(slide, x + 0.16, y + 0.44, w - 0.3, h - 0.5, body, size=11, color=MUTED)


def add_simple_bar_chart(slide, x, y, w, h, labels, values, colors):
    max_value = max(values) if values else 1
    chart_w = w - 0.5
    bar_w = chart_w / max(len(values), 1) - 0.1
    baseline = y + h - 0.35
    baseline_line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(baseline), Inches(w), Inches(0.02))
    baseline_line.fill.solid()
    baseline_line.fill.fore_color.rgb = RGBColor(200, 210, 220)
    baseline_line.line.fill.background()
    for idx, value in enumerate(values):
        bar_h = max(0.2, (h - 0.75) * value / max_value)
        bx = x + 0.15 + idx * (bar_w + 0.12)
        by = baseline - bar_h
        bar = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(bx), Inches(by), Inches(bar_w), Inches(bar_h))
        bar.fill.solid()
        bar.fill.fore_color.rgb = colors[idx % len(colors)]
        bar.line.fill.background()
        add_textbox(slide, bx - 0.02, baseline + 0.03, bar_w + 0.04, 0.26, labels[idx], 9, MUTED, False, PP_ALIGN.CENTER)
        add_textbox(slide, bx - 0.02, by - 0.23, bar_w + 0.04, 0.18, str(value), 11, NAVY, True, PP_ALIGN.CENTER)


def add_screenshot(slide, path, x, y, w, h):
    image = Path(path)
    if image.exists():
        pic = slide.shapes.add_picture(str(image), Inches(x), Inches(y), width=Inches(w))
        if pic.height > Inches(h):
            pic.height = Inches(h)
        pic.left = Inches(x)
        pic.top = Inches(y)
        frame = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x - 0.03), Inches(y - 0.03), Inches(w + 0.06), pic.height + Inches(0.06))
        frame.fill.background()
        frame.line.color.rgb = RGBColor(207, 220, 230)
        slide.shapes._spTree.remove(frame._element)
        slide.shapes._spTree.insert(2, frame._element)
        return pic
    return None


def build() -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    # Slide 1
    slide = prs.slides.add_slide(blank)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    cover_accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(6.78), prs.slide_width, Inches(0.18))
    cover_accent.fill.solid()
    cover_accent.fill.fore_color.rgb = TEAL
    cover_accent.line.fill.background()
    add_textbox(slide, 0.72, 1.05, 10.6, 0.65, "ComplianceRadar", 42, WHITE, True)
    add_textbox(slide, 0.78, 1.86, 10.2, 0.52, "Board-Level Early Warning for China Leasing & Factoring", 22, MINT)
    add_textbox(slide, 0.8, 2.7, 8.8, 0.82, "Evidence-backed regulatory signal, packaged as a portable executive demo.", 22, WHITE)
    add_card(slide, 0.82, 4.55, 3.75, 1.05, "Purpose", "Turn verified China signals into board-ready insight.", RGBColor(235, 250, 251))
    add_card(slide, 4.82, 4.55, 3.75, 1.05, "Audience", "China management and Global Compliance.", RGBColor(235, 250, 251))
    add_card(slide, 8.82, 4.55, 3.75, 1.05, "Rule", "No fake links. No placeholder institutions.", RGBColor(235, 250, 251))

    # Slide 2
    slide = prs.slides.add_slide(blank)
    add_header_band(slide)
    add_title(slide, "1. The Business Problem", "The issue is signal quality, not data volume.")
    add_bullets(slide, 0.75, 1.68, 5.7, 4.7, [
        "Official sources are fragmented across regulators and local bureaus.",
        "Manual monitoring does not scale across leasing, factoring, and penalties.",
        "Global teams need a short answer with original evidence attached.",
    ], 15)
    add_simple_bar_chart(slide, 7.0, 2.0, 5.2, 2.45, ["Source spread", "Manual burden", "Traceability gap", "Exec brief"], [8, 9, 10, 7], [TEAL, AMBER, NAVY, RGBColor(102, 187, 106)])
    add_card(slide, 7.05, 4.72, 5.2, 0.82, "Target State", "Weekly and ad hoc intelligence with real evidence.", RGBColor(233, 249, 246))
    add_footer(slide, 2)

    # Slide 3
    slide = prs.slides.add_slide(blank)
    add_header_band(slide)
    add_title(slide, "2. How Codex Built It", "From thread to executable in four moves.")
    steps = [
        ("1", "Business Need", "China leasing and factoring regulatory monitoring."),
        ("2", "Architecture", "Source Center, Model Gateway, Event Library, Regulatory Radar."),
        ("3", "Build", "GUI, APIs, persistence, evidence storage, executable packaging."),
        ("4", "Verification", "Real source sync tests, packaged exe launch, transparent failure reporting."),
    ]
    x = 0.78
    for num, title, body in steps:
        circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(2.0), Inches(0.58), Inches(0.58))
        circle.fill.solid()
        circle.fill.fore_color.rgb = TEAL
        circle.line.fill.background()
        add_textbox(slide, x + 0.16, 2.12, 0.25, 0.2, num, 12, WHITE, True, PP_ALIGN.CENTER)
        add_card(slide, x + 0.75, 1.72, 2.15, 1.08, title, body)
        if num != "4":
            add_textbox(slide, x + 3.05, 2.14, 0.4, 0.2, "→", 24, TEAL, True, PP_ALIGN.CENTER)
        x += 3.1
    add_screenshot(slide, ASSETS / "dashboard.png", 0.82, 3.56, 11.7, 2.45)
    add_footer(slide, 3)

    # Slide 4
    slide = prs.slides.add_slide(blank)
    add_header_band(slide)
    add_title(slide, "3. What the Tool Does", "A compact workflow from source to warning.")
    add_screenshot(slide, ASSETS / "event_library.png", 0.65, 1.58, 5.85, 4.05)
    add_screenshot(slide, ASSETS / "source_center.png", 7.0, 1.58, 5.65, 4.05)
    add_card(slide, 0.76, 5.82, 3.85, 0.65, "Event Library", "Real articles and verified links.")
    add_card(slide, 4.78, 5.82, 3.85, 0.65, "Source Center", "Official sources with transparent status.")
    add_card(slide, 8.8, 5.82, 3.45, 0.65, "Review & Export", "Evidence trail and module reports.")
    add_footer(slide, 4)

    # Slide 5
    slide = prs.slides.add_slide(blank)
    add_header_band(slide)
    add_title(slide, "4. How to Use It", "Four steps, one clear result.")
    add_bullets(slide, 0.78, 1.58, 5.3, 4.8, [
        "Open the executable.",
        "Choose a period.",
        "Update sources and review the results.",
    ], 16)
    add_screenshot(slide, ASSETS / "dashboard.png", 6.46, 1.48, 5.9, 4.45)
    add_card(slide, 6.65, 6.06, 5.5, 0.52, "Demo note", "Timeouts stay visible instead of being hidden.", RGBColor(255, 248, 232))
    add_footer(slide, 5)

    # Slide 6
    slide = prs.slides.add_slide(blank)
    add_header_band(slide)
    add_title(slide, "5. Why the Embedded Agent Matters", "It turns source events into management language.")
    add_screenshot(slide, ASSETS / "regulatory_radar.png", 0.68, 1.45, 5.95, 4.55)
    add_screenshot(slide, ASSETS / "model_gateway.png", 7.03, 1.45, 5.62, 4.55)
    add_card(slide, 0.78, 6.12, 3.72, 0.62, "Input", "Events, evidence, time window.")
    add_card(slide, 4.78, 6.12, 3.72, 0.62, "Agent Logic", "Configured role and style.")
    add_card(slide, 8.78, 6.12, 3.72, 0.62, "Output", "Short early warning.")
    add_footer(slide, 6)

    # Slide 7
    slide = prs.slides.add_slide(blank)
    add_header_band(slide)
    add_title(slide, "6. Demo Takeaways", "What Global should remember.")
    add_bullets(slide, 0.78, 1.58, 5.8, 4.35, [
        "Evidence first.",
        "Transparent failures.",
        "Portable executable.",
        "Management-ready warning.",
    ], 15)
    add_card(slide, 7.05, 1.7, 5.2, 0.88, "Next Step", "Harden source adapters.")
    add_card(slide, 7.05, 2.86, 5.2, 0.88, "AI Step", "Make the Agent sharper.")
    add_card(slide, 7.05, 4.02, 5.2, 0.88, "Scale Step", "Expand official coverage.")
    add_textbox(slide, 7.05, 5.62, 5.2, 0.42, "Bottom line: ComplianceRadar turns China signals into traceable early warning.", 15, NAVY, True)
    add_footer(slide, 7)

    prs.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
