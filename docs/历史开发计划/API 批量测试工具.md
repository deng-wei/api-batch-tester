# API 批量测试工具 (api-batch-tester)

批量测试生图/生视频 API 的命令行工具。支持灵活的输入参数组合，异步并发请求，断点续跑。

## 核心设计理念

1. **YAML 配置驱动**：每次测试用一个 YAML 文件描述完整的测试计划（API 信息、输入参数组合规则、输出存储路径等）
2. **灵活的参数组合**：支持「固定值 / 列表随机选一 / 文件列表笛卡尔积 / 按文件名关联」等多种输入组合模式
3. **异步并发**：基于 httpx + asyncio 实现可控并发度的批量请求
4. **断点续跑**：自动跳过已成功的任务，失败任务可重跑
5. **结果持久化**：输出文件 + JSON 结果日志，方便后续分析

## 项目结构

```
api-batch-tester/
├── main.py                  # CLI 入口
├── pyproject.toml           # 项目配置
├── configs/                 # 示例配置文件目录
│   └── example.yaml         # 示例配置
├── src/
│   ├── __init__.py
│   ├── config.py            # 配置加载与验证 (Pydantic models)
│   ├── runner.py            # 批量测试执行引擎
│   ├── param_resolver.py    # 参数解析器（处理灵活的输入组合逻辑）
│   ├── api_client.py        # HTTP 客户端（基于 httpx，支持重试和超时）
│   ├── result_tracker.py    # 结果追踪（JSON 日志、断点续跑）
│   └── utils.py             # 工具函数（base64 编解码、文件 I/O 等）
├── external/                # 外部参考代码（不参与构建）
└── README.md
```

---

## Proposed Changes

### 配置层 (Config)

#### [NEW] [example.yaml](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/configs/example.yaml)

YAML 配置文件示例，完整演示所有功能：

```yaml
# ========================================
# API 批量测试配置文件
# ========================================

# --- API 连接配置 ---
api:
  base_url: "https://api.example.com/v1/images/generations"
  api_key: "${API_KEY}"              # 支持环境变量引用
  method: "POST"
  timeout: 300                       # 单次请求超时（秒）
  max_retries: 3                     # 最大重试次数
  retry_backoff: 1.0                 # 退避因子
  concurrency: 5                     # 并发数

# --- 输入参数定义 ---
# 每个 key 都会作为请求 payload 的字段
# value 支持以下类型：
#   1. 固定值:          "some text" / 123 / true
#   2. 随机选一 (pick):  { pick: ["a", "b", "c"] }
#   3. 文件列表 (glob):  { glob: "inputs/images/*.png", as: "base64" }
#   4. 文件读取内容:     { file: "prompts.txt", split: "line" }

params:
  model: "doubao-seedream-4.0"
  size: "2K"
  response_format: "b64_json"
  
  prompt:
    file: "prompts.txt"              # 从文件读取，一行一个 prompt
    split: "line"
  
  image:
    glob: "inputs/images/*.png"      # 扫描输入图片
    as: "base64"                     # 自动转为 base64 编码

# --- 参数组合策略 ---
# product:  笛卡尔积（每个 prompt × 每张 image）
# zip:      一一对齐（prompt[0]+image[0], prompt[1]+image[1], ...）
# random:   每组随机选一个（适用于 pick 类型的字段）
combination: "product"

# --- 输出配置 ---
output:
  dir: "outputs/{timestamp}"         # 输出目录，支持 {timestamp} 变量
  save_response: true                # 保存完整 API 响应 JSON
  # 从响应中提取文件的规则
  extract:
    - field: "data[0].b64_json"      # 从响应 JSON 中提取的字段路径
      type: "base64_image"           # 类型：base64_image / base64_video / url
      suffix: ".png"                 # 保存文件后缀

# --- 结果日志 ---
result_log: "outputs/{timestamp}/results.jsonl"  # JSONL 格式的结果日志
```

---

#### [NEW] [config.py](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/src/config.py)

使用 Pydantic 定义配置结构，提供类型检查和校验：

- `APIConfig` — API 连接相关配置
- `ParamValue` — 支持固定值、pick、glob、file 四种模式的参数值
- `OutputExtractRule` — 从响应中提取文件的规则
- `OutputConfig` — 输出目录和提取规则
- `TaskConfig` — 最顶层配置对象，包含以上所有字段
- `load_config(path)` — 加载 YAML → 验证 → 返回 `TaskConfig`

---

### 参数组合层 (Param Resolver)

#### [NEW] [param_resolver.py](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/src/param_resolver.py)

核心模块，负责将 YAML 中声明的灵活参数定义展开为具体的请求参数列表。

