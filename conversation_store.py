from collections import defaultdict
from datetime import datetime

conversations = defaultdict(list)


def add_message(call_id, role, content):
    conversations[call_id].append({
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat()
    })


def get_recent(call_id, n=6):
    return conversations[call_id][-n:]
