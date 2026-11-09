"""一次性补救脚本:修复旧库 gongchenggl_jindu.jinduzhuangtai 全为 0 的存量数据。

背景:旧系统前端新增进度时 jinduzhuangtai 硬编码传 0(已修复源码),
进度记录的状态值失真;删除进度回滚主表状态时会取该值,导致状态错误回滚。

补救策略:
1. 每个工程最新一条进度 → jinduzhuangtai = 主表 Status(精确,主表状态正是由它写入)
2. 更早的记录 → 按描述文本强关键词推断(试压→3/通水→4/敷设→2/移交→6/归档→7),推断不出保持 0
3. 执行前自动备份原表到 gongchenggl_jindu_bak_<日期>

用法(backend 目录下):
    python -m scripts.fix_old_jindu_status            # 预览改动,不写入
    python -m scripts.fix_old_jindu_status --apply    # 备份并写入旧库
"""

import argparse

import pyodbc

# 强关键词 → 状态(只在描述里出现明确字眼时才推断,避免误判)
KEYWORD_RULES = [
    ("归档", 7),
    ("移交", 6),
    ("通水", 4),    # 含"通水未验收"——已通水即 4
    ("试压", 3),
    ("施压", 3),    # "施压"为"试压"错别字,如"已施压合格,管道冲洗中"
    ("敷设", 2),
]

# 第二遍:裸"验收"→已验收(排除验槽/管槽验收/沟槽验收/基础沙验收等施工环节词)
EXCLUDE_IF_CONTAINS = ["槽", "沙", "砂", "抽查", "切管", "见证", "材料"]
BARE_ACCEPT_RULES = [
    ("验收", 5),
    ("装表", 4),
    ("切换用水", 4),
]

STATUS_NAMES = {0: "未开工", 1: "施工中", 2: "已敷设", 3: "已试压", 4: "已通水", 5: "已验收", 6: "已移交", 7: "已归档"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="备份原表并写入")
    args = parser.parse_args()

    c = pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=db_plan;UID=sa;PWD=swgps;",
        timeout=10,
    )
    cur = c.cursor()
    cur.execute("SELECT id, gcglid, jindu, jinduzhuangtai FROM gongchenggl_jindu ORDER BY id")
    rows = cur.fetchall()
    cur.execute("SELECT id, Status FROM gongchenggl")
    main_status = {r.id: r.Status for r in cur.fetchall()}

    # 每个工程最新一条(按 id 最大)
    latest_by_gc = {}
    for r in rows:
        latest_by_gc[r.gcglid] = r.id

    changes = []  # (id, gcglid, 原值, 新值, 依据)
    for r in rows:
        rid, gcglid, jindu, old_val = r.id, r.gcglid, (r.jindu or ""), r.jinduzhuangtai
        if old_val != 0:
            continue
        if rid == latest_by_gc.get(gcglid):
            new_val = main_status.get(gcglid)
            if new_val is not None and new_val != 0:
                changes.append((rid, gcglid, new_val, f"最新一条,回填主表Status({STATUS_NAMES.get(new_val)})"))
                continue
        text = jindu.replace(" ", "")
        for kw, val in KEYWORD_RULES:
            if kw in text:
                changes.append((rid, gcglid, val, f"关键词「{kw}」→ {STATUS_NAMES[val]}"))
                break
        else:
            for kw, val in BARE_ACCEPT_RULES:
                if kw in text and not any(x in text for x in EXCLUDE_IF_CONTAINS):
                    changes.append((rid, gcglid, val, f"裸关键词「{kw}」→ {STATUS_NAMES[val]}"))
                    break

    print(f"共 {len(rows)} 条,拟修改 {len(changes)} 条:")
    for rid, gcglid, new_val, why in changes:
        print(f"  id={rid} gcgl={gcglid} 0 → {new_val}({STATUS_NAMES[new_val]})  依据:{why}")
    remain = len(rows) - len(changes)
    print(f"保持 0 不动:{remain} 条(描述无法可靠推断,如验槽/沟槽验收等施工环节)")

    if not args.apply:
        print("\ndry-run,未写入。加 --apply 执行(会先备份原表)")
        c.close()
        return

    # 备份
    bak = "gongchenggl_jindu_bak_20261107"
    cur.execute(f"""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='{bak}' AND type='U')
        SELECT * INTO {bak} FROM gongchenggl_jindu
    """)
    cur.execute(f"SELECT COUNT(*) FROM {bak}")
    print(f"已备份原表到 {bak}({cur.fetchone()[0]} 条)")

    for rid, gcglid, new_val, _ in changes:
        cur.execute("UPDATE gongchenggl_jindu SET jinduzhuangtai = ? WHERE id = ?", new_val, rid)
    c.commit()
    print(f"已更新 {len(changes)} 条")
    c.close()


if __name__ == "__main__":
    main()
    print("完成")
