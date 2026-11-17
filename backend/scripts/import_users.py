"""旧系统用户表迁移:db_plan.dbo.bb_user(+ bb_qxfenpei 菜单权限) → sswhl_new.users。

目标:切换新系统后,全员用**原用户名 + 原密码**直接登录,菜单权限与旧系统一致。

## 迁移内容

| 旧 | 新 | 说明 |
|---|---|---|
| bb_user.username | users.username | 中文姓名登录,与旧系统一字不差 |
| bb_user.unames | users.real_name | 为空时回退 username |
| bb_user.tel | users.phone | 顺带支持手机号登录(见 app/api/routes/auth.py) |
| bb_user.zw | users.zw | 职务;「停用」「退休」不是职务,落 is_active=0 |
| bb_user.bmid | user_department | 走 migration_reports/department_map.json 的 bmid_map |
| bb_user.password | users.password_hash + password_version | 见下 |
| bb_user.dllasttime | users.last_login_at | |
| bb_qxfenpei + bb_quanx | user_role + 旧系统权限角色 | 见下 |
| bb_user.otherqx | 额外权限(HR/工单管理/IP管理…) | 见 TAG_TO_PERMS |
| bb_user.clsp=1 | repair:audit | 旧系统车辆维修审批人 |

## 密码:原样保留,登录后透明升级

- `pbkdf2$迭代$盐$哈希` → password_version=2(旧 PasswordHasher,.NET Rfc2898DeriveBytes)
- 29~32 位十六进制 → password_version=3(旧无盐 MD5,UTF-16LE + 丢前导零,故长度不固定)
- 空密码 → 旧系统允许空密码登录(44 个账号如此),新系统不接受;
  这类账号统一发 settings.INITIAL_PASSWORD 并置 must_change_password=1,
  首次登录必须改密。名单写进报告,由管理员线下告知。
- 三种旧格式登录成功后都会自动重算为 Argon2id+pepper(v1),无需人工干预。

## 权限:按「旧菜单项」逐条折算成新权限码

新系统是「角色 → 权限码」模型,旧系统是「用户 → 菜单项」。为保持两边菜单一致,
本脚本为每个用到的权限码建一个 `legacy_*` 角色(名称=权限码的中文名),再把用户加入对应角色。
这样管理员在「角色权限」页看到的是「车辆查看/工单录入查看…」这种模块级角色,可读、可再重组。

只映射**已复刻**的模块;旧系统里未复刻的菜单(发票、小散、网盘、系统日记等)
不产生权限,统计进报告的 unmapped_menus,避免误以为漏迁。
传导完好率分组(旧菜单 68~71)已于 2026-11-15 复刻,现按 QX_TO_PERM 正常折算。

## id 规则（2026-11-15 16:17 起：1:1 恒等）

`users.id` 与旧 `bb_user.id` **完全一致**（199 个账号，3~382 跳号）：
- 早期迁移因新库已有 id=1 admin / id=7 林春，产生 3→7、7→383、207→1 三个特例；
  但 `sms_contact.id`、`gx_user_gxgz.userid`、`jh_ssdb(pz).zhuanguan`、`jh_yyfq.zgy`
  等表直接搬旧 id 未做映射，而 `plan_common.resolve_user_id()` 写入的是当前 users.id，
  两套口径不一致，历史行与新行按 userid 关联时对不上。
- 已用 `scripts/rebuild_user_ids.py` 重编号并修正全部引用列（含姓名快照语义校验）。
- 现在本脚本按 username 匹配现有账号、只做 UPDATE，不会再分配新 id；
  ⛔ 重跑前先确认 users.id 仍是旧 id 集合，别把恒等口径改回去。

⚠ `user_map.json` 会被本脚本重写为**全量映射**，import_overtime 等脚本只复用不重算。

## 用法(backend 目录下)

    python -m scripts.import_users --dry-run   # 只统计、不写库
    python -m scripts.import_users             # 正式迁移(幂等,可重跑)
"""

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pyodbc
import pymysql

