"""
Syncthing 事件流监听器 — 长轮询事件，驱动映记主动感知

用法:
    listener = EventListener(client, on_event=my_callback)
    listener.start()  # 后台线程持续监听
    # ...
    listener.stop()
"""

import threading
import time
import logging
from typing import Optional, Callable
from datetime import datetime

from syncthing_client import SyncthingClient, SyncthingError

logger = logging.getLogger("syncthing_events")


class EventListener:
    """
    事件流监听器。
    通过长轮询 /rest/events 接口，实时获取 Syncthing 事件。
    收到重要事件后触发回调，供映记处理。
    """

    # 关注的事件类型（其他事件不触发回调，减少噪音）
    IMPORTANT_EVENTS = {
        "DeviceConnected",
        "DeviceDisconnected",
        "DevicePaused",
        "DeviceResumed",
        "StateChanged",
        "FolderErrors",
        "FolderSummary",
        "FolderCompletion",
        "ItemStarted",
        "ItemFinished",
        "DownloadProgress",
        "LocalChangeDetected",
        "RemoteChangeDetected",
        "Failure",
        "StartupComplete",
        "ConfigSaved",
        "LoginAttempt",
        "ListenAddressesChanged",
        "PendingDevicesChanged",
        "PendingFoldersChanged",
    }

    def __init__(self, client: SyncthingClient,
                 on_event: Optional[Callable] = None,
                 poll_interval: float = 1.0):
        """
        Args:
            client: SyncthingClient 实例
            on_event: 事件回调，签名 on_event(event_type, event_data, raw_event)
            poll_interval: 轮询间隔（秒），无事件时等待间隔后再请求
        """
        self._client = client
        self._on_event = on_event
        self._poll_interval = poll_interval
        self._since = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._event_buffer = []  # 最近 100 条事件缓冲
        self._max_buffer = 100

    # ───────── 生命周期 ─────────

    def start(self):
        """在后台线程启动监听"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="syncthing-events")
        self._thread.start()
        logger.info(f"事件监听器已启动 (since={self._since})")

    def stop(self):
        """停止监听"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("事件监听器已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    # ───────── 事件缓冲查询 ─────────

    def recent_events(self, limit: int = 20,
                      event_type: Optional[str] = None) -> list:
        """获取最近的事件缓冲"""
        if event_type:
            return [e for e in self._event_buffer[-limit:]
                    if e.get("type") == event_type]
        return list(self._event_buffer[-limit:])

    def last_event_of(self, event_type: str) -> Optional[dict]:
        """获取指定类型的最后一条事件"""
        for e in reversed(self._event_buffer):
            if e.get("type") == event_type:
                return e
        return None

    def get_state_summary(self) -> dict:
        """
        从事件缓冲中提取当前状态摘要。
        不是查 REST API，而是从最近的事件推断。
        """
        summary = {
            "connected_devices": [],
            "disconnected_devices": [],
            "syncing_folders": [],
            "errors": [],
            "last_change": None,
        }
        for e in reversed(self._event_buffer):
            t = e.get("type", "")
            d = e.get("data", {})
            if t == "DeviceConnected":
                dev_id = d.get("id", "")
                if dev_id not in summary["connected_devices"]:
                    summary["connected_devices"].append(dev_id)
            elif t == "DeviceDisconnected":
                dev_id = d.get("id", "")
                if dev_id in summary["connected_devices"]:
                    summary["connected_devices"].remove(dev_id)
                if dev_id not in summary["disconnected_devices"]:
                    summary["disconnected_devices"].append(dev_id)
            elif t == "StateChanged" and d.get("to") == "syncing":
                fid = d.get("folder", "")
                if fid not in summary["syncing_folders"]:
                    summary["syncing_folders"].append(fid)
            elif t == "FolderErrors":
                fid = d.get("folder", "")
                errs = d.get("errors", [])
                summary["errors"].append({"folder": fid, "errors": errs})
            elif t == "ItemFinished":
                summary["last_change"] = {
                    "time": e.get("time"),
                    "folder": d.get("folder"),
                    "item": d.get("item"),
                    "error": d.get("error"),
                }
        return summary

    # ───────── 内部实现 ─────────

    def _run(self):
        """主循环：长轮询事件"""
        while self._running:
            try:
                self._poll()
            except SyncthingError as e:
                logger.warning(f"事件轮询失败: {e}")
                time.sleep(self._poll_interval * 5)
            except Exception as e:
                logger.error(f"事件轮询异常: {e}")
                time.sleep(self._poll_interval * 5)

    def _poll(self):
        """单次轮询"""
        path = f"/rest/events?since={self._since}"
        try:
            events = self._client._get(path)
        except SyncthingError as e:
            # 事件 API 超时正常（长轮询等待新事件）
            if "timeout" in str(e).lower():
                return
            raise

        if not isinstance(events, list):
            return

        for event in events:
            event_id = event.get("id", 0)
            event_type = event.get("type", "")
            event_data = event.get("data", {})
            event_time = event.get("time", "")

            # 更新 since
            if event_id > self._since:
                self._since = event_id

            # 存入缓冲
            self._event_buffer.append({
                "id": event_id,
                "type": event_type,
                "data": event_data,
                "time": event_time,
            })
            if len(self._event_buffer) > self._max_buffer:
                self._event_buffer.pop(0)

            # 触发回调（只重要事件）
            if self._on_event and event_type in self.IMPORTANT_EVENTS:
                try:
                    self._on_event(event_type, event_data, event)
                except Exception as e:
                    logger.error(f"事件回调异常 ({event_type}): {e}")

        # 无事件时等待
        if not events:
            time.sleep(self._poll_interval)
