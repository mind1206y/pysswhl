"""短信发送记录(照旧 SmsRecordController 复刻,只读)。

旧实现:EasyUI datagrid 分页 + 模糊搜索框,搜索匹配
lb/nr/tel/ren/zt/sender 六个字段,按 riqi 倒序;无增删改入口。
权限:旧 bb_quanx 80「短信发送」,新系统折算为 sms:view(超管自动全有)。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.models.sms import SmsRecord
from app.models.user import User

router = APIRouter()


@router.get("")
def list_sms_records(
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=200),
    mohu: str = Query("", description="模糊查询:类别/内容/手机/接收人/结果/发送人"),
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("sms:view")),
):
    """照旧 GetList/LoadSearchEntities:模糊匹配六字段,riqi 倒序分页。"""
    q = db.query(SmsRecord)
    keyword = (mohu or "").strip()
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(or_(
            SmsRecord.lb.like(like),
            SmsRecord.nr.like(like),
            SmsRecord.tel.like(like),
            SmsRecord.ren.like(like),
            SmsRecord.zt.like(like),
            SmsRecord.sender.like(like),
        ))
    total = q.count()
    rows = (
        q.order_by(SmsRecord.riqi.desc(), SmsRecord.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return {"total": total, "rows": [r.to_dict() for r in rows]}