from app.core.config import settings
from app.core.security import (
    CURRENT_PASSWORD_VERSION,
    LEGACY_MD5_VERSION,
    LEGACY_PBKDF2_VERSION,
    hash_password,
)

REPORT_DIR = Path(__file__).resolve().parent / "migration_reports"
DEPT_MAP_FILE = REPORT_DIR / "department_map.json"
USER_MAP_FILE = REPORT_DIR / "user_map.json"

# 旧 bb_user.zw 里表示「人已不在岗」的取值,不是职务;落库时清空 zw 并停用账号
INACTIVE_ZW = {"停用", "退休"}

# 旧 bb_quanx.id → 新系统权限码(仅已复刻模块;未列出的旧菜单＝未复刻,见报告 unmapped_menus)
QX_TO_PERM = {
    1: "system:role:manage",      # 功能模块(权限分配)
    2: "system:user:manage",      # 用户管理
    3: "system:dept:manage",      # 部门设置
    22: "plan:view",              # 计划查询(更新改造,正式计划页内)
    26: "vehicle:view",           # 车辆管理
    28: "gdzc:view",              # 固定资产
    30: "plan:view",              # 正式计划
    31: "plan:view",              # 我关注的计划
    41: "jcxt:view",              # 稽查系统
    43: "jhssdb:view",            # 售水计划申报(实施单表)
    44: "jhsshz:view",            # 计划汇总(实施汇总)
    45: "jhyyfaqi:view",          # 营业所计划申报
    47: "contract:view",          # 合同登记
    48: "contract:collect",       # 合同归集
    50: "simcard:view",           # 手机卡号(SIM 卡)
    51: "vehicle:view",           # 出险车辆
    55: "vehicle:view",           # 日常用车
    56: "simfee:view",            # 通信费
    57: "vehicle:view",           # 添加出险
    58: "repair:view",            # 修车登记
    59: "repair:view",            # 维修明细
    61: "vehicle:view",           # 假日用车审批
    62: "vehicle:view",           # 停放审批
    65: "oiltj:view",             # 油量统计
    66: "baofeizc:view",          # 清理报告
    68: "cdwhl:view",             # 传导完好率
    69: "cdgz:view",              # 传导故障
    70: "cddaxiu:view",           # 传导大修
    71: "cdbd:view",              # 传导变动表
    72: "celou:view",             # 测漏成果
    74: "oilcard:view",           # 油卡管理
    75: "plusoil:view",           # 加油明细
    79: "spjicha:view",           # 审批稽查
    80: "sms:view",               # 短信发送(bb_quanx 80, /SmsRecord 短信记录页)
    81: "jcdan:view",             # 稽查单
    82: "jcjl:view",              # 稽查奖励
    85: "vehicle:view",           # 车辆费用
    86: "baoxian:view",           # 车辆保险
    87: "chelfytj:view",          # 车辆费用统计
    92: "phone:view",             # 手机管理
    93: "ipadress:view",          # IP管理
    95: "gongdan:view",           # 工单录入
    96: "vehicle:view",           # 车辆违章
    97: "material:view",          # 工单材料库
    98: "workorder:view",         # 工单领料
    99: "waterfee:view",          # 特殊群体信息
    101: "lingliao:view",         # 领料申请
    102: "jiesuan:view",          # 结算单查看
    103: "jiesuandan:view",       # 领料结算
    104: "jiaban:view",           # 加班管理(维抢修加班)
    105: "project:view",          # 工程管理
    107: "leak:view",             # 测漏笔记
    110: "roadrepair:view",       # 路面修复管理
    111: "overtime:view",         # 加班申请
    117: "wzcgsq:view",           # 物资采购申请
}

