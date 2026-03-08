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
python3 openclaw_facade.py --mode full --json '{"name": "Mewtwo", "number": "150/165", "set_code": "SV1"}'
```

---

## � Flow B: For Simple Bots (Image-to-Market)
If you just want OpenClaw to handle everything (Vision + Report):
```python
from openclaw_facade import run_openclaw
result = await run_openclaw(image_path="card.jpg", mode="full")
```

---

## 📊 Precision Guide for AI Agents
To get 100% accurate market data, agents should pay attention to these fields:
- **`set_code`**: This is critical for PriceCharting/SNKRDUNK filters. Use codes like `SV1`, `OP01`, `EB01`.
- **`grade`**: Use `"PSA 10"`, `"BGS 9.5"`, or `"Raw"` (default).
- **`is_alt_art`**: Set to `true` if the card is a Parallel Art or Special Illustration Rare.

---

## 👾 Discord Interaction Protocol
1. **Isolate**: Always reply to the user by creating a **Thread**.
2. **Execute**: Run `run_openclaw` inside that thread.
3. **Report**: Post the Markdown analysis + the two generated posters (`poster_profile.png` & `poster_market.png`) back into the thread.

---

## 📁 Directory Structure
- `openclaw_facade.py`: The single entry point (Supports `--json` discovery).
- `scripts/`: Internal logic and visual assets (Do not modify).
- `SKILL.md`: This guide.
