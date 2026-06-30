"""
Syncthing Service — 为映记注册 Syncthing 操作

用法:
    from syncthing_client import SyncthingClient
    from syncthing_service import register_syncthing

    client = SyncthingClient(api_key="你的API_KEY")
    register_syncthing(client)

    # 之后 Yingji 就能处理 syncthing 相关的 intent 了
    from yingji import Yingji
    yj = Yingji()
    result = yj.chat({"intent": "query_syncthing_health", "content": "", "params": {}})
"""

from capabilities import register, SECURITY_LEVEL_READ, SECURITY_LEVEL_WRITE, SECURITY_LEVEL_DELETE
from syncthing_client import SyncthingClient, SyncthingError
from syncthing_events import EventListener

# ─── 全局持有客户端引用 ───
_client: SyncthingClient = None


def set_client(client: SyncthingClient):
    """设置/更新 Syncthing 客户端"""
    global _client
    _client = client


# ───────── 处理器函数 ─────────

def _handle_query_health(params: dict) -> dict:
    """聚合健康诊断"""
    if not _client:
        return {"status": "error", "message": "Syncthing 客户端未配置"}
    try:
        result = _client.diagnose()
        summary = result.get("summary", "")
        details = result.get("details", {})
        status_code = result.get("status", "unknown")

        # 构造自然语言回复
        folders = details.get("folders", [])
        conn = details.get("connections", {})
        conn_info = f"{conn.get('connected_devices', 0)}/{conn.get('total_devices', 0)} 台设备在线" if conn else "暂无连接信息"
        folder_info = f"{len(folders)} 个文件夹"
        msg = f"{summary} {conn_info}，{folder_info}。"
        if folders:
            syncing = [f for f in folders if f.get('state') == 'syncing']
            errors = [f for f in folders if f.get('pullErrors', 0) > 0]
            if syncing:
                msg += f" {len(syncing)} 个文件夹正在同步。"
            if errors:
                msg += f" {len(errors)} 个文件夹有同步错误。"

        return {
            "status": status_code,
            "summary": summary,
            "message": msg,
            "details": details,
            "action": "query_syncthing_health",
        }
    except SyncthingError as e:
        return {"status": "error", "message": str(e), "action": "query_syncthing_health"}


def _handle_query_system_status(params: dict) -> dict:
    """查询系统状态"""
    if not _client:
        return {"status": "error", "message": "Syncthing 客户端未配置"}
    try:
        status = _client.system_status()
        uptime_seconds = status.get("uptime", 0)
        uptime_str = f"{uptime_seconds // 3600}h{(uptime_seconds % 3600) // 60}m" if uptime_seconds else "N/A"
        # 提取关键信息
        discovery_ok = True
        discovery_errors = status.get("discoveryErrors", {})
        if discovery_errors:
            discovery_ok = False
        return {
            "status": "success",
            "myID": status.get("myID", "")[:20] + "...",
            "uptime": uptime_str,
            "startTime": status.get("startTime", ""),
            "discoveryOK": discovery_ok,
            "discoveryErrors": len(discovery_errors),
            "goroutines": status.get("goroutines", 0),
            "action": "query_syncthing_system_status",
        }
    except SyncthingError as e:
        return {"status": "error", "message": str(e), "action": "query_syncthing_system_status"}


def _handle_query_connections(params: dict) -> dict:
    """查询设备连接状态"""
    if not _client:
        return {"status": "error", "message": "Syncthing 客户端未配置"}
    try:
        conn = _client.system_connections()
        raw = conn.get("connections", {})
        total = conn.get("total", {}).get("inBytesTotal", 0)
        tout = conn.get("total", {}).get("outBytesTotal", 0)
        devices = []
        online = 0
        offline = 0
        paused = 0
        for dev_id, info in raw.items():
            is_connected = info.get("connected", False)
            is_paused = info.get("paused", False)
            devices.append({
                "id": dev_id[:16] + "...",
                "connected": is_connected,
                "paused": is_paused,
                "address": info.get("address", ""),
                "type": info.get("type", ""),
                "inBytes": info.get("inBytesTotal", 0),
                "outBytes": info.get("outBytesTotal", 0),
            })
            if is_connected:
                online += 1
            elif is_paused:
                paused += 1
            else:
                offline += 1
        return {
            "status": "success",
            "total_devices": len(devices),
            "online": online,
            "offline": offline,
            "paused": paused,
            "total_in_bytes": total,
            "total_out_bytes": tout,
            "devices": devices,
            "action": "query_syncthing_connections",
        }
    except SyncthingError as e:
        return {"status": "error", "message": str(e), "action": "query_syncthing_connections"}


