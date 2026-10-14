# 麦当劳 MCP 接入说明

## 业务价值

用户用照片表达想找的玩具，宿主 AI 根据照片和官方图鉴识别系列。麦麦寻玩将系列转换成真实门店菜单中的玩具名称/编码，输出相应门店、地址和套餐信息，让用户据此选择门店。

## 接入方式

- 官方服务：`https://mcp.mcd.cn`。
- 协议：MCP Streamable HTTP，初始化、工具调用与 JSON/SSE 响应由 Python 标准库客户端实现。
- 认证：`Authorization: Bearer ${MCD_MCP_TOKEN}`，运行时读取环境变量。
- 服务与工具依据：[麦当劳 MCP 官方仓库](https://github.com/M-China/mcd-mcp-server)。
- 三个业务工具均用于查询；每个客户端默认最多每秒发起 4 次请求、最多 4 个工作线程。

## 实际使用的工具

| 工具 | 输入 | 使用结果 |
| --- | --- | --- |
| `query-nearby-stores` | `searchType=2`、城市、商圈关键词、`beType=1` | 提取门店编码、名称、地址，按编码去重 |
| `query-meals` | 门店编码、`orderType=1`、`beType=1`，可选 `reservationDate` | 合并分类与餐品字典，筛选儿童餐、亲子餐和玩具餐品 |
| `query-meal-detail` | 门店编码、餐品 `code`、到店参数，可选 `reservationDate` | 检查 `rounds[].choices[]` 的玩具选项，匹配系列编码/完整名称 |

图鉴外系列通过 `--discover` 从玩具选项中提取，再按玩具编码获取官方系列图片，供客户端识别比对。

## 一条完整调用链

用户上传照片并指定“南京新街口，今天12点到店”，宿主将照片识别为“海绵宝宝×航海王系列玩具”。脚本执行以下调用（日期由用户当次计划决定）：

```json
{"name":"query-nearby-stores","arguments":{"searchType":2,"city":"南京市","keyword":"新街口","beType":1}}
```

对每个发现的门店调用：

```json
{"name":"query-meals","arguments":{"storeCode":"1990346","orderType":1,"beType":1,"reservationDate":"2026-10-14 12:00"}}
```

对菜单中实际存在的候选套餐调用：

```json
{"name":"query-meal-detail","arguments":{"storeCode":"1990346","code":"9900016056","orderType":1,"beType":1,"reservationDate":"2026-10-14 12:00"}}
```

系列匹配依据为详情中的 `521991` / `海绵宝宝×航海王系列玩具`。输出保留套餐编码、系列编码及 `evidence_tool`，便于追溯。

## 结果口径

门店菜单出现该系列即可列入结果，按搜索范围和接口次序展示，并标明查询时间和到店时段。部分查询失败时，保留已匹配门店并标注查询状态。

输出中的 `mode=live` 表示数据来自真实接口。`query.at` 为预约时间或空值，`query.menu_type` 分别标记预约菜单或当前菜单。`coverage.checked` 是本次尝试检查的门店数，`unknown` 是仍待确认的门店数，`failed` 是发生菜单/详情失败的门店数；后两项可能重叠。

客户端负责图片识别，插件通过麦当劳 MCP 查询城市、门店和餐品信息。

自动用例及真实接口执行结果见 [验证记录](docs/验证记录.md)。
