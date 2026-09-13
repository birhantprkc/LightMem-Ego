# Docker 复现说明

## 1. 准备环境

安装 Docker Engine 和 Docker Compose Plugin。首次运行前复制配置：

```bash
cp deploy/.env.example .env
```

然后在 `.env` 中填写自己的 OpenAI 兼容接口地址、API Key 和模型名。

镜像不包含任何密钥、用户录音录像或模型权重。`MODEL_DIR` 指向的目录只会以只读方式挂载到容器。

## 2. 启动网页和后端

```bash
docker compose up --build
```

打开 <http://localhost:8080>。API 通过网页容器的 `/api` 路径代理到后端，因此通常不需要额外配置浏览器跨域。

## 3. 模型服务

默认配置使用远程 LLM，视觉 embedding 使用 `mock`，文本 embedding 使用 `local`，这样没有模型时也不会在启动阶段等待不存在的服务。要运行完整的文本和视觉检索，需要提供自己的模型：

默认后端镜像安装 CPU 版 PyTorch，不会下载 CUDA 运行库；GPU 推理由 `models` profile 中的独立模型服务负责。

```text
docker-data/models/
├── Qwen3-Embedding-4B/
└── VLM2Vec-V2.0/
```

启动 Compose 中的 GPU 模型服务：

```bash
docker compose --profile models up --build
```

模型服务 profile 会启动 `vlm2vec` 和 `text-embedding` 两个容器。启用它们时，把 `.env` 中的 `EM2MEM_TEXT_EMBED_BACKEND` 改为 `remote`、`EM2MEM_VISUAL_BACKEND` 改为 `remote`，并保留对应的 Compose 服务地址；随后 `backend-workers` 会通过 Compose 服务名访问它们。

需要同时让后端 worker 使用 NVIDIA GPU 时，使用 GPU 覆盖配置：

```bash
docker compose -f compose.yaml -f compose.gpu.yaml --profile models up --build
```

这要求宿主机安装 NVIDIA Container Toolkit，并且模型目录结构与 `.env` 中的路径一致。也可以不启动这些容器，直接把 `EM2MEM_TEXT_EMBED_URL` 或 `EM2MEM_VLM2VEC_EMBED_URL` 改成自己的远程服务地址。

ASR 默认使用讯飞（Xfyun）WebAPI，不使用 WhisperX 模型。请在本地未提交的 `.env` 中填写自己的 `EM2MEM_XFYUN_APP_ID`、`EM2MEM_XFYUN_API_KEY` 和 `EM2MEM_XFYUN_API_SECRET`；这些凭据不会写入镜像或 Git。录制视频、音频窗口、实时流和语音提问的 ASR 后端均由对应的 `*_ASR_BACKEND=xfyun` 配置控制。

Docker 镜像不需要安装 WhisperX 依赖，也不包含任何 ASR 模型权重。若未填写讯飞凭据，容器仍可启动，但处理需要转写的音视频任务时会报告缺少凭据。讯飞 WebAPI 需要宿主机能够访问其 HTTPS 服务。

## 4. 实时流（可选）

只有使用 RTMP/WebRTC 时才启动 SRS：

```bash
docker compose --profile live up --build
```

生产环境仍需在 Docker 外配置 HTTPS、域名、访问控制和防火墙。

## 5. 数据持久化

运行时数据位于 `docker-data/`：

- `sessions/`：音视频、记忆和索引
- `tasks/`：异步任务队列
- `tasks-aborted/`：被取消或清理的任务记录
- `runtime/`：worker 状态
- `logs/`：API 和 worker 日志
- `models/`：宿主机提供的模型权重

删除容器不会删除这些目录。请把它们加入备份和隐私管理范围。
