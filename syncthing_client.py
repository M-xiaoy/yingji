"""
Syncthing REST API 客户端 — HTTP 封装层

用法:
    client = SyncthingClient(api_key="xxx", base_url="http://127.0.0.1:8384")
    status = client.system_status()
    folders = client.folder_status("default")
"""

import urllib.request
import urllib.error
import json
import urllib.parse
import ssl
from typing import Optional


class SyncthingError(Exception):
    """Syncthing API 调用异常"""
    def __init__(self, message: str, status_code: Optional[int] = None,
                 body: Optional[str] = None):
        self.status_code = status_code
        self.body = body
        super().__init__(f"[{status_code}] {message}" if status_code else message)


class SyncthingClient:
    """Syncthing REST API 的 Python 封装"""

    def __init__(self, api_key: str, base_url: str = "http://127.0.0.1:8384",
                 timeout: int = 10, verify_ssl: bool = False):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Syncthing 使用自签名证书，本地开发跳过验证
        self._ssl_ctx = ssl.create_default_context()
        if not verify_ssl:
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

    # ───────── 底层 HTTP 方法 ─────────

    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 params: Optional[dict] = None) -> dict:
        """通用 HTTP 请求"""
        # 构建 URL
        url = f"{self.base_url}{path}"
        if params:
            qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
            url = f"{url}?{qs}"

        # 构建请求
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-API-Key", self.api_key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        try:
            if url.startswith("https"):
                resp = urllib.request.urlopen(req, timeout=self.timeout,
                                              context=self._ssl_ctx)
            else:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise SyncthingError(
                f"HTTP {e.code}: {e.reason}", status_code=e.code, body=body
            )
        except urllib.error.URLError as e:
            raise SyncthingError(f"连接失败: {e.reason}")

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, params: Optional[dict] = None,
              body: Optional[dict] = None) -> dict:
        return self._request("POST", path, params=params, body=body)

    # ───────── 系统端点 ─────────

    def system_status(self) -> dict:
        """系统状态（运行时长、内存、发现服务状态等）"""
        return self._get("/rest/system/status")

    def system_connections(self) -> dict:
        """所有设备连接状态（在线/离线、流量）"""
        return self._get("/rest/system/connections")

    def system_version(self) -> dict:
        """版本信息"""
        return self._get("/rest/system/version")

    def system_ping(self) -> dict:
        """心跳检测"""
        return self._get("/rest/system/ping")

    def system_log(self) -> dict:
        """获取日志"""
        return self._get("/rest/system/log")

    def system_errors(self) -> dict:
        """获取错误列表"""
        return self._get("/rest/system/error")

    def system_clear_errors(self) -> dict:
        """清空错误"""
        return self._post("/rest/system/error/clear")

    def system_pause(self) -> dict:
        """暂停所有同步"""
        return self._post("/rest/system/pause")

    def system_resume(self) -> dict:
        """恢复所有同步"""
        return self._post("/rest/system/resume")

    def system_restart(self) -> dict:
        """重启（需要确认后才调用）"""
        return self._post("/rest/system/restart")

    def system_shutdown(self) -> dict:
        """关闭（需要确认后才调用）"""
        return self._post("/rest/system/shutdown")

    def system_discovery(self) -> dict:
        """发现服务状态"""
        return self._get("/rest/system/discovery")

    # ───────── 文件夹状态端点 ─────────

    def folder_status(self, folder_id: str) -> dict:
        """文件夹完整状态（global/local/need/state/pullErrors）"""
        return self._get("/rest/db/status", params={"folder": folder_id})

    def folder_completion(self, folder_id: str = "",
                          device_id: str = "") -> dict:
        """同步完成百分比 + 剩余文件/字节数"""
        params = {}
        if folder_id:
            params["folder"] = folder_id
        if device_id:
            params["device"] = device_id
        return self._get("/rest/db/completion", params=params)

    def folder_need(self, folder_id: str) -> dict:
        """需要同步的文件列表"""
        return self._get("/rest/db/need", params={"folder": folder_id})

    def folder_errors(self, folder_id: str) -> dict:
        """文件夹拉取错误"""
        return self._get("/rest/folder/errors", params={"folder": folder_id})

    # ───────── 配置端点 ─────────

    def config_get(self) -> dict:
        """获取完整配置"""
        return self._get("/rest/config")

    def config_folders(self) -> dict:
        """获取所有文件夹配置"""
        return self._get("/rest/config/folders")

    def config_devices(self) -> dict:
        """获取所有设备配置"""
        return self._get("/rest/config/devices")

    def config_restart_required(self) -> dict:
        """检查重启是否必要"""
        return self._get("/rest/config/restart-required")

    # ───────── 操作端点 ─────────

    def db_scan(self, folder_id: str) -> dict:
        """触发文件夹重新扫描"""
        return self._post("/rest/db/scan", params={"folder": folder_id})

    def db_override(self, folder_id: str) -> dict:
        """用本地版本覆盖冲突（⚠️ 有数据丢失风险）"""
        return self._post("/rest/db/override", params={"folder": folder_id})

    def db_revert(self, folder_id: str) -> dict:
        """撤销本地修改（⚠️ 有数据丢失风险）"""
        return self._post("/rest/db/revert", params={"folder": folder_id})

    def db_prio(self, folder_id: str, file_path: str) -> dict:
        """优先同步某个文件"""
        return self._post("/rest/db/prio",
                          params={"folder": folder_id, "file": file_path})

    # ───────── 健康检查（无需 API Key） ─────────

    def health(self) -> dict:
        """健康检查（不需要 API Key）"""
        return self._get("/rest/noauth/health")

    # ───────── 聚合查询（AI 友好） ─────────

    def diagnose(self) -> dict:
        """
        一次调用获取系统健康状况摘要。
        把最常用的几个查询聚合起来，减少 AI 调用 API 的次数。
        """
        result = {"status": "unknown", "summary": "", "details": {}}

        try:
            status = self.system_status()
            result["details"]["system"] = {
                "myID": status.get("myID", ""),
                "uptime": status.get("uptime", 0),
                "startTime": status.get("startTime", ""),
            }
        except SyncthingError as e:
            result["details"]["system_error"] = str(e)
            result["status"] = "error"
            result["summary"] = "无法连接到 Syncthing，请检查服务是否运行。"
            return result

        try:
            connections = self.system_connections()
            connected = 0
            total = 0
            devices = []
            for dev_id, info in connections.get("connections", {}).items():
                total += 1
                if info.get("connected"):
                    connected += 1
                devices.append({
                    "id": dev_id[:12] + "...",
                    "name": info.get("clientVersion", "unknown"),
                    "connected": info.get("connected", False),
                    "paused": info.get("paused", False),
                    "address": info.get("address", ""),
                    "inBytes": info.get("inBytesTotal", 0),
                    "outBytes": info.get("outBytesTotal", 0),
                })
            result["details"]["connections"] = {
                "total_devices": total,
                "connected_devices": connected,
                "devices": devices,
            }
        except SyncthingError as e:
            result["details"]["connections_error"] = str(e)

        # 尝试获取文件夹列表和状态
        try:
            folders_config = self.config_folders()
            folder_ids = []
            if isinstance(folders_config, list):
                for f in folders_config:
                    fid = f.get("id", "")
                    if fid:
                        folder_ids.append(fid)

            folder_statuses = []
            for fid in folder_ids:
                try:
                    fs = self.folder_status(fid)
                    folder_statuses.append({
                        "id": fid,
                        "label": fs.get("label", fid),
                        "state": fs.get("state", "unknown"),
                        "needFiles": fs.get("needFiles", 0),
                        "needBytes": fs.get("needBytes", 0),
                        "pullErrors": fs.get("pullErrors", 0),
                        "globalFiles": fs.get("globalFiles", 0),
                        "localFiles": fs.get("localFiles", 0),
                    })
                except SyncthingError:
                    pass

            result["details"]["folders"] = folder_statuses
        except SyncthingError:
            pass

        # 综合判断健康状态
        folders = result["details"].get("folders", [])
        has_error = any(f.get("pullErrors", 0) > 0 for f in folders)
        has_syncing = any(f.get("state") == "syncing" for f in folders)
        has_need = any(f.get("needFiles", 0) > 0 for f in folders)
        conn_ok = result["details"].get("connections", {}).get("connected_devices", 0) > 0

        if has_error:
            result["status"] = "warning"
            result["summary"] = "运行中，但有同步错误。"
        elif not conn_ok:
            result["status"] = "idle"
            result["summary"] = "运行中，暂无设备连接。"
        elif has_syncing:
            result["status"] = "syncing"
            result["summary"] = "正在同步中。"
        elif has_need:
            result["status"] = "pending"
            result["summary"] = "运行中，有待同步的文件。"
        else:
            result["status"] = "healthy"
            result["summary"] = "系统运行正常，所有设备均已同步。"
            if not folders:
                result["summary"] = "系统运行正常，没有配置文件夹。"

        return result


# ───────── 快捷方式 ─────────

def from_default() -> "SyncthingClient":
    """
    尝试从默认位置读取配置并创建客户端。
    需要先手动配置 api_key 和 base_url。
    """
    # 开发和测试用默认值（需要用户覆盖）
    raise NotImplementedError(
        "请创建 SyncthingClient(api_key='你的API_KEY') 实例"
    )
