"""水费系统 Excel 导入/更新/导出(照旧系统 UploadE/UploadUpdate/ExportExcel 系列)。

依赖 openpyxl。表头用中文列名映射;导入按 年度+身份证+事项 查重;
取消导入回写主表取消日期并写"取消日期"日志;导出列照旧系统清单。
"""

import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from app.models.user import User, Department
from app.models.water_fee import Shuifeixitong, ShuifeixitongBiandong, ShuifeixitongLog, ShuifeixitongQuxiao

# 中文表头 → 实体字段(导入/导出共用;照旧系统 BuildColumnMap + UploadE 的 GetCell 取数名)
COLUMN_MAP = {
    "市": "shi", "省市": "shi", "省/市": "shi", "区县": "quxian", "乡镇": "xiangzhen", "村": "cun",
    "事项": "shixiang", "办理事项": "shixiang", "姓名": "xingming", "申请人姓名": "xingming",
    "身份证号": "sfz", "证件号": "sfz", "申请人证件号码": "sfz",
    "居住地址": "juzhudizhi", "电话": "dianhua", "联系电话": "dianhua",
    "开户名": "kaihuming", "开户名称": "kaihuming",
    "银行账号": "yinhangzhanghao", "开户行": "kaihuhang", "开户身份证": "kaihushenfenzheng",
    "开户人身份证号码": "kaihushenfenzheng",
    "银行备注": "yinhangbeizhu", "银行账号备注": "yinhangbeizhu",
    "保障开始": "ksbriqi", "保障年月起": "ksbriqi", "起始保障年月": "ksbriqi",
    "保障结束": "jsbriqi", "保障年月止": "jsbriqi", "截止保障年月": "jsbriqi",
    "特困类别": "tekunlei",
    "供水方式": "gongyangfangshi", "供养方式": "gongyangfangshi",
    "供水机构": "gongyangjigou", "供养机构": "gongyangjigou",
    "营业所": "bm", "部门": "bm",
    "用户号": "yonghuhao", "其他用水情况": "qitayongshui",
    "备注": "beizhu", "受理日期": "shouliriqi", "受理时间": "shouliriqi",
    "优惠开始": "youhuiksriqi", "优惠年月起": "youhuiksriqi", "优惠开始年月": "youhuiksriqi",
    "优惠开始时间": "youhuiksriqi",
    "优惠结束": "youhuijsriqi", "优惠年月止": "youhuijsriqi", "优惠结束年月": "youhuijsriqi",
    "优惠结束时间": "youhuijsriqi",
    "污水费核退": "wushuifeihetui", "污水费核退时间": "wushuifeihetui",
    "系统导入情况": "daoruqingkuang",
    "返民政局": "fanhuiminzhengju",
    "柜台受理情况": "guitaishouli",
    "年度": "nd", "优惠月数": "yueshu", "文件序号": "序号列", "序号": "序号列",
    "取消日期": "quxiaoriqi", "取消年月": "quxiaoriqi",
}

# 各日期字段的解析格式优先级(旧数据是"年月"文本;8位数字照旧 ParseDateAllowNull)
DATE_PARSE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y%m", "%Y-%m", "%Y.%m", "%Y年%m月", "%Y"]


def parse_date(text):
    """把 Excel 里的年月文本解析为日期(取当月1号);解析失败返回 None。"""
    if text in (None, ""):
        return None
    if isinstance(text, datetime):
        return text
    s = str(text).strip()
    for fmt in DATE_PARSE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def cell_str(v):
    if v is None:
        return ""
    return str(v).strip()


def iter_bytes(file_bytes: bytes):
    """只解析各 sheet 的表头(供导入列选择界面)。"""
    out = []
    for name, header, _rows in iter_sheets(file_bytes):
        out.append((name, header))
    return out


def iter_sheets(file_bytes: bytes):
    """逐 sheet 产出 (sheet名, 表头行索引, 数据行迭代)。要求第一行为表头。"""
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = None
            for r in rows:
                if any(v not in (None, "") for v in r):
                    header = [cell_str(v) for v in r]
                    break
            if header:
                yield ws.title, header, rows
    finally:
        wb.close()


