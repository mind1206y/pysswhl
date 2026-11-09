"""测漏笔记 PDF 导出(照旧 LeakController.ExportPdf 布局复刻)。

reportlab 生成 A4 单页/多页 PDF:
- 标题、地点、详情描述(两列)、计算公式、备注、相关影像(每行 5 张)
- 中文字体优先用系统黑体/微软雅黑,找不到时回退 reportlab 内置 CID 字体
"""

import io
import os
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

_FONT = None
_FONT_CANDIDATES = [
    os.getenv("LEAK_PDF_FONT", ""),
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font_name() -> str:
    global _FONT
    if _FONT:
        return _FONT
    for path in _FONT_CANDIDATES:
        if not path or not Path(path).is_file():
            continue
        try:
            if path.lower().endswith(".ttc"):
                pdfmetrics.registerFont(TTFont("LeakCN", path, subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont("LeakCN", path))
            _FONT = "LeakCN"
            return _FONT
        except Exception:
            continue
    # reportlab 自带中文 CID 字体,不依赖字体文件
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _FONT = "STSong-Light"
    return _FONT


def _fmt_num(value, digits=2):
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_date(value):
    if not value:
        return "-"
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _fmt_time(value):
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _method_name(method):
    return {
        "coefficient": "面积乘系数法",
        "bucket": "桶量时间法",
        "meter": "水表读数法",
        "experience": "经验对比法",
    }.get(method or "", method or "-")


def _super_text(text):
    """转义用户文本,并把 ² / ³ 变成上标,避免 reportlab 解析标签报错。"""
    safe = escape(str(text or "-"))
    return safe.replace("²", "<super>2</super>").replace("³", "<super>3</super>")


def _remark_with_meta(record) -> str:
    remark = record.remark or "-"
    raw_meta = record.flow_meta or ""
    if raw_meta:
        import json
        try:
            meta = json.loads(raw_meta)
            original = meta.get("originalFlow")
            adjusted = meta.get("adjustedFlow")
            reason = meta.get("reason") or ""
            if original is not None:
                msg = (
                    f"原漏量值：{float(original):.2f} m³/h，因{reason}，"
                    f"最终值为：{float(adjusted or 0):.2f} m³/h"
                )
                if msg not in remark:
                    remark = msg if remark in ("", "-") else f"{remark}；{msg}"
        except Exception:
            pass
    return remark


def _compress_image(data: bytes, max_width: int = 180, quality: int = 50) -> bytes:
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            im.load()
            if im.width > max_width:
                height = max(1, int(im.height * max_width / im.width))
                im = im.resize((max_width, height), PILImage.LANCZOS)
            out = io.BytesIO()
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue()
    except Exception:
        return data


def build_pdf(record, images) -> bytes:
    """record: LeakRecord; images: [(文件名, 原始字节)]"""
    font = _font_name()
    body = ParagraphStyle("body", fontName=font, fontSize=8.5, leading=13,
                          textColor=colors.HexColor("#333333"))
    label = ParagraphStyle("label", parent=body, textColor=colors.HexColor("#555555"))
    title_style = ParagraphStyle("title", parent=body, fontSize=16, leading=22,
                                 textColor=colors.HexColor("#0d3b66"))
    section = ParagraphStyle("section", parent=body, fontSize=11.5, leading=16,
                             textColor=colors.HexColor("#0d3b66"), spaceBefore=4)
    name_style = ParagraphStyle("name", parent=body, fontSize=6.5, leading=9,
                                alignment=1, textColor=colors.HexColor("#666666"))
    block_style = ParagraphStyle("block", parent=body, fontSize=8.5, leading=13,
                                 textColor=colors.HexColor("#3f3118"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18, rightMargin=18, topMargin=22, bottomMargin=22,
        title=f"测漏记录详情 - {record.title or '-'}",
    )
    width = doc.width
    story = []

    story.append(Paragraph(_super_text(f"测漏记录详情 - {record.title or '-'}"), title_style))
    story.append(Spacer(1, 6))

    loc_table = Table(
        [[Paragraph(_super_text(f"地点：{record.location or '-'}"), body)]],
        colWidths=[width],
    )
    loc_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f7ff")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b8d8f0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(loc_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("详情描述", section))
    details = [
        ("记录ID", str(record.id)),
        ("记录时间", _fmt_time(record.create_time)),
        ("测漏人", record.detect_user or "-"),
        ("测漏队伍", record.detect_com or "-"),
        ("压力", f"{_fmt_num(record.pressure)} MPa"),
        ("面积", f"{_fmt_num(record.area)} cm²"),
        ("漏量", f"{_fmt_num(record.flow_rate)} m³/h"),
        ("排查类型", record.paicha_type or "-"),
        ("维修日期", _fmt_date(record.detect_time)),
        ("计量方法", _method_name(record.leak_method)),
    ]
    if record.leak_method == "bucket":
        details += [
            ("时间1/2/3", f"{_fmt_num(record.time1)} / {_fmt_num(record.time2)} / {_fmt_num(record.time3)} s"),
            ("平均时间", f"{_fmt_num(record.avg_time)} s"),
            ("定量桶", f"{_fmt_num(record.bucket_liters)} L"),
        ]
    elif record.leak_method == "meter":
        details += [
            ("计读时间", f"{_fmt_num(record.meter_time)} s"),
            ("计读流量", f"{_fmt_num(record.meter_volume, 3)} m³"),
        ]
    elif record.leak_method == "experience":
        details += [
            ("破口描述", record.experience_desc or "-"),
            ("估量漏量", f"{_fmt_num(record.experience_flow)} m³/h"),
        ]

    rows = []
    for i in range(0, len(details), 2):
        pair = details[i:i + 2]
        cells = [Paragraph(_super_text(f"{k}：{v}"), body) for k, v in pair]
        while len(cells) < 2:
            cells.append("")
        rows.append(cells)
    detail_table = Table(rows, colWidths=[width / 2, width / 2])
    detail_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(detail_table)
    story.append(Spacer(1, 8))

    def block(title_text, content):
        story.append(Paragraph(title_text, section))
        t = Table([[Paragraph(_super_text(content), block_style)]], colWidths=[width])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f7ff")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b8d8f0")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 8))

    block("计算公式", record.area_expression or "-")
    block("备注信息", _remark_with_meta(record))

    if images:
        story.append(Paragraph(f"相关影像（共{len(images)}张）", section))
        story.append(Spacer(1, 3))
        image_rows = []
        cell_width = width / 5
        for start in range(0, len(images), 5):
            chunk = images[start:start + 5]
            cells = []
            for file_name, data in chunk:
                try:
                    compressed = _compress_image(data)
                    img = Image(io.BytesIO(compressed))
                    max_w, max_h = cell_width - 4, 68
                    scale = min(max_w / img.imageWidth, max_h / img.imageHeight, 1)
                    img.drawWidth = img.imageWidth * scale
                    img.drawHeight = img.imageHeight * scale
                    display_name = file_name if len(file_name) <= 14 else file_name[:13] + "…"
                    cells.append([img, Paragraph(_super_text(display_name), name_style)])
                except Exception:
                    cells.append(Paragraph("(加载失败)", name_style))
            while len(cells) < 5:
                cells.append("")
            image_rows.append(cells)
        image_table = Table(image_rows, colWidths=[cell_width] * 5)
        image_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(image_table)

    doc.build(story)
    return buf.getvalue()


def pdf_filename(record) -> str:
    def clean(value):
        text = str(value or "")
        return "".join("_" if ch in '\\/:*?"<>|' else ch for ch in text).strip() or "-"

    detect_time = record.detect_time.strftime("%Y-%m-%d") if record.detect_time else datetime.now().strftime("%Y-%m-%d")
    flow_text = f"{_fmt_num(record.flow_rate)} m³/h" if record.flow_rate is not None else "未知漏量"
    name = "_".join([
        clean(detect_time),
        clean(record.detect_com or "未知队伍"),
        clean(record.detect_user or "未知测漏者"),
        clean(record.location or "未知地点"),
        clean(flow_text),
    ])
    if len(name) > 180:
        name = name[:176]
    return f"{name}.pdf"
