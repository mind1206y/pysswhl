"""新旧口径交叉核对:对同一辆车,比对旧 SQL Server 直算结果与新 /api/oiltj 列表行。"""
import os

import pyodbc
from base64 import b64encode
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User

NIAN, YUE = 2026, 10

old = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=127.0.0.1,1433;DATABASE=db_plan;"
    "UID=sa;PWD=swgps;", timeout=10)
cur = old.cursor()
cur.execute(
    "SELECT TOP 5 p.cheid, c.chehao, SUM(p.oill) "
    "FROM PlusOil p JOIN cl_che c ON c.id=p.cheid "
    "WHERE YEAR(p.ptime)=? AND MONTH(p.ptime)=? GROUP BY p.cheid, c.chehao",
    NIAN, YUE)
targets = cur.fetchall()
print("样本车:", targets[:5])

# 旧口径逐车直算(照 oiltjController.Get)
def old_calc(cheid):
    out = {}
    cur.execute("SELECT SUM(oill) FROM PlusOil WHERE cheid=? AND YEAR(ptime)=? AND MONTH(ptime)=?", cheid, NIAN, YUE)
    out["yoil"] = round(float(cur.fetchone()[0] or 0), 2)
    cur.execute("SELECT SUM(oill) FROM PlusOil WHERE cheid=? AND YEAR(ptime)=?", cheid, NIAN)
    out["noil"] = round(float(cur.fetchone()[0] or 0), 2)
    cur.execute("SELECT MAX(jsgl) FROM yongcherc WHERE cheid=? AND YEAR(jsdate)=? AND MONTH(jsdate)=?", cheid, NIAN, YUE)
    out["bydgls"] = int(cur.fetchone()[0] or 0)
    if YUE == 1:
        cur.execute("SELECT MAX(jsgl) FROM yongcherc WHERE cheid=? AND YEAR(jsdate)=? AND MONTH(jsdate)=12", cheid, NIAN - 1)
    else:
        cur.execute("SELECT MAX(jsgl) FROM yongcherc WHERE cheid=? AND YEAR(jsdate)=? AND MONTH(jsdate)=?", cheid, NIAN, YUE - 1)
    out["sydgls"] = int(cur.fetchone()[0] or 0)
    out["yssgls"] = out["bydgls"] - out["sydgls"]
    cur.execute("SELECT TOP 1 jsgl FROM yongcherc WHERE cheid=? AND YEAR(jsdate)=? AND jsgl<>0 ORDER BY jsdate DESC", cheid, NIAN)
    r = cur.fetchone()
    jn = int(r[0] or 0) if r else 0
    cur.execute("SELECT TOP 1 jsgl FROM yongcherc WHERE cheid=? AND YEAR(jsdate)=? AND jsgl<>0 ORDER BY jsdate DESC", cheid, NIAN - 1)
    r = cur.fetchone()
    sn = int(r[0] or 0) if r else 0
    out["ngls"] = jn - sn
    cur.execute("SELECT COUNT(*) FROM yongcherc WHERE cheid=? AND YEAR(ksdate)=?", cheid, NIAN)
    out["times"] = int(cur.fetchone()[0])
    return out

# 新系统登录 + 查列表
client = TestClient(app)
db = SessionLocal()
u = db.query(User).filter_by(username="smoke_oiltj").first()
if u is None:
    u = User(username="smoke_oiltj", password_hash=hash_password("Smoke@12345"),
             password_version=1, real_name="核对", is_superuser=True, is_active=True)
    db.add(u); db.commit()
db.close()
pub = client.get("/api/auth/public-key").json()["publicKey"].encode()
key = serialization.load_pem_public_key(pub)
enc = key.encrypt(b"Smoke@12345", padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
tok = client.post("/api/auth/login", json={"username": "smoke_oiltj", "password": b64encode(enc).decode()}).json()["token"]
h = {"Authorization": f"Bearer {tok}"}

ok = True
for cheid, chehao, _ in targets:
    r = client.get("/api/oiltj", params={"nian": NIAN, "yue": YUE, "px": "true", "sousou": chehao}, headers=h)
    rows = r.json()["rows"]
    new = next((x for x in rows if x["cheid"] == cheid), None)
    if new is None:
        print(f"❌ cheid={cheid} {chehao} 新列表未返回"); ok = False; continue
    o = old_calc(cheid)
    for k in ("yoil", "noil", "bydgls", "sydgls", "yssgls", "ngls", "times"):
        same = abs(float(new[k]) - float(o[k])) < 0.02
        ok = ok and same
        if not same:
            print(f"❌ {chehao} {k}: 旧={o[k]} 新={new[k]}")
    print(f"{'✅' if ok else '❌'} {chehao}: 月油 {new['yoil']} 年油 {new['noil']} 月里程 {new['yssgls']} 年里程 {new['ngls']} 次数 {new['times']}")

db = SessionLocal()
u = db.query(User).filter_by(username="smoke_oiltj").first()
db.delete(u); db.commit(); db.close()
print("新旧口径交叉核对:", "全部一致 ✅" if ok else "存在差异 ❌")
if not ok:
    raise SystemExit(1)
