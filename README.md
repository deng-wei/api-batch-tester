# API 批量测试工具

批量测试生图/生视频 API 的命令行工具。支持灵活的输入参数组合、异步并发请求、断点续跑。

## 功能特性

- **YAML 配置驱动**：一个 YAML 文件描述完整的测试计划
- **灵活参数组合**：支持固定值、随机选取、文件扫描、文件内容读取四种参数模式
- **三种组合策略**：笛卡尔积 (product)、一一对齐 (zip)、随机选取 (random)
- **异步并发**：基于 httpx + asyncio，可控并发度
- **断点续跑**：自动跳过已成功的任务，支持中断后重跑
- **结果持久化**：输出文件 + JSONL 结果日志

## 安装

```bash
# 确保已安装 uv
uv sync
```

## 快速开始

### 1. 准备配置文件

复制示例配置并修改：

```bash
cp configs/example.yaml configs/my_task.yaml
```

### 2. 设置环境变量

```bash
export API_KEY="your-api-key-here"
```

### 3. 预览任务

```bash
uv run python main.py configs/my_task.yaml --dry
```

### 4. 执行测试

```bash
uv run python main.py configs/my_task.yaml
```

## 配置说明

### 参数定义方式

| 方式 | 写法 | 说明 |
|------|------|------|
| 固定值 | `model: "gpt-4"` | 所有任务使用相同值 |
| 随机选一 | `prompt: { pick: ["a", "b"] }` | 每个任务随机选一个 |
| 文件扫描 | `image: { glob: "*.png", as: "base64" }` | 扫描文件并编码 |
| 文件内容 | `prompt: { file: "p.txt", split: "line" }` | 读取文件按行切分 |

### glob 的 `as` 选项

| 值 | 说明 |
|----|------|
| `base64` | 文件内容编码为 base64（默认） |
| `path` | 文件绝对路径字符串 |
| `filename` | 仅文件名 |

### 组合策略

| 策略 | 说明 | 示例 |
|------|------|------|
| `product` | 笛卡尔积 | 3 prompt × 5 image = 15 任务 |
| `zip` | 一一对齐 | prompt[0]+image[0]... |
| `random` | pick 随机选，其他做积 | 5 image × 随机 prompt |

### 输出提取类型

| 类型 | 说明 |
|------|------|
| `base64_image` | base64 编码的图片 |
| `base64_video` | base64 编码的视频 |
| `url` | 通过 URL 下载资源 |

## 项目结构

```
api-batch-tester/
├── main.py                  # CLI 入口
├── configs/                 # 配置文件目录
│   ├── example.yaml         # 完整示例
│   └── example_random_prompt.yaml  # 随机提示词示例
├── src/
│   ├── config.py            # 配置加载与验证
│   ├── runner.py            # 批量测试执行引擎
│   ├── param_resolver.py    # 参数解析器
│   ├── api_client.py        # 异步 HTTP 客户端
│   ├── result_tracker.py    # 结果追踪（断点续跑）
│   └── utils.py             # 工具函数
└── external/                # 外部参考代码（不参与构建）
```
