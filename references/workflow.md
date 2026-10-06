# 执行入口

团队项目先读 team-workflow.md，通过 ima_client.py 的 action=team 完成 inspect/init/refresh/begin，取得写入资格后执行以下本地脚本。收尾必须 team publish；仅本地／不同步的明确要求保留 pending_publish。旧 activate 和 shared_index publish 仅适用于尚未启用团队协议的历史项目，不可在 team_sync.enabled 的项目绕过新版入口。

使用真实Python，商店占位不可用时读取Codex bundled dependencies；配置runtime是本机线索。PDF用pypdf，图表回查pdfplumber；ima stdlib，无SDK。

```text
<python> <skill>/scripts/library.py --project <config> plan --batch <ID> --mode reconstruct --scope S001–S010
<python> <skill>/scripts/extract_pdf.py --pdf <PDF> --id S001 --output <input.json> [--legacy <旧MD>]
<python> <skill>/scripts/library.py --project <config> register --input <核验的新成果metadata.json>
<python> <skill>/scripts/library.py --project <config> commit --batch <ID> --input <审核paper.json>
<python> <skill>/scripts/library.py --project <config> validate
<python> <skill>/scripts/library.py --project <config> plan --batch <ID> --resume
<python> <skill>/scripts/library.py --project <config> export --batch <ID>
<python> <skill>/scripts/ima_client.py --operation <无凭据的JSON>
<python> <skill>/scripts/library.py --project <config> record-save --id S001 --kind card --receipt <JSON>
<python> <skill>/scripts/library.py --project <config> refresh-card-links --id S001
<python> <skill>/scripts/shared_index.py --project <config> --batch <ID> --output <索引目录> build-team
<python> <skill>/scripts/library.py --project <config> activate --manifest <已核验共享manifest.json>
```

--help和input-example.json给结构。plan持久化范围／逐篇待办，--dry-run只读；--resume不扩scope。mode为reconstruct/references-only/original-only/new。commit按模式要求卡／参考，refs-only保留有效卡。

用户要求保存ima时plan加 `--save-target ima`，仅本地加local；批次保存目标会持久化，resume沿用，不能把保存未执行当本地已生成就算完。plan分别列出verify_original/save_original/save_card/save_reference；有原文media_id先回读核验，不重传。

原文核验操作：`{"action":"verify","kb":"...","folder":"...","media_id":"...","path":"...pdf","receipt":"...json"}`；检查精确目录／文件名／hash后生成reused_verified回执，再record-save --kind original。没有上传新对象。

用户明确重做或修正后可 `commit --force`；相同正文仅刷新受影响的入口。模板版本变化会使对应产物失效，分类版本只使卡片失效。重复提交完整有效输入默认复用。

agent读原文／旧MD，核实版本题录、全文与图表，填metadata、七段card_sections、classification(code/path/reason/evidence)、references(number或null、order、raw、pages、type)。映射S/E须entity_id及identity_evidence；DOI已核验设doi_verified=true，不匹配留空，不猜DOI。review声明及参考数量必须与检查一致。

脚本UTF8、原子写与登记锁。锁残留先核实进程，不盲删；失败逐篇登记并继续独立项，不能把stdout有输出当成功。same input与有效hash复用，规则变化使关联步骤失效。

上传JSON {"action":"upload","kb":"...","folder":"...","path":"...md","receipt":"...json"}。version/list/download/inventory/ensure-folder也支持。凭据进程环境IMA_OPENAPI_CLIENTID/IMA_OPENAPI_APIKEY，或--session首行stdin内存后连续操作；明文凭据通过隐藏pipe，不用PTY、不打印或写首行。

请求的科学产物使用可跨机器定位的文件名与media_id；本机绝对路径只留JSON与恢复备份。有原文先核验复用。先保存参考并record-save，再refresh-card-links保留已审核正文、刷新第一节的真实参考media_id，最后保存卡片并record-save。刷新后hash变化只保存最终卡片。export五类MD与graph.json供本地复现；远端发布范围另按授权确定。

上述 activate 是旧项目路径。团队项目：每次变更自动标记 pending_publish；先 team publish 共享可恢复的控制状态。若五类完整MD也已核验，传 release_manifest 由 team publish 纳入同一入口。初始化成员不持有未共享 raw／卡片正文，validate 的控制记录警示不表示正文已核验；缺 raw 的完整 export 会拒绝，而控制状态仍可提交。scope 始终明确，不用重建空台账补编号。

团队项目常规单篇／批量保存：用build-team生成元数据索引，上传到文献目录与索引并核验，team publish传index_manifest纳入同一入口；不上传未指定篇的完整raw。五类完整记录仍仅本地，除非用户明确要求发布该范围。完整记录发布使用release_manifest，不能因索引更新自动扩大范围。

旧未启用团队协议的索引项目才使用shared_index.py的build/build-entry/publish；新版团队入口统一按team-workflow.md的parent链发布，不使用旧命令旁路。
