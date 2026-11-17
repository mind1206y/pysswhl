"""外部水务工单系统接口(旧站 3 个代理口溯源后的原始上游)。

旧站对外代理口 -> 真实上游:
- /ImageProxy/GetByNo            -> POST WorkOrderNoService: getFlowInfoById
- /ImageProxy/GetWorkOrderImages -> POST appServeApi?state=formImageList
- /ImageProxy/GetImage           -> GET  formImageList 返回的图片直链(域名白名单)

旧站停运后新系统直接调用上述上游,不再经过旧站转发。
"""

import json
import time
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from app.core.config import settings

# 原始报文诊断日志(排查上游字段名/结构漂移用,每条截断、文件封顶)
_DEBUG_LOG = Path(__file__).resolve().parents[2] / "logs" / "workorder_flow_debug.log"
_DEBUG_ENTRY_MAX = 1500
_DEBUG_FILE_MAX = 512 * 1024


def _log_raw_body(body) -> None:
    try:
        if not _DEBUG_LOG.parent.exists():
            _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        if _DEBUG_LOG.exists() and _DEBUG_LOG.stat().st_size > _DEBUG_FILE_MAX:
            _DEBUG_LOG.write_text("", encoding="utf-8")  # 封顶即清空重来
        text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text[:_DEBUG_ENTRY_MAX]}\n"
        with _DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # 诊断日志失败不影响主流程


def _post_json(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_workorder(no: str, timeout: Optional[int] = None) -> dict:
    """按工单号查工单详情,返回 {success, msg, data}。

    timeout 可由调用方压短(工单号失焦即触发的场景),默认用全局配置。
    """
    no = (no or "").strip()
    if not no.isdigit() or int(no) <= 0:
        return {"success": False, "msg": "工单号必须是正整数", "data": None}
    payload = {
        "appId": settings.WORKORDER_FLOW_APP_ID,
        "version": settings.WORKORDER_FLOW_VERSION,
        "data": {"id": int(no)},
    }
    try:
        body = _post_json(settings.WORKORDER_FLOW_URL, payload,
                          timeout or settings.WORKORDER_FLOW_TIMEOUT)
    except Exception as exc:
        return {
            "success": False,
            "msg": f"外部工单系统未接入或不可达（{type(exc).__name__}）",
            "data": None,
        }
    if not isinstance(body, dict):
        return {"success": False, "msg": "工单接口返回异常", "data": None}
    _log_raw_body(body)
    code = body.get("Code") if body.get("Code") is not None else body.get("code")
    if code is not None and str(code).strip() != "200":
        # 与旧站 WorkOrderNoService 对齐:Code!=200 一律视为失败
        return {
            "success": False,
            "msg": str(body.get("Msg") or body.get("msg") or f"工单接口返回码 {code}"),
            "data": None,
        }
    data = body.get("Data") or body.get("data")
    if isinstance(data, str):
        # 兜底:上游偶发把 Data 双重序列化成 JSON 字符串
        try:
            data = json.loads(data)
        except ValueError:
            data = None
    if not data:
        return {
            "success": False,
            "msg": body.get("Msg") or body.get("msg") or "工单不存在",
            "data": None,
        }
    return {"success": True, "msg": "获取成功", "data": normalize_flow_data(data)}


# 旧站 Newtonsoft 反序列化大小写不敏感,上游字段名若与规范名不一致旧站仍可用;
# 新系统按规范名精确取值,故在此统一归一(未知字段原样保留)。
CANONICAL_FIELDS = ("Id", "CreateTime", "AddressStr", "Problem", "OtherDemand",
                    "DamageType", "LeakageType", "CloseValve", "Status", "updateTime")


def normalize_flow_data(d: dict) -> dict:
    """把上游返回的工单字典归一到 WorkOrderOut 规范字段名(大小写不敏感补齐)。"""
    if not isinstance(d, dict):
        return d
    lower = {}
    for k, v in d.items():
        lower.setdefault(str(k).lower(), v)
    out = dict(d)
    for name in CANONICAL_FIELDS:
        if name not in out and name.lower() in lower:
            out[name] = lower[name.lower()]
    return out


def workorder_detail(d: dict) -> dict:
    """工单详情抽屉的规范化字段(jcxt/gongdan-info 与 workorder/external/info 共用)。

    同时保留旧表单回填用的 ksriqi/dizhi 与抽屉用的小驼峰字段。
    """
    return {
        "Id": d.get("Id"),
        "ksriqi": d.get("CreateTime"),
        "dizhi": d.get("AddressStr"),
        "createTime": d.get("CreateTime"),
        "updateTime": d.get("updateTime"),
        "addressStr": d.get("AddressStr"),
        "problem": d.get("Problem"),
        "otherDemand": d.get("OtherDemand"),
        "damageType": d.get("DamageType"),
        "leakageType": d.get("LeakageType"),
        "closeValve": d.get("CloseValve"),
        "status": d.get("Status"),
    }


IMAGE_SLOTS = (
    ("beforeImg", "处理前"),
    ("underwayImg", "处理中"),
    ("afterImg", "处理后"),
)


def fetch_workorder_images(flow_id) -> dict:
    """按工单流程 ID 查现场图片,固定返回 3 个槽位(处理前/中/后)。

    返回 {success, msg, images:[{kind,label,url}]};url 为空表示该阶段无图。
    """
    try:
        fid = int(flow_id)
    except (TypeError, ValueError):
        return {"success": False, "msg": "工单号无效", "images": []}
    if fid <= 0:
        return {"success": False, "msg": "工单号无效", "images": []}
    payload = {
        "appId": settings.WORKORDER_IMAGE_APP_ID,
        "version": settings.WORKORDER_IMAGE_VERSION,
        "data": {"flowId": fid},
    }
    try:
        body = _post_json(settings.WORKORDER_IMAGE_URL, payload,
                          settings.WORKORDER_IMAGE_TIMEOUT)
    except Exception as exc:
        return {
            "success": False,
            "msg": f"工单图片服务未接入或不可达（{type(exc).__name__}）",
            "images": [],
        }
    if not isinstance(body, dict) or str(body.get("code")) != "200":
        msg = body.get("msg") if isinstance(body, dict) else None
        return {"success": False, "msg": msg or "图片接口返回异常", "images": []}
    data = body.get("data") or {}
    images = [
        {"kind": kind, "label": label, "url": data.get(kind) or ""}
        for kind, label in IMAGE_SLOTS
    ]
    return {"success": True, "msg": "获取成功", "images": images}


def _host_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme in ("http", "https")
        and parsed.hostname == settings.WORKORDER_IMAGE_ALLOWED_HOST
    )


def fetch_image(url: str) -> tuple[bytes, str]:
    """代取图片直链内容,仅允许白名单域名。返回 (bytes, content_type)。"""
    if not _host_allowed(url):
        raise ValueError("非法图片地址")
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=settings.WORKORDER_IMAGE_TIMEOUT) as resp:
        content_type = resp.headers.get("Content-Type") or "image/jpeg"
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        limit = settings.WORKORDER_IMAGE_MAX_BYTES
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("图片过大")
    return data, content_type
