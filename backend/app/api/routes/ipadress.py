"""IP 地址管理(照旧 ipadressController 1:1 复刻)。

- 列表:按网络名称/地点/用途/使用人模糊、网段多选、状态筛选,部门子树数据权限
- 添加网络:按网段自动生成 2~254 共 253 个 IP,状态「未使用」,同时记录创建人
- 领用 IP:写使用人/位置/用途,状态改「已使用」,申请人/申请时间取当前登录人
- 收回 IP:重置为「未使用」并清空使用信息;非超管只能收回自己领用的(照旧)
- 删除网络:整段删除 IP 并清掉创建人记录,需 ipadress:manage
- 导出:13 列 Excel,筛选条件与列表一致(照旧 Excel 动作)

权限:
- ipadress:view   模块入口 + 列表/领取/收回/添加网络/导出
- ipadress:manage 删除网络(对应旧系统 pdqx(user, "IP管理"))
"""

import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.ipadress import Ipadress, IpNetCreator
from app.models.user import Department, User
from app.services.ipadress_common import (
    APPLY_LOCATIONS, APPLY_USES, STATUS_FILTERS, STATUS_UNUSED, STATUS_USED,
    build_excel, build_rows, content_disposition, has_perm, ip_query,
    netname_options,
)

router = APIRouter()

NET_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")


class NetworkIn(BaseModel):
    netname: str
    net: str
    bmid: Optional[int] = None


class ClaimIn(BaseModel):
    syren: str
    didian: str = ""
    yongtu: str = ""


def _get_ip_or_404(db: Session, ip_id: int) -> Ipadress:
    row = db.get(Ipadress, ip_id)
    if row is None:
        raise HTTPException(status_code=404, detail="IP 记录不存在")
    return row


def _check_visible(db: Session, user: User, row: Ipadress):
    scope = dept_scope_ids(db, user)
    if scope is not None and row.bmid not in scope:
        raise HTTPException(status_code=403, detail="没有操作该 IP 的权限")


def _resolve_bmid(db: Session, user: User, requested: Optional[int]) -> Optional[int]:
    """新增网段归属部门:超管可任选;普通用户限本人部门,越界/未选兜底第一个。"""
    allowed = {d.id for d in user.departments}
    if user.is_superuser:
        if requested and db.get(Department, requested) is not None:
            return requested
        return min(allowed) if allowed else None
    if requested in allowed:
        return requested
    return min(allowed) if allowed else None


# ==================== 列表 / 字典 / 导出 ====================
@router.get("")
def list_ips(
    page: int = 1,
    size: int = 25,
    keyword: str = "",
    netname: str = "",
    ipzt: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("ipadress:view")),
):
    q = ip_query(db, current, keyword=keyword, netnames=netname, ipzt=ipzt)
    total = q.count()
    rows = (
        q.order_by(Ipadress.netname, Ipadress.numb)
        .offset((page - 1) * size).limit(size).all()
    )
    return {"total": total, "items": build_rows(db, rows)}


@router.get("/dicts")
def dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("ipadress:view")),
):
    scope = dept_scope_ids(db, current)
    dq = db.query(Department)
    if scope is not None:
        dq = dq.filter(Department.id.in_(scope))
    departments = [{"id": d.id, "name": d.name} for d in dq.order_by(Department.id).all()]

    default_bmid = min((d["id"] for d in departments), default=None)
    return {
        "netnames": netname_options(db),
        "departments": departments,
        "default_bmid": default_bmid,
        "locations": APPLY_LOCATIONS,
        "uses": APPLY_USES,
        "status_filters": STATUS_FILTERS,
        "perms": {
            "view": True,
            "manage": has_perm(current, "ipadress:manage"),
        },
    }


@router.get("/export")
def export_excel(
    keyword: str = "",
    netname: str = "",
    ipzt: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("ipadress:view")),
):
    q = ip_query(db, current, keyword=keyword, netnames=netname, ipzt=ipzt)
    rows = q.order_by(Ipadress.netname, Ipadress.numb).all()
    buf = build_excel(build_rows(db, rows))
    filename = "IP地址信息表.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename)},
    )


# ==================== 网段 ====================
@router.post("/networks")
def create_network(
    data: NetworkIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("ipadress:view")),
):
    netname = (data.netname or "").strip()
    net = (data.net or "").strip()
    if not netname:
        raise HTTPException(status_code=400, detail="网络名称不能为空")
    if len(netname) > 50:
        raise HTTPException(status_code=400, detail="网络名称不能超过 50 个字符")
    if not NET_PATTERN.match(net):
        raise HTTPException(status_code=400, detail="网段格式无效")
    if db.query(Ipadress.id).filter(Ipadress.netname == netname).first():
        raise HTTPException(status_code=400, detail="网络名称重复")

    bmid = _resolve_bmid(db, current, data.bmid)
    now = datetime.now()
    db.add_all([
        Ipadress(netname=netname, net=net, numb=i, zt=STATUS_UNUSED,
                 netdate=now, bmid=bmid)
        for i in range(2, 255)
    ])
    if db.get(IpNetCreator, netname) is None:
        db.add(IpNetCreator(netname=netname, creator=current.username, createtime=now))
    db.commit()
    return {"ok": True, "created": 253, "netname": netname, "bmid": bmid}


@router.delete("/networks")
def delete_network(
    netname: str,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("ipadress:manage")),
):
    name = (netname or "").strip()
    rows = db.query(Ipadress).filter(Ipadress.netname == name).all()
    if not rows:
        raise HTTPException(status_code=404, detail="网络不存在")
    scope = dept_scope_ids(db, current)
    if scope is not None and any(r.bmid not in scope for r in rows):
        raise HTTPException(status_code=403, detail="该网络包含其他部门的 IP,无权删除")
    for row in rows:
        db.delete(row)
    creator = db.get(IpNetCreator, name)
    if creator is not None:
        db.delete(creator)
    db.commit()
    return {"ok": True, "deleted": len(rows)}


# ==================== 领用 / 收回 ====================
@router.post("/{ip_id}/claim")
def claim_ip(
    ip_id: int,
    data: ClaimIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("ipadress:view")),
):
    row = _get_ip_or_404(db, ip_id)
    _check_visible(db, current, row)
    syren = (data.syren or "").strip()
    if not syren:
        raise HTTPException(status_code=400, detail="使用人不能为空")
    row.zt = STATUS_USED
    row.syren = syren
    row.didian = (data.didian or "").strip() or None
    row.yongtu = (data.yongtu or "").strip() or None
    row.sqdate = datetime.now()
    row.sqren = current.username
    db.commit()
    db.refresh(row)
    return {"ok": True, "item": build_rows(db, [row])[0]}


@router.post("/{ip_id}/recycle")
def recycle_ip(
    ip_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("ipadress:view")),
):
    row = _get_ip_or_404(db, ip_id)
    _check_visible(db, current, row)
    if not current.is_superuser and (row.sqren or "") != (current.username or ""):
        raise HTTPException(status_code=403, detail="无法回收非自己领用的 IP 地址")
    row.zt = STATUS_UNUSED
    row.syren = None
    row.didian = None
    row.yongtu = None
    row.sqdate = datetime.now()
    db.commit()
    db.refresh(row)
    return {"ok": True, "item": build_rows(db, [row])[0]}