**核心功能**：
- `resolve_param_value(param_def)` — 解析单个参数定义，返回值列表
  - 固定值 → `[value]`
  - `pick: [...]` → 保留列表，在组合时随机选取
  - `glob: "*.png"` → 扫描文件，根据 `as` 字段决定是返回路径还是 base64
  - `file: "prompts.txt"` → 读取文件内容，按行/按分隔符切分
- `build_task_list(params, combination)` — 根据组合策略生成任务列表
  - `product` → `itertools.product` 笛卡尔积
  - `zip` → `zip` 对齐
  - `random` → 对 `pick` 类型随机选取，其他字段做笛卡尔积

---

### HTTP 客户端层 (API Client)

#### [NEW] [api_client.py](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/src/api_client.py)

基于 httpx 的异步 HTTP 客户端，参考 external 中的重试和错误处理模式：

- `APIClient` 类:
  - `__init__(config: APIConfig)` — 创建 httpx.AsyncClient，配置超时和重试
  - `async send(payload: dict) -> dict` — 发送单个请求，包含自动重试逻辑
  - `async close()` — 关闭连接

---

### 结果追踪层 (Result Tracker)

#### [NEW] [result_tracker.py](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/src/result_tracker.py)

管理任务执行状态，支持断点续跑：

- `ResultTracker` 类:
  - `__init__(log_path)` — 加载已有的 JSONL 日志
  - `is_completed(task_id)` — 检查某任务是否已成功完成
  - `record(task_id, status, response, elapsed, error)` — 记录结果
  - `summary()` — 返回统计摘要（成功/失败/跳过数量）

---

### 执行引擎 (Runner)

#### [NEW] [runner.py](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/src/runner.py)

批量测试的编排器：

- `BatchRunner` 类:
  - `__init__(config: TaskConfig)` — 初始化客户端、结果追踪器
  - `async run()` — 主流程：
    1. 调用 `param_resolver` 生成任务列表
    2. 过滤已完成的任务（断点续跑）
    3. 使用 `asyncio.Semaphore` 控制并发度
    4. 对每个任务：发请求 → 提取输出文件 → 记录结果
    5. 打印执行摘要

---

### 工具函数 (Utils)

#### [NEW] [utils.py](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/src/utils.py)

- `image_to_base64(path)` — 图片文件 → base64 字符串
- `video_to_base64(path)` — 视频文件 → base64 字符串
- `save_base64_image(b64_str, path)` — base64 → 保存为图片文件
- `save_base64_video(b64_str, path)` — base64 → 保存为视频文件
- `download_url(url, path)` — 下载 URL 资源到本地
- `extract_field(data, field_path)` — 用点分路径（如 `data[0].b64_json`）从嵌套 dict 中提取值
- `resolve_env_vars(text)` — 解析字符串中的 `${ENV_VAR}` 引用

---

### 入口 (Main)

#### [MODIFY] [main.py](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/main.py)

提供 CLI 入口：

```
uv run python main.py configs/example.yaml
```

- 解析命令行参数（配置文件路径）
- 加载配置
- 启动 `BatchRunner`

---

### 项目配置

#### [MODIFY] [pyproject.toml](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/pyproject.toml)

添加依赖：`pyyaml`

#### [MODIFY] [.gitignore](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/.gitignore)

添加 `outputs/`、`.env`

#### [NEW] [README.md](file:///mnt/Algo_new/DengWei/Project/DW/api-batch-tester/README.md)

项目文档。

---

## User Review Required

> [!IMPORTANT]
> **配置格式设计**：上面的 YAML 配置格式是否符合你的使用场景？特别是参数组合策略（product/zip/random）是否满足你 "每个输入图随机从3个提示词中选一个" 的需求？

> [!IMPORTANT]
> **API 请求格式**：从 external 参考代码来看，你主要对接的是 OpenAI 兼容协议 和 豆包图片生成 API。是否还有其他 API 格式需要支持？比如需要 multipart/form-data 上传文件而不是 base64？

> [!IMPORTANT]
> **输出提取规则**：目前设计的是通过 JSON 字段路径 + 类型来提取输出。是否有需要从 HTTP 响应头、或通过二次 URL 下载 来获取结果的场景？

## Verification Plan

### Automated Tests
1. 单元测试 `param_resolver`：验证各种参数组合策略的正确性
2. 用示例配置做一次 dry-run（不真正发请求），验证任务列表生成、输出路径规划

### Manual Verification
1. 准备几张测试图片和提示词，用真实 API 跑一次完整流程
2. 验证断点续跑：中断后重新运行，确认已完成任务被跳过
