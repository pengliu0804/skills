# 可复用脚本

- library.py：稳定S/E、五类记录、同源卡片／清单、批次／续办／hash核验、导出与保存登记。
- refresh-card-links子命令：参考保存后保留审核正文、刷新卡内参考对象定位，避免重传中间卡片。
- shared_index.py build-team：按当前批次生成可跨机器使用的元数据索引，配合team publish的index_manifest提交；不上传其他篇完整raw。
- extract_pdf.py：全文页与参考候选、旧raw复用及逐条页定位（仍须agent审核）。
- ima_client.py：完整目录、下载、目录核验、PDF／MD上传与回读SHA、无凭据receipt；内存或进程环境读取凭据。
- ima_upload.py：兼容入口，参数同ima_client.py，旧位置参数已取消。
- team_sync.py：团队初始化、控制状态恢复、按需下载、版本／单一写入者检查、追加修订发布与明确交接；由 ima_client.py 的 action=team 调用。
- test_team_sync.py：隔离验证跨路径接入、身份复用、版本／交接／分叉和不确定发布恢复，无真实团队交接。
- input-example.json：待审核输入结构，不是已完成模板。

历史硬编码下载／Crossref脚本及冲突规则已从活动skill移出，恢复副本见项目backups，不作为当前流程。详见references/workflow.md。
