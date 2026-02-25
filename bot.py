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


async def handle_image(attachment, message):
    """
    ** 並發核心函數（stream 模式）**

    流程：
    1. 建立討論串
    2. 下載圖片
    3. AI 分析 + 爬蟲 → 立即傳送文字報告
    4. （非同步）生成海報 → 生成完成後補傳

    這樣使用者不需要等海報生成完才看到文字報告。
    """
    # 1. 立刻回覆並建立討論串
    reply_msg = await message.reply(f"🔍 收到圖片：**{attachment.filename}**，分析中...")
    thread = await reply_msg.create_thread(name="卡片分析報表", auto_archive_duration=60)

    # 2. 建立暫存資料夾（海報存這裡）
    card_out_dir = tempfile.mkdtemp(prefix=f"tcg_bot_{message.id}_")
    img_path = os.path.join(card_out_dir, attachment.filename)
    await attachment.save(img_path)

    try:
        print(f"⚙️ [並發] 開始分析: {attachment.filename} (來自 {message.author})")

        market_report_vision.REPORT_ONLY = True
        api_key = os.getenv("MINIMAX_API_KEY")

        # 3. 使用 stream_mode=True：
        #    process_single_image 拿到文字報告後立即回傳，
        #    不等海報生成（海報生成約需額外 10~20 秒）
        result = await market_report_vision.process_single_image(
            img_path, api_key, out_dir=card_out_dir, stream_mode=True
        )

        if isinstance(result, tuple):
            report_text, poster_data = result
        else:
            report_text = result
            poster_data = None

        # 4. 立即傳送文字報告（不等海報）
        if report_text:
            if report_text.startswith("❌"):
                await thread.send(report_text)
            else:
                for chunk in smart_split(report_text):
                    await thread.send(chunk)
        else:
            await thread.send("❌ 分析失敗：未發現卡片資訊或發生未知錯誤。")
            return

        # 5. 生成海報（等文字報告傳出後才開始）
        #    使用者此時已經可以看到文字報告，海報生成完再補傳
        if poster_data:
            await thread.send("🖼️ 海報生成中，請稍候...")
            try:
                out_paths = await market_report_vision.generate_posters(poster_data)
                if out_paths:
                    for path in out_paths:
                        if os.path.exists(path):
                            await thread.send(file=discord.File(path))
                else:
                    await thread.send("⚠️ 海報生成失敗，但文字報告已完成。")
            except Exception as poster_err:
                await thread.send(f"⚠️ 海報生成時發生錯誤：{poster_err}")

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ 分析失敗 ({attachment.filename}): {e}", file=sys.stderr)
        await thread.send(
            f"❌ 執行 Python 腳本時發生系統異常：\n```python\n{error_trace[-1900:]}\n```"
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