# 旧 bb_user.otherqx 标签 → 额外权限码(旧系统在代码里 MyUtil.pdqx 判定,对应新系统的功能码)
TAG_TO_PERMS = {
    "HR": {"overtime:hr", "overtime:verify"},          # 加班:汇总 + 核销
    "加班管理": {"overtime:verify"},                    # 加班:核销
    "工单管理": {"material:manage"},                    # 工单材料库管理
    "领料单审核": {"lingliao:audit"},                   # 领料单审核
    "领料单结算": {"jiesuandan:manage"},                # 领料结算管理
    "手机管理": {"phone:huishou"},                      # 手机批量改「已回收」
    "IP管理": {"ipadress:manage"},                      # IP 删除
    "特殊群体管理": {"waterfee:manage"},                # 特殊群体维护
    "sim卡管理": {"simcard:manage"},                    # SIM 卡维护
    "测漏热力图": {"celou:manage"},                     # 测漏成果导入/维护
    "计划汇总": {"jhyyfaqi:summary"},                   # 营业所发起跨部门查看
    "传导管理": {"cdwhl:manage"},                       # 传导报表锁定/生成(旧 otherqx)
    # 「项目跟踪管理」对应模块未复刻,不产生权限
}

# otherqx 含 admin 的用户在旧系统是「模块管理员」,折算为新系统各模块的管理/特批码。
# 注意:不含 system:user:manage 等系统管理码——那些仍由旧菜单「用户管理」单独授予。
ADMIN_PERMS = {
    "vehicle:manage", "repair:manage", "repair:audit", "phone:manage", "phone:huishou",
    "celou:manage", "leak:manage", "contract:manage", "simcard:manage", "ipadress:manage",
    "waterfee:manage", "material:manage", "workorder:manage", "lingliao:audit",
    "jiesuandan:manage", "gongdan:manage", "project:manage", "plan:manage",
    "jhssdb:manage", "jhsshz:manage", "jhsshz:admin", "jhyyfaqi:manage",
    "jhyyfaqi:summary", "overtime:apply", "overtime:verify", "overtime:hr",
    "overtime:manage", "oilcard:manage", "gdzc:view", "baofeizc:view", "wzcgsq:view",
    "cdwhl:view", "cdgz:view", "cddaxiu:view", "cdbd:view", "cdwhl:manage",
}

ROLE_CODE_PREFIX = "legacy_"

# 旧菜单里的「修改密码/退出/换背景」属系统自带功能,新系统人人可用,不算未复刻模块
CHROME_QX = {23, 24, 25, 73}


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
        autocommit=False,
    )


def split_tags(otherqx):
    """otherqx 里逗号有全角半角两种,统一拆开去空白"""
    return [t.strip() for t in (otherqx or "").replace("，", ",").split(",") if t.strip()]


def fetch_old(cur):
    cur.execute(
        "SELECT [id], [username], [password], [bmid], [zw], [unames], [tel], "
        "[otherqx], [clsp], [dllasttime] FROM [bb_user] ORDER BY [id]"
    )
    users = []
    for r in cur.fetchall():
        users.append({
            "id": int(r[0]),
            "username": (r[1] or "").strip(),
            "password": (r[2] or "").strip(),
            "bmid": int(r[3]) if r[3] is not None else None,
            "zw": (r[4] or "").strip(),
            "unames": (r[5] or "").strip(),
            "tel": (r[6] or "").strip(),
            "otherqx": r[7] or "",
            "clsp": int(r[8]) if r[8] is not None else 0,
            "dllasttime": r[9],
        })
    return users


def fetch_old_menus(cur):
    """旧菜单项(bb_quanx)id → (名称, 分类),用于统计未复刻菜单与角色备注"""
    cur.execute("SELECT [id], [name], [bz] FROM [bb_quanx]")
    return {int(r[0]): ((r[1] or "").strip(), (r[2] or "").strip()) for r in cur.fetchall()}


def fetch_old_grants(cur):
    """旧权限分配:userid → set(qxid)"""
    cur.execute("SELECT [userid], [qxid] FROM [bb_qxfenpei]")
    out = defaultdict(set)
    for uid, qxid in cur.fetchall():
        out[int(uid)].add(int(qxid))
    return out


