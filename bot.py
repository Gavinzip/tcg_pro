#!/usr/bin/env python3
import discord
import os
import shutil
import tempfile
import threading
import asyncio
import traceback
import sys
import market_report_vision
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer

# ============================================================
# ⚠️ JINA AI RATE LIMITER 說明（重要！請勿刪除此說明）
# ============================================================
# market_report_vision.py 內部的 fetch_jina_markdown() 函數使用了一個
# 全域的 sliding window rate limiter：
#   - _jina_requests_queue: 記錄最近60秒內的請求時間戳
#   - _jina_lock: threading.Lock，確保多執行緒安全
#   - 限制：18 requests / 60 seconds（留兩次緩衝給 Jina 每分鐘20次的限額）
#
# 在併發情境下（多個用戶同時送圖），rate limiter 依然有效，因為：
# 1. Python module 是 singleton，所有 task 共用同一份 _jina_requests_queue
# 2. _jina_lock 是 threading.Lock，在 tasks 跑的 executor threads 中也是 thread-safe 的
# 3. 超過限額的 task 會自動 sleep 等待，不會炸掉 Jina
#
# 每次分析一張卡約會用掉 4~8 次 Jina 請求（PC: 2~3次, SNKRDUNK: 2~5次）
# ============================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass  # 安靜模式

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
    server.serve_forever()

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def smart_split(text, limit=1900):
    chunks = []
    current_chunk = ""
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > limit:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    return chunks


class LangSelectView(discord.ui.View):
    """
    語言選擇按鈕 View。
    當使用者點選後，設定 chosen_lang 並喚醒等待中的 Event。
    """
    def __init__(self):
        super().__init__(timeout=60)  # 60 秒未點選自動超時
        self.chosen_lang = None
        self._event = asyncio.Event()

    @discord.ui.button(label="🇹🇼  中文", style=discord.ButtonStyle.primary, custom_id="lang_zh")
    async def choose_zh(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.chosen_lang = "zh"
        self._event.set()
        await interaction.response.edit_message(
            content="✅ 已選擇**中文**，報告生成中...",
            view=None
        )

    @discord.ui.button(label="🇺🇸  English", style=discord.ButtonStyle.secondary, custom_id="lang_en")
    async def choose_en(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.chosen_lang = "en"
        self._event.set()
        await interaction.response.edit_message(
            content="✅ **English** selected, generating report...",
            view=None
        )

    async def wait_for_choice(self) -> str | None:
        """等待使用者點選按鈕，回傳 'zh' | 'en' | None（逾時）"""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=60)
            return self.chosen_lang
        except asyncio.TimeoutError:
            return None


async def handle_image(attachment, message):
    """
    ** 並發核心函數（stream 模式 + 語言選擇）**

    流程：
    1. 詢問使用者選擇語言（中文 / English）
    2. 建立討論串
    3. 下載圖片
    4. AI 分析 + 爬蟲 → 立即傳送文字報告
    5. （非同步）生成海報 → 生成完成後補傳
    """
    # 1. 先詢問語言
    lang_view = LangSelectView()
    lang_msg = await message.reply(
        f"🃏 收到圖片：**{attachment.filename}**\n請選擇報告語言 / Please select report language：",
        view=lang_view
    )

    lang = await lang_view.wait_for_choice()

    if lang is None:
        # 逾時未選擇
        await lang_msg.edit(
            content="⏰ 語言選擇逾時，已自動使用中文。Card language selection timed out, defaulting to Chinese.",
            view=None
        )
        lang = "zh"

    # 2. 建立討論串
    thread_name = "Card Analysis Report" if lang == "en" else "卡片分析報表"
    thread = await lang_msg.create_thread(name=thread_name, auto_archive_duration=60)

    # 3. 建立暫存資料夾（海報存這裡）
    card_out_dir = tempfile.mkdtemp(prefix=f"tcg_bot_{message.id}_")
    img_path = os.path.join(card_out_dir, attachment.filename)
    await attachment.save(img_path)

    try:
        print(f"⚙️ [並發] 開始分析: {attachment.filename} (lang={lang}, 來自 {message.author})")

        market_report_vision.REPORT_ONLY = True
        api_key = os.getenv("MINIMAX_API_KEY")

        result = await market_report_vision.process_single_image(
            img_path, api_key, out_dir=card_out_dir, stream_mode=True, lang=lang
        )

        if isinstance(result, tuple):
            report_text, poster_data = result
        else:
            report_text = result
            poster_data = None

        # 4. 立即傳送文字報告
        if report_text:
            if report_text.startswith("❌"):
                await thread.send(report_text)
            else:
                for chunk in smart_split(report_text):
                    await thread.send(chunk)
        else:
            err_msg = "❌ Analysis failed: No card info found or unknown error." if lang == "en" else "❌ 分析失敗：未發現卡片資訊或發生未知錯誤。"
            await thread.send(err_msg)
            return

        # 5. 生成海報
        if poster_data:
            wait_msg = "🖼️ Generating poster, please wait..." if lang == "en" else "🖼️ 海報生成中，請稍候..."
            await thread.send(wait_msg)
            try:
                out_paths = await market_report_vision.generate_posters(poster_data)
                if out_paths:
                    for path in out_paths:
                        if os.path.exists(path):
                            await thread.send(file=discord.File(path))
                else:
                    fail_msg = "⚠️ Poster generation failed, but the text report is complete." if lang == "en" else "⚠️ 海報生成失敗，但文字報告已完成。"
                    await thread.send(fail_msg)
            except Exception as poster_err:
                err_msg = f"⚠️ Poster generation error: {poster_err}" if lang == "en" else f"⚠️ 海報生成時發生錯誤：{poster_err}"
                await thread.send(err_msg)

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ 分析失敗 ({attachment.filename}): {e}", file=sys.stderr)
        await thread.send(
            f"❌ System error:\n```python\n{error_trace[-1900:]}\n```"
        )

    finally:
        shutil.rmtree(card_out_dir, ignore_errors=True)
        print(f"✅ [並發] 完成並清理: {attachment.filename}")


@client.event
async def on_ready():
    print(f'✅ 機器人已成功登入為 {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if client.user in message.mentions and message.attachments:
        for attachment in message.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp']):
                # 每張圖各自建立獨立並發 Task
                asyncio.create_task(handle_image(attachment, message))


if __name__ == "__main__":
    if not TOKEN:
        print("❌ 錯誤：找不到 DISCORD_BOT_TOKEN。")
    else:
        threading.Thread(target=run_health_server, daemon=True).start()
        print("啟動中...")
        client.run(TOKEN)
