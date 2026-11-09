"""SIM 卡管理公共口径:列表筛选、行组装、Excel 导入/导出/核对。

照旧 simkaguanliController / simService:
- 部门按登录人部门子树过滤(超管/未挂部门用户不限)
- 状态为空时默认排除"销卡";状态选"已删除"时查 delf=0 的软删除记录
- 关键字=卡号/使用人/地点/序列号/备注/用途/VPN 模糊
- 列表按最后修改时间倒序,同时间按 id 倒序
- 导出列照旧 simExcel.loadAllsim
"""

import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map
from app.models.simcard import (
    Feiyong, SimCard, SimEditLog, SimTaocan, SimVpn, SimWangluo, SimZhuangtai,
)
from app.models.user import Department

DELETED_STATUS = "已删除"
ACCOUNT_OPTIONS = ["移动A账户", "移动B账户", "电信售水", "电信集团"]

# 旧库 sim 字段 → 中文(编辑历史展示用,照旧 SimFieldDisplayNames)
FIELD_DISPLAY = {
    "kahao": "卡号", "xuliehao": "序列号", "imhao": "IM号", "ip": "IP",
    "vpn": "VPN", "taocan": "套餐", "zt": "状态", "wangluo": "运营商",
    "yongtu": "用途", "didian": "地点", "bm": "部门", "glren": "管理人",
    "syren": "使用人", "zhanghu": "账户", "bz": "备注",
    "dengjiren": "登记人", "djriqi": "登记时间", "bianjiren": "最后编辑人",
    "zhriqi": "最后时间",
}

# 编辑时记录日志的字段(照旧忽略 id/bianjiren/zhriqi/delf/dengjiren/djriqi)
LOG_FIELDS = [
    "kahao", "xuliehao", "imhao", "didian", "yongtu", "bz", "ip", "vpn",
    "glren", "zhanghu", "syren", "wangluo", "taocan", "zt", "bm",
]
IGNORE_LOG_FIELDS = {"id", "bianjiren", "zhriqi", "delf", "dengjiren", "djriqi"}


def _f(v):
    return float(v) if v is not None else None


