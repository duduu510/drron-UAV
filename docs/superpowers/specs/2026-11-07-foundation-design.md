# VDE-Inspect 第一开发批次设计

用户已要求按照交接压缩包开始开发；以包中桌面方案替代此前 Web 建议。当前交付阶段是可运行的桌面基础与数据闭环，不声称完成全部 S00–S12。

## Approaches
采用交接包指定的 Python 3.14 + PySide6 Qt Widgets + SQLite。Web/Electron 与包中 no_web 要求冲突，不采用。当前目录无既有 Git 项目，使用独立 vde_inspect 子目录隔离，不触碰已有材料。

## Intent and scope
建立八个一级模块、36 个二级页面的导航，原型要求的黑侧栏、白内容区、#1467E8 主色。重点实现项目新建/切换/持久化、JSON 项目导入导出、线网与资源基础维护、任务分段、不可变方案加载、真实空态与数据来源标记。统一错误提示。求解器缺失必须显示待接入。未实施的实验功能明确标记开发中。

## Data integrity
压缩包未含 docs/contracts、samples/xian 或算法源码，且“公共数据契约”是占位符 S12。因此本批次建立 provisional-1 契约；原始 JSON 可保留扩展字段，不能将文档中的回归数值用作演示结果。Task、Sortie、ScheduleEvent 分离；时间单位分钟，SOC 0–100。无方案指标显示未求解/—。修改项目不改变已保存方案。缺少任何必要验证均不能发布；不能信任导入数据自带的 passed 标记。

## Interfaces
见 docs/contracts/foundation.md。SQLite 与方案文件只写入用户工作空间。默认使用 QStandardPaths.AppLocalDataLocation，开发支持 --workspace。备份明确输出路径并校验 SHA256。JSON 导入失败不写入，ID 重复或悬空引用报错。项目修改产生 revision 与 input_hash。方案 ID 不能覆盖。

## UI
侧栏 240px，顶部 64px，内容边距 24px，最小 1280×720。微软雅黑/Segoe UI；正文 10–11pt。用 Qt 原生控件、QSS 与 QGraphicsView 实现；不启动 HTTP、不嵌入网页、不伪造运动。数据编辑有明确保存/取消，表格支持 ID、单位和来源。地图只渲染实际坐标；无坐标显示说明。

## Verification and limits
pytest + pytest-qt：新建后重开持久化、错误导入不影响数据、引用检查、分段守恒与虚拟节点、方案不可覆盖、发布限制、八模块36页导航、项目切换和最小窗口。Qt offscreen 截图复查布局，并正常启动桌面窗口。真实西安274/1011回归、求解耗时、Windows无Python安装机验收，等待原始数据和后续发布阶段，不能宣称通过。
