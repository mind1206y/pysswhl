"""短信发送(照旧 whl.BLL/SmsSender.cs)。

旧实现:JSON 明文 -> AES-128-ECB/PKCS7(密钥 __XM_SWJT__ISW__) -> 大写十六进制,
以 data=<hex> 表单 POST 到内部网关,响应同样十六进制加密,解密后写 SmsRecord。

新实现保持协议不变,网关地址/密钥/超时走 .env;短信失败不影响业务流程,
只把失败原因记入 sms_record.zt。
"""

import urllib.parse
import urllib.request

from datetime import datetime

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from sqlalchemy import or_

from app.core.config import settings
from app.models.sms import SmsContact, SmsRecord
from app.models.user import User

PREFIX = "(售水信息小助手)"


def _key() -> bytes:
    return (settings.SMS_AES_KEY or "").ljust(16, "\0")[:16].encode("utf-8")


def encrypt(content: str) -> str:
    padder = PKCS7(128).padder()
    data = padder.update(content.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_key()), modes.ECB()).encryptor()
    return (encryptor.update(data) + encryptor.finalize()).hex().upper()


def decrypt(content: str) -> str:
    raw = bytes.fromhex(content.strip())
    decryptor = Cipher(algorithms.AES(_key()), modes.ECB()).decryptor()
    padded = decryptor.update(raw) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")


def _post(encrypted: str) -> str:
    body = urllib.parse.urlencode({"data": encrypted}).encode("ascii")
    req = urllib.request.Request(
        settings.SMS_API_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=settings.SMS_TIMEOUT) as resp:
        return resp.read().decode("utf-8", "ignore").strip()


def find_phone(db, name: str) -> tuple[str, str]:
    """按姓名找手机号:先查新系统用户,再回退旧 bb_user 联系人目录。"""
    name = (name or "").strip()
    if not name:
        return "", ""
    user = (
        db.query(User)
        .filter(User.is_active == True)  # noqa: E712
        .filter(or_(User.username == name, User.real_name == name))
        .order_by((User.username == name).desc())
        .first()
    )
    if user and (user.phone or "").strip():
        return user.phone.strip(), (user.real_name or user.username)

    contact = (
        db.query(SmsContact)
        .filter(or_(SmsContact.username == name, SmsContact.real_name == name))
        .order_by((SmsContact.username == name).desc())
        .first()
    )
    if contact and (contact.phone or "").strip():
        return contact.phone.strip(), (contact.real_name or contact.username or name)
    return "", ""


def send_sms(db, sender: str, mobile: str, content: str, category: str, recname: str) -> dict:
    """发送一条短信并落 sms_record。只 flush,由调用方 commit。"""
    mobile = (mobile or "").strip()
    recname = (recname or "").strip()
    if not mobile:
        return {"ok": False, "name": recname, "message": "未找到手机号"}

    full = PREFIX + (content or "")
    status = ""
    ok = False
    if not settings.SMS_ENABLED:
        status = "短信通道未启用(未发送)"
    else:
        try:
            payload = (
                '{"method":"sendMSM","params":{"MOBILE":"%s","CONTENT":"%s"}}'
                % (mobile, full.replace("\\", "\\\\").replace('"', '\\"'))
            )
            raw = _post(encrypt(payload))
            try:
                status = decrypt(raw)
                ok = True
            except ValueError:
                status = raw
                ok = bool(raw)
        except Exception as exc:  # 网络错误/网关异常不影响业务
            status = f"发送失败:{type(exc).__name__}:{exc}"

    db.add(SmsRecord(
        lb=category, riqi=datetime.now(), nr=full, tel=mobile, ren=recname,
        zt=(status or "")[:310], sender=sender or "",
    ))
    return {"ok": ok, "name": recname, "mobile": mobile, "status": (status or "")[:310]}


def notify(db, sender: str, names, content: str, category: str) -> dict:
    """按姓名批量发送,自动去重/跳过无手机号的人。只 flush,由调用方 commit。"""
    seen = set()
    sent = 0
    skipped = []
    failed = []
    for name in names:
        name = (name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        mobile, real_name = find_phone(db, name)
        if not mobile:
            skipped.append(name)
            continue
        result = send_sms(db, sender, mobile, content, category, real_name or name)
        # riqi 的 default 只在 insert 时生效,这里显式写,便于立即查询
        if result.get("ok"):
            sent += 1
        else:
            failed.append({"name": name, "message": result.get("message") or result.get("status")})
    return {"sent": sent, "skipped": skipped, "failed": failed}


def summary_recipients(db) -> list[str]:
    """旧 otherqx 含「计划汇总」的人 -> 新系统持有汇总权限的账号。"""
    codes = {"jhyyfaqi:summary", "jhsshz:manage", "jhsshz:admin"}
    names = []
    for user in db.query(User).filter(User.is_active == True).all():  # noqa: E712
        owned = {p.code for role in user.roles for p in role.permissions}
        if user.is_superuser or owned.intersection(codes):
            names.append(user.username)
    return names


def notify_summary(db, sender: str, content: str, category: str = "年度计划汇总") -> dict:
    return notify(db, sender, summary_recipients(db), content, category)


def record_dicts(db, limit: int = 200, keyword: str = "") -> list[dict]:
    q = db.query(SmsRecord).order_by(SmsRecord.id.desc())
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(
            SmsRecord.lb.like(like), SmsRecord.nr.like(like), SmsRecord.tel.like(like),
            SmsRecord.ren.like(like), SmsRecord.zt.like(like), SmsRecord.sender.like(like),
        ))
    return [r.to_dict() for r in q.limit(limit).all()]
