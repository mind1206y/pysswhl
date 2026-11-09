"""材料结算单查看(照旧 JiesuanController 1:1 复刻,只读)。

路由挂 /api/jiesuan。权限 jiesuan:view(旧系统仅菜单控制访问)。
旧页面只有「材料名称或单号」搜索 + 分页列表,无增删改;控制器中的
SaveJiesuan/Edit 没有对应页面与入口,属残留死代码,不复刻。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import dept_scope_ids, require_permission
from app.db.session import get_db
from app.models.user import User
from app.services.jiesuan_common import view_rows

router = APIRouter()


@router.get("/details")
def list_details(
    page: int = 1,
    size: int = 20,
    keyword: str = "",
    db: Session = Depends(get_db),
    current: User = Depends(require_permission("jiesuan:view")),
):
    scope = dept_scope_ids(db, current)
    total, rows = view_rows(db, scope, keyword=keyword, page=page, size=size)
    return {"total": total, "rows": rows}