def parse_nd(text, default=None):
    """从文本解析年度(取4位数字年份),失败用 default。"""
    if text in (None, ""):
        return default
    s = str(text).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m", "%Y-%m", "%Y.%m", "%Y年%m月"):
        try:
            return datetime.strptime(s, fmt).year
        except ValueError:
            continue
    if len(s) == 4 and s.isdigit():
        return int(s)
    return default


def import_rows(
    db: Session, user: User, file_bytes: bytes, nd: int, selected_cols: List[str],
    is_quxiao: bool = False, quxiaoriqi: Optional[datetime] = None,
):
    """导入新增(照旧 UploadE/upcostNew)。返回统计 dict。

    普通导入:按 年+身份证+事项 查重(基准主表),插入主表。
    取消导入(is_quxiao,照旧):查重基准与插入目标都是【取消表】,并把主表中
    匹配(身份证+事项)的未取消记录回写取消日期+写日志;不插入主表。
    """
    cols = set(selected_cols) if selected_cols else set(COLUMN_MAP.values())
    now = datetime.now()
    # 部门映射字典(照旧 bumenDict:部门名 → id)
    dept_ids = {d.name: d.id for d in db.query(Department).all()}

    def parse_row(header, r):
        """按表头把一行解析成 {字段: 值}(只取勾选列)。"""
        rec = {}
        for i, h in enumerate(header):
            field = COLUMN_MAP.get(h)
            if field is None or field == "序号列" or field not in cols or i >= len(r):
                continue
            raw = r[i]
            if field in ("ksbriqi", "jsbriqi", "youhuiksriqi", "youhuijsriqi", "wushuifeihetui", "shouliriqi"):
                rec[field] = parse_date(raw)
            elif field == "nd":
                rec[field] = parse_nd(raw, default=nd)
            elif field in ("yueshu", "wenjianxuhao"):
                s = cell_str(raw)
                rec[field] = int(float(s)) if s.replace(".", "", 1).isdigit() else None
            else:
                rec[field] = cell_str(raw)
        return rec

    if is_quxiao:
        # ========== 取消导入(照旧 upcostNew 的 isQuxiao 分支) ==========
        exist = {
            f"{sfz or ''}|{sx or ''}"
            for sfz, sx in db.query(ShuifeixitongQuxiao.sfz, ShuifeixitongQuxiao.shixiang)
            .filter(ShuifeixitongQuxiao.nd == nd)
            .all()
        }
        qdate = quxiaoriqi or now
        added = skipped_dup = 0
        cancel_keys = set()
        for sheet_name, header, rows in iter_sheets(file_bytes):
            for r in rows:
                if not any(v not in (None, "") for v in r):
                    continue
                rec = parse_row(header, r)
                if not any(v for v in rec.values()):
                    continue
                key = f"{rec.get('sfz', '') or ''}|{rec.get('shixiang', '') or ''}"
                if key in exist:
                    skipped_dup += 1
                else:
                    exist.add(key)
                    db.add(ShuifeixitongQuxiao(
                        shi=rec.get("shi", ""), quxian=rec.get("quxian", ""),
                        xiangzhen=rec.get("xiangzhen", ""), cun=rec.get("cun", ""),
                        shixiang=rec.get("shixiang", ""), xingming=rec.get("xingming", ""),
                        sfz=rec.get("sfz", ""), juzhudizhi=rec.get("juzhudizhi", ""),
                        dianhua=rec.get("dianhua", ""), kaihuming=rec.get("kaihuming", ""),
                        yinhangzhanghao=rec.get("yinhangzhanghao", ""), kaihuhang=rec.get("kaihuhang", ""),
                        kaihushenfenzheng=rec.get("kaihushenfenzheng", ""), yinhangbeizhu=rec.get("yinhangbeizhu", ""),
                        ksbriqi=rec.get("ksbriqi"), jsbriqi=rec.get("jsbriqi"), tekunlei=rec.get("tekunlei", ""),
                        gongyangfangshi=rec.get("gongyangfangshi", ""), gongyangjigou=rec.get("gongyangjigou", ""),
                        bm=rec.get("bm", ""), yonghuhao=rec.get("yonghuhao", ""),
                        qitayongshui=rec.get("qitayongshui", ""), beizhu=rec.get("beizhu", ""),
                        shouliriqi=rec.get("shouliriqi"), youhuiksriqi=rec.get("youhuiksriqi"),
                        youhuijsriqi=rec.get("youhuijsriqi"), wushuifeihetui=rec.get("wushuifeihetui"),
                        daoruqingkuang=rec.get("daoruqingkuang", ""), fanhuiminzhengju=rec.get("fanhuiminzhengju", ""),
                        guitaishouli=rec.get("guitaishouli", ""),
                        nd=nd, yueshu=rec.get("yueshu"), wenjianxuhao=rec.get("wenjianxuhao"),
                        biaoming=sheet_name, caozuo=user.username, caozuoriqi=now,
                        quxiaoriqi=qdate, quxiaoren=user.username,
                    ))
                    added += 1
                if quxiaoriqi is not None:
                    cancel_keys.add(key)
        db.flush()
        # 回写主表:匹配 身份证+事项 的未取消记录 → 写取消日期+日志(照旧)
        cancel_marked = 0
        if cancel_keys:
            mains = (
                db.query(Shuifeixitong)
                .filter(Shuifeixitong.nd == nd, Shuifeixitong.quxiaoriqi.is_(None))
                .all()
            )
            for s in mains:
                if f"{s.sfz or ''}|{s.shixiang or ''}" in cancel_keys:
                    s.quxiaoriqi = quxiaoriqi
                    s.caozuo = user.username
                    s.caozuoriqi = now
                    db.add(ShuifeixitongLog(
                        main_id=s.id, field_name="取消日期", old_value="",
                        new_value=qdate.strftime("%Y-%m-%d %H:%M:%S"),
                        update_user=user.username, update_time=now, source="shuifeixitong",
                    ))
                    cancel_marked += 1
        db.commit()
        return {
            "added": added, "skipped_dup": skipped_dup,
            "cancel_inserted": added, "cancel_marked": cancel_marked,
        }

    # ========== 普通导入(插入主表) ==========
    added = skipped_dup = 0
    for sheet_name, header, rows in iter_sheets(file_bytes):
        for r in rows:
            if not any(v not in (None, "") for v in r):
                continue
            rec = parse_row(header, r)
            if not any(v for v in rec.values()):
                continue
            sfz = rec.get("sfz", "")
            shixiang = rec.get("shixiang", "")
            row_nd = rec.get("nd") or nd
            dup = None
            if sfz or shixiang:
                dup = (
                    db.query(Shuifeixitong)
                    .filter(Shuifeixitong.nd == row_nd, Shuifeixitong.sfz == sfz, Shuifeixitong.shixiang == shixiang)
                    .first()
                )
            if dup:
                skipped_dup += 1
                continue
            row = Shuifeixitong(biaoming=sheet_name, nd=row_nd)
            for k, v in rec.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            # 部门映射(照旧 bumenDict:bm 列 + "营业所" 匹配部门名,精确匹配再退全名)
            if rec.get("bm"):
                full = rec["bm"] + "营业所"
                row.bmid = dept_ids.get(full) or dept_ids.get(rec["bm"])
            row.caozuo = user.username
            row.caozuoriqi = now
            if quxiaoriqi is not None:
                row.quxiaoriqi = quxiaoriqi
            db.add(row)
            db.flush()
            added += 1
    db.commit()
    return {"added": added, "skipped_dup": skipped_dup, "cancel_inserted": 0, "cancel_marked": 0}


