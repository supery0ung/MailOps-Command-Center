"""
队列管理模块 - 处理 Claude 分类审核队列
"""
import json
import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional


QUEUE_FILE = ".claude/classify_queue.json"
RESULTS_FILE = ".claude/classify_results.json"


class QueueManager:
    """管理分类队列和结果文件"""

    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir
        self.queue_path = os.path.join(base_dir, QUEUE_FILE)
        self.results_path = os.path.join(base_dir, RESULTS_FILE)
        self._ensure_files_exist()

    def _ensure_files_exist(self):
        """确保队列和结果文件存在"""
        os.makedirs(os.path.dirname(self.queue_path), exist_ok=True)
        if not os.path.exists(self.queue_path):
            with open(self.queue_path, 'w') as f:
                json.dump([], f)
        if not os.path.exists(self.results_path):
            with open(self.results_path, 'w') as f:
                json.dump({}, f)

    def add_to_queue(self, emails: List[Dict]) -> str:
        """
        添加邮件到审核队列

        Args:
            emails: 邮件列表，每个包含 id, subject, sender, snippet

        Returns:
            queue_id: 队列任务 ID
        """
        queue_id = str(uuid.uuid4())

        # 读取现有队列
        with open(self.queue_path, 'r') as f:
            queue = json.load(f)

        # 添加新任务
        queue_item = {
            "id": queue_id,
            "timestamp": datetime.now().isoformat(),
            "status": "pending",
            "emails": emails
        }
        queue.append(queue_item)

        # 写回文件
        with open(self.queue_path, 'w') as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)

        return queue_id

    def get_result(self, queue_id: str) -> Optional[Dict]:
        """
        获取队列任务的分类结果

        Args:
            queue_id: 队列任务 ID

        Returns:
            分类结果字典，如果还未完成则返回 None
        """
        if not os.path.exists(self.results_path):
            return None

        with open(self.results_path, 'r') as f:
            results = json.load(f)

        return results.get(queue_id)

    def mark_completed(self, queue_id: str):
        """
        标记队列任务为已完成

        Args:
            queue_id: 队列任务 ID
        """
        # 读取队列
        with open(self.queue_path, 'r') as f:
            queue = json.load(f)

        # 更新状态
        for item in queue:
            if item["id"] == queue_id:
                item["status"] = "completed"
                break

        # 写回文件
        with open(self.queue_path, 'w') as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)

    def get_pending_tasks(self) -> List[Dict]:
        """
        获取所有待处理的队列任务

        Returns:
            待处理任务列表
        """
        with open(self.queue_path, 'r') as f:
            queue = json.load(f)

        return [item for item in queue if item["status"] == "pending"]

    def save_result(self, queue_id: str, classifications: List[Dict]):
        """
        保存分类结果（由 Claude 调用）

        Args:
            queue_id: 队列任务 ID
            classifications: 分类结果列表
        """
        # 读取现有结果
        with open(self.results_path, 'r') as f:
            results = json.load(f)

        # 添加新结果
        results[queue_id] = {
            "timestamp": datetime.now().isoformat(),
            "classifications": classifications
        }

        # 写回文件
        with open(self.results_path, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        # 标记队列任务为已完成
        self.mark_completed(queue_id)

    def clean_old_results(self, days: int = 7):
        """
        清理旧的结果文件

        Args:
            days: 保留天数
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=days)

        # 清理结果文件
        with open(self.results_path, 'r') as f:
            results = json.load(f)

        cleaned_results = {
            k: v for k, v in results.items()
            if datetime.fromisoformat(v["timestamp"]) > cutoff
        }

        with open(self.results_path, 'w') as f:
            json.dump(cleaned_results, f, indent=2, ensure_ascii=False)

        # 清理队列文件
        with open(self.queue_path, 'r') as f:
            queue = json.load(f)

        cleaned_queue = [
            item for item in queue
            if datetime.fromisoformat(item["timestamp"]) > cutoff
            or item["status"] == "pending"
        ]

        with open(self.queue_path, 'w') as f:
            json.dump(cleaned_queue, f, indent=2, ensure_ascii=False)
