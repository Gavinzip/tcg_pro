# OpenClaw Skill 🐾

Welcome to **OpenClaw**, the high-performance TCG intelligence engine. This guide ensures that both human developers and AI agents can achieve professional results in seconds.

---

## ⚡ Quick Start (The 2-Minute Setup)

### 1. 🔑 API Configuration
Create a `.env` file in the project root to unlock full capabilities:

```env
# Essential for Japanese cards & precise text recognition
MINIMAX_API_KEY=your_minimax_key_here

# Used for fallback recognition and report formatting
OPENAI_API_KEY=your_openai_key_here
```
> [!IMPORTANT]
> **Native Mode**: If these keys are missing, OpenClaw enters "Native Mode," performing basic identification using only file metadata.

### 2. Choose Your Entry Flow
| Flow | Best For | Requirement |
| :--- | :--- | :--- |
| **Flow A (External)** | AI Agents with Vision | Pre-extracted JSON |
| **Flow B (Internal)** | Automation / Simple Bots | Image Path |

> [!IMPORTANT]
> Both flows are first-class and must stay supported:
> - Use **Flow A** when the agent already has card metadata (its own vision system).
> - Use **Flow B** when the agent wants OpenClaw to do vision with API keys.
> Never remove one flow as a fallback for the other.

### 🖼️ Poster Template Versions
- Supported versions: `v1`, `v3` (legacy alias `b3` is accepted and mapped to `v3`)
- Default: `v3` (must be treated as default unless user explicitly requests otherwise)
- CLI override: `--poster_version v1` or `--poster_version v3` (or `b3`)
- JSON mode can optionally include `"poster_version": "v1"` / `"v3"` / `"b3"` in the input metadata.

---

## 🚀 Flow A: For AI Agents (Vision-to-Market)
If you are an AI agent with image analysis capabilities (e.g., Gemini, GPT-4o), follow this **Step-by-Step Logic Flow**:

### 🧠 Step 1: Internal Reasoning (Agent-Only)
When you receive a TCG card image, follow this internal checklist:
1. **Vision Check**: Look for the **Card Name**, **ID Number** (e.g., 001/165), and **Set Code** (e.g., SV1, OP05).
2. **Metadata Extraction**: Do not guess. If you see "Pikachu" and "005/015", that is your core data.
3. **Format**: Construct a metadata JSON using the template below.

### 📋 Step 2: Metadata Template (Copy & Fill)
Ensure your JSON matches this structure exactly:
```json
{
  "name": "Card Name (e.g., Pikachu V)",
  "number": "Card Number (e.g., 001/185)",
  "set_code": "Set ID (e.g., SV4)",
  "grade": "Common / PSA 10 / Raw",
  "category": "Pokemon / One Piece / Union Arena",
  "is_alt_art": false
}
```

### 🛠️ Step 3: Execution (The Handoff)
Pass your extracted data to OpenClaw via the CLI. This skips internal vision and goes straight to the market report.

**CLI Command:**
```bash
python3 openclaw_facade.py --mode full --poster_version v3 --json '{"name": "Mewtwo", "number": "150/165", "set_code": "SV1"}'
```

---

## 🤖 Flow B: Auto-Vision (Agent Provides Image, Script Does the Rest)
If you prefer not to write JSON manually, or if you want the script's built-in LLM to analyze the image, you can simply pass the image path directly to the script. The script will automatically parse the image, generate the markdown report, and build the posters.

**CLI Command:**
```bash
python3 openclaw_facade.py "path/to/downloaded/image.jpg" --mode full --poster_version v3
```

*Note: This flow requires `MINIMAX_API_KEY` or `OPENAI_API_KEY` to be set in the `.env` file to function properly.*

---

## 📊 Precision Guide for AI Agents
To get 100% accurate market data, agents should pay attention to these fields:
- **`set_code`**: This is critical for PriceCharting/SNKRDUNK filters. Use codes like `SV1`, `OP01`, `EB01`.
- **`grade`**: Use `"PSA 10"`, `"BGS 9.5"`, or `"Raw"` (default).
- **`is_alt_art`**: Set to `true` if the card is a Parallel Art or Special Illustration Rare.

---

## 👾 Discord Interaction Protocol (CRITICAL FOR UI AGENTS)
When you receive a user's request with an image in Discord, you **MUST** follow these 3 steps exactly.

