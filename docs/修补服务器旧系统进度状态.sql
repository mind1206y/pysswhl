-- =====================================================================
-- 修补旧系统 db_plan.dbo.gongchenggl_jindu.jinduzhuangtai 全为 0 的存量数据
-- 背景:旧前端新增进度时 jinduzhuangtai 硬编码传 0(源码已修复:
--      Views/Gongchengguanli/Index.cshtml 改为传 newStatus),
--      进度记录状态失真;删除进度回滚主表状态时会取该值导致错误回滚。
-- 策略:① 每个工程最新一条进度 ← 主表 Status(精确回填)
--      ② 更早的记录按描述关键词推断(试压/施压/通水/装表/切换用水/裸验收)
--      ③ 推断不出的保持 0(验槽/沟槽验收等施工环节记录,不硬猜)
-- 特性:可重复执行(已改过的行不再匹配 WHERE jinduzhuangtai=0),
--      首次执行自动备份原表到 gongchenggl_jindu_bak_20261107
-- 用法:SSMS 里连到服务器 db_plan 执行;或 sqlcmd -S 服务器 -d db_plan -i 本文件.sql
-- =====================================================================

SET NOCOUNT ON;

-- 0. 首次执行时备份原表
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name = 'gongchenggl_jindu_bak_20261107' AND type = 'U')
BEGIN
    SELECT * INTO gongchenggl_jindu_bak_20261107 FROM gongchenggl_jindu;
    PRINT '已备份原表到 gongchenggl_jindu_bak_20261107';
END
ELSE
    PRINT '备份表已存在,跳过备份';

-- 1. 每个工程最新一条进度 ← 主表 Status(精确)
UPDATE j
SET j.jinduzhuangtai = g.Status
FROM gongchenggl_jindu j
JOIN (SELECT gcglid, MAX(id) AS max_id FROM gongchenggl_jindu GROUP BY gcglid) t
     ON j.id = t.max_id
JOIN gongchenggl g ON g.id = j.gcglid
WHERE j.jinduzhuangtai = 0 AND g.Status <> 0;
PRINT '步骤1(最新一条回填主表Status)完成,影响 ' + CAST(@@ROWCOUNT AS varchar) + ' 行';

-- 2. 关键词推断(强词优先)
UPDATE gongchenggl_jindu SET jinduzhuangtai = 7 WHERE jinduzhuangtai = 0 AND jindu LIKE '%归档%';
UPDATE gongchenggl_jindu SET jinduzhuangtai = 6 WHERE jinduzhuangtai = 0 AND jindu LIKE '%移交%';
UPDATE gongchenggl_jindu SET jinduzhuangtai = 4 WHERE jinduzhuangtai = 0 AND jindu LIKE '%通水%';
UPDATE gongchenggl_jindu SET jinduzhuangtai = 3 WHERE jinduzhuangtai = 0 AND (jindu LIKE '%试压%' OR jindu LIKE '%施压%');  -- "施压"为"试压"错别字
UPDATE gongchenggl_jindu SET jinduzhuangtai = 2 WHERE jinduzhuangtai = 0 AND jindu LIKE '%敷设%';
UPDATE gongchenggl_jindu SET jinduzhuangtai = 4 WHERE jinduzhuangtai = 0 AND (jindu LIKE '%装表%' OR jindu LIKE '%切换用水%');
-- 裸"验收"→已验收(排除验槽/管槽/沟槽/沙/砂/抽查/切管/见证/材料等施工环节词)
UPDATE gongchenggl_jindu SET jinduzhuangtai = 5
WHERE jinduzhuangtai = 0 AND jindu LIKE '%验收%'
  AND jindu NOT LIKE '%槽%' AND jindu NOT LIKE '%沙%' AND jindu NOT LIKE '%砂%'
  AND jindu NOT LIKE '%抽查%' AND jindu NOT LIKE '%切管%' AND jindu NOT LIKE '%见证%'
  AND jindu NOT LIKE '%材料%';
PRINT '步骤2(关键词推断)完成';

-- 3. 核对:执行前后分布
SELECT jinduzhuangtai AS 状态, COUNT(*) AS 条数,
       CASE jinduzhuangtai WHEN 0 THEN '未开工' WHEN 1 THEN '施工中' WHEN 2 THEN '已敷设'
            WHEN 3 THEN '已试压' WHEN 4 THEN '已通水' WHEN 5 THEN '已验收'
            WHEN 6 THEN '已移交' WHEN 7 THEN '已归档' END AS 含义
FROM gongchenggl_jindu
GROUP BY jinduzhuangtai
ORDER BY jinduzhuangtai;

-- 4. 抽查:每个工程最新一条的状态应与主表一致(返回 0 行 = 一致)
SELECT g.id, g.xiangmuname, g.Status AS 主表状态, j.jinduzhuangtai AS 最新进度状态
FROM gongchenggl g
JOIN (SELECT gcglid, MAX(id) AS max_id FROM gongchenggl_jindu GROUP BY gcglid) t ON g.id = t.gcglid
JOIN gongchenggl_jindu j ON j.id = t.max_id
WHERE ISNULL(j.jinduzhuangtai, -1) <> ISNULL(g.Status, -1);
PRINT '核对完毕:上面查询返回 0 行说明最新进度与主表状态全部一致';
