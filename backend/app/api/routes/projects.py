from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.api.deps import dept_name_map, dept_scope_ids
from app.db.session import get_db
from app.models.project import STATUS_MAP, Gongchenggl
from app.models.user import User

router = APIRouter()


class ProjectIn(BaseModel):
    """全部可选:更新时没传的字段视为不修改。"""

    bmid: Optional[int] = None
    pianqu: Optional[str] = None
    xiangmuname: Optional[str] = None
    xiangmudizhi: Optional[str] = None
    xiangmuyezhu: Optional[str] = None
    daijiandanwei: Optional[str] = None
    shejidanwei: Optional[str] = None
    jianlidanwei: Optional[str] = None
    shigongdanwei: Optional[str] = None
    lianxiren: Optional[str] = None
    dianhua: Optional[str] = None
    shenbaoriqi: Optional[datetime] = None
    isyijiao: Optional[bool] = None
    yijiaoriqi: Optional[datetime] = None
    isguidang: Optional[bool] = None
    guidangriqi: Optional[datetime] = None
    xmleibie: Optional[str] = None
    zijinleixing: Optional[str] = None
    Status: Optional[int] = None
    StatusRemark: Optional[str] = None
    Remark: Optional[str] = None


TEXT_FIELDS = [
    "pianqu", "xiangmuname", "xiangmudizhi", "xiangmuyezhu", "daijiandanwei",
    "shejidanwei", "jianlidanwei", "shigongdanwei", "lianxiren", "dianhua",
    "xmleibie", "zijinleixing", "StatusRemark",
]


@router.get("")
def list_projects(
    page: int = 1,
    size: int = 10,
    keyword: str = "",
    status: Optional[int] = None,
    xmleibie: str = "",
    bmid: Optional[int] = None,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:view")),
):
    query = db.query(Gongchenggl)
    if keyword.strip():
        kw = f"%{keyword.strip()}%"
        query = query.filter(or_(
            Gongchenggl.xiangmuname.like(kw),
            Gongchenggl.xiangmudizhi.like(kw),
            Gongchenggl.xiangmuyezhu.like(kw),
            Gongchenggl.lianxiren.like(kw),
        ))
    if status is not None:
        query = query.filter(Gongchenggl.Status == status)
    if xmleibie.strip():
        query = query.filter(Gongchenggl.xmleibie == xmleibie.strip())
    if bmid:
        query = query.filter(Gongchenggl.bmid == bmid)
    # 部门数据权限:只看本部门(含子部门)的工程(照旧 bmcj)
    scope_ids = dept_scope_ids(db, current)
    if scope_ids is not None:
        query = query.filter(Gongchenggl.bmid.in_(scope_ids))
    total = query.count()
    items = query.order_by(Gongchenggl.id.desc()).offset((page - 1) * size).limit(size).all()
    names = dept_name_map(db)
    out = []
    for p in items:
        d = p.to_dict()
        # 营业所(关联部门名,照旧 Get 的 bumen 列)
        d["bumen"] = names.get(p.bmid, "")
        out.append(d)
    return {"total": total, "items": out}


@router.get("/categories")
def list_categories(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("project:view")),
):
    """项目类别下拉选项(已有数据的去重值)。"""
    rows = db.query(Gongchenggl.xmleibie).filter(Gongchenggl.xmleibie != "").distinct().all()
    return [r[0] for r in rows]


@router.post("")
def create_project(
    data: ProjectIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:view")),
):
    if data.xiangmuname is not None and not data.xiangmuname.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    if data.Status is not None and data.Status not in STATUS_MAP:
        raise HTTPException(status_code=400, detail="状态值不合法")
    p = Gongchenggl(CreateUser=current.username)
    apply_fields(p, data)
    # 照旧系统:新增工程归属登录人部门;多部门用户可在本人部门内自选,越界/未选则取第一个
    if not current.is_superuser and current.departments:
        my_ids = [d.id for d in current.departments]
        p.bmid = data.bmid if data.bmid in my_ids else my_ids[0]
    db.add(p)
    db.commit()
    db.refresh(p)
    return p.to_dict()


@router.put("/{project_id}")
def update_project(
    project_id: int,
    data: ProjectIn,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("project:view")),
):
    p = db.get(Gongchenggl, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    # 非超管只能编辑本人部门(含子部门)的工程(照旧部门范围兜底)
    scope = dept_scope_ids(db, current)
    if scope is not None and (p.bmid is None or p.bmid not in scope):
        raise HTTPException(status_code=403, detail="只能操作本部门(含子部门)的工程")
    if data.xiangmuname is not None and not data.xiangmuname.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    if data.Status is not None and data.Status not in STATUS_MAP:
        raise HTTPException(status_code=400, detail="状态值不合法")
    apply_fields(p, data)
    # 非超管只能把工程归到本人部门(未传 bmid 则保持不变),防止挪出自己可见范围
    if not current.is_superuser and data.bmid is not None and current.departments:
        my_ids = [d.id for d in current.departments]
        if data.bmid not in my_ids:
            p.bmid = p.bmid if p.bmid in my_ids else my_ids[0]
    p.LastUpdateTime = datetime.now()
    p.updateUser = current.username
    db.commit()
    return p.to_dict()


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("project:manage")),
):
    p = db.get(Gongchenggl, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="工程不存在")
    db.delete(p)
    db.commit()
    return {"message": "已删除"}


def apply_fields(p: Gongchenggl, data: ProjectIn):
    """把请求里显式传入的字段写到实体上;没传的不动。"""
    for f in TEXT_FIELDS:
        v = getattr(data, f)
        if v is not None:
            setattr(p, f, v.strip())
    for f in ["bmid", "Status", "isyijiao", "isguidang"]:
        v = getattr(data, f)
        if v is not None:
            setattr(p, f, v)
    for f in ["shenbaoriqi", "yijiaoriqi", "guidangriqi"]:
        # 前端全量提交,None 表示清空日期
        setattr(p, f, getattr(data, f))
    v = getattr(data, "Remark")
    if v is not None:
        p.Remark = v.strip()
    # 状态联动:移交/归档置位时自动补日期,取消时清空
    if data.isyijiao is True and p.yijiaoriqi is None:
        p.yijiaoriqi = datetime.now()
    if data.isyijiao is False:
        p.yijiaoriqi = None
    if data.isguidang is True and p.guidangriqi is None:
        p.guidangriqi = datetime.now()
    if data.isguidang is False:
        p.guidangriqi = None
