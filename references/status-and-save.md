# 状态与保存

共享状态为可下载MD和明确生效manifest，不依赖已删除的内置正本笔记。本地JSON／MD是处理与导出，未切manifest不冒充已同步；日期最新不自动生效。

状态：legacy_pending_migration、missing、local_verified、save_not_requested、save_pending、saved_verified、failed、invalidated。各步骤分开，外部DOI／分区待补不阻塞可靠卡与参考结构。

1. 完整实时目录、旧成果备份，核对目标folder、格式、大小。生成文件按 `Sxxx_论文原名_知识卡片_r内容hash前8位.md`、`Sxxx_论文原名_参考文献清单_r内容hash前8位.md` 命名。完整题名取已核验原文，处理非法字符及过长路径；已有原PDF和已保存成果不因命名规则更新自动改名或重传。
2. 查receipt／同名对象，远端回读hash相同复用；不同内容取消用新修订名并登记替代。嵌套重名响应必须识别，未知结构停止。
3. create_media→COS PUT(仅临时凭据)→add_knowledge，每步无秘密receipt。超时add_unknown先查实际目录／media_id，禁盲目create。存在则回读复用；确无对象核实orphan，使用原media_id及有效临时信息恢复，或明确失败再作新修订，不能删receipt强行重试。
4. folder内media_id／完整名／回读SHA全匹配才saved_verified；code0不等于验收。平台解析单列not_verified。
5. 请求成果保存后，团队项目按 team-workflow.md 必须提交受影响的控制状态及新版入口，分别记录科学产物保存与共享进度。具备完整原记录且获授权时，同源导出五类完整MD、全部核验后以 release_manifest 纳入团队入口。仅控制状态不能冒充完整五类记录；旧 activate／shared_index publish 不绕过团队版本检查。登记替代和旧版待人工清理，不自动删旧条目。

无连接完成本地并明确未同步。凭据仅内存／进程环境，退出关闭会话；receipt不存signed URL或临时credential。明确保存到ima覆盖指定成果和受影响的元数据索引、控制状态，不需每次重复确认。完整五类记录内含其他篇raw时，不因单篇任务自动上传。

控制状态发布失败保留 pending_publish 及 team/pending.json；它们分别表示本机有未共享变更和正在恢复的发布事务。无变更返回 reused_verified，不为重复调用新增入口。已共享入口用连续 parent 链确定，不用日期最新或同名覆盖。每个产生变更的正式库任务在结束前提交；用户明确只本地时保留待同步并报告。
