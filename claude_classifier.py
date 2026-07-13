#!/usr/bin/env python3
"""
Claude 分类助手 - 供 Claude Code 调用处理分类队列
"""
import json
from queue_manager import QueueManager


def process_queue():
    """处理待分类队列，由 Claude 手动调用"""
    qm = QueueManager()
    pending_tasks = qm.get_pending_tasks()

    if not pending_tasks:
        print("✓ 没有待处理的分类任务")
        return

    print(f"发现 {len(pending_tasks)} 个待处理任务\n")

    for task in pending_tasks:
        print(f"任务 ID: {task['id']}")
        print(f"创建时间: {task['timestamp']}")
        print(f"邮件数量: {len(task['emails'])}\n")

        print("待分类邮件:")
        print("=" * 80)
        for i, email in enumerate(task['emails'], 1):
            print(f"\n{i}. 邮件 ID: {email['id']}")
            print(f"   发件人: {email['sender']}")
            print(f"   主题: {email['subject']}")
            print(f"   摘要: {email['snippet'][:100]}...")
            print()

        print("=" * 80)
        print("\n请在 Claude Code 中分析以上邮件，然后调用 save_classifications() 保存结果")
        print(f"queue_id: {task['id']}\n")


def save_classifications(queue_id, classifications):
    """
    保存 Claude 的分类结果

    Args:
        queue_id: 队列任务 ID
        classifications: 分类列表，格式：
            [
                {"email_id": "...", "label": "Finance", "reason": "..."},
                {"email_id": "...", "label": "archive", "reason": "..."}
            ]
    """
    qm = QueueManager()
    qm.save_result(queue_id, classifications)
    print(f"✓ 已保存 {len(classifications)} 封邮件的分类结果")
    print(f"✓ 任务 {queue_id} 已完成")


def show_labels():
    """显示所有可用的 Gmail 标签"""
    from gmail_wrapper import GmailClient

    client = GmailClient()
    labels = client.list_labels()

    print("可用的 Gmail 标签:")
    print("=" * 60)

    # 按名称排序
    labels_sorted = sorted(labels, key=lambda x: x['name'])

    for label in labels_sorted:
        print(f"{label['id']:20s} - {label['name']}")

    print("=" * 60)


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 claude_classifier.py check       # 检查待处理队列")
        print("  python3 claude_classifier.py labels      # 显示所有标签")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'check':
        process_queue()
    elif cmd == 'labels':
        show_labels()
    else:
        print(f"未知命令: {cmd}")
