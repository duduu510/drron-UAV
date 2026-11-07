# 首批开发验证记录

日期：2026-11-07（Asia/Shanghai）。此报告只覆盖0.1.0桌面基础开发批次，不能替代完整系统或现场安全验收。

## 验证结果

- 完整测试：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q`，213 passed。
- 静态编译：`.venv/Scripts/python.exe -m compileall -q src`，exit 0。
- 依赖一致性：`.venv/Scripts/python.exe -m pip check`，No broken requirements found。
- Windows native Qt平台真实启动、工作空间初始化和截图：exit 0。
- 1440×900、1280×720驾驶舱截图；站点维护、任务页、历史图表页截图已人工检查。
- 单色线网主色#1467E8通过dataviz调色校验；历史图片原样保留，不重绘改动原图。

## 行为范围

覆盖项目存储、失败导入回滚、引用检查、乐观版本与并发写入、不可变方案、备份哈希、导出存储保护、非法JSON/ZIP和数字、任务分段及方向分组、真实数据转换、源标记、事件字段兼容与确定性seek、错误来源/数值的方案拒绝、发布失败关闭、八模块36页导航与部分数据维护、历史数据表格及原图加载。

修复了独立review指出的三项问题：导出路径可覆盖数据库、方案导出丢失包头、events/schedule_events不一致造成无法回放。均增加失败后通过的回归测试。

## 数据实测

cn-xian：13线路、248站、275区间、287站线记录；估算距离合计419.215km。0.5km规则：977物理分段、1954方向候选。
历史图表：19张，7line、7bar、2stacked、2scatter、1heatmap；七项费用合计20491.14770940965元。

## 未验证与后续阶段

没有真实求解器/完整历史方案，所以未验证真实求解、历史274/1011方案复现、全运营约束可行性、联动轨迹甘特SOC或无需Python的Windows安装包。当前验证器始终不能授予发布。不能用测试通过数量表示这些业务已经完成。

## 增补：新仿真基线开发与实跑

用户选择当前线网建立可复现新基线，已实现greedy-station-return/0.1、冻结实验副本、Qt独立进程/取消/实际进度、输入锁定和独立简化模型检查。独立审查修复了隐式等待漏计成本、运行中输入编辑导致结果丢失以及后台错误模态弹窗。

在Windows native平台执行 `scripts/native_smoke.py`，真实经过主窗口、配置页、QProcess、结果持久化；原始项目哈希保持不变，运行中P03编辑禁用，运行结束解锁。结果39/977物理任务，部分成本3307.1151666666665元；基线检查仅完成性失败，其余声明的模型检查通过。原运营可行性不因此获得通过。

基线原始请求/结果/JSONL/状态文件保存在build/baseline-demo。1440×900和1280×720真实结果页面截图已检查。测试最终数量见末尾最终验证行。

## 最终验证

- 全量 pytest：282 passed in11.60s，exit0。
- compileall：exit0；pipcheck：No broken requirements found。
- 同一西安数据、配置与seed7，两次独立QProcess实跑的coverage、五项成本、返场时刻、schedule_events与sorties逐项相同；run_id不同。证据见examples/baseline/reproducibility.json。
- 已复查独立审查的成本漏计、运行中编辑、后台模态错误三项；前两项review复核通过，最后一项notify调用及回归测试通过。
- 最终完整代码尚不含原GRASP、实测道路/能源接入或无Python安装包验收；当前交付为可运行桌面开发版和可复现研究基线。
