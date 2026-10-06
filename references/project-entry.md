# 项目入口

skill 必须完整安装，包括 references 与 scripts。共享项目状态在 ima；每人的本机路径和运行环境只保存在自己的配置。不得依赖作者电脑、实施计划或聊天历史。

## 定位与首次接入

用户指定配置／PAPER_LIBRARY_PROJECT 优先，其次工作目录及父目录的 paper-library.project.json。当前维护者配置为 `F:\UserData\Documents\ChatGPT\知识库构建\paper-library.project.json`，仅作本机线索，其他成员不得照抄路径。

找不到配置时，读取 [共享定位信息](project-locator.json)，从指定 KB 的“知识库更新状态”目录读取团队生效入口链。以连续 parent/media_id/hash/revision 唯一链确定生效版本，不以最新日期或文件名排序猜测。读取并校验入口引用的共享状态 MD。只询问本机工作目录、成员标识及缺少的连接条件；已有本机工作不受连接失败影响。

team init 为新成员建立本机配置、身份登记、出处映射、批次状态和缓存路径。状态包不含卡片正文及完整参考 raw；owner_local_only 表示原执行者持有，不能标成另一成员已完成或已拿到。先让原执行者保存被授权成果，或按用户明确指定的重构任务回查原文；不得为补本机缓存重新上传或分配编号。

## 已有项目与续办

读取 state_file、effective_manifest、working_manifest、last_batch、output_root 和 team_sync。effective_manifest 指向已回读核验的团队生效入口，artifact_release 单独指示科学产物／完整记录的发布范围。working_manifest 是本机完整导出，不能当作 ima 已生效。旧 index-only 入口保留为 artifact_release 历史，不冒充完整共享。

有 team_sync 时，变更前 team begin 检查共享版本及写入者。版本过期且本地无未发布变更时 team refresh；有本地变更先保留并对比，不能覆盖。按需 team hydrate 下载指定原文或已共享产物，核对真实 folder/title/media_id/SHA；连接失败继续已核验本地阅读和候选产物，未取得写入资格时不得向正式登记分配新 S/E 或发布。

任务产生变更时，收尾必读 [团队状态提交](team-workflow.md)。共享状态更新是正式库任务的一部分；用户明确“仅本地／不同步”时保留 pending_publish 并报告。无变更复用入口，长批次按小批提交。

本机维护正本 `F:\UserData\Desktop\manage-paper-library`；发现入口目录联接指向它。团队分发包是版本化副本，成员安装后分别核验发现；不把维护者目录联接照搬到其他电脑。
