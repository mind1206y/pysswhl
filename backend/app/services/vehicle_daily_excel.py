"""日常用车 Excel 导出与派车记录导入(照旧 loadjc / downWrong / downKong / exeExcel)。"""

import re
from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path

import xlrd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.vehicle import ClChe, Yongcherc


DAILY_COLUMNS = [
    ("编号", "ID"), ("部门", "bumen"), ("车号", "chehao"), ("派车事由", "yuanyin"),
    ("路线地点", "didian"), ("用车人", "usercar"), ("司机", "sj"), ("审核", "shenhe"),
    ("审批", "shenpi"), ("部门领导", "bumenld"), ("审核签字", "shenheqz"),
    ("开始时间", "ksdate"), ("结束时间", "jsdate"), ("开始公里", "ksgl"),
    ("结束公里", "jsgl"), ("里程数", "gl"),
]

MILEAGE_COLUMNS = [
    ("记录ID", "ID"), ("车号", "chehao"), ("车辆用途", "yongtu"), ("部门", "bumen"),
]

DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d",
    "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M",
    "%Y年%m月%d日", "%Y年%m月%d日 %H:%M:%S", "%Y年%m月%d日 %H:%M",
]
TIME_FORMATS = ["%H:%M:%S", "%H:%M", "%H点%M分", "%H时%M分"]


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _to_int(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    s = str(value).strip().replace(",", "").replace("，", "")
    match = re.search(r"-?\d+(?:\.\d+)?", s)
    if not match:
        return None
    return int(round(float(match.group())))


def _to_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return from_excel(float(value)).date()
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return from_excel(float(s)).date()
    except Exception:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_time(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        fraction = float(value) % 1
        seconds = int(round(fraction * 86400))
        return (datetime(1899, 12, 30) + timedelta(seconds=seconds)).time()
    s = str(value).strip()
    if not s:
        return None
    try:
        return _to_time(float(s))
    except ValueError:
        pass
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def _combine_datetime(day_value, time_value):
    d = _to_date(day_value)
    if d is None:
        return None
    if isinstance(day_value, datetime) and (time_value is None or _text(time_value) == ""):
        if day_value.time() != time.min:
            return day_value
    t = _to_time(time_value) if time_value not in (None, "") else time.min
    return datetime.combine(d, t or time.min)


def _to_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            result = from_excel(float(value))
            return result if isinstance(result, datetime) else datetime.combine(result, time.min)
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _read_rows(file_bytes: bytes, filename: str) -> list:
    suffix = Path(filename or "").suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        wb = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
        try:
            ws = wb.worksheets[0]
            return [list(row) for row in ws.iter_rows(values_only=True)]
        finally:
            wb.close()

    if suffix == ".xls":
        book = xlrd.open_workbook(file_contents=file_bytes)
        sheet = book.sheet_by_index(0)
        rows = []
        for rx in range(sheet.nrows):
            values = []
            for cx in range(sheet.ncols):
                cell = sheet.cell(rx, cx)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        values.append(datetime(*xlrd.xldate_as_tuple(cell.value, book.datemode)))
                    except Exception:
                        values.append(cell.value)
                elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    values.append(None)
                else:
                    values.append(cell.value)
            rows.append(values)
        return rows

    raise ValueError("只支持 .xls / .xlsx 文件")


def _eq(column, value):
    return column.is_(None) if value is None else column == value


def import_dispatch_excel(db: Session, user: User, file_bytes: bytes, filename: str) -> dict:
    """导入水务派车 Excel。列位置照旧系统 exeExcel:车号23、开始日期15/16、结束17/18、
    开始公里12、结束公里13、事由5、地点9、用车人8、司机21、审批29。"""
    rows = _read_rows(file_bytes, filename)
    if not rows:
        raise ValueError("Excel 没有数据")

    success = 0
    failed = 0
    total = 0
    errors = []
    seen = set()
    pending = 0
    batch_success = 0
    now = datetime.now()

    for idx, cells in enumerate(rows[1:], start=2):
        cells = list(cells or [])
        if not cells or _text(cells[0] if len(cells) > 0 else None) == "":
            break
        total += 1

        def cell(i):
            return cells[i] if i < len(cells) else None

        plate = _text(cell(23))
        if not plate:
            failed += 1
            errors.append({"row": idx, "reason": "找不到车号"})
            continue

        tail = plate[-4:]
        cars = (
            db.query(ClChe)
            .filter(ClChe.delf != 0, ClChe.chehao.like(f"%{tail}%"), ~ClChe.chehao.like("%废%"))
            .all()
        )
        if len(cars) != 1:
            failed += 1
            errors.append({"row": idx, "reason": f"车号有误/不唯一：{tail}"})
            continue
        car = cars[0]

        ksdate = _combine_datetime(cell(15), cell(16))
        jsdate = _combine_datetime(cell(17), cell(18))
        if ksdate is None:
            failed += 1
            errors.append({"row": idx, "reason": "开始日期无法解析"})
            continue

        ksgl = _to_int(cell(12))
        jsgl = _to_int(cell(13))
        key = (car.id, ksdate, jsdate, ksgl, jsgl)
        if key in seen:
            failed += 1
            errors.append({"row": idx, "reason": "文件内用车记录重复"})
            continue

        exists = (
            db.query(Yongcherc.id)
            .filter(
                Yongcherc.cheid == car.id,
                _eq(Yongcherc.ksdate, ksdate),
                _eq(Yongcherc.jsdate, jsdate),
                _eq(Yongcherc.ksgl, ksgl),
                _eq(Yongcherc.jsgl, jsgl),
            )
            .first()
        )
        if exists:
            failed += 1
            errors.append({"row": idx, "reason": "用车记录已存在（重复）"})
            continue

        rec = Yongcherc(
            cheid=car.id,
            ksdate=ksdate,
            jsdate=jsdate,
            ksgl=ksgl,
            jsgl=jsgl,
            yuanyin=_text(cell(5)),
            didian=_text(cell(9)),
            usercar=_text(cell(8)),
            sj=_text(cell(21)),
            shenpi=_text(cell(29)),
            shenQingTime=_to_datetime(cell(2)),
            shenhe=car.shenheren or "",
            bumenld="审批通过",
            shenheqz="审核通过",
            beizhu="已提交",
            czy=f"{user.username}上传",
            cz=now,
            ok=True,
        )
        db.add(rec)
        seen.add(key)
        batch_success += 1
        pending += 1

        if pending >= 500:
            try:
                db.commit()
                success += batch_success
            except Exception as exc:
                db.rollback()
                failed += batch_success
                errors.append({"row": idx, "reason": f"批量写入失败：{exc}"})
            pending = 0
            batch_success = 0

    if pending:
        try:
            db.commit()
            success += batch_success
        except Exception as exc:
            db.rollback()
            failed += batch_success
            errors.append({"row": idx, "reason": f"批量写入失败：{exc}"})

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "errors": errors[:500],
        "errors_truncated": len(errors) > 500,
    }


def _build_excel(title: str, columns: list, rows: list) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = title

    thin = Side(style="thin", color="d0d7de")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="eef2f7")

    for c, (label, _key) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for r, row in enumerate(rows, start=2):
        for c, (_label, key) in enumerate(columns, start=1):
            value = row.get(key)
            ws.cell(row=r, column=c, value=value if value is not None else "")
        for c in range(1, len(columns) + 1):
            ws.cell(row=r, column=c).border = border

    for i, (label, key) in enumerate(columns, start=1):
        width = max(10, min(30, len(label) * 2 + 4))
        if key in ("bumen", "yuanyin", "didian", "ksdate", "jsdate"):
            width = 20
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_daily_excel(rows: list) -> BytesIO:
    return _build_excel("用车登记表", DAILY_COLUMNS, rows)


def build_overlap_excel(rows: list) -> BytesIO:
    return _build_excel("公里数出错列表", MILEAGE_COLUMNS, rows)


def build_gap_excel(rows: list) -> BytesIO:
    return _build_excel("公里数空挡列表", MILEAGE_COLUMNS, rows)
