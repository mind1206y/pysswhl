"""传导完好率分组公共字典(4 页共用下拉/报表日期/锁定状态)。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_any_permission
from app.db.session import get_db
from app.models.user import User
from app.services.cd_common import dicts_data

router = APIRouter()


@router.get("/dicts")
def cd_dicts(
    db: Session = Depends(get_db),
    current: User = Depends(require_any_permission(
        "cdwhl:view", "cdgz:view", "cddaxiu:view", "cdbd:view"
    )),
):
    return dicts_data(db, current)
