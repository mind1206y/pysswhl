"""车辆保险(照旧 CLbaoxianController 1:1 复刻)。

- 列表:cl_baoxian 关联 cl_che,关键字(保险公司/车号)/年度/保险种类/部门筛选,
  部门子树数据权限,返回筛选结果合计金额(footer 合计行)
- 增删改:登记人取当前登录人;编辑仅限登记人本人或登记人为空的历史数据(旧口径);
  删除无本人限制(旧 Deletegz 无校验)
- 字典:年度/部门/车辆下拉(用途≠油卡、未删除)/历史保险公司聚合标签
- 模板下载/上传导入(.xlsx、文件名含「保险」、保单号去重)/导出 Excel 12 列

权限:旧系统仅菜单控制访问,单个 view 码覆盖全部日常操作(与路面修复等口径一致)。
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.user import Department, User
from app.models.vehicle import ClBaoxian, ClChe
from app.services.baoxian import (
    LX_OPTIONS, baoxian_query, build_excel, build_rows, build_template,
    content_disposition, import_xlsx, sum_jine,
)

router = APIRouter()


class BaoxianIn(BaseModel):
    cheid: Optional[int] = None
    tbdate: Optional[date] = None
    bdnumber: Optional[str] = None
    lx: Optional[str] = None
    jine: Optional[float] = None
    bxcom: Optional[str] = None
    dqdate: Optional[date] = None
    jingshou: Optional[str] = None
    bz: Optional[str] = None


# ==================== 公共辅助 ====================
def _get_or_404(db: Session, bx_id: int) -> ClBaoxian:
    row = db.get(ClBaoxian, bx_id)
    if row is None:
        raise HTTPException(status_code=404, detail="保险记录不存在")
    return row


def _car_of(db: Session, row: ClBaoxian) -> Optional[ClChe]:
    return db.get(ClChe, row.cheid) if row.cheid else None


def _check_visible(db: Session, user: User, car: Optional[ClChe]):
    """非超管不能操作本人部门子树之外的记录(与列表作用域一致)。"""
    if car is None:
        raise HTTPException(status_code=404, detail="车辆不存在")
    scope = dept_scope_ids(db, user)
    if scope is not None and car.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该保险记录的权限")


def _row_dict(db: Session, row: ClBaoxian, car: Optional[ClChe]) -> dict:
    from app.api.deps import dept_name_map

    d = row.to_dict()
    d["chehao"] = car.chehao if car else ""
    d["yongtu"] = (car.yongtu or "") if car else ""
    dept_name = (dept_name_map(db).get(car.bmid) if car and car.bmid else "") or ""
    d["bumen"] = dept_name or (car.bm if car else "") or ""
    return d


# ==================== 列表 / 字典 / 下拉 ====================
@router.get("")
def list_baoxian(
    page: int = 1,
    size: int = 30,
    keyword: str = "",
    year: Optional[int] = None,
    lx: str = "",
    dept: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    q = baoxian_query(db, current, keyword=keyword, year=year, lx=lx, dept=dept)
    total = q.count()
    tj = sum_jine(q)
    pairs = (
        q.order_by(ClBaoxian.tbdate.desc(), ClBaoxian.id.desc())
        .offset((page - 1) * size).limit(size).all()
    )
    return {"total": total, "tj": tj, "items": build_rows(db, pairs)}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]
    years = [
        int(y) for (y,) in (
            db.query(func.year(ClBaoxian.tbdate))
            .filter(ClBaoxian.tbdate.isnot(None))
            .distinct().order_by(func.year(ClBaoxian.tbdate).desc()).all()
        )
    ]
    return {"departments": departments, "years": years, "lx": LX_OPTIONS}


@router.get("/vehicles")
def vehicle_options(
    q: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    """车号下拉(照旧 Getch:用途≠油卡、delf≠0、部门子树)。"""
    query = db.query(ClChe).filter(ClChe.yongtu != "油卡", ClChe.delf != 0)
    scope = dept_scope_ids(db, current)
    if scope is not None:
        query = query.filter(ClChe.bmid.in_(scope))
    kw = (q or "").strip()
    if kw:
        query = query.filter(ClChe.chehao.like(f"%{kw}%"))
    cars = query.order_by(ClChe.chehao).all()
    return [{"id": c.id, "chehao": c.chehao or ""} for c in cars]


@router.get("/bxcoms")
def bxcom_list(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    """历史保险公司聚合标签(照旧 GetbxcomList:去重排序)。"""
    rows = (
        db.query(ClBaoxian.bxcom).filter(
            ClBaoxian.bxcom.isnot(None), ClBaoxian.bxcom != "")
        .distinct().order_by(ClBaoxian.bxcom).all()
    )
    return [{"duixiang": v} for (v,) in rows]


# ==================== 模板 / 导入 / 导出 ====================
@router.get("/template")
def download_template(
    current: User = Depends(require_permission("baoxian:view")),
):
    buf = build_template()
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition("保险导入模板.xlsx")},
    )


@router.post("/import")
def upload_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    """照旧 UploadFile:文件名须含「保险」且为 .xlsx。"""
    name = file.filename or ""
    if not name.lower().endswith(".xlsx") or "保险" not in name:
        raise HTTPException(status_code=400, detail="文件名须包含“保险”且为 .xlsx 文件")
    data = file.file.read()
    return import_xlsx(data, current.username, db)


@router.get("/export")
def export_excel(
    keyword: str = "",
    year: Optional[int] = None,
    lx: str = "",
    dept: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    """导出(照旧 loadexcel/loadbxExcel 12 列;关键字口径与列表一致,含车号)。"""
    q = baoxian_query(db, current, keyword=keyword, year=year, lx=lx, dept=dept)
    pairs = q.order_by(ClBaoxian.tbdate.desc(), ClBaoxian.id.desc()).all()
    buf = build_excel(build_rows(db, pairs))
    filename = f"保险费用清单（{datetime.now():%Y年%m月%d日}）.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )


# ==================== 单条 / 增删改(动态路由放最后) ====================
@router.get("/{bx_id}")
def get_baoxian(
    bx_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    row = _get_or_404(db, bx_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    return _row_dict(db, row, car)


@router.post("")
def create_baoxian(
    data: BaoxianIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    if data.cheid is None:
        raise HTTPException(status_code=400, detail="请选择车辆")
    if data.tbdate is None:
        raise HTTPException(status_code=400, detail="投保日期不能为空")
    if data.dqdate is None:
        raise HTTPException(status_code=400, detail="保险到期不能为空")
    car = db.get(ClChe, data.cheid)
    _check_visible(db, current, car)
    row = ClBaoxian(
        cheid=data.cheid,
        tbdate=data.tbdate,
        bdnumber=(data.bdnumber or "").strip(),
        lx=(data.lx or "").strip(),
        jine=data.jine,
        bxcom=(data.bxcom or "").strip(),
        dqdate=data.dqdate,
        djname=current.username,
        djdate=datetime.now(),
        jingshou=(data.jingshou or "").strip(),
        bz=(data.bz or "").strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_dict(db, row, car)


@router.put("/{bx_id}")
def update_baoxian(
    bx_id: int,
    data: BaoxianIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    row = _get_or_404(db, bx_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)
    # 旧口径:登记人为空的历史数据允许修改,非登记人本人拒绝
    if (row.djname or "") and row.djname != current.username:
        raise HTTPException(status_code=403, detail="只有登记人才能编辑该记录")

    if "cheid" in data.model_fields_set and data.cheid is not None and data.cheid != row.cheid:
        new_car = db.get(ClChe, data.cheid)
        _check_visible(db, current, new_car)
        row.cheid = data.cheid
        car = new_car
    if "tbdate" in data.model_fields_set:
        if data.tbdate is None:
            raise HTTPException(status_code=400, detail="投保日期不能为空")
        row.tbdate = data.tbdate
    if "dqdate" in data.model_fields_set:
        if data.dqdate is None:
            raise HTTPException(status_code=400, detail="保险到期不能为空")
        row.dqdate = data.dqdate
    for f in ("bdnumber", "lx", "bxcom", "jingshou", "bz"):
        if f in data.model_fields_set:
            setattr(row, f, (getattr(data, f) or "").strip())
    if "jine" in data.model_fields_set:
        row.jine = data.jine
    row.djdate = datetime.now()  # 照旧 Editgz:编辑时刷新登记日期,登记人不变
    db.commit()
    db.refresh(row)
    return _row_dict(db, row, car)


@router.delete("/{bx_id}")
def delete_baoxian(
    bx_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("baoxian:view")),
):
    row = _get_or_404(db, bx_id)
    car = _car_of(db, row)
    _check_visible(db, current, car)  # 旧 Deletegz 无本人校验,仅要求记录可见
    db.delete(row)
    db.commit()
    return {"message": "已删除"}
