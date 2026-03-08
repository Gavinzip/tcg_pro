#!/usr/bin/env python3
import sys
import os
import asyncio
import json
import argparse
import traceback

# 直接在當前目錄下執行，因為 tcg_pro copy 本身就是技能家目錄
import market_report_vision as mrv

async def run_openclaw(image_path, mode="json", lang="zh", debug_dir=None):
    """
    OpenClaw 核心門面函數
    mode: "json" (僅辨識輸出欄位) 或 "full" (完整行情與報表)
    """
    if not os.path.exists(image_path):
        return {"error": f"找不到圖片: {image_path}"}

    if debug_dir:
        mrv._set_debug_dir(debug_dir)

    api_key = os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "缺少 API_KEY (MINIMAX 或 OPENAI)"}

    try:
        if mode == "json":
            # 模式一：純影像辨識與欄位提取
            print(f"🔍 [OpenClaw] 模式: JSON 辨識 | 處理圖片: {os.path.basename(image_path)}")
            res = await mrv.process_image_for_candidates(image_path, api_key, lang=lang)
            if res and len(res) >= 1:
                card_info = res[0]
                # 儲存到 debug 資料夾 (如有)
                if debug_dir:
                    mrv._debug_save("openclaw_meta.json", json.dumps(card_info, indent=2, ensure_ascii=False))
                return card_info
            return {"error": "辨識失敗，未找到卡片資訊"}

        elif mode == "full":
            # 模式二：完整市場行情分析報告
            print(f"📊 [OpenClaw] 模式: FULL 報告 | 處理圖片: {os.path.basename(image_path)}")
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
