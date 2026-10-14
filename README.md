# 麦麦寻玩

**看到喜欢的麦当劳玩具，发张图，找门店。**

[下载安装包](https://github.com/JaffarL/maimai-toy-finder/releases/latest) · [查看源码](https://github.com/JaffarL/maimai-toy-finder)

麦麦寻玩是装在 AI 客户端里的技能插件。上传玩具照片、包装图或社交平台截图，告诉它城市或商圈，客户端识别玩具系列，插件通过麦当劳官方 MCP 查询当地门店与套餐，给出可前往的门店名称、地址和查询时间。

适合想找同款玩具的消费者、开心乐园餐玩具爱好者，以及安排亲子出行的家庭。按**玩具系列**匹配门店，列出该系列对应的套餐和菜单时段。

## 使用效果

在装好技能的 AI 客户端中上传图片，输入：

> 用麦麦寻玩找一下这个玩具，南京新街口，今天中午12点去。

客户端会完成：图片识别系列 → 查找商圈门店 → 读取套餐玩具选项 → 返回门店表格。

结果包含系列名称、门店与地址、对应套餐及菜单标价、查询时间和检查范围。图鉴没有收录的新系列，会先从官方接口发现当地系列与参考图，再由客户端进行图片比对。

## 安装

准备 **Python 3.10 或更新版本**，以及支持图片输入、本地技能和 Python 脚本执行的 AI 客户端。客户端负责识图，插件负责查店；查询脚本全部使用 Python 标准库。

### 1. 准备技能

从[发布页面](https://github.com/JaffarL/maimai-toy-finder/releases)下载技能 ZIP，解压出 `maimai-toy-finder` 文件夹；也可克隆本仓库。进入该目录后，Codex 本地安装：

```powershell
python scripts/install_skill.py
```

默认安装到用户目录下的 `.codex/skills/maimai-toy-finder`；设置了 `CODEX_HOME` 时使用该目录下的 `skills`。安装后开启新会话即可使用。更新已有版本时，先备份并移走旧技能目录，再运行安装器。

其他支持本地技能的客户端：将整个文件夹导入技能管理界面，并启用本地 Python 执行。

### 2. 配置麦当劳接口令牌

按[麦当劳官方 MCP 接入说明](https://github.com/M-China/mcd-mcp-server)获取自己的令牌，并设置环境变量 `MCD_MCP_TOKEN`。PowerShell 可通过隐藏输入设置当前终端的令牌：

```powershell
$麦麦令牌 = Read-Host '请输入麦当劳 MCP 令牌' -AsSecureString
$env:MCD_MCP_TOKEN = [System.Net.NetworkCredential]::new('', $麦麦令牌).Password
Remove-Variable 麦麦令牌
python scripts/find_stores.py --doctor
```

设置后从该终端启动客户端，即可继承令牌。也可在 Windows 用户环境变量界面配置，再重新打开客户端。

脚本通过环境变量 `MCD_MCP_TOKEN` 连接麦当劳 MCP；`mcp-config.example.json` 提供客户端配置参考。

### 3. 发图使用

上传图片并说出城市，例如：

> 用麦麦寻玩，帮我看看这个玩具在南京哪家店能买到。

> 看这张截图，帮我找上海徐家汇附近提供同系列玩具的门店。

文字名称也能查询：

> 麦麦寻玩，找南京新街口的海绵宝宝×航海王系列，今天12点到店。

## 命令行验证

在项目根目录运行以下命令，按系列查店或发现当地玩具系列：

```powershell
python scripts/find_stores.py --list-series
python scripts/find_stores.py --series spongebob-onepiece --city 南京市 --area 新街口 --max-stores 5
python scripts/find_stores.py --discover --city 南京市 --area 新街口 --max-stores 5 --format json
```

默认查询当前菜单。指定到店时间时，加 `--at "2026-10-14 12:00"`，将日期时间改为实际计划。

默认检查 10 家门店，`--max-stores` 可设为 1～30。用 `--area` 指定商圈，或按城市预设商圈查询；结果展示查询范围和匹配数量。

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

安装包生成到 `dist`。代码采用 [MIT 许可](LICENSE)。
