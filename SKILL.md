---
name: openclaw
description: TCG Vision & Market Intelligence skill. Identifies card images and generates market reports.
---

# OpenClaw: TCG Vision & Market Intelligence

OpenClaw is a specialized skill for identifying TCG cards (Pokémon, One Piece) from images and providing real-time market valuations.

## 🛠 Usage Modes

### 1. Mode: JSON (Recognition Only)
Analyzes an image and returns structured metadata.
- **Command**: `python3 openclaw_facade.py <image_path> --mode json`
- **Output**: JSON object with `name`, `number`, `set_code`, `grade`, etc.

### 2. Mode: FULL (Market Report)
Performs recognition AND crawls market sources for a full arbitrage report and poster.
- **Command**: `python3 openclaw_facade.py <image_path> --mode full`
- **Output**: Markdown report & optional poster images.

## ⚙️ Configuration
- Requires `MINIMAX_API_KEY` or `OPENAI_API_KEY` in `.env`.
- Facade: `openclaw_facade.py`.
- Core: `market_report_vision.py`.
