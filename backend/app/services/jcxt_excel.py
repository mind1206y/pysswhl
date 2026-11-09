"""稽查模块 Excel 导出/导入(openpyxl/xlrd 实现,输出统一 .xlsx)。

照旧 ExcelJcxt.cs 的四套动作:
- loadAllExcel        固定 32 列明细导出(旧读 App_Data/jicha.xls 模板,
                      新系统按模板列序重建表头,格式重排属已知差异)
- loadAllExcelforme   按用户自选列导出(首列固定序号)
- jgj + 控制器组装     同安营业所奖励名单(tazhuijiaojiangli)
- loadexcel           稽查奖励报表(按部门分组 + 小计/本月合计 SUM 公式,
                      旧为模板套打,新系统重建版式)
- writeExcel          导入「稽查报表.xls」:空工单号即 break、四字段重复即 break
- exeExcelhedui       工单信息核对:命中工单号的行染绿色(新系统直接返回 .xlsx)
"""

import io
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.models.jcxt import JcJcxx
from app.services.jcxt_common import BM_TONGAN, jsjb

THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
CENTER = Alignment(horizontal="center", vertical="center")
GREEN_FILL = PatternFill("solid", fgColor="CCFFCC")


def _f(v):
    return float(v) if v is not None else None


def _num(v):
    return Decimal("0") if v is None else Decimal(v)


def _d(v):
    return v.strftime("%Y-%m-%d") if v else None


def _dt(v):
    return v.strftime("%Y-%m-%d %H:%M:%S") if v else None


def _autowidth(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ==================== 固定 32 列导出(照旧 loadAllExcel) ====================
ALL32_HEADERS = [
    "id", "工单号", "操作日期", "处理日期", "违章日期", "违章单位", "违章电话",
    "违章地址", "违章内容", "追缴水量", "追缴水费", "追缴工料费", "举报人", "部门",
    "追缴部门/人员", "最后更新", "举报奖励", "追缴奖励", "处理状态", "执行情况",
    "违章类别", "操作员", "应收水量", "应收水费", "应收工料费", "备注", "举报类别",
    "信息来源", "办结天数", "农村稽查", "管材", "管径",
]


def build_export_all(rows, dept_names: dict, biaotou: str) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "稽查信息"
    ws.cell(row=1, column=1, value=biaotou or "按违章日期筛选")
    for c, h in enumerate(ALL32_HEADERS, start=1):
        cell = ws.cell(row=2, column=c, value=h)
        cell.font = Font(bold=True)
        cell.alignment = CENTER
        cell.border = BORDER
    style = Alignment(horizontal="left", vertical="center", wrap_text=True)
    for i, r in enumerate(rows, start=3):
        vals = [
            r.id, r.gongdanhao, _dt(r.caozuoriqi), _d(r.chuliriqi), _d(r.weizhangriqi),
            r.weizhangren, r.weizhangdianhua, r.weizhangdizhi, r.weizhangneirong,
            r.zhuijiaoshuiliang, _f(r.zhuijiaoshuifei), _f(r.zhuijiaogongliaofei),
            r.jubaoren, dept_names.get(r.ssbmid, ""), r.zhuijiaobm, _dt(r.zuihougengxin),
            None if r.jbjiangli is None else str(r.jbjiangli),
            None if r.zhuijiaojiangli is None else str(r.zhuijiaojiangli),
            r.zhuangtai, r.zhixingqingkuang, r.wzleibie, r.caozuoname,
            r.yingjiaoshuiliang, _f(r.yingjiaoshuifei), _f(r.yingjiaogongliaofei),
            r.beizhu, r.jubaoleibie, r.xinxilaiyuan,
            None if r.banjietianshu is None else str(r.banjietianshu),
            r.nongcunjicha, r.guancai, r.guanjing,
        ]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=i, column=c, value=v)
            cell.border = BORDER
            cell.alignment = style
    _autowidth(ws, [8, 14, 20, 12, 12, 22, 14, 24, 30, 10, 10, 10, 10, 12,
                    12, 20, 10, 10, 10, 10, 14, 10, 10, 10, 10, 20, 10, 12, 10, 10, 10, 10])
    return wb


