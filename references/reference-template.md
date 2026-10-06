# 参考清单 1.0.0

头部：来源S、采用版本、原文文件名／media_id／PDFhash、模板／schema、日期、总数、旧数据复用依据、参考区范围、文献目录与关系入口。ima版使用共享对象定位，本机缓存及备份绝对路径只留本地记录。

逐条：稳定出现ID、印刷编号或无编号声明、order、原始题录、逐条PDF页、作品ID、类型、DOI／替代标识、身份状态与证据。页码从1起，不把全参考区范围填给每条。书、网页、设备、数据全部保留；缺陷保留并记问题，不猜补。

extract_pdf.py --legacy只在旧头部SHA匹配时复用raw／编号，仍对当前PDF定位各页／数量／首尾，版本由agent核实；旧MD保留恢复备份。缺清单从来源原文提取，无需下载被引全文。

编号制查1..N连续；作者年份制number=null，order明示整理顺序。自动提取是候选，检查双栏／跨页、首尾、作者简介和版权页脚。正文引用不是参考条目；低质量行回看图像。

commit要求references_checked及reference_count与条目数一致。结构转换完成不等于外部DOI全匹配；source_reference_verified与identity unresolved分别保存。
