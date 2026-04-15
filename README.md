# API Batch Tester

English | [简体中文](./README_zh.md)

A CLI tool for batch testing Image/Video generation APIs. It supports flexible input parameter combinations, asynchronous concurrent requests, and resume functionality.

## Features

- **YAML Configuration Driven**: A single YAML file describes the entire test plan.
- **Flexible Parameter Combinations**: Supports four parameter modes: fixed values, random selection, file system scanning (glob), and reading from file content.
- **Three Combination Strategies**: Cartesian product (`product`), pairwise alignment (`zip`), and random selection (`random`).
- **Asynchronous Concurrency**: Built with `httpx` + `asyncio` for controlled concurrency.
- **Resume Functionality**: Automatically skips already completed tasks, allowing for easy retries after interruption.
- **Result Persistence**: Outputs files and logs results in JSONL format.
- **Response Error Classification**: If the response body contains an `error` object, the task is recorded as `failed` (not `success`) to avoid incorrect resume skips.

## Installation

```bash
# Ensure uv is installed
uv sync
```

## Quick Start

### 1. Prepare Configuration File

Copy the example configuration and modify it:

```bash
cp configs/example.yaml configs/my_task.yaml
```

### 2. Configure API Key

Copy `.env.example` to `.env` and fill in your actual Keys:

```bash
cp .env.example .env
# Edit .env and fill in your API Key and Base URL
```

Example `.env` file (supports multiple API providers):

```env
# DeerAPI
DEERAPI_KEY=sk-your-deerapi-key
DEERAPI_BASE_URL=https://api.deerapi.com/v1

# Volcengine (Ark)
VOLCENGINE_KEY=your-volcengine-key
VOLCENGINE_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

Reference them in your YAML config using `${VAR_NAME}`:

```yaml
api:
  base_url: "${DEERAPI_BASE_URL}/images/generations"
  api_key: "${DEERAPI_KEY}"
```

> **Note**: The `.env` file is ignored by `.gitignore` and will not be committed. System environment variables take precedence over the `.env` file.

### 3. Dry Run (Preview Tasks)

```bash
uv run python main.py configs/my_task.yaml --dry
```

### 4. Execute Test

```bash
uv run python main.py configs/my_task.yaml
```

## Configuration Guide

### Parameter Definition Modes

| Mode | Syntax | Description |
|------|--------|-------------|
| Fixed Value | `model: "gpt-4"` | Same value used for all tasks |
| Pick One | `prompt: { pick: ["a", "b"] }` | Randomly selects one for each task |
| Glob Scan | `image: { glob: "*.png", as: "base64" }` | Scans files and encodes content |
| File Content | `prompt: { file: "p.txt", split: "line" }` | Reads file and splits by line |

### Glob `as` Options

| Value | Description |
|-------|-------------|
| `base64` | Encodes file content as base64 (default) |
| `path` | Absolute path string of the file |
| `filename` | Only the filename |

### Image Base64 Encoding Options (for `glob` + `as: base64`)

| Field | Value | Description |
|-------|-------|-------------|
| `image_encode` | `none` | Keep original file bytes (default) |
| `image_encode` | `smart_jpeg` | Convert static non-transparent images to JPEG when smaller |
| `jpeg_quality` | `1-95` | JPEG quality for `smart_jpeg` (default: `95`) |

Example:

```yaml
params:
  image:
    glob: "inputs/images/*"
    as: "base64"
    image_encode: "smart_jpeg"
    jpeg_quality: 95
```

### Combination Strategies

| Strategy | Description | Example |
|----------|-------------|---------|
| `product` | Cartesian Product | 3 prompts × 5 images = 15 tasks |
| `zip` | Pairwise alignment | prompt[0]+image[0]... |
| `random` | Randomly pick for `pick` mode, product for others | 5 images × random prompt |

### Output Extraction Types

| Type | Description |
|------|-------------|
| `base64_image` | Base64 encoded image |
| `base64_video` | Base64 encoded video |
| `url` | Download resource from URL |

## Project Structure

```
api-batch-tester/
├── main.py                  # CLI Entry point
├── .env.example             # Environment variable template
├── configs/                 # Configuration directory
│   ├── example.yaml         # Full example
│   └── example_random_prompt.yaml  # Random prompt example
├── src/
│   ├── config.py            # Configuration loading and validation
│   ├── runner.py            # Batch execution engine
│   ├── param_resolver.py    # Parameter resolver
│   ├── api_client.py        # Async HTTP client
│   ├── result_tracker.py    # Result tracking (checkpoint/resume)
│   └── utils.py             # Utility functions
└── external/                # External reference code (not part of the build)
```