def import_cancel_writeback(
    db: Session, user: User, file_bytes: bytes, nd: int, quxiaoriqi: datetime,
):
    """取消名单回写(照旧 upcostNew 的取消分支):按 年+身份证+事项 匹配主表,写取消日期+日志。"""
    marked = 0
    now = datetime.now()
    for sheet_name, header, rows in iter_sheets(file_bytes):
        hmap = {cell_str(h): i for i, h in enumerate(header)}
        sfz_i = next((i for h, i in hmap.items() if COLUMN_MAP.get(h) == "sfz"), None)
        shixiang_i = next((i for h, i in hmap.items() if COLUMN_MAP.get(h) == "shixiang"), None)
        if sfz_i is None:
            continue
        for r in rows:
            sfz = cell_str(r[sfz_i]) if sfz_i < len(r) else ""
            shixiang = cell_str(r[shixiang_i]) if shixiang_i is not None and shixiang_i < len(r) else ""
            if not sfz and not shixiang:
                continue
            cond = [Shuifeixitong.nd == nd]
            if sfz:
                cond.append(Shuifeixitong.sfz == sfz)
            if shixiang:
                cond.append(Shuifeixitong.shixiang == shixiang)
            targets = db.query(Shuifeixitong).filter(*cond, Shuifeixitong.quxiaoriqi.is_(None)).all()
            for row in targets:
                row.quxiaoriqi = quxiaoriqi
                row.caozuo = user.username
                row.caozuoriqi = now
                db.add(ShuifeixitongLog(
                    main_id=row.id, field_name="取消日期", old_value="", new_value=str(quxiaoriqi),
                    update_user=user.username, update_time=now, source="shuifeixitong",
                ))
                # 同步取消表
                q = ShuifeixitongQuxiao(
                    shi=row.shi, quxian=row.quxian, xiangzhen=row.xiangzhen, cun=row.cun,
                    shixiang=row.shixiang, xingming=row.xingming, sfz=row.sfz,
                    juzhudizhi=row.juzhudizhi, dianhua=row.dianhua, nd=row.nd,
                    yonghuhao=row.yonghuhao, biaoming=sheet_name, caozuo=user.username,
                    caozuoriqi=now, quxiaoriqi=quxiaoriqi, quxiaoren=user.username,
                )
                db.add(q)
                marked += 1
    db.commit()
    return {"cancel_marked": marked}


