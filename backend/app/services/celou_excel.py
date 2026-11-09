"""测漏成果 Excel:导入(照 ExcelCL.CelouExcel)、导出(照 celouExcel.loadcgExcel)。

- 导入支持 .xls(xlrd) / .xlsx(openpyxl);6 个营业所 sheet 逐表读,13 列表头校验,
  管径解析、日期解析、五字段重复校验、事务整体回滚、测漏队伍字典自动增长。
- 导出 21 列 xlsx(旧模板 13 列 + 上诉人/年度/月份/节约水量/坐标/计算过程 8 列)。
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.models.celou import (
    CelouTb, CLdui, EXPORT_COLUMNS, IMPORT_HEADERS, IMPORT_SHEET_DEPTS,
)
from app.models.user import Department
from app.services.celou_common import calc_qjll, calc_qjll_process, export_row

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "assets" / "测漏成果表.xls"
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S")


class ImportError_(Exception):
    """面向前端的导入校验错误(整批回滚)。"""


def _read_sheets(data: bytes, filename: str) -> dict:
    """统一成 {sheet名: [[单元格值...], ...]}。"""
    ext = Path(filename).suffix.lower()
    if ext not in (".xls", ".xlsx"):
        raise ImportError_("不是后缀.xls或.xlsx的Excel文件")
    out = {}
    if ext == ".xls":
        import xlrd
        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as e:
            raise ImportError_(f"Excel 文件无法读取: {e}")
        for sh in book.sheets():
            rows = []
            for r in range(sh.nrows):
                line = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            line.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                        except Exception:
                            line.append(cell.value)
                    else:
                        line.append(cell.value)
                rows.append(line)
            out[sh.name] = rows
    else:
        try:
            book = load_workbook(BytesIO(data), data_only=True, read_only=True)
        except Exception as e:
            raise ImportError_(f"Excel 文件无法读取: {e}")
        for sh in book.worksheets:
            out[sh.title] = [list(r) for r in sh.iter_rows(values_only=True)]
        book.close()
    return out


def _cell(row, idx):
    return row[idx] if idx < len(row) else None


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _validate_header(rows: list) -> tuple:
    if not rows or len(rows) < 2:
        raise ImportError_("Excel 首行为空")
    header = rows[1]
    for i in range(11):
        got = _text(_cell(header, i))
        if got != IMPORT_HEADERS[i]:
            raise ImportError_(f"测漏 Excel 表格验证失败: Excel 列标题不正确，第 {i + 1} 列应为 "
                               f"'{IMPORT_HEADERS[i]}', 当前为 '{got}'")
    for i in (11, 12):
        got = _text(_cell(header, i))
        if got and IMPORT_HEADERS[i] not in got:
            raise ImportError_(f"测漏 Excel 表格验证失败: Excel 列标题不正确，第 {i + 1} 列应包含 "
                               f"'{IMPORT_HEADERS[i]}', 当前为 '{got}'")
    jd = wd = -1
    for i in range(len(header)):
        t = _text(_cell(header, i))
        if "经度" in t:
            jd = i
        if "纬度" in t:
            wd = i
    return jd, wd


def _parse_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
        except (OverflowError, ValueError):
            return None
    s = str(v).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_guanjing(text: str) -> tuple:
    import re
    s = (text or "").strip()
    if not s:
        raise ImportError_("管径不能为空")
    parts = [p.strip() for p in re.split(r"[/、×*xX]", s) if p.strip()]
    if len(parts) == 1:
        try:
            v = int(parts[0])
        except ValueError:
            raise ImportError_(f"管径必须为数字，当前值: {s}")
        return v, v
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            raise ImportError_(f"管径必须为数字，当前值: {s}")
    raise ImportError_(f"管径格式错误，必须为单个数字或用 /、、、×、*、x、X 分隔，当前值: {s}")


def _parse_decimal(v):
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def import_workbook(db: Session, data: bytes, filename: str, *, user: str, duiwu: str,
                    nian: int, yue: int, yudingliang: bool, zuobiao_leibie: str) -> dict:
    """返回 {imported, sheets:{sheet: 行数}, team_created}。出错抛 ImportError_。"""
    if not duiwu:
        raise ImportError_("请选择或填写测漏单位")
    if not nian:
        raise ImportError_("请选择年度")
    if not yue:
        raise ImportError_("请选择月份")

    sheets = _read_sheets(data, filename)
    dept_by_name = {n: i for i, n in db.query(Department.id, Department.name).all()}
    bm_by_name = {}
    for r in db.query(CelouTb.bmid, CelouTb.bm).filter(CelouTb.bm.isnot(None)).distinct().all():
        bm_by_name.setdefault(r[0], r[1])

    # 重复校验用内存集合,口径照旧:漏量+工单号+地点+上报日期+修复日期五字段全等
    exist = set()
    for r in db.query(CelouTb.louliang, CelouTb.gongdan, CelouTb.didian,
                      CelouTb.bgdate, CelouTb.xiufudate).all():
        exist.add((str(r[0]), r[1] or "", r[2] or "", str(r[3]), str(r[4])))

    new_rows = []
    sheet_counts = {}
    for bm in IMPORT_SHEET_DEPTS:
        rows = sheets.get(bm)
        if rows is None:
            continue
        jd_col, wd_col = _validate_header(rows)
        count = 0
        for i in range(2, len(rows)):
            row = rows[i]
            first = _text(_cell(row, 0))
            if not first:
                break
            if any(k in first.lower() for k in ("合计", "总计", "total")):
                break
            excel_row = i + 1
            try:
                bh = int(float(first))
            except (ValueError, TypeError):
                raise ImportError_(f"第{excel_row}行【编号】格式错误，值：{first}")

            gongdan = _text(_cell(row, 1))
            bgdate = _parse_date(_cell(row, 2))
            xiufudate = _parse_date(_cell(row, 3))
            didian = _text(_cell(row, 4))
            guanjing = _text(_cell(row, 5))
            gjsmall = gjbig = None
            if guanjing:
                try:
                    gjsmall, gjbig = _parse_guanjing(guanjing)
                except ImportError_ as e:
                    raise ImportError_(f"第{excel_row}行【管径】格式错误，值：{guanjing}，原因：{e}")

            louliang = _parse_decimal(_cell(row, 10))
            if _text(_cell(row, 10)) and louliang is None:
                raise ImportError_(f"第{excel_row}行【漏量】格式错误，值：{_text(_cell(row, 10))}")

            jd = _parse_decimal(_cell(row, jd_col)) if jd_col >= 0 else None
            wd = _parse_decimal(_cell(row, wd_col)) if wd_col >= 0 else None

            key = (str(louliang), gongdan, didian, str(bgdate), str(xiufudate))
            if key in exist:
                raise ImportError_(f"第{excel_row}行数据已存在（漏量={louliang}，工单号={gongdan}）")
            exist.add(key)

            dept_id = dept_by_name.get(bm)
            new_rows.append(CelouTb(
                bh=bh, gongdan=gongdan, bgdate=bgdate, xiufudate=xiufudate,
                didian=didian, guanjing=guanjing, guancai=_text(_cell(row, 6)),
                yy=_text(_cell(row, 7)), dwwucha=_text(_cell(row, 8)),
                dingliang=_text(_cell(row, 9)), louliang=louliang,
                bmid=dept_id, bm=bm if bm else "", celoudw=duiwu,
                nian=nian, yue=yue, scdatetime=datetime.now(), username=user,
                gjsmall=gjsmall, gjbig=gjbig, yudingliang=bool(yudingliang),
                zuobiao_leibie=zuobiao_leibie or "高德火星坐标",
                zuobiao_jingdu=jd, zuobiao_weidu=wd,
            ))
            count += 1
        sheet_counts[bm] = count

    if not new_rows:
        raise ImportError_("没有导入数据")

    team_created = False
    if not db.query(CLdui).filter(CLdui.coname == duiwu).first():
        db.add(CLdui(coname=duiwu))
        team_created = True
    db.add_all(new_rows)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise ImportError_(f"写入数据库失败: {e}")
    return {"imported": len(new_rows), "sheets": sheet_counts, "team_created": team_created}


THIN = Side(style="thin", color="7f7f7f")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def build_export(rows, year: int, dept_names: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "测漏成果记录"
    n = len(EXPORT_COLUMNS)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    title = ws.cell(1, 1, f"{year}年度售水测漏成果记录表" if year else "全部年度售水测漏成果记录表")
    title.font = Font(size=15, bold=True)
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28
    for c, label in enumerate(EXPORT_COLUMNS, 1):
        cell = ws.cell(2, c, label)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[2].height = 32

    for i, row in enumerate(rows, 1):
        values = export_row(row, i, dept_names)
        for c, v in enumerate(values, 1):
            cell = ws.cell(i + 2, c, v)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=(c in (5, 8, 21)))
            if c in (3, 4) and v:
                cell.number_format = "yyyy/mm/dd"
            if c in (11, 17):
                cell.number_format = "0.00"
    widths = [8, 14, 13, 13, 34, 10, 12, 20, 10, 14, 16, 14, 26, 10, 8, 8, 18, 16, 14, 14, 26]
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A3"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_filename(year: int) -> str:
    return f"测漏成果明细表_{year or '全部年度'}.xlsx"


def content_disposition(filename: str) -> str:
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")