### ✅ Required Delivery Sequence (No Skips)
You MUST follow this exact order:
1. Create thread and capture `thread_id`.
2. Run OpenClaw and parse output JSON.
3. Send `report_text` into that `thread_id`.
4. Send `poster_data.profile` into that `thread_id`.
5. Send `poster_data.market` into that `thread_id`.

Never send only posters without `report_text`.
Never send any report/poster to the parent channel.
If `thread_id` is missing, stop and report an error instead of sending anything.

### 🚨 Transport Rule (Must Follow in This Environment)
For thread messaging, always use `action="send"` with `channelId=<thread_id>`.

**Correct (send text to thread):**
```python
message(
  action="send",
  channel="discord",
  channelId="1480914216608071832",
  message="訊息內容"
)
```

**Correct (send image to thread):**
```python
message(
  action="send",
  channel="discord",
  channelId="1480914216608071832",
  message="圖片說明",
  filePath="~/clawd/圖片.png"
)
```

**Wrong (do not use):**
```python
message(
  action="thread-reply",
  target="主頻道ID",
  threadId="ThreadID"
)
```

`thread-reply` with `target` routes to the parent channel in this setup and may not deliver inside the thread.  
After creating the thread, always store that thread ID and reuse it as `channelId` for both text and image sends.

### 🚫 Forbidden Behaviors
- Sending posters to main channel.
- Sending posters before sending `report_text`.
- Skipping thread creation and posting directly to parent channel.
- If OpenClaw returns both text and posters, sending only posters.

**1. Isolate (Create Thread):**
You MUST NOT reply with the report in the main channel. You MUST use your thread-creation action/tool to create a new thread for the user's request.

For `message(action="thread-create", ...)`, the parameter name is **`threadName`** (not `name`).

**Correct:**
```python
message(
  action="thread-create",
  channel="discord",
  guildId="1469685526427734181",
  threadName="Gastly SV2a 市場報告"
)
```

**Wrong:**
```python
message(
  action="thread-create",
  channel="discord",
  guildId="1469685526427734181",
  name="Gastly SV2a 市場報告"
)
```

**2. Execute (Run openclaw):**
You MUST execute `openclaw_facade.py` in FULL mode. You have TWO ways to do this, choose ONE based on your capabilities:

- **Flow A (External JSON)**: If you extract the card info yourself, run:
  `python3 openclaw_facade.py --mode full --poster_version v3 --json '{"name": "...", "number": "...", "set_code": "...", "grade": "..."}'`

- **Flow B (Image Pass-through)**: If you want the script's native vision to do the work, download the image and pass it:
  `python3 openclaw_facade.py "path/to/downloaded/image.jpg" --mode full --poster_version v3`

- **Optional switch to legacy layout**: add `--poster_version v1` only if user asks for old design.

**Important Note:** The script will always output a JSON containing the textual report AND the absolute paths to the generated poster images. It looks exactly like this:
```json
{
  "report_text": "Markdown string of the market report...",
  "poster_data": {
    "profile": "/path/to/report_xxx_profile.png",
    "market": "/path/to/report_xxx_data.png"
  },
  "status": "success"
}
```

### 🔒 Output Contract (Non-Negotiable)
When your tool returns JSON from OpenClaw:
- `report_text` is the **source of truth** for message content. Post it as-is.
- Do **not** rewrite, summarize, translate, or reformat `report_text`.
- Do **not** invent your own report template.
- Always upload both `poster_data.profile` and `poster_data.market`.
- If `poster_data` is empty or missing, treat that as a tool error and report it explicitly.
- If your messaging tool cannot send text+file in one call, send in 3 separate calls in the SAME thread: text -> profile image -> market image.

**3. Report (Post in Thread):**
You MUST read the output JSON from the script. Then, send a new message in the created thread where:
- The **message text** is exactly the string found in `"report_text"`.
- You **MUST upload BOTH image files** listed under `"poster_data"` (`profile` and `market` paths). Do not assume the files don't exist; wait for them and USE YOUR LOCAL SYSTEM TOOLS to read and attach those two absolute file paths!
If you forget to upload the posters, the user will be very disappointed.

### 🧪 Final Pre-Send Checklist
Before sending anything, verify:
- I have a valid `thread_id`.
- All sends use `action="send"` and `channelId=<thread_id>`.
- I will send `report_text` first.
- I will send both posters after text.
- I am not sending to parent channel.

## 📁 Directory Structure
- `openclaw_facade.py`: The single entry point (Supports `--json` discovery).
- `scripts/`: Internal logic and visual assets (Do not modify).
- `SKILL.md`: This guide.
