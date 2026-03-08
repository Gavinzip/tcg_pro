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

## � Discord Integration Guide (Best Practices)

When integrating OpenClaw into a Discord Bot, it is recommended to use **Threads** to keep the channel clean and provide a focused analysis space.

### 1. Unified Message & Thread Flow
Instead of flooding the channel, create a private/public thread for each analysis:

```python
async def on_message(message):
    if message.attachments:
        # 1. Reply to start the thread
        init_msg = await message.reply("🃏 收到圖片，正在建立分析討論串...")
        
        # 2. Create the thread
        thread = await init_msg.create_thread(name="卡片分析報表", auto_archive_duration=60)
        
        # 3. Add the user to the thread
        await thread.add_user(message.author)

        # 4. Save and run OpenClaw
        img_path = await attachment.save(temp_path)
        result = await run_openclaw(img_path, mode="full")
        
        # 5. Post chunks to thread
        for chunk in smart_split(result["report_text"]):
            await thread.send(chunk)
            
        # 6. Post posters
        if "poster_data" in result:
             paths = await mrv.generate_posters(result["poster_data"])
             for p in paths:
                 await thread.send(file=discord.File(p))
```

### 2. Handling Interaction (Buttons/Selects)
For cards with multiple versions (like One Piece SR/L Parallel), `run_openclaw` may return a `need_selection` status. You should use `discord.ui.View` with buttons or select menus to let the user choose the correct version slug before generating the final report.

## �🔑 Environment Variables
- `DISCORD_BOT_TOKEN`: Required for Discord integration.
- `MINIMAX_API_KEY`: Priority vision model for precise recognition.
- `OPENAI_API_KEY`: Fallback vision model and report refinement.
