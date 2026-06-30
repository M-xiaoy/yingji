"""
映记 v0.2 — 能力声明模块

程序启动时，映记扫描自己能访问的数据和功能，
生成一个结构化描述。外部 AI 通过 chat() 连接时，
映记先发能力声明，让对方知道「我能做什么、不能做什么」。
"""

from config import AI_NAME, AI_DESCRIPTION, SECURITY_LEVEL_READ, SECURITY_LEVEL_WRITE, SECURITY_LEVEL_DELETE


def discover() -> dict:
    """
    扫描并返回当前映记实例的能力声明。
    v1：静态声明，后续改为动态扫描挂载的服务。
    """
    # 这里后续会动态扫描已注册的 YingjiService
    # v1 静态声明（后续由 capabilities.py 动态注册接管）
    return {
        "name": AI_NAME,
        "version": "0.2.0",
        "description": AI_DESCRIPTION,
        "services": {
            "memory": {
                "description": "映记内置的记忆系统，管理程序记忆的存、查、删。",
                "operations": {
                    "recall": {
                        "description": "检索与给定话题相关的记忆",
                        "security_level": SECURITY_LEVEL_READ,
                        "requires_confirmation": False,
                        "parameters": {
                            "query": "搜索关键词（中文优先）",
                            "top_k": "返回条数（默认 3，上限 10）",
                        },
                    },
                    "store": {
                        "description": "存储一条新的记忆",
                        "security_level": SECURITY_LEVEL_WRITE,
                        "requires_confirmation": True,
                        "parameters": {
                            "content": "记忆内容",
                            "type": "类型（fact/preference/decision）",
                            "importance": "重要性 0-1",
                        },
                    },
                    "list": {
                        "description": "列出最近的记忆，按时间排序",
                        "security_level": SECURITY_LEVEL_READ,
                        "requires_confirmation": False,
                        "parameters": {
                            "limit": "返回条数（默认 10）",
                            "type": "按类型过滤（可选）",
                        },
                    },
                    "delete": {
                        "description": "删除一条指定的记忆",
                        "security_level": SECURITY_LEVEL_DELETE,
                        "requires_confirmation": True,
                        "parameters": {
                            "id": "要删除的记忆 ID",
                        },
                    },
                },
            },
        },
        "limitations": [
            "不执行代码",
            "不访问外部网络",
            "不操作本地文件系统",
            "不可修改程序自身的配置",
        ],
        "security": {
            "read_level": SECURITY_LEVEL_READ,
            "write_level": SECURITY_LEVEL_WRITE,
            "delete_level": SECURITY_LEVEL_DELETE,
            "write_requires_confirmation": True,
            "delete_requires_dual_confirmation": True,
        },
    }


def describe() -> str:
    """
    返回纯文本版能力描述，供 chat() 作为系统提示词使用。
    """
    cap = discover()
    lines = [
        f"名称：{cap['name']}",
        f"版本：{cap['version']}",
        f"描述：{cap['description']}",
        "",
        f"我能做什么：",
    ]
    for service_name, service in cap["services"].items():
        lines.append(f"  [{service_name}] {service['description']}")
        for op_name, op in service["operations"].items():
            confirm = "（需确认）" if op.get("requires_confirmation") else ""
            lines.append(f"    - {op_name}: {op['description']}{confirm}")
            if op.get("parameters"):
                for pname, pdesc in op["parameters"].items():
                    lines.append(f"      · {pname}: {pdesc}")

    lines.extend([
        "",
        "我不能做的：",
    ] + [f"  - {lim}" for lim in cap["limitations"]])

    return "\n".join(lines)
