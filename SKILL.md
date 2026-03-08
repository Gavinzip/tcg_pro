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

## � Usage Modes

OpenClaw supports two primary operational modes via `openclaw_facade.py`:

### 1. JSON Recognition Mode (`mode="json"`)
Quickly identify a card and extract its metadata into a structured JSON format.
- **Native Mode**: Automatically used if no API Keys are present. Uses internal heuristics for basic identification.
- **LLM Mode**: Automatically enabled when `MINIMAX_API_KEY` or `OPENAI_API_KEY` is detected. Provides deep analysis and precise field extraction.

### 2. Full Market Report (`mode="full"`)
Generates a comprehensive market analysis, including:
- Recent sales history from PriceCharting and SNKRDUNK.
- Statistical trends (Highest, Lowest, Average).
- Two high-end visual posters (Profile & Market Data).
- Available in Traditional Chinese (`zh`) and English (`en`).
- **Note**: Requires LLM API keys for accurate data grounding.

## 🛠️ Integration Example

```python
import asyncio
from openclaw_facade import run_openclaw

async def main():
    # JSON Recognition
    card_info = await run_openclaw("card.jpg", mode="json")
    print(card_info)

    # Full Market Analysis
    report = await run_openclaw("card.jpg", mode="full", lang="zh")
    print(report["report_text"])

if __name__ == "__main__":
    asyncio.run(main())
```

## 🔑 Environment Variables
- `DISCORD_BOT_TOKEN`: Required for Discord integration.
- `MINIMAX_API_KEY`: Priority vision model for Precise recognition.
- `OPENAI_API_KEY`: Fallback vision model and report refinement.