def import_update(
    db: Session, user: User, file_bytes: bytes, nd: int, selected_cols: List[str],
):
    """上传更新(照旧 UploadUpdate):按 年+身份证+事项 匹配,只更新最小 id,空单元格也覆盖;差异写日志。"""
    cols = set(selected_cols) if selected_cols else set(COLUMN_MAP.values())
    updated = not_found = 0
    now = datetime.now()
    # 部门映射字典(照旧 bumenDict:部门名 → id)
    dept_ids = {d.name: d.id for d in db.query(Department).all()}
    for sheet_name, header, rows in iter_sheets(file_bytes):
        hmap = {}
        for i, h in enumerate(header):
            field = COLUMN_MAP.get(h)
            if field and field != "序号列" and field in cols and field not in ("nd",):
                hmap[i] = field
        sfz_i = next((i for i, f in hmap.items() if f == "sfz"), None)
        shixiang_i = next((i for i, f in hmap.items() if f == "shixiang"), None)
        for r in rec_iter(rows):
            sfz = cell_str(r[sfz_i]) if sfz_i is not None and sfz_i < len(r) else ""
            shixiang = cell_str(r[shixiang_i]) if shixiang_i is not None and shixiang_i < len(r) else ""
            if not sfz and not shixiang:
                continue
            target = (
                db.query(Shuifeixitong)
                .filter(Shuifeixitong.nd == nd, Shuifeixitong.sfz == sfz, Shuifeixitong.shixiang == shixiang)
                .order_by(Shuifeixitong.id.asc())
                .first()
            )
            if target is None:
                not_found += 1
                continue
            before = {f: getattr(target, f, None) for f in set(hmap.values())}
            for i, field in hmap.items():
                raw = r[i] if i < len(r) else None
                if field in ("ksbriqi", "jsbriqi", "youhuiksriqi", "youhuijsriqi", "wushuifeihetui", "shouliriqi"):
                    setattr(target, field, parse_date(raw))
                elif field in ("yueshu",):
                    s = cell_str(raw)
                    setattr(target, field, int(float(s)) if s.replace(".", "", 1).isdigit() else None)
                else:
                    setattr(target, field, cell_str(raw))
            if "bm" in hmap.values() and target.bm:
                # 同步部门映射(照旧)
                full = target.bm + "营业所"
                target.bmid = dept_ids.get(full) or dept_ids.get(target.bm)
            after = {f: getattr(target, f, None) for f in set(hmap.values())}
            from app.services.water_fee_common import diff_and_log
            diff_and_log(db, before, after, target.id, user, "shuifeixitong")
            target.caozuo = user.username
            target.caozuoriqi = now
            updated += 1
    db.commit()
    return {"updated": updated, "not_found": not_found}


