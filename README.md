# 起点天榜 · 热度观察

## 个人选题与对标工作台

```bash
python -m pip install -r workbench/requirements.txt
python -m playwright install chromium
python -m workbench
```

打开 http://127.0.0.1:8765 。新建构思，检索相关作品，选择 3–5 本，补全简介并记录原文证据与个人笔记，最后填写选题卡和验证任务。支持手动加入榜单外作品、Markdown 导出和 JSON 备份导入。更改后点击“保存研究”；导出、切换项目和调用 AI 前也会保存。

顶部可切换“选题研究”和“榜单观察”。榜单观察包含原来的榜单总览、分类风向、题材洞察、周报和研究工具；打开作品详情可直接加入已有选题，或新建选题并加入。切换到榜单前会保存当前研究。启动命令会先构建本地榜单产物，再启动同一端口的工作台；不会自动重新爬取源站。采集仍按下方命令或周度工作流执行，更新数据后重启工作台即可展示。

SQLite 与详情/AI 缓存保存在被 Git 忽略的 `private/`；公开构建仍只发布白名单文件。默认服务仅监听本机。服务器部署采用 HTTPS、nginx 登录保护和独立私有存储，见 [部署说明](deploy/README.md)。每次启动或点击刷新重新读取本地快照；更新快照后不会覆盖个人笔记。

详情补全仅在点击后访问选中的起点公开作品页；验证页、缺失字段或访问失败时保留原材料并支持粘贴。完整简介不等于正文分析，未知首发时间和字数保持为空。详情缓存保留采集时间。

AI 使用现有 `OPENAI_API_KEY` 环境变量对应的 DeepSeek 接口。展开 AI 区域可查看发送材料；仅主动点击才发送当前项目、所选简介和笔记。生成内容单独展示、逐项采纳；原文引用会校验，最多一次生成与一次格式修正。未配置密钥时全部人工研究功能照常可用。

本机接口测试：`python -m pytest tests/test_workbench.py -q`。检索的真实相关性和三个个人构思的价值验收仍需使用者判断，自动测试不代表写作建议已通过作者验证。

定期采集起点公开排行榜，以静态网页展示书籍、分类和题材观察。适合个人研究与写作参考。统一侧栏工作台使用 ECharts 和原生 JavaScript 模块，没有前端打包步骤。主界面为榜单总览、分类风向、题材洞察、周度报告；作品、分类、研究工具、报告问答和数据方法通过抽屉查看。旧页面地址自动跳转对应分区。

## 安装与本地预览

使用 Python 3.12；Node.js 24 仅用于前端测试。

```bash
python -m pip install -r scraper/requirements.txt
python -m playwright install chromium
python scripts/build_site.py
python -m http.server 8080 --directory dist/site
```

访问 `http://localhost:8080`。应预览生成的 `dist/site/`，源码 `docs/` 不再维护数据副本。ECharts 6.0.0 随站点提供；Google Fonts 不可用时使用系统字体。

`scraper/requirements.lock` 固定直接和间接依赖。升级依赖时须更新锁文件并通过全部测试。

## 采集与分析

```bash
# 实际访问起点；dry-run 不写快照，但仍产生网站请求
python scraper/crawl.py --dry-run --max-per-rank 20
python scraper/crawl.py

# 默认：汇总 → 文本 → 统计 → 可选 LLM 抽取 → 统一周报
python scraper/analysis/pipeline.py

# 可独立执行，也可用 --week 重跑历史周
python scraper/analysis/pipeline.py summary --week 2026-W27
python scraper/analysis/pipeline.py text --week 2026-W27
python scraper/analysis/pipeline.py data --week 2026-W27
python scraper/analysis/pipeline.py llm --week 2026-W27
python scraper/analysis/pipeline.py report --week 2026-W27

# Agent 只在明确选择时执行
python scraper/analysis/pipeline.py agent --week 2026-W27
```

`--data-dir PATH` 可将分析隔离到其他数据目录。旧 `--text-only`、`--data-mining-only`、`--agent-only` 和 `--skip-text-mining` 分别映射到 `text`、`data`、`agent` 和 `llm`，并发出弃用提示；不能与明确阶段混用。`--skip-data-mining` 仅用于默认 `all`。

