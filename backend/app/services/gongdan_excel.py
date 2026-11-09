"""工单信息录入导出(照旧 Gongdan/ExportGongdanToExcel 的 20 列 .xls 重建为 .xlsx)。

旧导出依赖 TempData 缓存上一次 GetList 的查询条件(即「导出上次查询结果」);
新系统改为前端把当前筛选条件原样传给 /api/gongdan/export,语义一致且无会话依赖。
时长列照旧把分钟数转成 `H:mm`(小时不补零、分钟两位),分钟数列另存原始 shijian。
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADERS = [
    "ID", "开始日期", "开始时间", "结束日期", "结束时间", "时长", "地址", "内容",
    "材质", "管径", "工单号", "停水", "水量", "材料", "抢修班组", "登记日期",
    "最后日期", "登记人", "分钟数", "备注",
]


def _split(dt: str) -> tuple[str, str]:
    """列表值是 yyyy-MM-dd HH:mm:ss;拆成日期与时间两列。"""
    txt = dt or ""
    if len(txt) >= 10:
        return txt[:10], txt[11:19] if len(txt) >= 19 else ""
    return "", ""


def _duration(minutes) -> str:
    total = int(minutes or 0)
    return f"{total // 60}:{total % 60:02d}"


def build_export(rows: list[dict]) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "工单材料数据"
    ws.append(HEADERS)
    for item in rows:
        kd, kt = _split(item.get("ksriqi"))
        jd, jt = _split(item.get("jsriqi"))
        ws.append([
            item.get("ID"), kd, kt, jd, jt,
            _duration(item.get("shijian")),
            item.get("dizhi") or "", item.get("neirong") or "",
            item.get("caizhi") or "", item.get("guanjing") or "",
            item.get("gongdanhao") or "", item.get("tingshui") or "",
            item.get("shuiliang") or 0, item.get("cailiao") or "",
            item.get("qiangxiurenyuan") or "", item.get("djriqi") or "",
            item.get("zuihouriqi") or "", item.get("djren") or "",
            item.get("shijian") or 0, item.get("beizhu") or "",
        ])
    fill = PatternFill("solid", fgColor="DDEBF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for col in ws.columns:
        width = max((len(str(c.value or "")) for c in col), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 9), 48)
    ws.freeze_panes = "A2"
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out
