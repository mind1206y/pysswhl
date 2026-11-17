"""车辆年检定时短信(照旧 CarNianJian.cs Quartz Job,原每天 08:25 触发)。

旧实现:Quartz IJob 遍历未年检车辆,按「下次年检日」剩余天数分级:
  级别 1 = 90 天 / 2 = 30 天 / 3 = 7 天,各级别每年度发一次固定文案短信;
  已过期车辆 ReminderLevel=4,每 10 天催办一次;
  已标注年检且下次年检日进入 90 天窗口的,重置进下个提醒周期。

新实现:逻辑逐条照搬,由 app/main.py 启动一个守护线程在每天 08:25 调
run_nianjian_job();短信走 app/services/sms.py 同一网关,发送人记「系统自动」。
短信失败不影响流程,只记 sms_record.zt(与手动发送口径一致)。
"""

import logging
import time
import traceback
from datetime import date, datetime, timedelta

from sqlalchemy import or_

from app.db.session import SessionLocal
from app.models.plan import ConsolTb
from app.models.vehicle import ClChe
from app.services import sms as sms_service
from app.services.vehicle_common import _vehicle_age, inspection_dates

logger = logging.getLogger("nianjian_job")

# 提醒短信总开关(consol_tb,超管在车辆管理页控制;无记录默认开启)
SMS_SWITCH_NAME = "车辆年检提醒短信"


def sms_reminder_enabled(db) -> bool:
    row = db.query(ConsolTb).filter(ConsolTb.conName == SMS_SWITCH_NAME).first()
    return bool(row.val) if row is not None else True

# 每天触发时刻(照旧 08:25)
JOB_HOUR, JOB_MINUTE = 8, 25
# 过期催办间隔(照旧 HandleExpiredReminder)
EXPIRED_REMIND_DAYS = 10


def _cycle_info(register: date, vehicle_type: str, today: date) -> str:
    """照旧 GetCycleInfo:货=车龄≥10 每半年否则每年;摩托=≥4 每年否则每2年;
    其他=≥10 每年否则每2年。"""
    age = _vehicle_age(register, today)
    if "货" in (vehicle_type or ""):
        return "每半年" if age >= 10 else "每年"
    if "摩托" in (vehicle_type or ""):
        return "每年" if age >= 4 else "每2年"
    return "每年" if age >= 10 else "每2年"


def _reminder_message(car: ClChe, level: int, days: int, due: date, cycle: str) -> str:
    """照旧 GenerateReminderMessage 的 1~3 级固定文案。"""
    if level == 1:
        return (f"（90天提醒）车辆{car.chehao}{cycle}年检即将到期（{due:%Y-%m-%d}），"
                f"剩余{days}天。请及时办理，如已年检通知车辆管理员标注信息。")
    if level == 2:
        return (f"（30天提醒）车辆{car.chehao}{cycle}年检即将到期（{due:%Y-%m-%d}），"
                f"剩余{days}天。请尽快办理，如已年检通知车辆管理员标注信息。")
    if level == 3:
        return (f"（7天紧急提醒）车辆{car.chehao}{cycle}年检即将到期（{due:%Y-%m-%d}），"
                f"仅剩{days}天！请立即办理！！！如已年检通知车辆管理员标注信息。")
    return ""


def _expired_message(car: ClChe, due: date) -> str:
    return (f"（已过期提醒）车辆{car.chehao}年检已过期（{due:%Y-%m-%d}），"
            "请尽快办理！如已年检请通知车管员标注信息")


def _should_send(car: ClChe, level: int, year: int) -> bool:
    """照旧 ShouldSendReminder:同级别且今年已发过则跳过。"""
    if (
        (car.ReminderLevel or 0) >= level
        and car.LastReminderDate
        and car.LastReminderDate.year == year
    ):
        return False
    return True


def _expired_reminder(db, car: ClChe, due: date, results: list):
    """照旧 HandleExpiredReminder:过期车每 10 天催一次。"""
    now = datetime.now()
    if car.LastReminderDate and (now - car.LastReminderDate).total_seconds() < EXPIRED_REMIND_DAYS * 86400:
        return
    if not (car.telphone or "").strip():
        return
    result = sms_service.send_sms(
        db, "系统自动", car.telphone, _expired_message(car, due),
        "车辆年检过期提醒", car.jiashiyuan,
    )
    results.append({"id": car.id, "chehao": car.chehao, "kind": "过期催办", **result})
    car.LastReminderDate = now


