"""水费系统公共工具:字段中文映射、diff 写日志、取消表同步。"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.water_fee import Shuifeixitong, ShuifeixitongBiandong, ShuifeixitongLog, ShuifeixitongQuxiao
from app.models.user import User

# 可编辑字段 → 中文列名(用于修改日志,照旧系统 CompareAndLog 的 field_name)
FIELD_LABELS = {
    "yonghuhao": "用户号",
    "qitayongshui": "其他用水情况",
    "beizhu": "备注",
    "shouliriqi": "受理日期",
    "youhuiksriqi": "优惠开始",
    "youhuijsriqi": "优惠结束",
    "yueshu": "优惠月数",
    "wushuifeihetui": "污水费核退",
    "daoruqingkuang": "系统导入情况",
    "fanhuiminzhengju": "返民政局",
    "guitaishouli": "柜台受理情况",
    "juzhudizhi": "居住地址",
    "dianhua": "电话",
    "kaihuming": "开户名",
    "yinhangzhanghao": "银行账号",
    "kaihuhang": "开户行",
    "kaihushenfenzheng": "开户身份证",
    "yinhangbeizhu": "银行备注",
    "shi": "市",
    "quxian": "区县",
    "xiangzhen": "乡镇",
    "cun": "村",
    "shixiang": "事项",
    "xingming": "姓名",
    "sfz": "证件号",
    "ksbriqi": "保障开始",
    "jsbriqi": "保障结束",
    "tekunlei": "特困类别",
    "gongyangfangshi": "供水方式",
    "gongyangjigou": "供水机构",
    "bm": "营业所",
    "bmid": "营业所(部门)",
    "quxiaoriqi": "取消日期",
    "nd": "年度",
}

DATE_FIELDS = {
    "ksbriqi", "jsbriqi", "youhuiksriqi", "youhuijsriqi",
    "wushuifeihetui", "shouliriqi", "caozuoriqi", "quxiaoriqi",
}
INT_FIELDS = {"nd", "bmid", "yueshu", "wenjianxuhao"}
TEXT_FIELDS = [f for f in FIELD_LABELS if f not in DATE_FIELDS | INT_FIELDS]
# 受理日期旧系统只比到日期(忽略时分秒)
DATE_DAY_ONLY = {"shouliriqi"}


def norm_value(field, value) -> str:
    """转成日志/比较用的规范字符串。"""
    if value is None:
        return ""
    if field in DATE_DAY_ONLY and isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)


def diff_and_log(db: Session, before: dict, after: dict, main_id: int, user: User, source: str):
    """对比前后字段字典,差异写中文修改日志。before/after 为 {字段: 原始值}。"""
    now = datetime.now()
    rows = []
    for field, label in FIELD_LABELS.items():
        old_v = norm_value(field, before.get(field))
        new_v = norm_value(field, after.get(field))
        if old_v != new_v:
            rows.append(ShuifeixitongLog(
                main_id=main_id, field_name=label, old_value=old_v, new_value=new_v,
                update_user=user.username, update_time=now, source=source,
            ))
    if rows:
        suffix = "(变动)" if source == "shuifeixitongbiandong" else ""
        for r in rows:
            r.update_user = user.username + suffix
        db.add_all(rows)
    return len(rows)


def snapshot(entity) -> dict:
    """实体字段快照(编辑前取一份用于 diff)。"""
    return {f: getattr(entity, f, None) for f in FIELD_LABELS}


def sync_quxiao_table(db: Session, row: Shuifeixitong, user: User):
    """主表取消日期变更时同步取消名单表(照旧 SaveEdit):
    设置了取消日期 → 按年+身份证+事项插入/更新取消表;清空取消日期 → 删除取消表记录。"""
    q = (
        db.query(ShuifeixitongQuxiao)
        .filter(
            ShuifeixitongQuxiao.nd == row.nd,
            ShuifeixitongQuxiao.sfz == row.sfz,
            ShuifeixitongQuxiao.shixiang == row.shixiang,
        )
        .first()
    )
    if row.quxiaoriqi:
        if q is None:
            q = ShuifeixitongQuxiao(
                shi=row.shi, quxian=row.quxian, xiangzhen=row.xiangzhen, cun=row.cun,
                shixiang=row.shixiang, xingming=row.xingming, sfz=row.sfz,
                juzhudizhi=row.juzhudizhi, dianhua=row.dianhua, kaihuming=row.kaihuming,
                yinhangzhanghao=row.yinhangzhanghao, kaihuhang=row.kaihuhang,
                kaihushenfenzheng=row.kaihushenfenzheng, yinhangbeizhu=row.yinhangbeizhu,
                ksbriqi=row.ksbriqi, jsbriqi=row.jsbriqi, tekunlei=row.tekunlei,
                gongyangfangshi=row.gongyangfangshi, gongyangjigou=row.gongyangjigou,
                bm=row.bm, caozuo=user.username, caozuoriqi=datetime.now(),
                yonghuhao=row.yonghuhao, qitayongshui=row.qitayongshui, beizhu=row.beizhu,
                shouliriqi=row.shouliriqi, youhuiksriqi=row.youhuiksriqi,
                youhuijsriqi=row.youhuijsriqi, wushuifeihetui=row.wushuifeihetui,
                daoruqingkuang=row.daoruqingkuang, fanhuiminzhengju=row.fanhuiminzhengju,
                guitaishouli=row.guitaishouli, nd=row.nd, bmid=row.bmid, yueshu=row.yueshu,
            )
            db.add(q)
        q.quxiaoriqi = row.quxiaoriqi
        q.quxiaoren = user.username
    elif q is not None:
        db.delete(q)


def extract_snapshot(row: Shuifeixitong, user: User) -> ShuifeixitongBiandong:
    """把主表记录提取为一条变动历史快照(照旧 ExtractToHistory)。"""
    return ShuifeixitongBiandong(
        zhuid=row.id,
        biandongriqi=datetime.now(),
        yonghuhao=row.yonghuhao,
        qitayongshui=row.qitayongshui,
        beizhu=row.beizhu,
        youhuiksriqi=row.youhuiksriqi,
        youhuijsriqi=row.youhuijsriqi,
        wushuifeihetui=row.wushuifeihetui,
        daoruqingkuang=row.daoruqingkuang,
        fanhuiminzhengju=row.fanhuiminzhengju,
        guitaishouli=row.guitaishouli,
        yueshu=row.yueshu,
        bmid=row.bmid,
        caozuo=user.username,
        shoulishijian=row.shouliriqi or datetime.now(),
        juzhudizhi=row.juzhudizhi,
    )


def calc_months(ks, js):
    """按优惠起止年月计算月数(照旧 BatchInLishi 公式:年差*12+月差,不含+1)。

    注:旧系统编辑页 calcMonths 是含+1 的另一套口径,前端编辑弹窗沿用 +1。
    """
    if not ks or not js:
        return None
    return (js.year - ks.year) * 12 + (js.month - ks.month)


MOHU_FIELDS = [
    "shixiang", "xingming", "sfz", "dianhua", "kaihuming", "yonghuhao",
    "qitayongshui", "beizhu", "daoruqingkuang", "guitaishouli", "tekunlei",
    "gongyangfangshi", "gongyangjigou", "juzhudizhi", "fanhuiminzhengju", "kaihuhang",
]