采集使用有间隔的顺序请求，最多重试三次。每页检查重复书目、重复页面和名次连续性；只有达到请求条数或确认源站结束，才能判定该榜完整。不完整采集以非零状态退出，候选数据写入 `data/partial/`，不会覆盖正式快照。工作流会保留诊断产物。

样例数据与正式数据分开，默认使用种子 42：

```bash
python scraper/generate_sample.py 3
python scraper/generate_sample.py 3 --output tests/fixtures/sample --seed 42
```

## 数据与结果约定

| 位置 | 内容 |
| --- | --- |
| `data/YYYY-WNN.json` | 原始周快照；新版本包含 `schema_version`、`source`、逐榜 `quality` 和可选 `book_id` |
| `data/index.json` | 正式周快照索引；构建时重新核验 |
| `data/analysis/YYYY-WNN/*.json` | 按目标周保存的分析，包含 `week`、`source_weeks`、`generated_at`、`method_version`、`status` |
| `data/analysis/index.json` | 各项最近有效结果及最近尝试状态；历史重跑不会把最新指针移回过去 |
| `data/analysis/YYYY-WNN/attempts/` | 失败或不可用尝试，保留原先成功结果 |
| `data/cache/` | 私有 LLM 抽取缓存，按作品、简介、模型和提示版本区分；不进入静态产物 |
| `dist/site/` | VPS、Cloudflare 共用的发布产物及 SHA-256 文件清单 |

作品去重兼容 `(title, author)`。旧 W20–W21 为已知样例，明确排除；不再用记录数量识别样例。旧采集器每榜最多访问九页，因此历史完整榜按连续的 Top 180 核验。低于这个深度视为不完整；新快照使用采集时记录的结束原因与请求数量。

历史原始文件保留。旧书籍链接被分类地址覆盖时，读取层将其规范化为无链接文本，不根据书名猜测书籍 ID。原有无来源周的累计分析文件保留供审计，新页面不将它们当作本周结果。

## 指标如何解释

- **热度**：对每本书累计 `weight / sqrt(rank)`；月票 1.0、畅销 0.95、阅读指数 0.85、推荐 0.8、收藏 0.75、签约新书 0.7、书友 0.6、更新 0.5。权重为启发式设定。
- **周间变化**：只比较相邻 ISO 周共同完整的榜单，并统一截取深度。页面列出实际参与比较的榜单与 Top N。无可比数据时不输出动量。
- **新书活跃观察分 EFS**：分类去重书目中的新书榜占比 × 0.45，加上 `(1−CR3) × 0.30` 和归一化最佳名次 × 0.25。CR3 是该分类前三本书的热度占比。新书榜或需求榜不完整时，相关观察分不可用。
- **综合观察分 MGS**：需求榜归一化名次 × 0.35、竞争空间 × 0.25、EFS × 0.25、同口径增长信号 × 0.15。缺乏可比动量或必要榜单时不输出。
- **题材关键词与标签**：仅使用目标周去重书籍的简介。全局与分类 TF-IDF 共用拟合词表；分类至少需要十份有效简介。
- **条件共现矩阵**：直接统计所有两榜组合；支持度至少 5%、置信度至少 50%。这与原先 `max_len=2` 的频繁项集口径等价。矩阵支持环与双向关系，不表示读者流动或因果。
- **聚类与异常**：聚类只使用完整榜单，展示全部样本点；异常只在相邻周、同榜同分类的重叠书目中计算，至少五条且标准差不低于 0.5。
- **实验预测**：完整且连续的周序列按同一深度拟合 Holt；训练至少四周，对未来一、二周进行至少四次滚动回测。只有 MAE 严格优于“保持上周值”才展示点预测；缺失周保留缺口，不输出未经校准的 95% 区间。

这些指标仅描述已采集榜单样本，无法测量全站供需、平台签约偏好或新人成功概率。分类示例和写作提示标为通用建议。

## 可选 AI

设置 `OPENAI_API_KEY` 后使用兼容接口的 DeepSeek `deepseek-chat`。未配置时，构建仍生成可复核的确定性周报。构建命令本身从不调用付费模型。