def rec_iter(rows):
    for r in rows:
        if any(v not in (None, "") for v in r):
            yield r


# ==================== 导出 ====================

# 全量导出(照旧 ExportExcel, sheet=民政局数据)
EXPORT_COLUMNS = [
    ("id", "ID"), ("nd", "年度"), ("bm", "营业所"), ("caozuo", "操作者"), ("caozuoriqi", "最后编辑日期"),
    ("shi", "省/市"), ("quxian", "区县"), ("xiangzhen", "乡镇"), ("cun", "村"),
    ("shixiang", "办理事项"), ("xingming", "申请人姓名"), ("sfz", "申请人证件号码"),
    ("ksbriqi", "起始保障年月"), ("jsbriqi", "截止保障年月"), ("tekunlei", "特困类别"),
    ("gongyangfangshi", "供养方式"), ("gongyangjigou", "供养机构"),
    ("juzhudizhi", "居住地址"), ("dianhua", "联系电话"), ("kaihuming", "开户名称"),
    ("yinhangzhanghao", "银行账号"), ("kaihuhang", "开户行"), ("kaihushenfenzheng", "开户人身份证号码"),
    ("yinhangbeizhu", "银行账号备注"),
    ("yonghuhao", "用户号"), ("qitayongshui", "其他用水情况"), ("beizhu", "备注"),
    ("daoruqingkuang", "系统导入情况"), ("fanhuiminzhengju", "返回民政局"), ("guitaishouli", "柜台受理情况"),
    ("shouliriqi", "受理时间"), ("youhuiksriqi", "优惠开始时间"), ("youhuijsriqi", "优惠结束时间"),
    ("yueshu", "优惠月数"), ("wushuifeihetui", "污水费核退时间"),
]
# 简化导出(照旧 ExportExcel_Simplified, sheet=特殊群体用户信息):全量列 + 取消日期/原文件序号/营业所部门
EXPORT_SIMPLIFIED_COLUMNS = EXPORT_COLUMNS + [
    ("quxiaoriqi", "取消日期"), ("wenjianxuhao", "原文件序号"), ("bm2", "营业所部门"),
]

# 变动历史导出(照旧 ExportLsExcel, sheet=民政局变动历史数据;需主表联查字段)
LS_EXPORT_COLUMNS = [
    ("id", "ID"), ("nd", "年度"), ("bm", "营业所"), ("caozuo", "操作者"), ("biandongriqi", "最后编辑日期"),
    ("xingming", "申请人姓名"), ("sfz", "申请人证件号码"),
    ("juzhudizhi_bd", "原居住地址"), ("dianhua_main", "联系电话"),
    ("yonghuhao", "用户号"), ("qitayongshui", "其他用水情况"), ("beizhu", "备注"),
    ("daoruqingkuang", "系统导入情况"), ("fanhuiminzhengju", "返回民政局"), ("guitaishouli", "柜台受理情况"),
    ("shoulishijian", "受理时间"), ("youhuiksriqi", "优惠开始时间"), ("youhuijsriqi", "优惠结束时间"),
    ("yueshu", "优惠月数"), ("wushuifeihetui", "污水费核退时间"), ("juzhudizhi_main", "新居住地址"),
]

# 保障/优惠起止、取消日期按 yyyyMM 展示(照旧 yyyyMM 单元格格式);其余日期 yyyy-MM-dd
YM_EXPORT_FIELDS = {"ksbriqi", "jsbriqi", "youhuiksriqi", "youhuijsriqi", "quxiaoriqi"}


