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


    async def wait_for_choice(self) -> str | None:
        """等待使用者點選按鈕，回傳 'zh' | 'en' | None（逾時）"""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=60)
            return self.chosen_lang
        except asyncio.TimeoutError:
            return None

# 移除 LangSelectView，改為透過訊息內容判斷語言

class VersionSelectView(discord.ui.View):
    """
    版本選擇按鈕 View (航海王專用)。
    """
    def __init__(self, candidates):
        super().__init__(timeout=180)  # 3 分鐘超時
        self.chosen_url = None
        self._event = asyncio.Event()
        self.candidates = candidates
        
        # 動態建立按鈕
        for i, url in enumerate(candidates, start=1):
            btn = discord.ui.Button(label=f"選擇版本 {i}", style=discord.ButtonStyle.primary, custom_id=f"ver_{i}")
            btn.callback = self.make_callback(url, i)
            self.add_item(btn)

    def make_callback(self, url, idx):
        async def callback(interaction: discord.Interaction):
            self.chosen_url = url
            self._event.set()
            await interaction.response.edit_message(content=f"✅ 已選擇 **第 {idx} 個版本**，繼續生成報告...", view=None)
        return callback

    async def wait_for_choice(self) -> str | None:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=180)
            return self.chosen_url
        except asyncio.TimeoutError:
            return None


async def handle_image(attachment, message):
    """
    ** 並發核心函數（直接回覆，不再使用討論串）**
    """
    # 1. 判斷語言（預設中文，訊息包含 "en" 則切換英文）
    lang = "en" if "en" in message.content.lower() else "zh"
    
    # 2. 初始回覆
    init_msg_text = f"🃏 正在分析：**{attachment.filename}** (語言: {'English' if lang == 'en' else '中文'})..."
    init_msg = await message.reply(init_msg_text)
    
    # 使用當前頻道
    channel = message.channel

    # 3. 建立暫存資料夾（海報存這裡）
    card_out_dir = tempfile.mkdtemp(prefix=f"tcg_bot_{message.id}_")
    img_path = os.path.join(card_out_dir, attachment.filename)
    await attachment.save(img_path)

    try:
        print(f"⚙️ [並發] 開始分析: {attachment.filename} (lang={lang}, 來自 {message.author})")

        market_report_vision.REPORT_ONLY = True
        api_key = os.getenv("MINIMAX_API_KEY")

        # 1. 第一階段分析
        result = await market_report_vision.process_single_image(
            img_path, api_key, out_dir=card_out_dir, stream_mode=True, lang=lang
        )

        # 2. 處理「需要版本選擇」的狀態 (航海王)
        if isinstance(result, dict) and result.get("status") == "need_selection":
            candidates = result["candidates"]
            candidates = list(dict.fromkeys(candidates))
            
            await channel.send(f"⚠️ 偵測到**航海王**有多個候選版本，請根據下方預覽圖選擇正確的版本：")
            
            # 抓取每個候選版本的縮圖並以 Embed 呈現
            loading_msg = await channel.send("🖼️ 正在抓取版本預覽中...")
            loop = asyncio.get_running_loop()
            
            for i, url in enumerate(candidates, start=1):
                print(f"DEBUG: Fetching thumbnail for candidate {i}: {url}")
                _re, _url, thumb_url = await loop.run_in_executor(None, lambda: market_report_vision._fetch_pc_prices_from_url(url, skip_hi_res=True))
                slug = url.split('/')[-1]
                
                embed = discord.Embed(title=f"版本 #{i}", description=f"Slug: `{slug}`", url=url, color=0x3498db)
                if thumb_url:
                    embed.set_thumbnail(url=thumb_url)
                else:
                    embed.description += "\n*(無法取得預覽圖)*"
                await channel.send(embed=embed)

            await loading_msg.delete()

            ver_view = VersionSelectView(candidates)
            await channel.send("請點選下方按鈕進行選擇：", view=ver_view)
            selected_url = await ver_view.wait_for_choice()

            if not selected_url:
                await channel.send("⏰ 選擇逾時，已中止。")
                return

            # 使用選擇的 URL 重新抓取並完成報告
            final_pc_res = await loop.run_in_executor(None, market_report_vision._fetch_pc_prices_from_url, selected_url)
            pc_records, pc_url, pc_img_url = final_pc_res
            
            snkr_result = result["snkr_result"]
            snkr_records, final_img_url, snkr_url = snkr_result if snkr_result else (None, None, None)
            if not final_img_url and pc_img_url:
                final_img_url = pc_img_url
            
            jpy_rate = market_report_vision.get_exchange_rate()
            # 呼叫 helper 完成剩餘流程
            result = await market_report_vision.finish_report_after_selection(
                result["card_info"], pc_records, pc_url, pc_img_url, snkr_records, final_img_url, snkr_url, jpy_rate, result["out_dir"], result["lang"], stream_mode=True
            )

        # 3. 處理最終結果
        if isinstance(result, tuple):
            report_text, poster_data = result
        else:
            report_text = result
            poster_data = None

        # 4. 傳送文字報告
        if report_text:
            if report_text.startswith("❌"):
                await channel.send(report_text)
            else:
                for chunk in smart_split(report_text):
                    await channel.send(chunk)
        else:
            err_msg = "❌ Analysis failed." if lang == "en" else "❌ 分析失敗。"
            await channel.send(err_msg)
            return

        # 5. 生成海報
        if poster_data:
            try:
                out_paths = await market_report_vision.generate_posters(poster_data)
                if out_paths:
                    for path in out_paths:
                        if os.path.exists(path):
                            await channel.send(file=discord.File(path))
            except Exception as poster_err:
                print(f"⚠️ Poster generation error: {poster_err}")

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ 分析失敗 ({attachment.filename}): {e}", file=sys.stderr)
        await channel.send(
            f"❌ System error:\n```python\n{error_trace[-1900:]}\n```"
        )
    finally:
        shutil.rmtree(card_out_dir, ignore_errors=True)
        print(f"✅ 完成並清理暫存: {attachment.filename}")


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
