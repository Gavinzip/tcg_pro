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

def _normalize_card_info(card_info, native_mode=False):
    data = dict(card_info or {})
    neutral_desc = "N/A（資料不足）"
    native_desc = "N/A（未啟用 API 視覺辨識）"
    default_desc = native_desc if native_mode else neutral_desc

    defaults = {
        "name": "Unknown Card",
        "number": "Unknown",
        "set_code": "",
        "grade": "Ungraded",
        "jp_name": "",
        "c_name": "",
        "category": "Pokemon",
        "release_info": "Unknown",
        "illustrator": "Unknown",
        "market_heat": default_desc,
        "collection_value": default_desc,
        "competitive_freq": default_desc,
        "features": "N/A",
        "is_alt_art": False,
    }

    for k, v in defaults.items():
        cur = data.get(k)
        if cur is None or (isinstance(cur, str) and not cur.strip()):
            data[k] = v

    # Normalize common "unknown" literals into neutral text.
    unknown_markers = {"unknown", "n/a", "na", "none", "null", "未提供", "未知"}
    for k in ("market_heat", "collection_value", "competitive_freq", "features"):
        cur = str(data.get(k, "")).strip()
        if not cur or cur.lower() in unknown_markers:
            data[k] = default_desc if k != "features" else "N/A"

    if isinstance(data.get("is_alt_art"), str):
        data["is_alt_art"] = data["is_alt_art"].strip().lower() == "true"

    return data

async def run_openclaw(image_path=None, mode="json", lang="zh", poster_version="v3", debug_dir=None, card_info=None):
    """
    OpenClaw 核心門面函數 (Facade)
    
    支援兩條路徑：
    A. 外部辨識 (External): 由 AI 代理傳入 card_info (JSON)，跳過內部辨識。
    B. 內部辨識 (Internal): 傳入 image_path，腳本自動調用 Native 或 LLM 辨識。
    """
    if debug_dir:
        mrv._set_debug_dir(debug_dir)

    api_key = (os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    current_card_info = None

    # --- 階段 1: 取得卡片資訊 (Recognition Phase) ---
    if card_info:
        print(f"📡 [OpenClaw] 使用外部傳入的 JSON 資訊，跳過視覺辨識。")
        current_card_info = _normalize_card_info(card_info, native_mode=False)
    else:
        if not image_path or not os.path.exists(image_path):
            return {"error": f"找不到圖片或未提供 card_info: {image_path}"}
            
        is_llm_mode = bool(api_key)
        vision_mode_str = "LLM (OpenAI/MiniMax)" if is_llm_mode else "Native (OpenClaw)"
        print(f"📡 [OpenClaw] 辨識模式: {vision_mode_str}")

        if is_llm_mode:
            print(f"🔍 [OpenClaw] 執行 LLM 辨識 | 處理圖片: {os.path.basename(image_path)}")
            res = await mrv.process_image_for_candidates(image_path, api_key, lang=lang)
            if res and len(res) >= 1:
                current_card_info = _normalize_card_info(res[0], native_mode=False)
            else:
                return {"error": "LLM 辨識失敗"}
        else:
            # Native Mode 佔位邏輯
            print(f"🔍 [OpenClaw] 執行 Native 辨識 | 處理圖片: {os.path.basename(image_path)}")
            current_card_info = _normalize_card_info({
                "name": os.path.basename(image_path).split('.')[0], # 直接從檔名猜
                "number": "Unknown",
                "set_code": "",
                "grade": "Ungraded",
                "note": "使用 Native 模式 (未偵測到 API Key)"
            }, native_mode=True)

    # 儲存到 debug 資料夾 (如有)
    if debug_dir and current_card_info:
        mrv._debug_save("openclaw_meta.json", json.dumps(current_card_info, indent=2, ensure_ascii=False))

    # --- 階段 2: 執行後續流程 ---
    try:
        if mode == "json":
            return current_card_info

        elif mode == "full":
            # 模式二：完整市場行情分析報告
            print(f"📊 [OpenClaw] 執行 FULL 報告流程 | 語言: {lang}")
            
            # FULL 模式即使有外部 card_info，如果需要高品質分析仍建議有 API Key (用於描述潤色)
            # 但我們允許在有 card_info 的情況下繼續執行爬蟲
            mrv.REPORT_ONLY = True
            
            # 將 stream_mode 改為 False，強制產生海報圖片
            result = await mrv.process_single_image(
                image_path,
                api_key,
                out_dir=debug_dir,
                stream_mode=False,
                poster_version=poster_version,
                lang=lang,
                external_card_info=current_card_info
            )
            
            if isinstance(result, tuple):
                report_text, out_paths = result
                
                # out_paths 是由 image_generator 回傳的 [profile_path, data_path]
                poster_data = {}
                if isinstance(out_paths, list):
                    poster_data["profile"] = str(out_paths[0]) if len(out_paths) > 0 else ""
                    poster_data["market"] = str(out_paths[1]) if len(out_paths) > 1 else ""
                else:
                    poster_data = out_paths

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
    parser.add_argument("image", nargs="?", help="Path to the card image (optional if --json or --json_file is provided)")
    parser.add_argument("--mode", choices=["json", "full"], default="json", help="Mode: json (recognition) or full (report)")
    parser.add_argument("--lang", choices=["zh", "en"], default="zh", help="Language for output")
    parser.add_argument(
        "--poster_version",
        choices=["v1", "v3", "b3"],
        default="v3",
        help="Poster template version (v1 or v3, b3 is alias of v3; default: v3)",
    )
    parser.add_argument("--debug", help="Directory to save debug logs and artifacts")
    parser.add_argument("--json", help="Raw JSON string of card metadata (Flow A)")
    parser.add_argument("--json_file", help="Path to a JSON file containing card metadata (Flow A)")
    
    args = parser.parse_args()
    
    from dotenv import load_dotenv
    load_dotenv()

    # 處理傳入的 JSON 資訊
    external_card_info = None
    if args.json:
        external_card_info = json.loads(args.json)
    elif args.json_file and os.path.exists(args.json_file):
        with open(args.json_file, 'r', encoding='utf-8') as f:
            external_card_info = json.load(f)

    result = asyncio.run(run_openclaw(
        args.image, 
        mode=args.mode, 
        lang=args.lang, 
        poster_version=args.poster_version,
        debug_dir=args.debug, 
        card_info=external_card_info
    ))
    print(json.dumps(result, indent=2, ensure_ascii=False))