def load_dept_map():
    if not DEPT_MAP_FILE.exists():
        print(f"⚠ 未找到 {DEPT_MAP_FILE.name},用户部门将全部留空;请先跑 import_departments.py")
        return {}
    data = json.loads(DEPT_MAP_FILE.read_text(encoding="utf-8"))
    return {int(k): int(v) for k, v in data.get("bmid_map", {}).items()}


def load_user_map():
    if not USER_MAP_FILE.exists():
        return {}
    data = json.loads(USER_MAP_FILE.read_text(encoding="utf-8"))
    out = {}
    for k, v in (data.get("user_map") or {}).items():
        try:
            out[int(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def pwd_plan(raw):
    """判定旧密码形态 → (存库哈希, password_version, 是否需要强制改密)"""
    if not raw:
        # 旧系统空密码＝直接放行,新系统必须给个初始密码
        return hash_password(settings.INITIAL_PASSWORD), CURRENT_PASSWORD_VERSION, True
    if raw.startswith("pbkdf2$"):
        return raw, LEGACY_PBKDF2_VERSION, False
    return raw, LEGACY_MD5_VERSION, False


def perms_of(user, grants, menu_names, unmapped_counter):
    """按旧菜单 + otherqx + clsp 折算新权限码集合"""
    perms = set()
    for qxid in grants.get(user["id"], ()):
        code = QX_TO_PERM.get(qxid)
        if code:
            perms.add(code)
        elif qxid in menu_names and qxid not in CHROME_QX:
            unmapped_counter[menu_names[qxid][0]] += 1
    tags = split_tags(user["otherqx"])
    for tag in tags:
        perms |= TAG_TO_PERMS.get(tag, set())
        if tag == "admin":
            perms |= ADMIN_PERMS
    if user["clsp"] == 1:
        perms.add("repair:audit")   # 旧系统车辆维修审批人
    return perms


def backup_new(cur, stamp):
    """动 users 前把用户相关的三张表整表备份成 JSON,便于回滚"""
    dump = {}
    for table, sql in (
        ("users", "SELECT * FROM users"),
        ("user_role", "SELECT * FROM user_role"),
        ("user_department", "SELECT * FROM user_department"),
    ):
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            rec = {}
            for col, val in zip(cols, r):
                if isinstance(val, datetime):
                    val = val.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(val, bytes):
                    val = val.decode("utf-8", "replace")
                rec[col] = val
            rows.append(rec)
        dump[table] = rows
    path = REPORT_DIR / f"users_backup_{stamp}.json"
    path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已备份现有用户数据({', '.join(f'{k} {len(v)} 行' for k, v in dump.items())}) → {path.name}")


def ensure_legacy_roles(cur, codes, perm_names, perm_ids):
    """为每个权限码准备一个 legacy_* 角色,并把该权限挂到角色上,返回 code → role_id

    ⚠ 角色只是容器:不写 role_permission 的话,用户即使挂在角色上也拿不到任何权限码。
    """
    role_ids = {}
    used_names = set()
    cur.execute("SELECT name FROM roles")
    for (name,) in cur.fetchall():
        used_names.add(name)
    for code in sorted(codes):
        role_code = ROLE_CODE_PREFIX + code.replace(":", "_")
        cur.execute("SELECT id FROM roles WHERE code = %s", (role_code,))
        row = cur.fetchone()
        if row:
            role_ids[code] = row[0]
        else:
            name = perm_names.get(code) or code
            if name in used_names:
                name = f"{name}({code})"
            cur.execute(
                "INSERT INTO roles (name, code, remark, created_at) VALUES (%s, %s, %s, NOW())",
                (name, role_code, f"旧系统菜单权限迁移生成 · 对应权限码 {code}"),
            )
            role_ids[code] = cur.lastrowid
            used_names.add(name)
        cur.execute(
            "INSERT IGNORE INTO role_permission (role_id, permission_id) VALUES (%s, %s)",
            (role_ids[code], perm_ids[code]),
        )
    return role_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计,不写库")
    args = parser.parse_args()

    oc = old_conn()
    try:
        ocur = oc.cursor()
        old_users = fetch_old(ocur)
        menu_names = fetch_old_menus(ocur)
        grants = fetch_old_grants(ocur)
    finally:
        oc.close()
    print(f"旧库 bb_user: {len(old_users)} 个账号,bb_qxfenpei 分配 {sum(len(v) for v in grants.values())} 条")

    bmid_map = load_dept_map()
    old_map = load_user_map()
    unmapped_counter = Counter()

    nc = new_conn()
    try:
        cur = nc.cursor()
        cur.execute(
            "SELECT id, username, is_superuser, phone, zw, real_name, password_version, "
            "must_change_password FROM users"
        )
        new_users = {r[0]: {"username": r[1], "is_superuser": bool(r[2]),
                            "phone": r[3] or "", "zw": r[4] or "", "real_name": r[5] or "",
                            "password_version": r[6], "must_change_password": bool(r[7])}
                     for r in cur.fetchall()}
        by_username = {v["username"]: k for k, v in new_users.items()}
        cur.execute("SELECT code, name FROM permissions")
        perm_names = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT code, id FROM permissions")
        perm_ids = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT id, name FROM departments")
        dept_names = {r[0]: r[1] for r in cur.fetchall()}

        # ===== 阶段 1:算出每个旧账号的目标 id 与要写的字段(不落库,便于 dry-run 预览) =====
        # id 分配两轮:先让所有不冲突的账号沿用旧 id,冲突的(旧 7 已被林春占用)再统一排到最大 id 之后,
        # 否则逐个顺延会把后面所有人的 id 整体推高一位,user_map 与已迁数据全部错位。
        pending = []
        for u in old_users:
            if not u["username"]:
                print(f"⚠ 旧 id={u['id']} 用户名为空,跳过")
                continue
            target_id = old_map.get(u["id"])
            if target_id not in new_users:
                target_id = by_username.get(u["username"])
            pending.append((u, target_id))

        taken_ids = set(new_users.keys())
        assigned = {}
        for u, target_id in pending:
            if target_id is None and u["id"] not in taken_ids:
                assigned[u["id"]] = u["id"]
                taken_ids.add(u["id"])
        next_free = max(taken_ids | {0}) + 1
        for u, target_id in pending:
            if target_id is None and u["id"] not in assigned:
                assigned[u["id"]] = next_free
                taken_ids.add(next_free)
                next_free += 1

        plan = []
        for u, target_id in pending:
            if target_id is None:
                target_id = assigned[u["id"]]
            source = "update" if target_id in new_users else "insert"
            perms = perms_of(u, grants, menu_names, unmapped_counter)
            dept_id = bmid_map.get(u["bmid"]) if u["bmid"] is not None else None
            pwd_hash, pwd_ver, force_change = pwd_plan(u["password"])
            existing = new_users.get(target_id) or {}
            # 已经是 v1(登录时透明升级过的账号)就不要再被旧哈希覆盖,否则重跑会把升级成果打回去
            keep_password = (existing.get("password_version") == CURRENT_PASSWORD_VERSION
                             and not existing.get("must_change_password"))
            inactive = u["zw"] in INACTIVE_ZW
            plan.append({
                "old_id": u["id"], "new_id": target_id, "source": source,
                "username": u["username"],
                "real_name": u["unames"] or u["username"],
                "phone": u["tel"],
                "zw": "" if inactive else u["zw"][:50],
                "is_active": not inactive,
                "password_hash": pwd_hash, "password_version": pwd_ver,
                "must_change_password": force_change,
                "keep_password": keep_password,
                "last_login_at": u["dllasttime"],
                "dept_id": dept_id, "dept_old_bmid": u["bmid"],
                "perms": perms, "otherqx": u["otherqx"], "clsp": u["clsp"],
                "is_superuser": new_users.get(target_id, {}).get("is_superuser", False),
            })

        inserts = [p for p in plan if p["source"] == "insert"]
        updates = [p for p in plan if p["source"] == "update"]
        no_pwd = [p for p in plan if p["must_change_password"]]
        no_dept = [p for p in plan if p["dept_id"] is None]
        inactive_users = [p for p in plan if not p["is_active"]]
        all_codes = {c for p in plan for c in p["perms"]}
        unknown_codes = sorted(c for c in all_codes if c not in perm_names)

        update_desc = ", ".join("{}→{}".format(p["username"], p["new_id"]) for p in updates)
        print(f"待新增 {len(inserts)} 个账号,更新 {len(updates)} 个: {update_desc}")
        print(f"权限:用到 {len(all_codes)} 个权限码 → 建/复用 {len(all_codes)} 个 legacy_* 角色")
        print(f"密码:保留旧 PBKDF2 {sum(1 for p in plan if p['password_version'] == LEGACY_PBKDF2_VERSION)} 个,"
              f"保留旧 MD5 {sum(1 for p in plan if p['password_version'] == LEGACY_MD5_VERSION)} 个,"
              f"原空密码发初始密码 {len(no_pwd)} 个(首次登录强制改密)")
        kept = sum(1 for p in plan if p.get("keep_password"))
        if kept:
            print(f"     其中 {kept} 个账号已是 v1(登录过并升级),保持现有密码不动")
        if inactive_users:
            print(f"停用 {len(inactive_users)} 个(旧 zw=停用/退休):"
                  f" {', '.join(p['username'] for p in inactive_users)}")
        if no_dept:
            print(f"⚠ {len(no_dept)} 个账号的 bmid 无部门映射,部门留空:"
                  f" {', '.join(str(p['dept_old_bmid']) for p in no_dept)}")
        if unknown_codes:
            print(f"⚠ 以下权限码在 permissions 表里不存在(请先跑 scripts.init_db):{unknown_codes}")
        if unmapped_counter:
            print("ℹ 旧系统未复刻菜单(不产生权限):")
            for name, n in unmapped_counter.most_common():
                print(f"    {name}: {n} 人次")

        if args.dry_run:
            print("dry-run:未写入任何数据")
            return

        # ===== 阶段 2:落库 =====
        REPORT_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_new(cur, stamp)

        if USER_MAP_FILE.exists():
            bak = REPORT_DIR / f"user_map_before_users_import_{stamp}.json"
            bak.write_text(USER_MAP_FILE.read_text(encoding="utf-8"), encoding="utf-8")

        role_ids = ensure_legacy_roles(cur, {c for c in all_codes if c in perm_names},
                                       perm_names, perm_ids)
        legacy_role_ids = tuple(role_ids.values()) or (0,)

        for p in plan:
            if p["is_superuser"]:
                # 超管账号(新库 admin)不动密码/用户名/角色,只补联系方式
                cur.execute(
                    "UPDATE users SET real_name=COALESCE(NULLIF(real_name,''),%s), "
                    "phone=COALESCE(NULLIF(phone,''),%s), zw=COALESCE(NULLIF(zw,''),%s) WHERE id=%s",
                    (p["real_name"], p["phone"], p["zw"], p["new_id"]),
                )
            elif p["source"] == "insert":
                cur.execute(
                    "INSERT INTO users (id, username, password_hash, password_version, real_name, "
                    "phone, zw, is_active, is_superuser, must_change_password, failed_attempts, "
                    "created_at, last_login_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,%s,0,NOW(),%s)",
                    (p["new_id"], p["username"], p["password_hash"], p["password_version"],
                     p["real_name"], p["phone"], p["zw"], 1 if p["is_active"] else 0,
                     1 if p["must_change_password"] else 0, p["last_login_at"]),
                )
            else:
                if p["keep_password"]:
                    cur.execute(
                        "UPDATE users SET username=%s, real_name=%s, phone=%s, zw=%s, "
                        "is_active=%s, last_login_at=COALESCE(last_login_at,%s) WHERE id=%s",
                        (p["username"], p["real_name"], p["phone"], p["zw"],
                         1 if p["is_active"] else 0, p["last_login_at"], p["new_id"]),
                    )
                else:
                    cur.execute(
                        "UPDATE users SET username=%s, password_hash=%s, password_version=%s, "
                        "real_name=%s, phone=%s, zw=%s, is_active=%s, must_change_password=%s, "
                        "last_login_at=COALESCE(last_login_at,%s) WHERE id=%s",
                        (p["username"], p["password_hash"], p["password_version"], p["real_name"],
                         p["phone"], p["zw"], 1 if p["is_active"] else 0,
                         1 if p["must_change_password"] else 0, p["last_login_at"], p["new_id"]),
                    )

            # 部门:先清掉本人旧关联再写(一人一部门,与旧 bmid 一致)
            if p["dept_id"] is not None:
                cur.execute("DELETE FROM user_department WHERE user_id=%s", (p["new_id"],))
                cur.execute(
                    "INSERT IGNORE INTO user_department (user_id, department_id) VALUES (%s,%s)",
                    (p["new_id"], p["dept_id"]),
                )

            # 角色:清掉本人所有 legacy_* 角色后按旧权限重建(保留人工建的角色)
            if not p["is_superuser"]:
                placeholders = ",".join(["%s"] * len(legacy_role_ids))
                cur.execute(
                    f"DELETE FROM user_role WHERE user_id=%s AND role_id IN ({placeholders})",
                    (p["new_id"], *legacy_role_ids),
                )
                for code in sorted(p["perms"]):
                    rid = role_ids.get(code)
                    if rid:
                        cur.execute(
                            "INSERT IGNORE INTO user_role (user_id, role_id) VALUES (%s,%s)",
                            (p["new_id"], rid),
                        )

        nc.commit()

        # ===== 阶段 3:报告 + 全量 user_map =====
        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "db_plan.dbo.bb_user / bb_qxfenpei / bb_quanx",
            "target": f"{settings.DB_NAME}.users",
            "summary": {
                "old_total": len(old_users), "inserted": len(inserts), "updated": len(updates),
                "inactive": len(inactive_users), "initial_password": len(no_pwd),
                "legacy_pbkdf2": sum(1 for p in plan if p["password_version"] == LEGACY_PBKDF2_VERSION),
                "legacy_md5": sum(1 for p in plan if p["password_version"] == LEGACY_MD5_VERSION),
                "roles_touched": len(all_codes), "dept_missing": len(no_dept),
                "password_kept_v1": sum(1 for p in plan if p.get("keep_password")),
            },
            "initial_password_accounts": [
                {"username": p["username"], "real_name": p["real_name"],
                 "phone": p["phone"], "dept": dept_names.get(p["dept_id"], "")}
                for p in no_pwd
            ],
            "inactive_accounts": [
                {"username": p["username"], "real_name": p["real_name"]} for p in inactive_users
            ],
            "rows": [
                {"old_id": p["old_id"], "new_id": p["new_id"], "username": p["username"],
                 "real_name": p["real_name"], "phone": p["phone"], "zw": p["zw"],
                 "is_active": p["is_active"], "password_version": p["password_version"],
                 "dept": dept_names.get(p["dept_id"], ""), "perms": sorted(p["perms"])}
                for p in plan
            ],
            "unmapped_menus": [
                {"menu": name, "users": n} for name, n in unmapped_counter.most_common()
            ],
        }
        report_path = REPORT_DIR / f"users_import_report_{stamp}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        USER_MAP_FILE.write_text(
            json.dumps({
                "source": "db_plan.dbo.bb_user",
                "target": f"{settings.DB_NAME}.users",
                "match_rules": ["old id → 新 id 1:1 恒等(rebuild_user_ids.py 重建后)"],
                "user_map": {str(p["old_id"]): p["new_id"] for p in plan},
                "missing": [],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"完成:新增 {len(inserts)},更新 {len(updates)},停用 {len(inactive_users)}")
        print(f"报告 → {report_path.name};全量映射 → {USER_MAP_FILE.name}")
        if no_pwd:
            print(f"需线下告知初始密码({settings.INITIAL_PASSWORD})的账号 {len(no_pwd)} 个,名单见报告")
    finally:
        nc.close()


if __name__ == "__main__":
    main()