def _handle_query_folders(params: dict) -> dict:
    """查询所有文件夹状态"""
    if not _client:
        return {"status": "error", "message": "Syncthing 客户端未配置"}
    try:
        folders_config = _client.config_folders()
        if not isinstance(folders_config, list):
            return {"status": "error", "message": "获取文件夹列表失败"}
        results = []
        for f in folders_config:
            fid = f.get("id", "")
            if not fid:
                continue
            try:
                fs = _client.folder_status(fid)
                results.append({
                    "id": fid,
                    "label": f.get("label", fid),
                    "path": f.get("path", ""),
                    "type": f.get("type", "sendreceive"),
                    "state": fs.get("state", "unknown"),
                    "globalFiles": fs.get("globalFiles", 0),
                    "localFiles": fs.get("localFiles", 0),
                    "needFiles": fs.get("needFiles", 0),
                    "needBytes": fs.get("needBytes", 0),
                    "pullErrors": fs.get("pullErrors", 0),
                })
            except SyncthingError:
                pass
        return {
            "status": "success",
            "total": len(results),
            "folders": results,
            "action": "query_syncthing_folders",
        }
    except SyncthingError as e:
        return {"status": "error", "message": str(e), "action": "query_syncthing_folders"}


def _handle_query_folder_detail(params: dict) -> dict:
    """查询单个文件夹的详细状态"""
    if not _client:
        return {"status": "error", "message": "Syncthing 客户端未配置"}
    folder_id = params.get("folder_id", params.get("id", ""))
    if not folder_id:
        return {"status": "error", "message": "缺少 folder_id 参数", "action": "query_syncthing_folder_detail"}
    try:
        status = _client.folder_status(folder_id)
        completion = _client.folder_completion(folder_id)
        errors = _client.folder_errors(folder_id)
        need = _client.folder_need(folder_id)
        return {
            "status": "success",
            "folder_id": folder_id,
            "state": status.get("state", "unknown"),
            "stateChanged": status.get("stateChanged", ""),
            "globalFiles": status.get("globalFiles", 0),
            "globalBytes": status.get("globalBytes", 0),
            "localFiles": status.get("localFiles", 0),
            "localBytes": status.get("localBytes", 0),
            "needFiles": status.get("needFiles", 0),
            "needBytes": status.get("needBytes", 0),
            "inSyncFiles": status.get("inSyncFiles", 0),
            "pullErrors": status.get("pullErrors", 0),
            "completion": completion.get("completion", 0),
            "errors": errors.get("errors", []),
            "need": need.get("files", [])[:10],  # 只取前10个
            "action": "query_syncthing_folder_detail",
        }
    except SyncthingError as e:
        return {"status": "error", "message": str(e), "action": "query_syncthing_folder_detail"}


def _handle_trigger_rescan(params: dict) -> dict:
    """触发文件夹重新扫描"""
    if not _client:
        return {"status": "error", "message": "Syncthing 客户端未配置"}
    folder_id = params.get("folder_id", params.get("id", ""))
    if not folder_id:
        return {"status": "error", "message": "缺少 folder_id 参数", "action": "trigger_syncthing_rescan"}
    try:
        _client.db_scan(folder_id)
        return {
            "status": "success",
            "message": f"已触发文件夹 '{folder_id}' 的重新扫描",
            "action": "trigger_syncthing_rescan",
        }
    except SyncthingError as e:
        return {"status": "error", "message": str(e), "action": "trigger_syncthing_rescan"}


def _handle_query_errors(params: dict) -> dict:
    """查询最近的错误和日志"""
    if not _client:
        return {"status": "error", "message": "Syncthing 客户端未配置"}
    try:
        errors = _client.system_errors()
        error_list = errors.get("errors", [])
        return {
            "status": "success",
            "total": len(error_list),
            "errors": [{"time": e.get("when", ""), "message": e.get("message", "")[:200]}
                       for e in error_list[:20]],
            "action": "query_syncthing_errors",
        }
    except SyncthingError as e:
        return {"status": "error", "message": str(e), "action": "query_syncthing_errors"}


# ───────── 事件流查询 ─────────

_listener = None


def set_listener(listener):
    """设置事件监听器引用"""
    global _listener
    _listener = listener


def _handle_query_recent_events(params: dict) -> dict:
    """查询最近的事件流"""
    if not _listener:
        return {"status": "error", "message": "事件监听器未启动"}
    event_type = params.get("event_type", "")
    limit = min(params.get("limit", 20), 100)
    events = _listener.recent_events(limit=limit, event_type=event_type or None)
    # 筛选重要事件，减少噪音
    important = [e for e in events if e.get("type") in EventListener.IMPORTANT_EVENTS]
    if not important:
        important = events[-5:]
        
    # 构造自然语言摘要
    summary_lines = []
    type_counts = {}
    for e in events:
        t = e.get("type", "")
        type_counts[t] = type_counts.get(t, 0) + 1
    if type_counts:
        parts = [f"{t} x{c}" for t, c in sorted(type_counts.items(),
                 key=lambda x: -x[1])[:5]]
        summary_lines.append("最近 " + ", ".join(parts))
    
    return {
        "status": "success",
        "total": len(events),
        "since": _listener._since,
        "events": important,
        "summary": "\n".join(summary_lines),
        "action": "query_syncthing_recent_events",
    }