def _fmt_cell(field, v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        if field in YM_EXPORT_FIELDS:
            return v.strftime("%Y%m")
        return v.strftime("%Y-%m-%d")
    return v


def build_excel(rows: list, columns, sheet_name: str = "Sheet1", value_maps: dict = None) -> StreamingResponse:
    """value_maps: {字段: fn(row) → 单元格值},用于联查转换(如 bmid → 部门名)。"""
    value_maps = value_maps or {}
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append([label for _, label in columns])
    for r in rows:
        vals = []
        for f, _ in columns:
            if f in value_maps:
                vals.append(value_maps[f](r))
            else:
                vals.append(_fmt_cell(f, getattr(r, f, None)))
        ws.append(vals)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from urllib.parse import quote
    filename = f"{sheet_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    quoted = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=\"export_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx\"; filename*=UTF-8''{quoted}"
        },
    )


def build_report_excel(stats: list, year: int) -> StreamingResponse:
    """匹配率报表(照旧 Export/CreateReport):部门×事项矩阵,每事项 户数/已匹配/匹配率 3 列 + 合计。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "匹配情况报表"
    item_names = sorted({s["shixiang"] for s in stats})
    departments = sorted({s["bm"] for s in stats})
    stat_map = {(s["bm"], s["shixiang"]): s for s in stats}

    last_col = 1 + len(item_names) * 3 + 3  # 部门列 + N事项×3 + 合计3

    def cell(r, c, v, bold=False):
        x = ws.cell(row=r, column=c, value=v)
        if bold:
            from openpyxl.styles import Font
            x.font = Font(bold=True)
        return x

    # 第1行:年度
    cell(1, 1, "年度：")
    cell(1, 2, str(year))
    # 第3行:办理事项大标题
    cell(3, 2, "办理事项", bold=True)
    ws.merge_cells(start_row=3, start_column=2, end_row=3, end_column=last_col)
    # 第4行:部门 + 各事项列头
    cell(4, 1, "部门", bold=True)
    for i in range(len(item_names)):
        c = 2 + i * 3
        cell(4, c, item_names[i], bold=True)
        ws.merge_cells(start_row=4, start_column=c, end_row=4, end_column=c + 2)
    cell(4, 2 + len(item_names) * 3, "合计", bold=True)
    ws.merge_cells(start_row=4, start_column=2 + len(item_names) * 3, end_row=4, end_column=last_col)
    # 第5行:子表头 户数/已匹配/匹配率
    sub = ["户数", "已匹配", "匹配率"]
    for i in range(len(item_names) + 1):
        for j, t in enumerate(sub):
            cell(5, 2 + i * 3 + j, t, bold=True)

    def fill_row(r, dept, row_map):
        """填一个部门行;row_map: {事项: {total, matched, rate}},空 dict 填空格。"""
        totals = [0, 0]
        for i, item in enumerate(item_names):
            s = row_map.get(item)
            if s is None:
                cell(r, 2 + i * 3, "")
                cell(r, 2 + i * 3 + 1, "")
                cell(r, 2 + i * 3 + 2, "")
                continue
            cell(r, 2 + i * 3, s["total"])
            cell(r, 2 + i * 3 + 1, s["matched"])
            cell(r, 2 + i * 3 + 2, f"{s['rate']}%")
            totals[0] += s["total"]
            totals[1] += s["matched"]
        cell(r, 2 + len(item_names) * 3, totals[0])
        cell(r, 2 + len(item_names) * 3 + 1, totals[1])
        cell(r, 2 + len(item_names) * 3 + 2, f"{round(totals[1] / totals[0] * 100, 1)}%" if totals[0] else "0%")
        cell(r, 1, dept)

    r = 6
    for dept in departments:
        fill_row(r, dept, {s["shixiang"]: s for s in stats if s["bm"] == dept})
        r += 1
    # 合计行(全年度汇总)
    agg = {}
    for s in stats:
        a = agg.setdefault(s["shixiang"], {"total": 0, "matched": 0, "rate": 0})
        a["total"] += s["total"]
        a["matched"] += s["matched"]
    for a in agg.values():
        a["rate"] = round(a["matched"] / a["total"] * 100, 1) if a["total"] else 0
    fill_row(r, "合计", agg)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from urllib.parse import quote
    filename = f"匹配情况报表_{year}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    quoted = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=\"report_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx\"; filename*=UTF-8''{quoted}"
        },
    )
