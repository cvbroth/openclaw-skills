"""Reversible metadata operations; never unlink original files or dependants."""

from datetime import datetime, timezone


class ArtifactManagement:
    def edit_artifact(self, pid, aid, data):
        from .tasks import ACTIVE
        from ..artifact_project import emit_viewer

        if not isinstance(data, dict) or not data or set(data) - {"name", "recycled"}:
            raise ValueError("仅允许name/recycled字段。")
        with self.lock:
            p = self.get(pid)
            a = next((a for a in p["artifacts"] if a["artifact_id"] == aid), None)
            if a is None:
                raise ValueError("产物ID不存在。")
            if aid == p.get("source_artifact_id") and "recycled" in data:
                raise ValueError("原件请通过项目级操作管理。")
            if (
                any(t["status"] in ACTIVE for t in p.get("tasks", []))
                or a.get("preview_render", {}).get("status") in ACTIVE
            ):
                raise ValueError("请先取消或等待活动任务/预览结束。")
            if "name" in data:
                name = data["name"]
                if (
                    not isinstance(name, str)
                    or not name.strip()
                    or len(name) > 120
                    or any(ord(c) < 32 for c in name)
                ):
                    raise ValueError("name: 需要1–120字符，不含控制字符。")
                a["display_name_override"] = name.strip()
            if "recycled" in data:
                if type(data["recycled"]) is not bool:
                    raise ValueError("recycled: boolean required")
                a["recycled"] = data["recycled"]
            a.setdefault("management_history", []).append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "changes": dict(data),
                }
            )
            self.save(self.path(pid), p)
            emit_viewer(self.path(pid), p)
            return a

    def archive_task(self, pid, tid, archived):
        from .tasks import ACTIVE

        if type(archived) is not bool:
            raise ValueError("archived: boolean required")
        with self.lock:
            p = self.get(pid)
            t = self.task(p, tid)
            if t["status"] in ACTIVE:
                raise ValueError("运行任务请先取消或等待终态。")
            t["archived"] = archived
            self.save(self.path(pid), p)
            return {"task_id": tid, "archived": archived}
