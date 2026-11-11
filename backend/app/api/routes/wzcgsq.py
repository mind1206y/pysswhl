"""物资采购申请(照旧 wzcgsqController 1:1 复刻)。

- 列表:部门范围(mine/all/指定部门) + 登记日期区间 + 关键字(部门/原因/物品),
  footer 合计是筛选后全量;按登记日期倒序
- 录入:单弹窗主表 2 字段 + 可编辑明细行,服务端重算小计/合计(不信任前端)
- 输出:打印页数据(申请单 + 验收单)、两个 Excel 下载、明细模板、明细 Excel 解析
- 编辑/删除限本人录入(照旧 IsOwner),并补旧 GetMx/ShowEditInfo 的越权校验
- 无状态机 / 无审批流:审核、验收只体现在打印纸的签字栏
"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import dept_name_map, require_permission
from app.db.session import get_db
from app.models.finance import Wzcgsq, WzcgsqMx
from app.models.user import User
from app.services.finance_common import (
    default_bmid, dept_cj_map, dept_options, display_name, is_owner, user_dept_id,
    wzcgsq_query, wzcgsq_rows, wzcgsq_visible,
)
from app.services.finance_excel import (
    content_disposition, parse_mx_excel, wzcgsq_sq_excel, wzcgsq_template_excel,
    wzcgsq_ys_excel,
)

router = APIRouter()
PERM = "wzcgsq:view"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LIMITS = {"bumen": 50, "sgyy": 200, "wpmc": 100, "ggxh": 100,
          "danwei": 20, "ysqk": 20, "beizhu": 200}


class MxLine(BaseModel):
    wpmc: str = ""
    ggxh: Optional[str] = ""
    danwei: Optional[str] = ""
    shuliang: float = 0
    danjia: float = 0
    ysqk: Optional[str] = "完成"
    beizhu: Optional[str] = ""


class MainIn(BaseModel):
    bumen: Optional[str] = ""
    sgyy: Optional[str] = ""
    mx: list[MxLine] = []


def _check_lengths(data: MainIn):
    for key, value, limit in [
        ("bumen", data.bumen, 50), ("sgyy", data.sgyy, 200),
    ]:
        if value and len(value) > limit:
            raise HTTPException(status_code=400, detail=f"{key} 不能超过 {limit} 字")
    for m in data.mx:
        for key, value, limit in [
            ("wpmc", m.wpmc, 100), ("ggxh", m.ggxh, 100), ("danwei", m.danwei, 20),
            ("ysqk", m.ysqk, 20), ("beizhu", m.beizhu, 200),
        ]:
            if value and len(value) > limit:
                raise HTTPException(status_code=400, detail=f"明细 {key} 不能超过 {limit} 字")


def _mx_lines(data: MainIn):
    """照旧 ParseMx:跳过空物品名;小计服务端 Math.Round(数量*单价,2)。"""
    out = []
    for m in data.mx:
        name = (m.wpmc or "").strip()
        if not name:
            continue
        qty = Decimal(str(m.shuliang or 0))
        price = Decimal(str(m.danjia or 0))
        xiaoji = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out.append({
            "wpmc": name, "ggxh": (m.ggxh or "").strip() or None,
            "danwei": (m.danwei or "").strip() or None,
            "shuliang": qty, "danjia": price, "xiaoji": xiaoji,
            "ysqk": (m.ysqk or "").strip() or "完成",
            "beizhu": (m.beizhu or "").strip() or None,
        })
    if not out:
        raise HTTPException(status_code=400, detail="请至少填写一条物品明细")
    return out


def _mx_of(db, main_id):
    return [m.to_dict() for m in db.query(WzcgsqMx).filter(
        WzcgsqMx.mainid == main_id).order_by(WzcgsqMx.id).all()]


def _user_bm(db, current):
    names = dept_name_map(db)
    return names.get(user_dept_id(current) or 0, "")


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    year = date.today().year
    return {
        "departments": dept_options(db, current),
        "mybm": _user_bm(db, current),
        "years": list(range(year, year - 6, -1)),
        "default_start": f"{year}-01-01",
        "default_end": date.today().isoformat(),
    }


@router.get("")
def list_main(
    page: int = 1,
    size: int = 30,
    keyword: str = "",
    start: str = "",
    end: str = "",
    scope: str = "mine",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    q = wzcgsq_query(db, current, keyword=keyword, start=start, end=end, scope=scope)
    total = q.count()
    hjsum = float(q.order_by(None).with_entities(
        func.coalesce(func.sum(Wzcgsq.hj), 0)).scalar() or 0)
    rows = (q.order_by(Wzcgsq.djriqi.desc(), Wzcgsq.id.desc())
            .offset((page - 1) * size).limit(size).all())
    return {"total": total, "sum_hj": round(hjsum, 2),
            "items": wzcgsq_rows(db, rows)}


@router.get("/template")
def download_template(current: User = Depends(require_permission(PERM))):
    buf = wzcgsq_template_excel()
    return Response(content=buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": content_disposition("物资采购明细模板.xlsx")})


@router.post("/upload-mx")
async def upload_mx(
    file: UploadFile = File(...),
    current: User = Depends(require_permission(PERM)),
):
    """照旧 UploadMx:只解析不入库,返回行给前端明细表。"""
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 10MB")
    try:
        rows, skipped = parse_mx_excel(content, file.filename or "明细.xls")
    except ValueError as e:
        return {"ok": False, "rows": [], "skipped": 0, "msg": str(e)}
    except Exception:
        return {"ok": False, "rows": [], "skipped": 0, "msg": "文件解析失败,请使用明细模板"}
    return {"ok": True, "rows": rows, "skipped": skipped, "msg": ""}


@router.get("/{mid}/mx")
def get_mx(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    wzcgsq_visible(db, current, mid)
    return {"total": len(_mx_of(db, mid)), "items": _mx_of(db, mid)}


@router.get("/{mid}/print")
def print_data(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    m = wzcgsq_visible(db, current, mid)
    return {"main": m.to_dict(), "mx": _mx_of(db, mid), "userBm": _user_bm(db, current)}


@router.get("/{mid}/download-sq")
def download_sq(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    m = wzcgsq_visible(db, current, mid)
    buf = wzcgsq_sq_excel(m.to_dict(), _mx_of(db, mid), _user_bm(db, current))
    return Response(content=buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": content_disposition(
                        f"物资采购申请单（{m.bumen}）.xlsx")})


@router.get("/{mid}/download-ys")
def download_ys(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    m = wzcgsq_visible(db, current, mid)
    buf = wzcgsq_ys_excel(m.to_dict(), _mx_of(db, mid), _user_bm(db, current))
    return Response(content=buf.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": content_disposition(
                        f"物资采购验收单（{m.bumen}）.xlsx")})


@router.get("/{mid}/edit")
def show_edit(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    m = wzcgsq_visible(db, current, mid)
    return {"id": m.id, "bumen": m.bumen, "sgyy": m.sgyy or "", "mx": _mx_of(db, mid)}


@router.get("/{mid}")
def get_main(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    return wzcgsq_visible(db, current, mid).to_dict()


@router.post("")
def create_main(
    data: MainIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    _check_lengths(data)
    lines = _mx_lines(data)
    dept_id = default_bmid(current)
    main = Wzcgsq(
        bumen=(data.bumen or "").strip() or _user_bm(db, current) or "未指定部门",
        sgyy=(data.sgyy or "").strip() or None,
        hj=sum((x["xiaoji"] for x in lines), Decimal("0")),
        cj=dept_cj_map().get(dept_id or 0, ""),
        djriqi=datetime.now().replace(microsecond=0),
        username=display_name(current), userid=current.id, bmid=dept_id,
    )
    db.add(main)
    db.flush()
    for x in lines:
        db.add(WzcgsqMx(mainid=main.id, **x))
    db.commit()
    return {"ok": True, "id": main.id}


@router.put("/{mid}")
def update_main(
    mid: int,
    data: MainIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    m = wzcgsq_visible(db, current, mid)
    if not is_owner(current, m) and not current.is_superuser:
        raise HTTPException(status_code=403, detail="不能编辑非自己录入的数据。")
    _check_lengths(data)
    lines = _mx_lines(data)
    m.bumen = (data.bumen or "").strip() or m.bumen
    m.sgyy = (data.sgyy or "").strip() or None
    m.hj = sum((x["xiaoji"] for x in lines), Decimal("0"))
    m.username = display_name(current)
    m.userid = current.id
    # 旧 Edit 会把 djriqi 重置为 Now,导致历史单据日期被篡改;这里保留原登记日期
    db.query(WzcgsqMx).filter(WzcgsqMx.mainid == mid).delete(synchronize_session=False)
    db.flush()
    for x in lines:
        db.add(WzcgsqMx(mainid=mid, **x))
    db.commit()
    return {"ok": True}


@router.delete("/{mid}")
def delete_main(
    mid: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(PERM)),
):
    m = wzcgsq_visible(db, current, mid)
    if not is_owner(current, m) and not current.is_superuser:
        raise HTTPException(status_code=403, detail="不能删除非自己录入的数据。")
    db.query(WzcgsqMx).filter(WzcgsqMx.mainid == mid).delete(synchronize_session=False)
    db.delete(m)
    db.commit()
    return {"ok": True}
