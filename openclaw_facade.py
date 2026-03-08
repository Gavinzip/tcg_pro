#!/usr/bin/env python3
import sys
import os
import asyncio
import json
import argparse
import traceback

# 將 scripts 目錄加入路徑，讓它可以載入內部的 market_report_vision
sys.path.append(os.path.join(os.path.dirname(__file__), "scripts"))
import market_report_vision as mrv

async def run_openclaw(image_path, mode="json", lang="zh", debug_dir=None):
    """
    OpenClaw 核心門面函數
    模式一 (Native): 當環境變數缺少 API Key 時，使用系統內建辨識 (目前為 Mock/佔位)。
    模式二 (LLM): 當環境變數有 API Key 時，自動啟用 OpenAI/MiniMax 高階辨識。
    """
    if not os.path.exists(image_path):
        return {"error": f"找不到圖片: {image_path}"}

    if debug_dir:
        mrv._set_debug_dir(debug_dir)

    api_key = os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY")
    
    # 影像辨識邏輯選擇
    is_llm_mode = api_key is not None
    vision_mode_str = "LLM (OpenAI/MiniMax)" if is_llm_mode else "Native (OpenClaw)"
    print(f"📡 [OpenClaw] 辨識模式: {vision_mode_str}")

    try:
        if mode == "json":
            # 模式一：純影像辨識與欄位提取
            print(f"🔍 [OpenClaw] 執行 JSON 辨識 | 處理圖片: {os.path.basename(image_path)}")
            
            if is_llm_mode:
                res = await mrv.process_image_for_candidates(image_path, api_key, lang=lang)
                if res and len(res) >= 1:
                    card_info = res[0]
                else:
                    return {"error": "LLM 辨識失敗"}
            else:
                # Native Mode 佔位邏輯
                card_info = {
                    "name": os.path.basename(image_path).split('.')[0], # 直接從檔名猜
                    "number": "Unknown",
                    "set_code": "",
                    "grade": "Common",
                    "note": "使用 Native 模式 (未偵測到 API Key)，請手動確認資訊或補上 API Key"
                }
            
            # 儲存到 debug 資料夾 (如有)
            if debug_dir:
                mrv._debug_save("openclaw_meta.json", json.dumps(card_info, indent=2, ensure_ascii=False))
            return card_info

        elif mode == "full":
            # 模式二：完整市場行情分析報告
            print(f"📊 [OpenClaw] 執行 FULL 報告 | 處理圖片: {os.path.basename(image_path)}")
            
            if not is_llm_mode:
                 return {"error": "FULL 模式 (行情分析) 目前必須使用 LLM 辨識以確保準確度，請設置 API Key。"}

            mrv.REPORT_ONLY = True
            
            result = await mrv.process_single_image(
                image_path, api_key, out_dir=debug_dir, stream_mode=True, lang=lang
            )
            
            if isinstance(result, tuple):
                report_text, poster_data = result
                return {
                    "report_text": report_text,
                    "poster_data": poster_data,
                    "status": "success"
                }
            return {"report_text": result, "status": "success"}

    except Exception as e:
        error_msg = traceback.format_exc()
        return {"error": str(e), "trace": error_msg}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenClaw: TCG Vision & Market Intelligence")
    parser.add_argument("image", help="Path to the card image")
    parser.add_argument("--mode", choices=["json", "full"], default="json", help="Mode: json (recognition) or full (report)")
    parser.add_argument("--lang", choices=["zh", "en"], default="zh", help="Language for output")
    parser.add_argument("--debug", help="Directory to save debug logs and artifacts")
    
    args = parser.parse_args()
    
    from dotenv import load_dotenv
    load_dotenv()

    result = asyncio.run(run_openclaw(args.image, mode=args.mode, lang=args.lang, debug_dir=args.debug))
    print(json.dumps(result, indent=2, ensure_ascii=False))
