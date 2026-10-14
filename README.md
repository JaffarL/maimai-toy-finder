# 麦麦寻玩

**看到喜欢的麦当劳玩具，发张图，找门店。**

[下载安装包](https://github.com/JaffarL/maimai-toy-finder/releases) · [查看源码](https://github.com/JaffarL/maimai-toy-finder) · [参赛信息](docs/参赛信息.md)

麦麦寻玩是装在 AI 客户端里的技能插件。上传玩具照片、包装图或社交平台截图，告诉它城市或商圈，客户端识别玩具系列，插件通过麦当劳官方 MCP 查询当地门店与套餐，给出可前往的门店名称、地址和查询时间。

适合想找同款玩具的消费者、开心乐园餐玩具爱好者，以及安排亲子出行的家庭。匹配单位是**玩具系列**；结果表示查询时段内门店菜单提供该系列，具体角色由门店实际供应决定。

这是由参赛者独立开发的麦当劳程序员节创意开发大赛参赛作品。使用提示与参赛声明见 [CONTEST_DECLARATION.md](CONTEST_DECLARATION.md)。

## 使用效果

在装好技能的 AI 客户端中上传图片，输入：

> 用麦麦寻玩找一下这个玩具，南京新街口，今天中午12点去。

客户端会完成：图片识别系列 → 查找商圈门店 → 读取套餐玩具选项 → 返回门店表格。

结果包含系列名称、门店与地址、对应套餐及菜单标价、查询时间和检查范围。图鉴没有收录的新系列，会先从官方接口发现当地系列与参考图，再由客户端进行图片比对。

## 安装

运行需要 **Python 3.10 或更新版本**，运行代码全部使用标准库。AI 客户端需要同时支持图片输入、加载本地技能与执行本地 Python 脚本。仅能看图的聊天窗口，还需要补齐技能或脚本执行能力。模型和图片理解由所用客户端提供，插件读取其识别结果。

### 1. 准备技能

从[发布页面](https://github.com/JaffarL/maimai-toy-finder/releases)下载技能 ZIP，解压出 `maimai-toy-finder` 文件夹；也可克隆本仓库。进入该目录后，Codex 本地安装：

```powershell
python scripts/install_skill.py
```

安装器将技能复制到 `CODEX_HOME/skills/maimai-toy-finder`，未设置 `CODEX_HOME` 时使用用户目录下的 `.codex/skills`。已有同名目录时提示用户处理，保护原安装。安装后开启新会话加载技能。

其他支持本地技能的客户端：将整个文件夹导入其技能管理界面，并启用本地 Python 执行。各客户端的导入入口与模型额度以客户端自身说明为准。

### 2. 配置麦当劳接口令牌

按[麦当劳官方 MCP 接入说明](https://github.com/M-China/mcd-mcp-server)获取自己的令牌，并设置环境变量 `MCD_MCP_TOKEN`。PowerShell 可通过隐藏输入设置当前终端的令牌：

```powershell
$麦麦令牌 = Read-Host '请输入麦当劳 MCP 令牌' -AsSecureString
$env:MCD_MCP_TOKEN = [System.Net.NetworkCredential]::new('', $麦麦令牌).Password
Remove-Variable 麦麦令牌
python scripts/find_stores.py --doctor
```

从该终端新启动的客户端可继承变量；已经打开的客户端不会自动继承。也可在 Windows 用户环境变量界面配置后重新打开客户端。真实令牌保留在个人运行环境中。

`mcp-config.example.json` 是比赛要求的脱敏 MCP 配置示例。本项目脚本直接读取环境变量，无需加载该 JSON；其他客户端的变量展开语法需按其文档适配。

### 3. 发图使用

上传图片并说出城市，例如：

> 用麦麦寻玩，帮我看看这个玩具在南京哪家店能买到。

> 看这张截图，帮我找上海徐家汇附近提供同系列玩具的门店。

文字名称也能查询：

> 麦麦寻玩，找南京新街口的海绵宝宝×航海王系列，今天12点到店。

## 命令行验证

以下命令在项目根目录运行；图片识别由 AI 客户端执行，命令行负责验证系列到门店的查询。

```powershell
python scripts/find_stores.py --list-series
python scripts/find_stores.py --series spongebob-onepiece --city 南京市 --area 新街口 --max-stores 5
python scripts/find_stores.py --discover --city 南京市 --area 新街口 --max-stores 5 --format json
```

指定预计到店时间时，加 `--at "2026-10-14 12:00"`，请改为实际日期时间。默认查询当前菜单，早餐与午餐可能展示不同套餐。

默认检查最多 10 家，`--max-stores` 可设为 1～30。指定 `--area` 时按该范围查店；未指定时使用城市商圈表逐步查找，按门店编码去重。结果会说明发现与检查数量，便于判断覆盖范围。

## 实现与验证

- `SKILL.md`：图片识别、动态系列发现、查店及回答流程。
- `scripts/mcd_client.py`：官方 MCP 的只读客户端，支持 JSON/SSE、会话、有限重试和请求限速。
- `scripts/find_stores.py`：门店去重、儿童餐与亲子餐玩具选项提取、系列匹配与结果汇总。
- `references/series.json`：可核对来源的系列图鉴；当前首个种子是海绵宝宝×航海王系列。
- [MCP_INTEGRATION.md](MCP_INTEGRATION.md)：工具、参数、调用链和接口证据。
- [验证记录](docs/验证记录.md)：实际测试结果与验证范围。

自动测试与本地打包：

```powershell
python -m unittest discover -s tests -v
python scripts/build_release.py
```

发布包通过文件清单选取源码、技能与文档，生成到 `dist`。图鉴以链接引用麦当劳官方参考图片；代码许可见 [LICENSE](LICENSE)，图片、商标和角色权利归各权利人。

## 参赛信息

按 [2026 年活动规则](https://github.com/M-China/mcd-developer-innovation-challenge/blob/main/activityGuidelines.md)准备，作品形式为技能插件，真实调用麦当劳 MCP。项目已公开并提交[报名 Issue #657](https://github.com/M-China/mcd-developer-innovation-challenge/issues/657)。报名截止为 **2026 年 10 月 25 日 23:59，北京时间**；报名校验结果以官方回复为准。

当前使用本地技能开发流程。WorkBuddy 专项奖励需要真实使用记录，后续采用 WorkBuddy 开发或验证时再据实补充 `workbuddy.md`。
