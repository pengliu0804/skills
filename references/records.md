# schema 1.0.0

state/library.json是科学产物处理输入，五类记录同源导出。团队控制状态由已核验 ima 状态包及连续入口链确定；本机保留正文／raw 和审阅证据。新本地状态未发布是候选，控制状态同步不表示科学产物或完整五类记录已经共享。

- literature：稳定ID、roles(group/reference/citing)、题名／作者／日期／来源／类型、DOI和核验状态、版本与adopted_version、原文摘要／作者关键词及出处、整理标签、分类、原文／卡／参考对象及步骤状态。legacy保留旧对象与待迁移。作品、version_id、file_sha256、media_id分开。中科院大类／年份／来源，JCR各学科／年份／来源分别记录；引用按库／日期独立数组。
- occurrences：S@version#ref-N或order-N，来源／版本、原编号(null表示无)／顺序、raw题录、实际PDF页数组、作品ID／类型、身份状态／证据、日期。来源出现已核验与端点未匹配可同时成立。
- relations：ID、from/to及版本、类型、陈述、evidence(页码、出现ID、URL、来源、日期)、citation_status、identity_status、use/use_status、有效／历史。方向施引→被引；未读用途为unreviewed。

`to_version`用于定位被引作品当前登记采用版，不意味着原引用指定了该文件修订。原参考通常只识别作品／出版版；确有版次证据另记录target_version_evidence，没有证据必须明确“具体修订版本未指定”，不能据登记版推定版本级施引成立。
- searches：种子／版本、库、query_at／条件、收录状态、分页完成、hits、候选、失败／重试原因。not_run的时间、分页和hits为null，不能写0。
- batches：ID、mode/scope、规则版本、逐篇步骤、输入指纹／产物hash／替代、local_verified/pending/failed/not_requested、远端回执、生效状态和下一步。

S延续最大编号不补空号；分配前查登记、实时全库与PDFhash。DOI须核对题录／版本，title相似仅候选。E在登记锁下分配，参考／施引多角色复用实体。完全相同raw可暂共享同一未匹配E；不同格式只有已核验DOI或执行者完整身份依据才共享。未匹配E是可追踪占位身份，不表示外部全文已读。

候选题名／来源作者字符串可从raw解析，但明确source_parser_candidate，不能自动提升identity。未解析题名为null，display_label展示原引文；年份有歧义保留候选，不将访问年当发表年。原raw完整保留，外部核对后才确认为正式题录。

映射S输入entity_id和identity_evidence，须对照被引题名／作者／年份与S原文首页，不能仅旧卡片标题。预印本与正式版不偷换，S015基线采用Research Square v1，不得用latest.pdf换版。

输入指纹包括原文hash、版本及各规则版本。原文变化使内容／参考／出处／边失效；分类变化影响卡和索引；参考变更影响映射／边／图。默认图仅当前identity/citation核验边，自引保留，候选另导出。
