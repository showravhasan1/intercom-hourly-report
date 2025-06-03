import requests
import os
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)  # ✅ Timezone-aware UTC datetime
one_hour_ago = now - timedelta(hours=1)
since = int(one_hour_ago.timestamp())
until = int(now.timestamp())

# Securely load from GitHub Actions secrets
INTERCOM_TOKEN = os.environ.get("INTERCOM_TOKEN")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK")

headers = {
    'Authorization': f'Bearer {INTERCOM_TOKEN}',
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

# === STEP 1: SEARCH CONVERSATIONS UPDATED THIS HOUR ===
search_url = 'https://api.intercom.io/conversations/search'
search_payload = {
    "query": {
        "field": "updated_at",
        "operator": ">=",
        "value": since
    },
    "pagination": {"per_page": 100}
}

resp = requests.post(search_url, headers=headers, json=search_payload)
conversations = resp.json().get('conversations', [])

# === STEP 2: TRACK FIRST REPLY PER AGENT IN HOUR ===
agent_chats = {}
agent_chat_details = {}

for conv in conversations:
    conv_id = conv.get("id")
    source = conv.get("source", {})
    delivered_as = source.get("delivered_as", "")
    ai_agent = conv.get("ai_agent") or {}
    source_type = ai_agent.get("source_type", "")

    if any(x in (delivered_as, source_type) for x in ["fin_preview", "workflow_preview", "operator_test", "bot"]):
        continue

    details_url = f"https://api.intercom.io/conversations/{conv_id}"
    details_resp = requests.get(details_url, headers=headers)
    conv_full = details_resp.json()

    parts = conv_full.get("conversation_parts", {}).get("conversation_parts", [])
    valid_parts = sorted(
        [p for p in parts if p.get("part_type") != "note"],
        key=lambda x: x.get("created_at", 0)
    )

    for part in valid_parts:
        created = part.get("created_at", 0)
        author = part.get("author", {})
        if (
            author.get("type") == "admin"
            and author.get("name") != "Fin"
            and author.get("id")
        ):
            # Check if the FIRST admin reply is inside the hour
            if since <= created < until:
                first_agent = author.get("id")
                reply_time = datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M")
                agent_chats.setdefault(first_agent, set())
                agent_chat_details.setdefault(first_agent, [])
                if conv_id not in agent_chats[first_agent]:
                    agent_chats[first_agent].add(conv_id)
                    agent_chat_details[first_agent].append((conv_id, reply_time))
                break
            else:
                break  # first reply was outside window
        # If a reply exists but by someone else (e.g. user), skip until we find admin or break

# === STEP 3: GET ADMIN NAMES ===
admins_url = 'https://api.intercom.io/admins'
admins_resp = requests.get(admins_url, headers=headers)
admins = admins_resp.json().get('admins', [])
id_to_name = {admin['id']: admin['name'] for admin in admins}

# === STEP 4: PRINT CONVERSATION DETAILS ===
print("\n=== Conversation Breakdown Per Agent ===")
for agent_id, chats in agent_chat_details.items():
    name = id_to_name.get(agent_id, 'Unknown')
    print(f"\n{name} ({len(chats)} chats):")
    for conv_id, timestamp in chats:
        print(f"- Chat ID: {conv_id} at {timestamp}")

# === STEP 5: FORMAT SLACK REPORT ===
report_lines = [f"🕐 *Hourly Chats per Agent* ({one_hour_ago.strftime('%H:%M')} – {now.strftime('%H:%M')} UTC)"]

if agent_chats:
    for agent_id, convs in agent_chats.items():
        name = id_to_name.get(agent_id, 'Unknown')
        report_lines.append(f"- *{name}*: {len(convs)} chats")
else:
    report_lines.append("No agent-handled chats this hour.")

# === STEP 6: SEND TO SLACK ===
requests.post(SLACK_WEBHOOK, json={"text": "\n".join(report_lines)})