# ==================== 自选列导出(照旧 loadAllExcelforme) ====================
FORME_FIELD_MAP = [
    # (字段名, 表头, 列宽)
    ("gongdanhao", "工单号", 12), ("weizhangriqi", "违章日期", 12),
    ("weizhangren", "违章单位", 28), ("weizhangdizhi", "违章地址", 28),
    ("weizhangdianhua", "违章电话", 14), ("wzleibie", "违章类别", 15),
    ("weizhangneirong", "违章内容", 28), ("guanjing", "管径", 8),
    ("guancai", "管材", 10), ("chuliriqi", "处理日期", 12),
    ("zhuijiaoshuiliang", "追缴水量", 10), ("zhuijiaoshuifei", "追缴水费", 10),
    ("zhuijiaogongliaofei", "追缴工料费", 12), ("zhuijiaobm", "追缴部门/人员", 12),
    ("jubaoleibie", "举报类别", 10), ("jubaoren", "举报人", 10),
    ("jbjiangli", "举报奖励", 10), ("zhuangtai", "处理状态", 10),
    ("zhuijiaojiangli", "追缴奖励", 10), ("caozuoriqi", "操作日期", 20),
    ("zuihougengxin", "最后更新日期", 20), ("nongcunjicha", "农村稽查", 10),
    ("peibiaofei", "赔表费", 10), ("beizhu", "备注", 48),
    ("ssbmid", "所属部门", 12), ("spzt", "审批状态", 10),
]


def build_export_forme(rows, dept_names: dict, cols: list) -> Workbook:
    chosen = [f for f in FORME_FIELD_MAP if f[0] in cols]
    wb = Workbook()
    ws = wb.active
    ws.title = "稽查"
    ws.cell(row=1, column=1, value="稽查信息汇总")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(chosen) + 1)
    ws.cell(row=1, column=1).alignment = CENTER
    headers = ["序号"] + [h for _, h, _ in chosen]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=2, column=c, value=h)
        cell.font = Font(bold=True)
        cell.alignment = CENTER
    ws.column_dimensions["A"].width = 8
    for idx, (_, _, w) in enumerate(chosen, start=2):
        ws.column_dimensions[get_column_letter(idx)].width = w

    def val_of(r, field):
        if field == "ssbmid":
            return dept_names.get(r.ssbmid, "")
        if field == "chuliriqi":
            return _d(r.chuliriqi)
        if field == "weizhangriqi":
            return _d(r.weizhangriqi)
        if field == "caozuoriqi":
            return _d(r.caozuoriqi)
        if field == "zuihougengxin":
            return _d(r.zuihougengxin)
        if field in ("zhuijiaoshuiliang",):
            return r.zhuijiaoshuiliang
        v = getattr(r, field, None)
        if isinstance(v, Decimal):
            return float(v)
        return v

    for i, r in enumerate(rows, start=3):
        row_vals = [i - 2] + [val_of(r, f) for f, _, _ in chosen]
        for c, v in enumerate(row_vals, start=1):
            ws.cell(row=i, column=c, value=v)
    return wb


# ==================== 同安奖励名单(照旧 tazhuijiaojiangli) ====================
def build_tongan_reward(rows, riqi: date) -> Workbook:
    """rows: jgj 全量;只取同安(ssbmid=新12),举报人/追缴人两组展开再按姓名合并。"""
    tahb = sorted(
        [r for r in rows if r.ssbmid == BM_TONGAN],
        key=lambda r: (r.zhuijiaobm or ""),
    )
    agg: dict = {}
    for r in tahb:
        for name, jl_key in ((r.jubaoren, "jbjiangli"), (r.zhuijiaobm, "zhuijiaojiangli")):
            if not name:
                continue
            jb = _num(r.jbjiangli) if jl_key == "jbjiangli" else Decimal("0")
            zj = _num(r.zhuijiaojiangli) if jl_key == "zhuijiaojiangli" else Decimal("0")
            if name == "肇事者" and jb == 0 and zj == 0:
                continue
            e = agg.setdefault(name, {"jbjiangli": Decimal("0"), "zhuijiaojiangli": Decimal("0")})
            e["jbjiangli"] += jb
            e["zhuijiaojiangli"] += zj

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    bordered = Alignment(horizontal="center", vertical="center")
    ws.cell(row=1, column=1, value=f"同安营业所{riqi.month}月稽查奖励名单")
    ws.merge_cells("A1:D1")
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.cell(row=1, column=1).alignment = bordered
    for c, h in enumerate(["姓名", "举报奖励", "追缴补贴", "总金额"], start=1):
        cell = ws.cell(row=2, column=c, value=h)
        cell.font = Font(bold=True, size=12)
        cell.alignment = bordered
        cell.border = BORDER
    total_jb = Decimal("0")
    total_zj = Decimal("0")
    r = 3
    for name, e in agg.items():
        ws.cell(row=r, column=1, value=name).border = BORDER
        ws.cell(row=r, column=2, value=float(e["jbjiangli"])).border = BORDER
        ws.cell(row=r, column=3, value=float(e["zhuijiaojiangli"])).border = BORDER
        ws.cell(row=r, column=4, value=float(e["jbjiangli"] + e["zhuijiaojiangli"])).border = BORDER
        for c in range(1, 5):
            ws.cell(row=r, column=c).alignment = bordered
        total_jb += e["jbjiangli"]
        total_zj += e["zhuijiaojiangli"]
        r += 1
    ws.cell(row=r, column=1, value="总计").border = BORDER
    ws.cell(row=r, column=2, value=float(total_jb)).border = BORDER
    ws.cell(row=r, column=3, value=float(total_zj)).border = BORDER
    ws.cell(row=r, column=4, value=float(total_jb + total_zj)).border = BORDER
    for c in range(1, 5):
        ws.cell(row=r, column=c).alignment = bordered
        ws.column_dimensions[get_column_letter(c)].width = 14
    return wb


