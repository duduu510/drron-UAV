# VDE-Inspect 0.1.0

Windows 原生车机能巡检桌面软件的首批开发版本。Python 3.14、PySide6 Qt Widgets、SQLite；没有 Web 服务。

## 启动

原开发电脑已配置 `.venv`，可以直接双击 `启动软件.bat`。从 GitHub 克隆后，先按下面的步骤安装依赖。首次启动会把随包保存的真实西安线网导入用户工作空间，并加载历史实验图表；在「智能调度」确认研究假设后，可运行新的仿真基线。

### 从 GitHub 安装运行

在 Windows 安装 Python 3.14 后，打开 PowerShell：

```powershell
git clone https://github.com/duduu510/drron-UAV.git
cd drron-UAV
python -m venv .venv
& '.venv/Scripts/python.exe' -m pip install -r requirements.lock
$env:PYTHONPATH='src'
& '.venv/Scripts/python.exe' -m vde_inspect.app
```

之后可双击 `启动软件.bat`。仓库不包含虚拟环境、缓存或本机工作空间数据库。

命令行：

```powershell
$env:PYTHONPATH='src'
& '.venv/Scripts/python.exe' -m vde_inspect.app
```

默认数据目录由 Qt `QStandardPaths.AppLocalDataLocation` 生成，界面底部显示准确位置，不写入安装目录。指定独立空间：`--workspace "D:/VDE-Inspect/workspace"`。同一工作空间只允许一个实例打开。

其他电脑开发安装：Python 3.13 或更新版本，`python -m venv .venv`，`.venv/Scripts/python -m pip install -r requirements.lock`。这是源码开发交付，尚未制作无需 Python 的正式安装包。

## 已实现

- 八个一级模块与36项二级页面导航；未开发业务明确标记，不代表36页全部功能完成。
- 新建/切换/保存项目，线路、站点、区间、车场、设备型号/实例、电池及参数的基础维护。
- 区间任务分段预览、保存和撤销；任务计划快照；JSON 项目导入导出。
- 真实坐标的 Qt 线网拓扑；无结果时 KPI 使用“—”。
- SQLite 事务、乐观版本控制、输入 SHA256、不可变方案、完整方案导出、存储目录防覆盖和可校验备份。
- 原算法适配器仍标记待接入；已新增真实计算的仿真贪婪基线、QProcess、取消、真实进度、冻结输入和独立基线检查。
- 离线方案格式校验、事件级确定性回放；运营完整校验未完成时禁止发布。
- 19张历史实验原图及逐点数据浏览，保留来源、SHA256和缺失观察。

## 数据口径

`samples/xian/cn-xian.zip` 是用户提供的原始线网：13条线路、248站、275区间、287站线记录。原包距离多数是 haversine 估算，客运行程时间不能当无人车地面转运时间。没有合法起降/接应许可，因此默认不允许服务，必须另行配置。

按当前最大0.5km分段规则得到977个物理任务、1954个方向候选（每个物理任务按允许方向完成一次），与交接材料274区间/1011任务不是同一口径。程序不删改原始数据以凑数。导入后任务默认空，点击分段预览后才创建。

`samples/xian/historical-charts.zip` 是用户提供的运行图表，含19张PNG、19张SVG和 `figure_data.json`。标记“历史实验数据（未独立复核）”；不冒充当前项目、实时求解或完整方案。

两份额外 Excel 用于人工交叉核对。成本表为30800、25572.71、20491.15元。完成率表含241个时间点和4区序列；全网列空白，全网曲线由历史JSON提供，不能简单平均四区比例。

## 当前缺少

原 GRASP 求解器、原实验输入快照、逐任务指派与逐车逐机事件、车场/责任区/合法服务站映射、地面转运时间/距离矩阵、能源参数及完整成本口径。只有汇总图无法恢复这些记录。

通用运营验证仍保持 `validation_passed=false`、`publishable=false`，不能对现场业务可行性背书。新基线的独立检查只针对声明的简化仿真模型；未完成覆盖不能通过。原GRASP、完整运营验证、联动轨迹/甘特/能源、实验批量运行及S12发行版留待后续。

## 测试

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& '.venv/Scripts/python.exe' -m pytest -q
```

详见 `docs/test-report.md`、`docs/data-assessment.md` 和 `docs/contracts/foundation.md`。文件规划在上级目录 `.planning/2026-11-07-vde-inspect-foundation/`；交接原件保存在上级 `handoff/`，未修改原件。

## 新基线实验（用户已选择当前数据口径）

打开「智能调度」：选择实际站点作仿真基地，设置团队数、种子、窗口、速度/能源和五项成本，勾选明确的实验服务假设，再点击运行。每队一车一机、无人机同站往返，地面道路用轨道最短距离代理。所有假设随运行冻结；原线网不变。当前只是一种保守研究基线，不是原GRASP，也不是运营调度建议。

已经保存的本机试跑可双击 `查看基线试跑.bat` 打开。从仓库克隆后，先运行下方复现命令生成本机记录；也可以从 `examples/baseline/` 导入冻结项目和结果。当前样例4队/240min/seed7/钟楼起点：39/977物理任务、11/275原区间完成，部分成本3307.1151666666665元，最晚返场239.76966666666667min；未完成，不提供完整方案成本，不可与历史完整方案比成本。全部输入、结果和日志在 `build/baseline-demo/runs/`。

复现实跑（实际启动独立Python进程）：

```powershell
$env:PYTHONPATH='src'
& '.venv/Scripts/python.exe' scripts/run_baseline_sample.py --workspace build/baseline-demo --teams 4 --window 240 --seed 7
```

新生成的运行ID/方案ID不同，声明输入与种子相同时调度数值和事件行为可复现。汇总在 `build/baseline-demo/latest-summary.json`，完整方案在该摘要指向的运行目录 `result.json`，不能把摘要当成完整方案导入。
