# 团队接入与状态提交

## 共享范围与写入者

团队控制状态包含项目／目录定位、规则版本、S/E 身份、引用出处／页码／raw hash、关系状态、检索状态和逐篇批次进度。credentials、本机路径、卡片正文和未授权完整参考清单不进入状态包。正文和 raw 可留原执行者本机；远端有对象定位不等于本机核验通过。完整五类记录与控制状态的发布分开，标明实际范围。

默认一个明确的 writer_id 负责正式写入。其他成员可初始化、查询、下载和阅读。明确要求交接时，由现写入者发布 handoff_to 后，新成员 refresh → begin；未指明目标成员不自行交接。关闭本机会话不释放共享写入权。ima 未实测分布式锁或原子 compare-and-swap，版本检查与分叉检测只能发现冲突，不能保证并发安全；本地 .lock 不是团队锁。

## 操作入口

沿用 ima_client.py 的无凭据操作 JSON，action 为 team。进程环境调用 --operation，或 --session 内存 stdin 首行凭据会话。路径由本机配置决定，凭据不进操作文件。

```json
{"action":"team","team_action":"init","root":"D:/论文库工作区","member_id":"member-02"}
```

已有项目：

```json
{"action":"team","team_action":"inspect","project":"D:/论文库工作区/paper-library.project.json"}
{"action":"team","team_action":"refresh","project":"D:/论文库工作区/paper-library.project.json"}
{"action":"team","team_action":"begin","project":"D:/论文库工作区/paper-library.project.json"}
{"action":"team","team_action":"hydrate","project":"D:/论文库工作区/paper-library.project.json","id":"S001","kinds":["original","card","reference"]}
{"action":"team","team_action":"publish","project":"D:/论文库工作区/paper-library.project.json"}
```

首次发布由维护者核实旧入口和实时目录后使用 initial=true；不能让新成员猜建空台账。

## 每次产生变更后的必执行步骤

1. 正式登记变更由 library.py 自动标 pending_publish。新编号、重构、分类、身份映射、保存回执和失败进度均纳入收尾；仅查询、下载缓存或完全复用不生成新版本。
2. 要求保存 ima 时先逐项保存原文／卡／参考并回读核验，record-save 记录各自状态。失败篇保留步骤；已完成其他篇可提交。只授权本地科学产物但允许共享状态时，publish 仅共享控制状态，owner_local_only 保持明确。
   指定成果保存后，用 `shared_index.py --project <config> --batch <ID> --output <索引目录> build-team` 生成共享元数据索引，保存到文献目录与索引并使用生成的index-receipt.json。publish 传 `index_manifest` 指向该目录的index-manifest.json；脚本核验目录、名字、media_id及回读SHA后，将索引纳入新版入口。索引只包含定位、状态及本次来源映射，不夹带其他篇正文／完整raw；full_records_state仍为local_not_published。
3. publish 对照 begin 的 base_head；不同则停止并保留本机与回执，不自动合并。先上传状态 MD，回读核验后再检查 head；最后新增修订名团队入口，再完整读链及状态回读。结果不确定保留 team/pending.json 与 receipt，下一次原路径重试，禁止删回执后盲目创建。
4. 成功后更新本地 effective_manifest 与 base_head，批次标 control_state_published。失败保持 pending_publish；交付明确科学产物保存状态、控制状态是否提交、失败步骤及续办路径。
5. 同时发布完整五类记录时：完整原始工作数据 export，五份 MD 保存核验后，publish 传 release_manifest。脚本再次检查五类对象及回读 SHA，将对象映射写入团队入口。不要用旧 activate／shared_index publish 绕过版本检查。只有控制状态的成员缺参考 raw 时，补回可信原记录或逐篇证据后才能完整导出，不能冒充完整记录。

新入口保留 parent 链和 artifact_release，不覆盖或删除旧 MD。更新索引时，将继承的旧非团队索引入口标为historical_entry，不能继续作为当前entry；当前索引由新版团队入口的artifact_release.index指定。遇到分叉、多根、孤立入口或 hash 错误，停止正式写入并保留候选，不按时间选支。知识库／目录或规则版本变化随提交更新共享定位与要求版本；本地运行路径始终私有。

KB或共享状态根目录本身变更时，维护者还须更新project-locator.json并重新分发skill；原定位失效时不能仅靠旧入口猜新库。

## 常规调用

已接入项目的用户仍只指定任务和范围；skill 自行 begin、处理、保存和提交受影响状态。新成员仅首次指定工作目录及成员标识，不需实施计划。续办沿用原保存目标；明确“只本地”保留未同步。安装更新 skill 不自动重做全部旧卡。
