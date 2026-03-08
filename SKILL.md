# OpenClaw Skill 🐾

OpenClaw is a powerful TCG intelligence engine designed for collectors and players. It provides instant card recognition, market value analysis, and investment-grade reporting for Pokémon and One Piece TCG.

## 📂 Directory Structure

```text
tcg_pro copy/
├── openclaw_facade.py      # Main entry point (Facade)
├── SKILL.md                # This documentation
└── scripts/                # Core logic and assets
    ├── fonts/              # Typography assets
    ├── templates/          # HTML report templates
    ├── market_report_vision.py # Market analysis engine
    └── image_generator.py  # High-end report generation
```

## 🚀 Usage Modes

OpenClaw supports two primary operational modes via `run_openclaw(image_path, mode, lang)`:

### 1. JSON Recognition Mode (`mode="json"`)
Quickly identify a card and extract its metadata.
- **Native Mode**: Fallback if no API Keys are present.
- **LLM Mode**: Precise field extraction using `MINIMAX_API_KEY` or `OPENAI_API_KEY`.

**Example Output Schema:**
```json
{
  "name": "Venusaur ex",
  "number": "003/165",
  "set_code": "SV1en",
  "grade": "PSA 10",
  "category": "Pokemon",
  "is_alt_art": false,
  "market_heat": "High...",
  "collection_value": "Medium...",
  "features": "Full art, holo...",
  "illustrator": "Mitsuhiro Arita"
}
```

### 2. Full Market Report (`mode="full"`)
Generates a comprehensive analysis. **Requires LLM API keys.**

**Return Structure:**
- `report_text`: A detailed Markdown analysis.
- `poster_data`: (Optional) Metadata used to generate posters.
- `status`: `"success"` or `"need_selection"`.

#### ⚠️ Disambiguation Protocol (`need_selection`)
If the system finds multiple versions for a card (e.g., One Piece Parallel Art), it returns:
```json
{
  "status": "need_selection",
  "candidates": ["url_to_version_1", "url_to_version_2"],
  "card_info": { ... }
}
```
**Action Required**: The developer must show these candidates to the user and then call `generate_report_from_selected(card_info, selected_pc_url, selected_snkr_url)` to finish.

## 👾 Discord Integration Guide

When integrating into Discord, use **Threads** to isolate analysis:

```python
# Create thread -> Send "Analyzing..."
result = await run_openclaw(img_path, mode="full")

if result.get("status") == "need_selection":
    # Show buttons with candidates
    # Wait for user click -> call generate_report_from_selected
else:
    # Send report_text and generated posters
```

## 🔑 Environment Variables
- `MINIMAX_API_KEY`: Priority vision model.
- `OPENAI_API_KEY`: Fallback vision model and report refinement.
