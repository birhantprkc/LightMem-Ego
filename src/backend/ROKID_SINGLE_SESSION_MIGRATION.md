# Rokid Single-Session Migration

本次迁移将 Rokid DAY 模型从“每个 DAY 创建 child session，结束后合并到 parent”改为：

- 一副眼镜持续使用同一个 `session_id`。
- 每次开始采集使用新的 `run_id`。
- DAY1、DAY2 等信息保存在同一 session 的 `stream/day_state.json`。
- 帧、音频 index 和相对时间在多个 run 之间连续递增。
- evidence、caption 和 episodic 条目根据相对时间记录所属 DAY。
- 不再创建 child session，不再产生或消费 DAY merge task。

相关源码已直接包含在本仓库中，不需要额外应用补丁。

## 验证

```bash
PYTHONPATH=. .venv/bin/python -c "from online_pipeline.rokid_day import enrich_start_response_for_single_session_day, reserve_single_session_day_run, single_session_metadata_patch, update_single_session_metadata; print('single-session imports ok')"
PYTHONPATH=. .venv/bin/pytest -q
python -m py_compile api_server.py online_pipeline/rokid_day.py online_query/query_engine.py
bash -n scripts/cleanup_session.sh scripts/start_online_all_workers.sh scripts/stop_server_and_workers.sh
```

## 重启服务

部署新源码不会替换已经加载到 Python 进程内存里的旧模块，也不会自动停止旧 DAY merge worker。选择维护窗口执行：

```bash
bash scripts/stop_server_and_workers.sh
```

新的 `start_online_all_workers.sh` 不会再启动 `online_rokid_day_merge_worker.py`。停止脚本仍保留对旧进程名的识别，用于清理迁移前已经运行的 worker。

重启后检查：

```bash
ps -ef | grep -E 'online_rokid_day_merge_worker|uvicorn.*api_server'
```

输出中不应再有 `online_rokid_day_merge_worker.py`。

## 客户端调用约定

第一次开始采集时可以不传 `session_id`，服务端返回一个新的 `session_id` 和 DAY1 上下文。后续 DAY 必须复用该 `session_id`，同时提供新的 `run_id`：

```json
{
  "session_id": "same-session-id",
  "run_id": "new-run-id",
  "input_mode": "rokid_frame_audio"
}
```

客户端不再发送或依赖：

```text
parent_session_id
child_session_id
create_parent_session
is_rokid_day_child
```

## 历史数据边界

补丁不会自动合并或改写已经存在的 `parent__day0001` 等历史目录。需要保留这些历史数据时，应在上线前归档，或单独编写一次性迁移脚本。

新代码只保证补丁应用后的新 run 使用 single-session 模型。旧的 merge 队列目录可以归档后删除，但不要在仍有旧 worker 运行时直接删除队列数据。
