# Warp AI 代理服务与账号池系统

这是一个功能完备的Warp AI API代理服务，它不仅提供了与OpenAI Chat Completions API的兼容性，还集成了一套全自动的账号注册、维护和分配系统。项目的设计目标是提供一个稳定、高效且易于管理的Warp AI接口。

该项目的设计思路和部分实现得益于以下优秀项目：
- **Protobuf协议逆向基础**: [libaxuan/Warp2Api](https://github.com/libaxuan/Warp2Api)
- **账号池与注册机思路**: [dundunduan/warp2api](https://github.com/dundunduan/warp2api)

---

## 🚀 核心特性

- **OpenAI API 兼容**: 完全兼容 OpenAI Chat Completions API 格式，可无缝对接现有生态。
- **全自动账号池**:
    - **自动注册**: 通过Outlook API自动购买邮箱并注册Warp账号。
    - **自动维护**: 定期检查账号状态，自动刷新即将过期的Token。
    - **智能分配**: 通过独立的API服务，安全、高效地分配和回收账号。
- **统一启动与管理**: 使用`main.py`一键启动所有服务，也支持为调试目的单独启动某个服务。
- **中心化配置**: 所有配置项（端口、API密钥、数据库路径等）均在`config.py`中统一管理，清晰明了。
- **高性能架构**:
    - **Protobuf 通信**: 底层与Warp服务通过高效的Protobuf协议进行通信。
    - **多进程模型**: 每个核心服务（API、账号池、维护等）都运行在独立的进程中，互不干扰。
- **流式响应 (Streaming)**: 完全支持OpenAI的SSE流式响应格式。
- **WebSocket 监控**: 内置WebSocket端点，用于实时监控Protobuf通信数据包。

## 📁 项目结构

项目采用扁平化结构，核心服务均在主目录下，方便理解和修改。

```
/
├── main.py                  # 🚀 统一服务启动器
├── config.py                # ⚙️ 全局配置文件
│
├── server.py                # 🔌 Protobuf 核心服务 (端口: 8000)
├── openai_compat.py         # 🤖 OpenAI 兼容API服务 (端口: 8010)
│
├── pool_service.py          # 💧 账号池API服务 (端口: 8019)
├── pool_maintenance.py      # 🛠️ 账号池维护与Token刷新服务
├── warp_register.py         # 📧 Warp 账号自动注册服务
│
├── warp_accounts.db         # 🗃️ 存储Warp账号的SQLite数据库
├── requirements.txt         # 🐍 Python 依赖
└── README.md                # 📄 项目文档
```

## 🛠️ 安装与配置

### 1. 克隆仓库

```bash
git clone https://github.com/xzzvsxd/Warp2Api_Plus
cd Warp2Api_Plus-master
```

### 2. 安装依赖

推荐使用 `uv` 或 `pip` 安装 `requirements.txt` 中的依赖。

```bash
# 使用 uv (推荐)
uv pip install -r requirements.txt

# 或者使用 pip
pip install -r requirements.txt
```

### 3. 配置 `config.py`

这是最关键的一步。打开 [`config.py`](config.py) 文件并填写必要的配置信息。

**必须配置的选项:**

- `OUTLOOK_BASE_URL`: 你的Outlook邮箱API购买地址的基础URL。
- `OUTLOOK_API_CONFIG`:
    - `app_id`: 你的Outlook API App ID。
    - `app_key`: 你的Outlook API App Key。

**可选配置（通常保持默认即可）:**

- 各个服务的端口号（`SERVER_PORT`, `OPENAI_COMPAT_PORT`, `POOL_SERVICE_PORT`）。
- 代理地址 `PROXY_URL`。
- 账号池大小 `MIN_POOL_SIZE`, `MAX_POOL_SIZE`。
- 目标注册账号数 `TARGET_ACCOUNTS`。

## 🎯 使用方法

我们提供了统一的启动脚本 [`main.py`](main.py)，极大简化了服务的管理和调试。

### 一键启动所有服务（推荐）

在终端中运行以下命令，即可启动全部五个核心服务：

```bash
python main.py all
```

脚本会为每个服务创建一个独立的进程，并打印出每个服务的启动信息和进程ID。你可以通过 `Ctrl+C` 来优雅地关闭所有服务。

### 单独启动服务（用于调试）

如果你想单独调试某个服务，可以使用 `main.py` 启动它。这对于问题排查非常有用。

```bash
# 仅启动 Protobuf 主服务
python main.py server

# 仅启动 OpenAI 兼容API
python main.py openai

# 仅启动账号池API服务
python main.py pool_service

# 仅启动账号池维护脚本
python main.py pool_maintenance

# 仅启动账号注册服务
python main.py register
```

## 📝 API 使用

服务启动后，你可以通过两个主要的API端点与系统交互。

### 1. OpenAI 兼容 API (`http://127.0.0.1:8010`)

你可以使用任何支持OpenAI API的客户端来访问此接口。

- **Base URL**: `http://127.0.0.1:8010/v1`
- **API Key**: **无需提供**。你可以填写任意字符串（例如 "dummy"），服务器不会进行验证。

#### Python 示例

```python
import openai

client = openai.OpenAI(
    base_url="http://127.0.0.1:8010/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="gemini-2.5-pro", # 或者其他Warp支持的模型
    messages=[
        {"role": "user", "content": "你好，请介绍一下你自己"}
    ],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

#### cURL 示例

```bash
curl -X POST http://127.0.0.1:8010/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-4-sonnet",
    "messages": [
      {"role": "user", "content": "解释量子计算的基本原理"}
    ],
    "stream": true
  }'
```

### 2. 账号池服务 API (`http://0.0.0.0:8019`)

你可以直接与账号池服务交互来监控其状态。

#### 查看账号池状态

```bash
curl http://localhost:8019/api/status | jq
```

这将返回一个JSON对象，包含总账号数、可用账号数、锁定账号数等信息。

#### 健康检查

```bash
curl http://localhost:8019/api/health
```

## 🏗️ 架构说明

系统由五个协同工作的独立服务进程组成：

1.  **账号注册服务 (`warp_register.py`)**: 作为一个生产者，它不断地通过Outlook API获取新邮箱，并自动完成Warp账号的注册流程，然后将成功的账号存入`warp_accounts.db`数据库。

2.  **账号池维护服务 (`pool_maintenance.py`)**: 这是一个后台守护进程，定期扫描数据库中的所有账号，检查其Token的有效性。当Token即将过期时，它会自动执行刷新操作，确保账号池中的账号始终保持可用状态。

3.  **账号池API服务 (`pool_service.py`)**: 这是一个面向内部的API服务，负责管理对数据库中账号的访问。当其他服务需要一个Warp账号时，会向它请求。它会从池中分配一个当前未被使用的账号，并将其标记为“锁定”状态，以防止并发冲突。使用完毕后，账号会被释放回池中。

4.  **Protobuf主服务 (`server.py`)**: 这是与Warp官方服务器直接通信的核心桥梁。它接收内部请求，使用Protobuf协议对数据进行编码，然后发送给Warp。同样，它也负责解码从Warp返回的Protobuf数据。

5.  **OpenAI兼容API服务 (`openai_compat.py`)**: 这是暴露给最终用户的服务。它接收一个标准格式的OpenAI API请求，然后向**账号池API服务**申请一个可用的Warp账号。获取到账号凭证后，它将请求转发给**Protobuf主服务**进行处理，最终将Warp的响应转换成OpenAI格式返回给用户。

这个多进程、微服务化的架构确保了各个模块职责单一、高内聚、低耦合，提高了系统的健壮性和可维护性。

## 🐛 故障排查

- **服务无法启动**:
    - 检查`config.py`中的端口是否被其他程序占用。
    - 查看终端日志，了解详细的错误信息。
- **账号注册失败**:
    - 确保`config.py`中的Outlook API信息 (`app_id`, `app_key`, `base_url`) 正确无误且账户有余额。
    - 检查`PROXY_URL`是否可用，注册过程依赖代理。
- **账号池为空**:
    - 首次启动时，请耐心等待`warp_register.py`服务完成第一批账号的注册。
    - 查看`warp_register.py`进程的日志，确认注册流程是否正常。
- **API请求失败**:
    - 确保`all`服务都已正常启动。
    - 检查`openai_compat.py`和`server.py`的日志，定位请求失败的具体环节。