def _round4(v) -> Decimal:
    if v is None:
        v = 0
    return Decimal(str(v)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    if isinstance(v, Decimal):
        return str(v)
    return str(v).strip()


def parse_amount(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            return _round4(v)
        except InvalidOperation:
            return None
    s = cell_str(v).replace(",", "").replace("，", "").replace("元", "").strip()
    if not s:
        return None
    try:
        return _round4(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def iter_sheet_rows(file_bytes: bytes, filename: str) -> list:
    """读取第一个 sheet 的全部行(支持 .xls / .xlsx)。"""
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    if ext == "xlsx":
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
        try:
            ws = wb.worksheets[0]
            return [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
    if ext == "xls":
        import xlrd

        wb = xlrd.open_workbook(file_contents=file_bytes)
        sh = wb.sheet_by_index(0)
        return [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    raise ValueError("仅支持 .xls 或 .xlsx 文件")


def _cell(row, idx, default=""):
    if row is None or idx >= len(row):
        return default
    v = row[idx]
    return default if v is None else v


def list_query(
    db: Session, user, year: Optional[int] = None, month: Optional[int] = None,
    bmid: str = "", zt: str = "", zhanghu: str = "", wangluo: str = "",
    djr: str = "", keyword: str = "",
):
    """构建 SIM 卡列表查询。返回 (query, year, month, 是否查已删除)。"""
    from app.api.deps import dept_scope_ids

    today = date.today()
    year = year or today.year
    month = month or today.month

    is_deleted = zt == DELETED_STATUS
    del_flag = 0 if is_deleted else 1

    q = db.query(SimCard).filter(SimCard.delf == del_flag)

    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(SimCard.bm.in_(scope))

    ids = []
    for part in (bmid or "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    if ids:
        q = q.filter(SimCard.bm.in_(ids))

    if is_deleted:
        # 已删除:保留原状态,不再按状态名过滤
        pass
    elif (zt or "").strip():
        q = q.filter(SimCard.zt == zt.strip())
    else:
        q = q.filter(or_(SimCard.zt.is_(None), SimCard.zt != "销卡"))

    if (djr or "").strip():
        q = q.filter(SimCard.dengjiren == djr.strip())
    if (wangluo or "").strip():
        q = q.filter(SimCard.wangluo == wangluo.strip())
    if (zhanghu or "").strip():
        q = q.filter(SimCard.zhanghu == zhanghu.strip())

    kw = (keyword or "").strip()
    if kw:
        q = q.filter(or_(
            SimCard.kahao.contains(kw),
            SimCard.syren.contains(kw),
            SimCard.didian.contains(kw),
            SimCard.xuliehao.contains(kw),
            SimCard.bz.contains(kw),
            SimCard.yongtu.contains(kw),
            SimCard.vpn.contains(kw),
        ))

    q = q.order_by(SimCard.zhriqi.desc(), SimCard.id.desc())
    return q, year, month, is_deleted


def build_rows(db: Session, sims: list, year: int, month: int) -> list:
    """组装列表行:部门名 + 当月话费(fy)。"""
    if not sims:
        return []
    names = dept_name_map(db)
    kahao_list = {s.kahao for s in sims if s.kahao}
    fees = {}
    if kahao_list:
        for kahao, total in (
            db.query(Feiyong.kahao, func.coalesce(func.sum(Feiyong.jine), 0))
            .filter(Feiyong.nian == year, Feiyong.yue == month, Feiyong.kahao.in_(kahao_list))
            .group_by(Feiyong.kahao)
            .all()
        ):
            fees[kahao] = float(total or 0)
    rows = []
    for s in sims:
        row = s.to_dict(names.get(s.bm) or "")
        row["fy"] = fees.get(s.kahao, 0)
        rows.append(row)
    return rows


def monthly_fees(db: Session, kahao: str, year: int) -> dict:
    """某卡指定年度的 1-12 月话费及合计(照旧 getHf)。"""
    months = [Decimal("0")] * 12
    if kahao:
        rows = (
            db.query(Feiyong.yue, func.coalesce(func.sum(Feiyong.jine), 0))
            .filter(Feiyong.nian == year, Feiyong.kahao == kahao)
            .group_by(Feiyong.yue)
            .all()
        )
        for yue, total in rows:
            if yue and 1 <= int(yue) <= 12:
                months[int(yue) - 1] = total or Decimal("0")
    return {
        "kahao": kahao or "",
        "nian": year,
        "months": [float(v) for v in months],
        "zong": float(sum(months)),
    }


def ensure_taocan(db: Session, taocan: str):
    value = (taocan or "").strip()
    if not value:
        return
    if not db.query(SimTaocan.id).filter(SimTaocan.taocan == value).first():
        db.add(SimTaocan(taocan=value))


def import_sim(db: Session, user, file_bytes: bytes, filename: str,
               default_bmid: Optional[int]) -> dict:
    """上传 SIM 卡模板文件(照旧 simExcel.exeExcel):卡号已存在(有效)则跳过。"""
    rows = iter_sheet_rows(file_bytes, filename)
    if not rows:
        return {"added": 0, "skipped": 0}
    dept_ids = {d.name: d.id for d in db.query(Department).all()}
    active = {r[0] for r in db.query(SimCard.kahao).filter(SimCard.delf == 1).all() if r[0]}
    now = datetime.now()
    added = skipped = 0
    for row in rows[1:]:
        kahao = cell_str(_cell(row, 0))
        if not kahao:
            break  # 照旧:遇到空卡号即停止
        if kahao in active:
            skipped += 1
            continue
        bm = None
        bm_name = cell_str(_cell(row, 10))
        if bm_name:
            bm = dept_ids.get(bm_name)
        if bm is None:
            bm = default_bmid
        sim = SimCard(
            kahao=kahao,
            didian=cell_str(_cell(row, 1)),
            yongtu=cell_str(_cell(row, 2)),
            bz=cell_str(_cell(row, 3)),
            xuliehao=cell_str(_cell(row, 4)),
            wangluo=cell_str(_cell(row, 5)),
            zt=cell_str(_cell(row, 6)),
            vpn=cell_str(_cell(row, 7)),
            taocan=cell_str(_cell(row, 8)),
            zhanghu=cell_str(_cell(row, 9)),
            bm=bm,
            dengjiren=user.username,
            bianjiren=user.username,
            djriqi=now,
            zhriqi=now,
            delf=1,
        )
        db.add(sim)
        ensure_taocan(db, sim.taocan)
        active.add(kahao)
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}


def import_status(db: Session, user, file_bytes: bytes, filename: str) -> dict:
    """上传批量状态更改(照旧 simExcel.upzt):每行 卡号+新状态,写字段日志。"""
    rows = iter_sheet_rows(file_bytes, filename)
    if not rows:
        return {"updated": 0, "skipped": 0}
    sims = {s.kahao: s for s in db.query(SimCard).all() if s.kahao}
    now = datetime.now()
    updated = skipped = 0
    for row in rows[1:]:
        kahao = cell_str(_cell(row, 0))
        status = cell_str(_cell(row, 1))
        if not kahao or not status:
            break
        sim = sims.get(kahao)
        if sim is None:
            skipped += 1
            continue
        db.add(SimEditLog(
            sim_id=sim.id, field_name="zt", old_value=sim.zt or "",
            new_value=status, edit_user=user.username, edit_time=now, edit_type="edit",
        ))
        sim.zt = status
        sim.zhriqi = now
        sim.bianjiren = f"{user.username}批量"
        updated += 1
    db.commit()
    return {"updated": updated, "skipped": skipped}


def import_fees(db: Session, user, file_bytes: bytes, filename: str,
                bmid: int, year: int, month: int, file_type: str) -> dict:
    """上传话费清单(照旧 UploadCost/upcost):第一列卡号、第二列金额。

    file_type=mobile 时移动清单以"分"为单位,除以 100。
    """
    rows = iter_sheet_rows(file_bytes, filename)
    if not rows:
        return {"count": 0, "skipped": 0}
    existing = {
        r[0] for r in db.query(Feiyong.kahao).filter(
            Feiyong.nian == year, Feiyong.yue == month
        ).all() if r[0]
    }
    sim_map = {s.kahao: s for s in db.query(SimCard).all() if s.kahao}
    count = skipped = 0
    for row in rows[1:]:
        col0 = cell_str(_cell(row, 0))
        col1 = cell_str(_cell(row, 1))
        if "合计" in col0 or "总计" in col0 or "合计" in col1 or "总计" in col1:
            break
        if not col0:
            continue
        amount = parse_amount(_cell(row, 1))
        if amount is None:
            continue
        if file_type == "mobile":
            amount = _round4(amount / Decimal("100"))
        if col0 in existing:
            skipped += 1
            continue
        bm = bmid
        sim = sim_map.get(col0)
        if sim is not None and sim.bm and sim.bm > 0:
            bm = sim.bm
        db.add(Feiyong(
            kahao=col0, jine=amount, nian=year, yue=month,
            syren=user.username, bm=bm, bz="",
        ))
        existing.add(col0)
        count += 1
    db.commit()
    return {"count": count, "skipped": skipped}


def _find_match(tmp: str, by_kahao: dict, prefixes: list):
    hit = by_kahao.get(tmp)
    if hit is not None:
        return hit
    for xuliehao, sim in prefixes:
        if xuliehao and tmp.startswith(xuliehao):
            return sim
    return None


def _matched_values(sim: Optional[SimCard]) -> list:
    if sim is None:
        return [""] * 9
    return [
        sim.yongtu or "", sim.taocan or "", sim.zt or "", sim.dengjiren or "",
        sim.djriqi.strftime("%Y-%m-%d") if sim.djriqi else "",
        sim.wangluo or "", sim.didian or "", sim.bz or "", sim.zhanghu or "",
    ]


def reconcile(db: Session, file_bytes: bytes, filename: str) -> bytes:
    """上传 SIM 卡核对文件(照旧 simExcel.exeExcelhedui)。

    逐行按卡号匹配(次选:上传值以序列号开头),把匹配到的卡信息写回第 2-10 列;
    同时新增「剩余卡号」sheet,列出系统内未被上传文件覆盖的卡。
    输出统一为 .xlsx(旧 .xls 也能读,格式重排属已知差异)。
    """
    rows = iter_sheet_rows(file_bytes, filename)
    if not rows:
        raise ValueError("文件为空")
    sims = db.query(SimCard).all()
    by_kahao = {s.kahao: s for s in sims if s.kahao}
    prefixes = [(s.xuliehao, s) for s in sims if s.xuliehao]
    uploaded = set()

    out = Workbook()
    ws = out.active
    ws.title = "核对结果"
    header = list(rows[0])
    for c, val in enumerate(header, start=1):
        ws.cell(row=1, column=c, value=val)
    # 保证至少有 10 列(卡号 + 9 个回填字段)
    while len(header) < 10:
        header.append("")
        ws.cell(row=1, column=len(header), value="")
    for r, row in enumerate(rows[1:], start=2):
        tmp = cell_str(_cell(row, 0))
        values = [cell_str(_cell(row, c)) for c in range(len(header))]
        for c, val in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=val)
        if tmp:
            uploaded.add(tmp)
        sim = _find_match(tmp, by_kahao, prefixes) if tmp else None
        for c, val in enumerate(_matched_values(sim), start=2):
            ws.cell(row=r, column=c, value=val)

    left = out.create_sheet("剩余卡号")
    left_headers = ["卡号", "用途", "套餐", "状态", "登记人", "登记日期", "网络", "地点", "备注", "账户"]
    for c, val in enumerate(left_headers, start=1):
        left.cell(row=1, column=c, value=val)
    r = 2
    for s in sims:
        if s.kahao and s.kahao not in uploaded:
            vals = [s.kahao] + _matched_values(s)
            for c, val in enumerate(vals, start=1):
                left.cell(row=r, column=c, value=val)
            r += 1

    _style_sheet(ws, header)
    _style_sheet(left, left_headers)
    buf = io.BytesIO()
    out.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_sim_template() -> bytes:
    headers = ["卡号", "地点", "用途", "备注", "序列号", "运营商网络", "使用状态", "VPN", "套餐", "账户", "部门"]
    wb = Workbook()
    ws = wb.active
    ws.title = "SIM卡"
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    _style_sheet(ws, headers)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_fee_template() -> bytes:
    headers = ["卡号", "话费", "年度", "月份"]
    wb = Workbook()
    ws = wb.active
    ws.title = "话费清单"
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    _style_sheet(ws, headers)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def build_status_template() -> bytes:
    headers = ["卡号", "状态"]
    wb = Workbook()
    ws = wb.active
    ws.title = "批量状态更改"
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    _style_sheet(ws, headers)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


EXPORT_COLUMNS = [
    ("ID", "ID"), ("卡号", "kahao"), ("地点", "didian"), ("用途", "yongtu"),
    ("备注", "bz"), ("序列号", "xuliehao"), ("部门", "bumen"),
    ("登记人", "dengjiren"), ("管理人", "glren"), ("运营商网络", "wangluo"),
    ("使用状态", "zt"), ("VPN", "vpn"), ("套餐", "taocan"),
    ("登记时间", "djriqi"), ("使用人", "syren"), ("删除标志", "delf"),
    ("账户", "zhanghu"),
]


def build_export(rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "SIM卡列表"
    for c, (label, _key) in enumerate(EXPORT_COLUMNS, start=1):
        ws.cell(row=1, column=c, value=label)
    for r, row in enumerate(rows, start=2):
        for c, (_label, key) in enumerate(EXPORT_COLUMNS, start=1):
            v = row.get(key)
            if key == "delf":
                v = 0 if v == 0 else 1
            ws.cell(row=r, column=c, value=v if v is not None else "")
    widths = {
        "ID": 10, "kahao": 18, "didian": 30, "yongtu": 14, "bz": 30,
        "xuliehao": 20, "bumen": 16, "dengjiren": 12, "glren": 12,
        "wangluo": 16, "zt": 12, "vpn": 20, "taocan": 16, "djriqi": 20,
        "syren": 12, "delf": 10, "zhanghu": 16,
    }
    for c, (_label, key) in enumerate(EXPORT_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(c)].width = widths.get(key, 14)
    _style_header(ws, len(EXPORT_COLUMNS))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _style_header(ws, count: int):
    thin = Side(style="thin", color="d0d7de")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    fill = PatternFill("solid", fgColor="eef2f7")
    for c in range(1, count + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border


def _style_sheet(ws, headers: list):
    for c, h in enumerate(headers, start=1):
        width = max(12, min(40, len(str(h)) * 2 + 6))
        ws.column_dimensions[get_column_letter(c)].width = width
    _style_header(ws, len(headers))


def history_value(field_name: str, value: str, dept_names: dict) -> str:
    if field_name != "bm" or not value:
        return value
    try:
        return dept_names.get(int(value), value)
    except (TypeError, ValueError):
        return value
