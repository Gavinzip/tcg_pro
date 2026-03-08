# OpenClaw Skill 🐾

Welcome to **OpenClaw**, the high-performance TCG intelligence engine. Whether you are a developer or an AI agent, this guide will help you get started in seconds.

---

## ⚡ Quick Start

### 1. 🔑 API Configuration
To unlock full vision and market analysis, create a `.env` file in the root or set these environment variables:

```env
# Priority: Precise recognition & Japanese card support
MINIMAX_API_KEY=your_minimax_key_here

# Fallback: General recognition & report refinement
OPENAI_API_KEY=your_openai_key_here
```
> [!TIP]
> If no keys are provided, OpenClaw falls back to **Native Mode** (Basic identification based on file metadata).

### 2. Choose Your Entry Flow

OpenClaw is designed to be "smart-agent aware." You can choose between two primary workflows:

#### **Flow A: External Recognition (Agent Data)**
*Best if your AI Agent already analyzed the image.*
- **Action**: Pass pre-extracted JSON to `card_info`.
- **Result**: Skips vision phase; performs instant market analysis.
```python
result = await run_openclaw(mode="full", card_info={"name": "Pikachu V", "number": "005/015"})
```

#### **Flow B: Internal Recognition (Image Path)**
*Best for end-to-end automation.*
- **Action**: Pass the `image_path`.
- **Result**: OpenClaw handles Vision (Native/LLM) + Market Analysis + Posters.
```python
result = await run_openclaw(image_path="card.jpg", mode="full")
```

---

## 📊 Technical Specifications

### Card Metadata Schema (`card_info`)
Regardless of the flow, card data follows this standard:
```json
{
  "name": "Venusaur ex",
  "number": "003/165",
  "set_code": "SV1en",
  "grade": "PSA 10",
  "category": "Pokemon",
  "is_alt_art": false,
  "market_heat": "High",
  "illustrator": "Mitsuhiro Arita"
}
```

### Disambiguation Protocol (`need_selection`)
If a card has multiple versions (e.g., One Piece Parallel Art), `run_openclaw` returns:
- `status`: `"need_selection"`
- `candidates`: List of candidate URLs.
**Action**: Show candidates to the user, then call `generate_report_from_selected(card_info, selected_url)`.

---

## 🤖 For AI Agents & Robots

If you are an AI agent with image analysis capabilities (like Gemini, GPT-4o, etc.), you should follow **Flow A** for maximum efficiency.

### 🧩 The "Handoff" Protocol
1. **Analyze**: Use your own internal vision tools to identify the card's `name`, `number`, and `set_code`.
2. **Transform**: Format your findings into the `card_info` JSON schema defined above.
3. **Execute**: Call OpenClaw via CLI using the `--json` or `--json_file` flag to generate the final market report.

**CLI Example for Agents:**
```bash
python3 openclaw_facade.py --mode full --json '{"name": "Mewtwo", "number": "150/165"}'
```

---

## 👾 Discord Integration Guide
Use **Threads** to isolate analysis and keep channels clean:
1. Reply to user -> Create Thread.
2. Run `run_openclaw`.
3. Post results (Markdown text + Generated Posters) into the thread.

---

## 📁 Directory Structure
- `openclaw_facade.py`: Unified entry point (Supports CLI `--json` discovery).
- `scripts/`: Internal logic and visual assets.
- `SKILL.md`: This guide.