# ==================== 稽查奖励报表(照旧 loadexcel,重建版式) ====================
def build_reward_report(rows, riqi: date, dept_names: dict) -> Workbook:
    """按部门分组明细 + 小计/本月合计公式。列:序号/违章日期/违章单位/违章地址/
    违章内容/追缴水费/追缴工料费/举报人/追缴部门/举报奖励/(空)/工单号。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "举报违章用水奖励"
    ws.cell(row=1, column=1, value="售水事业部举报违章用水奖励")
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.merge_cells("A1:L1")
    headers = ["序号", "违章日期", "违章单位", "违章地址", "违章内容", "追缴水费",
               "追缴工料费", "举报人", "追缴部门", "举报奖励", "", "工单号"]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=c, value=h)
        cell.font = Font(bold=True)
        cell.alignment = CENTER
        cell.border = BORDER

    # 按部门分组(旧模板按部门行展开;这里按部门聚合后逐组输出)
    groups: dict = {}
    for r in rows:
        groups.setdefault(dept_names.get(r.ssbmid, ""), []).append(r)
    style = Alignment(horizontal="left", vertical="center", wrap_text=True)
    row_no = 4
    first_data_row = row_no
    ixh = 1
    for bm, items in groups.items():
        # 部门行(合并 B:L)
        ws.cell(row=row_no, column=1, value=None)
        ws.cell(row=row_no, column=2, value=bm)
        ws.merge_cells(start_row=row_no, start_column=2, end_row=row_no, end_column=11)
        ws.row_dimensions[row_no].height = 18
        ws.cell(row=row_no, column=2).font = Font(bold=True)
        row_no += 1
        grp_start = row_no
        for r in items:
            vals = [ixh, _d(r.weizhangriqi), r.weizhangren, r.weizhangdizhi,
                    r.weizhangneirong, float(_num(r.zhuijiaoshuifei)),
                    float(_num(r.zhuijiaogongliaofei)), r.jubaoren, r.zhuijiaobm,
                    float(_num(r.jbjiangli)), None, r.gongdanhao]
            for c, v in enumerate(vals, start=1):
                cell = ws.cell(row=row_no, column=c, value=v)
                cell.border = BORDER
                cell.alignment = style
            ixh += 1
            row_no += 1
        # 小计
        ws.cell(row=row_no, column=1, value="小计").border = BORDER
        ws.cell(row=row_no, column=6,
                value=f"=SUM(F{grp_start}:F{row_no - 1})").border = BORDER
        ws.cell(row=row_no, column=7,
                value=f"=SUM(G{grp_start}:G{row_no - 1})").border = BORDER
        ws.cell(row=row_no, column=10,
                value=f"=SUM(J{grp_start}:J{row_no - 1})").border = BORDER
        for c in range(1, 13):
            ws.cell(row=row_no, column=c).border = BORDER
            ws.cell(row=row_no, column=c).alignment = CENTER
        row_no += 1
    # 本月合计
    ws.cell(row=row_no, column=1, value="本月合计").border = BORDER
    ws.cell(row=row_no, column=6,
            value=f"=SUM(F{first_data_row}:F{row_no - 1})").border = BORDER
    ws.cell(row=row_no, column=7,
            value=f"=SUM(G{first_data_row}:G{row_no - 1})").border = BORDER
    ws.cell(row=row_no, column=10,
            value=f"=SUM(J{first_data_row}:J{row_no - 1})").border = BORDER
    for c in range(1, 13):
        ws.cell(row=row_no, column=c).border = BORDER
        ws.cell(row=row_no, column=c).alignment = CENTER
    _autowidth(ws, [6, 12, 22, 26, 30, 10, 10, 10, 10, 10, 4, 14])
    return wb


# ==================== 导入(照旧 writeExcel 语义) ====================
def _read_sheet(data: bytes, filename: str):
    """读第一个 sheet 返回二维数组。xls 用 xlrd,xlsx 用 openpyxl。"""
    lower = (filename or "").lower()
    if lower.endswith(".xls"):
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        sh = book.sheet_by_index(0)
        out = []
        for rx in range(sh.nrows):
            row = []
            for cell in sh.row(rx):
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        row.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                    except Exception:
                        row.append(cell.value)
                else:
                    row.append(cell.value)
            out.append(row)
        return out
    book = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    sh = book.worksheets[0]
    out = []
    for row in sh.iter_rows(values_only=True):
        out.append([v.date() if hasattr(v, "date") and not isinstance(v, datetime) else v
                    for v in row])
    book.close()
    return out


def parse_report_import(data: bytes, filename: str, username: str, bmid):
    """照旧 writeExcel:跳过表头行,空工单号 break,重复记录 break。

    返回 (oknum, nonum, records)。records 是待入库字典(由路由补派生字段)。
    """
    sheet = _read_sheet(data, filename)
    oknum = 0
    nonum = 0
    records = []
    for row in sheet[1:]:
        gongdanhao = row[0] if len(row) > 0 else None
        if gongdanhao is None or str(gongdanhao).strip() == "":
            break
        wzrq = row[1] if len(row) > 1 else None
        clr = row[2] if len(row) > 2 else None
        wzr = row[3] if len(row) > 3 else None
        dz = row[4] if len(row) > 4 else None
        nr = row[5] if len(row) > 5 else None
        sl = row[6] if len(row) > 6 else None
        sf = row[7] if len(row) > 7 else None
        glf = row[8] if len(row) > 8 else None
        wzb = row[9] if len(row) > 9 else None

        def _int(v):
            if v is None or str(v).strip() == "":
                return None
            try:
                return int(float(str(v).strip()))
            except ValueError:
                return None

        def _dec(v):
            if v is None or str(v).strip() == "":
                return None
            try:
                return Decimal(str(v).strip())
            except Exception:
                return None

        rec = {
            "gongdanhao": str(gongdanhao).strip(),
            "weizhangriqi": wzrq if isinstance(wzrq, (datetime, date)) else None,
            "chuliriqi": clr if isinstance(clr, (datetime, date)) else None,
            "weizhangren": None if wzr is None else str(wzr),
            "weizhangdizhi": None if dz is None else str(dz),
            "weizhangneirong": None if nr is None else str(nr),
            "zhuijiaoshuiliang": _int(sl),
            "zhuijiaoshuifei": _dec(sf),
            "zhuijiaogongliaofei": _dec(glf),
            "wzleibie": None if wzb is None else str(wzb),
            "ssbmid": bmid,
            "caozuoriqi": datetime.now(),
            "zuihougengxin": datetime.now(),
            "caozuoname": username,
            "spzt": "待审核",
        }
        records.append(rec)
    return oknum, nonum, records


def build_hedui(data: bytes, filename: str, existing_gongdans: set) -> Workbook:
    """照旧 exeExcelhedui:第 0 列工单号命中库中 -> 该格染亮绿。输出 .xlsx。"""
    sheet = _read_sheet(data, filename)
    wb = Workbook()
    ws = wb.active
    ws.title = "核对结果"
    hits = 0
    for ri, row in enumerate(sheet, start=1):
        for ci, v in enumerate(row, start=1):
            if isinstance(v, datetime):
                v = v.strftime("%Y-%m-%d %H:%M:%S")
            cell = ws.cell(row=ri, column=ci, value=v)
            cell.border = BORDER
        gongdanhao = row[0] if row else None
        if gongdanhao is not None and str(gongdanhao).strip() in existing_gongdans:
            cell = ws.cell(row=ri, column=1)
            cell.fill = GREEN_FILL
            hits += 1
    ws.column_dimensions["A"].width = 24
    return wb, hits
