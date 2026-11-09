"""IP 地址管理公共口径:筛选、列表行组装、网段下拉、Excel 导出。

照旧 ipadressService.LoadSearchEntities / FilterByZt:
- 关键字模糊匹配 网络名称 / 地点 / 用途 / 使用人
- 网段多选(前端传逗号串)
- 状态「可领用」= 未使用,「已占用」= 状态为空或不是未使用
- 部门按登录人部门子树过滤(超管/未挂部门用户不限)
"""

from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import or_

from app.api.deps import dept_name_map, dept_scope_ids
from app.models.ipadress import Ipadress, IpNetCreator

STATUS_UNUSED = "未使用"
STATUS_USED = "已使用"

STATUS_FILTERS = [
    {"value": "", "label": "全部"},
    {"value": "可领用", "label": "可领用"},
    {"value": "已占用", "label": "已占用"},
]

APPLY_LOCATIONS = [
    "综合办", "营业厅", "抄表班", "资讯室", "调度平台", "管网技术部", "营业部",
    "稽查", "所长室", "二供管网", "二供营业", "二供综合办", "二供抄表", "二供经理",
]

APPLY_USES = ["办公", "打印机", "柜台收费", "公用", "其他"]

EXPORT_COLUMNS = [
    ("序号", "_seq"),
    ("网络名称", "netname"),
    ("部门", "bm"),
    ("登记人", "sqren"),
    ("网段", "net"),
    ("IP", "numb"),
    ("完整IP", "ip"),
    ("地点", "didian"),
    ("使用人", "syren"),
    ("用途", "yongtu"),
    ("状态", "zt"),
    ("申请日期", "_sqdate"),
    ("系统日期", "_netdate"),
]


def ip_query(db, user, keyword: str = "", netnames: str = "", ipzt: str = ""):
    q = db.query(Ipadress)
    scope = dept_scope_ids(db, user)
    if scope is not None:
        q = q.filter(Ipadress.bmid.in_(scope))

    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(
            Ipadress.netname.like(like),
            Ipadress.didian.like(like),
            Ipadress.yongtu.like(like),
            Ipadress.syren.like(like),
        ))

    names = [n.strip() for n in (netnames or "").split(",") if n.strip()]
    if names:
        q = q.filter(Ipadress.netname.in_(names))

    zt = (ipzt or "").strip()
    if zt == "可领用":
        q = q.filter(Ipadress.zt == STATUS_UNUSED)
    elif zt == "已占用":
        q = q.filter(or_(Ipadress.zt.is_(None), Ipadress.zt != STATUS_UNUSED))
    return q


def full_ip(row: Ipadress) -> str:
    net = (row.net or "").rstrip(".")
    if not net:
        return "" if row.numb is None else str(row.numb)
    return f"{net}.{row.numb}" if row.numb is not None else net


def _minute(v):
    return v.strftime("%Y-%m-%d %H:%M") if v else ""


def build_rows(db, rows: list) -> list:
    names = dept_name_map(db)
    out = []
    for r in rows:
        d = r.to_dict()
        d["bm"] = names.get(r.bmid, "") if r.bmid else ""
        d["ip"] = full_ip(r)
        d["sqdate"] = _minute(r.sqdate)
        d["netdate"] = _minute(r.netdate)
        out.append(d)
    return out


def netname_options(db) -> list:
    names = [
        n for (n,) in db.query(Ipadress.netname)
        .filter(Ipadress.netname.isnot(None)).distinct().all()
        if n
    ]
    creators = {
        c.netname: c.creator or ""
        for c in db.query(IpNetCreator).all()
    }
    return [
        {"value": name, "text": name, "creator": creators.get(name, "")}
        for name in sorted(names)
    ]


def has_perm(user, code: str) -> bool:
    if user.is_superuser:
        return True
    return any(p.code == code for role in user.roles for p in role.permissions)


def content_disposition(filename: str) -> str:
    return (f'attachment; filename="export.xlsx"; '
            f"filename*=UTF-8''{quote(filename)}")


def build_excel(rows: list) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "IP地址信息"

    thin = Side(style="thin", color="d0d7de")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="eef2f7")

    for c, (label, _key) in enumerate(EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = Font(bold=True, color="1f2937")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for r, row in enumerate(rows, start=2):
        for c, (_label, key) in enumerate(EXPORT_COLUMNS, start=1):
            if key == "_seq":
                v = r - 1
            elif key == "_sqdate":
                v = row.get("sqdate") or ""
            elif key == "_netdate":
                v = row.get("netdate") or ""
            else:
                v = row.get(key)
            if v is None:
                v = ""
            cell = ws.cell(row=r, column=c, value=v)
            cell.border = border

    widths = {
        "_seq": 6, "netname": 24, "bm": 18, "sqren": 12, "net": 16,
        "numb": 8, "ip": 18, "didian": 22, "syren": 14, "yongtu": 16,
        "zt": 10, "_sqdate": 18, "_netdate": 18,
    }
    for c, (_label, key) in enumerate(EXPORT_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(c)].width = widths.get(key, 12)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
