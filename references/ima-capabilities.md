# ima能力

启动 POST https://ima.qq.com/openapi/check_skill_update，body {"version":"1.1.10"}；官方包 https://app-dl.ima.qq.com/skills/ima-skills-1.1.10.zip，更新时读当前文档。版本和具体实测日期在项目evidence，不以skill替代实时状态。

HTTPS同源ima.qq.com，headers ima-openapi-clientid/apikey，仅内存；scripts/ima_client.py负责凭据／URL错误脱敏。

| 能力 | 约束 |
| --- | --- |
| wiki/v1/get_knowledge_list | knowledge_base_id、可选folder_id、cursor、limit≤50；检查is_end/next_cursor；99folder、1PDF、7MD、11note |
| get_knowledge_base | 当前body ids:[KB] |
| get_media_info | media_id→url_info.url/headers只本次使用，不存signedURL；无URL不等于不存在 |
| 文件上传 | 嵌套check_repeated_names→create_media(file_ext无点)→临时COS→add_knowledge(title含扩展名、folder明确)→list和SHA回读 |
| create_folder | 历史及本项目实测，但官方公开文件文档未列；KB/name/可选parent，之后list核验；失败不猜新endpoint |
| 内置note | 官方note/v1/get_doc_content读、append_doc按权限追加；非覆盖MD，本项目未实施该分支，不能称已测或完全不可读 |
| 覆盖／删除／移动MD | 未找到足以实施的公开接口，用新名+替代，不假定覆盖或历史可排除检索 |

PDF≤200MB、MD≤10MB，执行时核对最新限制。空文件／signature／UTF8先查；未测类型不自行上传。文件回读和ima平台检索解析分开，本地解析不证明平台解析。

只读查询的传输超时最多重试一次；已分配COS键的幂等PUT可在临时凭据仍处于同一内存会话时，对完全相同键和字节重试一次，不新增media_id。新建、add_knowledge 不盲重试，先查回执与远端。HTTP错误不重试。会话结束丢失临时凭据的created回执先核实保留对象，不能删回执重新分配；明确记录无知识库对象及失败的孤立保留后，才使用新修订名。首次团队发布可使用当前一小时内、KB匹配且完整分页的 inventory 作为初始目录核验；入口与提交对象仍现场核验。历史目录记录不满足这个条件。