LLM 按八榜轮流选择头部书籍，去重后最多 120 本，每批 30 本；严格校验作品身份、字段类型和枚举。页面展示实际榜单及分类覆盖，该样本不是总体随机抽样。

统一客户端请求超时 45 秒，SDK 最多重试一次；抽取格式最多尝试三次。每个阶段最多 16 次调用、保守文本与输出预算 100000；Agent 最多八轮加一次最终报告调用。失败记录在清单中，既有有效结果保留并显示所属周。FAQ 只匹配预生成周报，不实时调用模型。

## 验证

```bash
python -m pytest tests/test_collection.py tests/test_finalize.py tests/test_analysis.py tests/test_build.py -q
node --test tests/frontend.test.js
python scripts/build_site.py
python -m pytest tests/test_browser.py -q
```

浏览器测试阻断外网，覆盖四页、缺失分析文件、持续切榜、无效历史链接、报告 HTML 转义和 375px 布局。CI 对 PR 执行同样的构建与测试。

## 发布与排查

周度工作流顺序执行验证采集、确定性分析、可选 AI 和产物检查。默认不运行 Agent；手动触发时可选 `run_agent`。同一数据工作流不并发运行，阶段状态写入 Actions 摘要，失败采集与分析尝试上传为诊断产物。AI 缓存通过 Actions Cache 跨运行复用。

- **VPS**：已有 `VPS_HOST`、`VPS_USERNAME`、`VPS_SSH_PRIVATE_KEY` secrets 时，发布经过验证的 `dist/site/`；未配置主机时跳过 VPS 步骤。
- **Cloudflare**：构建命令设为 `pip install -r scraper/requirements.txt && python scripts/build_site.py`，静态目录使用 `dist/site/`。`wrangler.jsonc` 指向同一目录。Cloudflare 构建需使用 Python 3.12 环境。
- **GitHub Pages 或其他静态主机**：上传 `dist/site/` 全部内容，不能继续直接发布 `docs/`。

如果页面提示本周不可用，先检查 `analysis/index.json` 中的 `attempt_status` 与来源周，再查看对应 `attempts/` 及 Actions 日志。采集不完整时先处理缺榜、页面结构或源站限制，不将重试失败解释成市场变化。

可回滚到先前通过验证的完整静态产物。提交分析改动前应更新全部页面及构建脚本；旧静态路径的迁移已在发布入口完成。

## 参考与许可证

参考了 [TrendRadar](https://github.com/sansan0/TrendRadar) 的职责边界与失败来源记录、[NewsNow](https://github.com/newsnext/newsnow) 的来源状态接口、[DailyHotApi](https://github.com/imsyy/DailyHotApi) 的更新时间与缓存来源表达。相关实现根据本项目需求独立编写。

本地 ECharts 分发文件保留在 `docs/vendor/`，随附 Apache 2.0 LICENSE 与 NOTICE。

## 采集恢复与诊断

主采集由 GitHub Actions 每周一北京时间 08:00 调度，限时 25 分钟。网络、限流或验证失败的榜单通过 SSH 在阿里云独立环境补采，补采步骤限时 20 分钟；结构错误不会盲目重试。两端使用同一份采集代码，只选择整榜通过验证的结果。

候选采集：`python scraper/crawl.py --week 2026-W44 --ranks signnewbook --output data/partial/manual/candidate.json`。合并发布：`python scripts/finalize_collection.py --primary data/partial/manual/github.json --fallback data/partial/manual/aliyun.json`。

至少一个榜完整便发布，缺失榜不进入分析；全部失败或同周覆盖退步时保留原快照。部分发布后 Actions 最终状态仍标失败，诊断产物保留 14 天。失败 HTML、截图不进入公开网站。签约新书榜改用官方 signNewBkAll，口径版本与旧 signnewbook 隔离，不补造历史周。阿里云安装需预先具备 python3.12-venv。

恢复设计参考 [novel-tracker](https://github.com/dylan-byte-max/novel-tracker/blob/main/scrapers/qidian.js)，重试复用 [Tenacity](https://github.com/jd/tenacity)。未照搬移动端不同榜单的替代映射。