def _handle_query_notable_changes(params: dict) -> dict:
    """查询值得关注的变化（设备状态变动、同步状态变化、错误）"""
    if not _listener:
        return {"status": "error", "message": "事件监听器未启动"}
    summary = _listener.get_state_summary()
    
    # 构造自然语言
    msg_parts = []
    if summary["connected_devices"]:
        msg_parts.append(f"{len(summary['connected_devices'])} 台设备在线")
    if summary["disconnected_devices"]:
        msg_parts.append(f"{len(summary['disconnected_devices'])} 台设备离线")
    if summary["syncing_folders"]:
        msg_parts.append(f"{len(summary['syncing_folders'])} 个文件夹正在同步")
    if summary["errors"]:
        total_err = sum(len(e.get("errors", [])) for e in summary["errors"])
        msg_parts.append(f"{total_err} 个错误")
    if summary["last_change"]:
        lc = summary["last_change"]
        msg_parts.append(f"上次变更: {lc.get('item', '?')}")
    
    msg = "，".join(msg_parts) if msg_parts else "最近没有值得关注的变化"
    return {
        "status": "success",
        "message": msg,
        "summary": summary,
        "action": "query_syncthing_notable_changes",
    }


# ───────── 注册到映记 ─────────

def register_syncthing(client: SyncthingClient):
    """
    将 Syncthing 操作注册到映记的能力注册中心。
    调用此函数后，Yingji 实例即可处理 syncthing 相关的 intent。

    用法:
        client = SyncthingClient(api_key="...")
        register_syncthing(client)
        yj = Yingji()
    """
    set_client(client)

    # ── 只读操作（安全等级 1） ──
    register(
        "query_syncthing_health",
        "聚合查询 Syncthing 系统健康状况（状态摘要 + 连接 + 文件夹）",
        security_level=SECURITY_LEVEL_READ,
        parameters={},
        handler=_handle_query_health,
    )
    register(
        "query_syncthing_system_status",
        "查询 Syncthing 系统状态（运行时间、发现服务、版本）",
        security_level=SECURITY_LEVEL_READ,
        parameters={},
        handler=_handle_query_system_status,
    )
    register(
        "query_syncthing_connections",
        "查询所有设备的连接状态（在线/离线/已暂停/流量）",
        security_level=SECURITY_LEVEL_READ,
        parameters={},
        handler=_handle_query_connections,
    )
    register(
        "query_syncthing_folders",
        "查询所有文件夹的同步状态",
        security_level=SECURITY_LEVEL_READ,
        parameters={},
        handler=_handle_query_folders,
    )
    register(
        "query_syncthing_folder_detail",
        "查询单个文件夹的详细状态（同步进度、错误、待同步文件）",
        security_level=SECURITY_LEVEL_READ,
        parameters={
            "folder_id": {"type": "string", "required": True},
        },
        handler=_handle_query_folder_detail,
    )
    register(
        "query_syncthing_errors",
        "查询 Syncthing 最近的错误和日志",
        security_level=SECURITY_LEVEL_READ,
        parameters={},
        handler=_handle_query_errors,
    )

    # ── 写入操作（安全等级 2，需确认） ──
    register(
        "trigger_syncthing_rescan",
        "触发指定文件夹重新扫描本地文件",
        security_level=SECURITY_LEVEL_WRITE,
        requires_confirmation=True,
        parameters={
            "folder_id": {"type": "string", "required": True},
        },
        handler=_handle_trigger_rescan,
    )

    # ── 事件流操作（安全等级 1） ──
    register(
        "query_syncthing_recent_events",
        "查询最近的事件流（设备连接/断开、文件同步、错误等）",
        security_level=SECURITY_LEVEL_READ,
        parameters={
            "event_type": {"type": "string", "optional": True},
            "limit": {"type": "integer", "default": 20},
        },
        handler=_handle_query_recent_events,
    )
    register(
        "query_syncthing_notable_changes",
        "查询值得关注的变化摘要（设备状态变动、同步状态、错误）",
        security_level=SECURITY_LEVEL_READ,
        parameters={},
        handler=_handle_query_notable_changes,
    )


def register_syncthing_with_events(client: SyncthingClient,
                                    listener: EventListener):
    """注册 Syncthing 操作 + 事件监听器（一步到位）"""
    register_syncthing(client)
    set_listener(listener)


def has_syncthing() -> bool:
    """检查是否已配置 Syncthing 客户端"""
    return _client is not None
