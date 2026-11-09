"""CLfeiyong 页面 CDP 实机回归:创建临时超管 + 登录取 token,支持 --cleanup 删除。

用法(backend 目录下):
    python -m scripts.ui_check_clfeiyong            # 打印 {"token": ...}
    python -m scripts.ui_check_clfeiyong --cleanup  # 删除临时账号
"""

import base64
import json
import sys
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User

USER = "ui_check_fy"
PWD = "UiCheck@12345"


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def cleanup():
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == USER).first()
        if u is not None:
            db.delete(u)
            db.commit()
        print("已删除临时账号 " + USER)
    finally:
        db.close()


def main():
    if "--cleanup" in sys.argv:
        cleanup()
        return 0
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == USER).first()
        if u is None:
            u = User(username=USER, password_hash=hash_password(PWD), password_version=1,
                     real_name=USER, is_superuser=True, is_active=True)
            db.add(u)
            db.commit()
    finally:
        db.close()

    pub = get("http://127.0.0.1:8000/api/auth/public-key")["publicKey"]
    pubkey = serialization.load_pem_public_key(pub.encode())
    enc = pubkey.encrypt(PWD.encode(), padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    res = post("http://127.0.0.1:8000/api/auth/login",
               {"username": USER, "password": base64.b64encode(enc).decode()})
    print(json.dumps({"token": res["token"], "user": USER, "pwd": PWD}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
