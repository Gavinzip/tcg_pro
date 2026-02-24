#!/usr/bin/env python3
import discord
import os
import tempfile
import threading
import asyncio
import traceback
import market_report_vision
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer

def smart_split(text, limit=1900):
    chunks = []
    current_chunk = ""
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 > limit:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass # 安靜模式，不要在終端機一直洗版

def run_health_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
    server.serve_forever()

# 載入環境變數 (確保你在 .env 中加入了 DISCORD_BOT_TOKEN=你的機器人Token)
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

intents = discord.Intents.default()
# 必須開啟 message_content intent 才能讀取訊息與附件
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'✅ 機器人已成功登入為 {client.user}')
    print(f'📂 已成功載入 market_report_vision 模組')

@client.event
async def on_message(message):
    # 避免機器人自己回覆自己
    if message.author == client.user:
        return

    # 檢查是否有人傳了檔案，且「同時有 Tag (提及) 機器人」
    if client.user in message.mentions and message.attachments:
        for attachment in message.attachments:
            # 簡單過濾，只處理副檔名是圖片的檔案
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp']):
                
                # 1. 用「引用回覆」(replyTo) 傳送初始訊息
                reply_msg = await message.reply("🔍 收到圖片")
                
                # 2. 對這則回覆建立專屬的討論串
                thread = await reply_msg.create_thread(name=f"卡片分析報表", auto_archive_duration=60)

                # 3. 將 discord 上的圖片下載到本機暫存區
                temp_dir = tempfile.gettempdir()
                req_id = f"{message.id}_{attachment.id}"
                img_path = os.path.join(temp_dir, f"{req_id}_{attachment.filename}")
                await attachment.save(img_path)
                
                # Create a temporary output dir for this card's report files
                report_out_dir = os.path.join(temp_dir, f"report_{req_id}")
                os.makedirs(report_out_dir, exist_ok=True)
                
                try:
                    # 使用智慧異步處理優化的模組，支援瀏覽器複用與併發控制
                    print(f"⚙️ 開始異步分析圖片: {img_path}")
                    market_report_vision.REPORT_ONLY = True
                    api_key = os.getenv("MINIMAX_API_KEY")
                    
                    # 取代 asyncio.to_thread，直接 await 異步版模組
                    result = await market_report_vision.process_single_image(
                        img_path, api_key, out_dir=report_out_dir
                    )
                    
                    report_text = ""
                    out_images = []
                    if isinstance(result, tuple):
                        report_text, out_images = result
                    else:
                        report_text = result
                    
                    if report_text:
                        # 5. 成功拿到純淨的 Markdown 報表或內建的錯誤字串
                        if report_text.startswith("❌"):
                            await thread.send(report_text)
                        else:
                            # 傳送報表檔案 (如果有產生的話)
                            files = []
                            for img_f in out_images:
                                if os.path.exists(img_f):
                                    files.append(discord.File(img_f))
                            
                            if len(report_text) > 1900:
                                chunks = smart_split(report_text)
                                for i, chunk in enumerate(chunks):
                                    # 只在最後一個分段附加圖片
                                    if i == len(chunks) - 1:
                                        await thread.send(chunk, files=files)
                                    else:
                                        await thread.send(chunk)
                            else:
                                await thread.send(report_text, files=files)
                    else:
                         await thread.send("❌ 分析失敗，未發現卡片資訊或發生未知錯誤。")

                except Exception as e:
                    error_trace = traceback.format_exc()
                    await thread.send(f"❌ 執行 Python 腳本時發生系統異常：\n```python\n{error_trace[-1900:]}\n```")
                    
                finally:
                    # 6. 處理完畢，清理所有暫存檔案與資料夾
                    if os.path.exists(img_path): os.remove(img_path)
                    if os.path.exists(report_out_dir):
                        import shutil
                        shutil.rmtree(report_out_dir)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ 錯誤：找不到 DISCORD_BOT_TOKEN。請確保你在 '.env' 檔案中設定了它！")
    else:
        # 在背景啟動一個迷你伺服器，專門用來應付 Zeabur 的 8080 port 健康檢查！
        threading.Thread(target=run_health_server, daemon=True).start()
        print("啟動中...")
        client.run(TOKEN)