def run_nianjian_job(db) -> dict:
    """定时任务主体(照旧 IJob.Execute),调用方负责提供与关闭会话。"""
    if not sms_reminder_enabled(db):
        logger.warning("车辆年检提醒短信开关已关闭,本次定时任务跳过(不发短信、不推进状态)")
        return {"vehicles": 0, "reset": 0, "marked_expired": 0, "sent": 0,
                "results": [], "skipped": True}

    today = date.today()
    year = today.year
    now = datetime.now()
    results: list = []
    reset = 0
    marked_expired = 0

    # ===== ResetExpiredInspections:已年检且下次年检日进入 90 天窗口 → 重置进新周期 =====
    cutoff = today + timedelta(days=90)
    for v in (
        db.query(ClChe)
        .filter(ClChe.IsInspected == True, ClChe.NextInspectionDate.isnot(None))  # noqa: E712
        .all()
    ):
        if v.NextInspectionDate <= cutoff:
            v.IsInspected = False
            v.InspectionDate = None
            v.ReminderLevel = 0
            v.LastReminderDate = None
            reset += 1
    db.commit()

    # ===== 遍历未年检车辆(delf=1、非油卡、注册日期非空,照旧查询条件) =====
    vehicles = (
        db.query(ClChe)
        .filter(
            ClChe.delf == 1,
            ClChe.yongtu != "油卡",
            ClChe.chuchang.isnot(None),
            or_(ClChe.IsInspected.is_(None), ClChe.IsInspected == False),  # noqa: E712
        )
        .all()
    )

    for car in vehicles:
        try:
            # 照旧 CalculateCorrectNextInspectionDate(vehicle, "检查过期")
            _prev, nxt, _nn = inspection_dates(car.chuchang, car.lx, today)
            next_due = _prev if car.ReminderLevel == 4 else nxt
            days = (next_due - today).days

            if car.ReminderLevel == 4:
                car.NextInspectionDate = next_due
                _expired_reminder(db, car, next_due, results)
            if car.NextInspectionDate and car.NextInspectionDate < today:
                car.ReminderLevel = 4
                _expired_reminder(db, car, next_due, results)

            if days < 0:
                # MarkAsExpired:置 4 并把下次年检日落到本次计算的到期日
                if car.ReminderLevel != 4:
                    car.ReminderLevel = 4
                    car.NextInspectionDate = next_due
                    car.LastReminderDate = now
                    marked_expired += 1
                _expired_reminder(db, car, next_due, results)
                continue

            # 提前提醒:级别 1(≤90天) / 2(≤30天) / 3(≤7天)
            level = 3 if days <= 7 else 2 if days <= 30 else 1 if days <= 90 else 0
            if 1 <= level <= 3 and _should_send(car, level, year):
                if (car.telphone or "").strip():
                    days_ceil = max(int(days), 0)
                    cycle = _cycle_info(car.chuchang, car.lx, today)
                    result = sms_service.send_sms(
                        db, "系统自动", car.telphone,
                        _reminder_message(car, level, days_ceil, next_due, cycle),
                        "车辆年检提醒", car.jiashiyuan,
                    )
                    results.append({"id": car.id, "chehao": car.chehao,
                                    "kind": f"{level}级提醒", **result})
                # UpdateVehicleReminderStatus:无论是否发出(无手机号也推进级别,照旧)
                car.ReminderLevel = level
                car.LastReminderDate = now
        except Exception:  # 单车失败不阻断整批
            logger.warning("车辆 %s 年检提醒处理失败:\n%s", car.chehao, traceback.format_exc())

    db.commit()
    return {
        "vehicles": len(vehicles), "reset": reset, "marked_expired": marked_expired,
        "sent": sum(1 for r in results if r.get("ok")),
        "results": results,
    }


def nianjian_loop():
    """守护线程入口:每天 08:25 跑一次(照旧 Quartz cron)。"""
    while True:
        now = datetime.now()
        target = now.replace(hour=JOB_HOUR, minute=JOB_MINUTE, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        time.sleep(max(1.0, (target - now).total_seconds()))
        db = SessionLocal()
        try:
            summary = run_nianjian_job(db)
            logger.warning(
                "车辆年检定时任务完成:处理 %s 辆,重置 %s 辆,标记过期 %s 辆,短信 %s 条",
                summary["vehicles"], summary["reset"], summary["marked_expired"], summary["sent"],
            )
        except Exception:
            logger.error("车辆年检定时任务执行失败:\n%s", traceback.format_exc())
        finally:
            db.close()
