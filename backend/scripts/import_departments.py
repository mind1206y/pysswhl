"""旧系统部门表迁移:db_plan.dbo.bb_bumen → sswhl_new.departments。

背景(见 docs/数据迁移约定.md):
新库 departments 原本只手工建了 9 个部门,id 与旧 bb_bumen.id 完全不对应且数字撞车
(旧 7=海沧营业所,新 7=售水事业部)。旧库共 38 个部门,车辆/工程/水费等模块迁移时
按部门名匹配,有 15 个旧部门(特水、原水、各水厂、停用部门等)在新库无同名,
导致这些记录的 bmid 被置 NULL。

本脚本把旧部门表整体补齐到新库,原则:
1. **不动现有部门**:同名部门(9 个)保留原 id / name / parent_id,用户关联与已迁移
   数据里的 bmid 全部继续有效;remark 为空时补来源标记,不覆盖人工备注。
2. 缺失部门按旧 id 顺序 INSERT,新 id 由自增分配;再统一按旧 _parentId 还原父子树
   (两阶段,避免父部门还没插入)。
3. 旧 id=23「超级」是旧系统的虚拟根节点(历史 bb_user 里有 bmid=23,必须保留映射),
   建为**孤立的顶级部门**,不还原它到子节点的父子关系——这样「集团」仍是顶级,
   与现有树/数据权限语义完全一致;其旧子节点(安兜/舫山/停用部门)也为顶级。
4. 旧 bmid=10 对应的部门在 bb_bumen 中已被删除(仅 tb_op/tb_yyfaqi 用到,均未迁移),
   无同名可映射,后续迁移按约定置 NULL 并告警。
5. 产出 scripts/migration_reports/department_map.json:旧 bmid → 新 departments.id
   的持久化映射 + 旧表全字段备份,供后续所有迁移脚本复用,不再依赖名称现算。
6. 幂等:按 name 唯一键判重,重复执行 0 新增;--dry-run 只预览。
   执行前会把 departments 全表备份到 migration_reports/departments_backup_*.json。

补齐后请接着跑 repair_bmid_from_old.py 回填历史表里被置空的 bmid。

用法(backend 目录下):
    python -m scripts.import_departments --dry-run
    python -m scripts.import_departments
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings

REPORT_DIR = Path(__file__).parent / "migration_reports"
MAP_FILE = REPORT_DIR / "department_map.json"
VIRTUAL_ROOT_OLD_ID = 23  # bb_bumen 中「超级」:旧系统虚拟根节点

OLD_SQL = (
    "SELECT [id], [bm], [cj], [px], [zg], [sh], [dnnum], [xuhaotou], "
    "[htdaihao], [_parentId] FROM [bb_bumen] ORDER BY [id]"
)
OLD_FIELDS = ["id", "bm", "cj", "px", "zg", "sh", "dnnum", "xuhaotou", "htdaihao", "_parentId"]


def old_conn():
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('OLD_DB_HOST', '127.0.0.1')},{os.environ.get('OLD_DB_PORT', '1433')};"
        f"DATABASE={os.environ.get('OLD_DB_NAME', 'db_plan')};"
        f"UID={os.environ.get('OLD_DB_USER', 'sa')};PWD={os.environ.get('OLD_DB_PASSWORD', 'swgps')};",
        timeout=10,
    )


def new_conn():
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, charset="utf8mb4",
    )


def fetch_old(ocur):
    ocur.execute(OLD_SQL)
    out = []
    for r in ocur.fetchall():
        rec = dict(zip(OLD_FIELDS, r))
        rec["bm"] = (rec["bm"] or "").strip()
        out.append(rec)
    return out


def remark_of(d):
    bits = [f"旧id={d['id']}"]
    if d["cj"]:
        bits.append(f"层级码 {d['cj']}")
    if d["px"] is not None:
        bits.append(f"排序 {d['px']}")
    return "旧系统迁入 · " + " · ".join(bits)


def backup_departments(cur, stamp):
    cur.execute("SELECT id, name, parent_id, remark, created_at FROM departments ORDER BY id")
    rows = [
        {
            "id": r[0], "name": r[1], "parent_id": r[2], "remark": r[3],
            "created_at": r[4].strftime("%Y-%m-%d %H:%M:%S") if r[4] else None,
        }
        for r in cur.fetchall()
    ]
    path = REPORT_DIR / f"departments_backup_{stamp}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已备份现有 {len(rows)} 个部门 → {path.name}")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只预览,不写入")
    args = parser.parse_args()

    oc = old_conn()
    try:
        old = fetch_old(oc.cursor())
    finally:
        oc.close()
    print(f"旧库 bb_bumen: {len(old)} 个部门")

    nc = new_conn()
    try:
        cur = nc.cursor()
        cur.execute("SELECT id, name, parent_id, remark FROM departments ORDER BY id")
        existing = {r[1]: {"id": r[0], "parent_id": r[2], "remark": r[3] or ""} for r in cur.fetchall()}
        print(f"新库 departments: {len(existing)} 个同名部门(保留不动)")

        cur.execute("SELECT AUTO_INCREMENT FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='departments'")
        next_id = cur.fetchone()[0] or 1

        # 阶段 1:确定每个旧部门对应的新 id(已有沿用,缺失新增)
        id_by_old, plan = {}, []
        for d in old:
            name = d["bm"]
            if not name:
                print(f"⚠ 旧 id={d['id']} 部门名为空,跳过")
                continue
            if name in existing:
                info = existing[name]
                id_by_old[d["id"]] = info["id"]
                plan.append({**d, "new_id": info["id"], "source": "existing",
                             "current_parent_id": info["parent_id"]})
            else:
                id_by_old[d["id"]] = next_id
                plan.append({**d, "new_id": next_id, "source": "imported",
                             "current_parent_id": None})
                next_id += 1

        missing = [p for p in plan if p["source"] == "imported"]
        start_hint = f"(新 id {min(p['new_id'] for p in missing)} 起)" if missing else "(部门表已完整)"
        print(f"将补建 {len(missing)} 个部门{start_hint}:")
        for p in missing:
            print(f"  + 旧 {p['id']:>2} {p['bm']:<16} → 新 {p['new_id']:>3}"
                  f"  (旧父 {p['_parentId']}, 层级码 {p['cj'] or '-'})")

        # 阶段 2:按旧 _parentId 还原父子关系(仅新增部门;同名老部门一律不动)
        parent_by_new, tree_diff = {}, []
        for p in plan:
            pid = p["_parentId"]
            if pid is None or pid == VIRTUAL_ROOT_OLD_ID:
                continue  # 虚拟根「超级」不还原父子,其旧子节点保持顶级
            if pid not in id_by_old:
                print(f"⚠ 旧 {p['id']} 的父部门 {pid} 不在 bb_bumen,parent_id 置空")
                continue
            target = id_by_old[pid]
            if p["source"] == "imported":
                parent_by_new[p["new_id"]] = target
            elif p["current_parent_id"] != target:
                tree_diff.append((p["bm"], p["current_parent_id"], target))
        if tree_diff:
            print("ℹ 以下同名部门当前层级与旧树不同,按约定保留现状(不覆盖):")
            for name, curp, oldp in tree_diff:
                print(f"    {name}: 当前父 {curp} / 旧树父 {oldp}")

        if args.dry_run:
            print(f"dry-run:将新增 {len(missing)} 个部门、设置 {len(parent_by_new)} 个 parent_id,未写入")
            return

        REPORT_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_departments(cur, stamp)

        # 插入时以数据库实际 lastrowid 为准,同步修正映射(正常等于预估值)
        for p in missing:
            cur.execute(
                "INSERT INTO departments (name, parent_id, remark, created_at) "
                "VALUES (%s, NULL, %s, NOW())",
                (p["bm"], remark_of(p)),
            )
            real_id = cur.lastrowid
            if real_id != p["new_id"]:
                print(f"⚠ {p['bm']} 实际分配 id={real_id}(预估 {p['new_id']}),已按实际值修正")
                id_by_old[p["id"]] = real_id
                p["new_id"] = real_id

        # 按最终 id 重建父子映射,杜绝预估/实际不一致
        final_parent = {}
        for p in plan:
            pid = p["_parentId"]
            if p["source"] != "imported" or pid is None or pid == VIRTUAL_ROOT_OLD_ID:
                continue
            if pid in id_by_old:
                final_parent[p["new_id"]] = id_by_old[pid]
        for dept_id, parent_id in final_parent.items():
            cur.execute("UPDATE departments SET parent_id = %s WHERE id = %s", (parent_id, dept_id))
        for p in plan:
            if p["source"] == "imported" and p["new_id"] not in final_parent:
                cur.execute("UPDATE departments SET parent_id = NULL WHERE id = %s", (p["new_id"],))
        # 同名老部门 remark 为空时补来源标记(不覆盖人工备注)
        for p in plan:
            if p["source"] == "existing" and not existing[p["bm"]]["remark"]:
                cur.execute(
                    "UPDATE departments SET remark = %s WHERE id = %s AND (remark IS NULL OR remark = '')",
                    (remark_of(p), p["new_id"]),
                )

        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "db_plan.dbo.bb_bumen",
            "target": f"{settings.DB_NAME}.departments",
            "note": "旧id=23「超级」为虚拟根节点,建为孤立顶级部门;其旧子节点保持顶级,"
                    "已有 9 个同名部门的 id/层级不变。旧 bmid=10 的部门在旧库已删除,无映射。",
            "depts": {
                str(p["id"]): {
                    "new_id": p["new_id"], "name": p["bm"], "cj": p["cj"], "px": p["px"],
                    "zg": p["zg"], "sh": p["sh"], "dnnum": p["dnnum"],
                    "xuhaotou": p["xuhaotou"], "htdaihao": p["htdaihao"],
                    "old_parent_id": p["_parentId"],
                    "new_parent_id": final_parent.get(p["new_id"])
                    if p["source"] == "imported" else p["current_parent_id"],
                    "source": p["source"],
                }
                for p in plan
            },
            "bmid_map": {str(p["id"]): p["new_id"] for p in plan},
        }
        nc.commit()
        MAP_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完成:新增 {len(missing)} 个部门,设置 {len(final_parent)} 个 parent_id")
        print(f"旧 bmid → 新 id 映射({len(report['bmid_map'])} 项)已写入 {MAP_FILE.name}")
    finally:
        nc.close()


if __name__ == "__main__":
    main()
