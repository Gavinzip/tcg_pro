import argparse
import subprocess
import re
import requests
import json
import time
import urllib.parse
import concurrent.futures
import os
import base64
import threading
import image_generator
import tempfile
from collections import deque
from dotenv import load_dotenv

load_dotenv()

REPORT_ONLY = False

_original_print = print
def print(*args, **kwargs):
    if REPORT_ONLY and not kwargs.get('force', False):
        return
    if 'force' in kwargs:
        del kwargs['force']
    _original_print(*args, **kwargs)

_jina_requests_queue = deque()
_jina_lock = threading.Lock()

def fetch_jina_markdown(target_url):
    global _jina_requests_queue
    
    # Rate Limiter: 18 requests per 60 seconds (1 minute)
    MAX_REQUESTS = 18
    WINDOW_SIZE = 60.0
    
    with _jina_lock:
        now = time.time()
        # Remove requests older than 60 seconds
        while _jina_requests_queue and now - _jina_requests_queue[0] > WINDOW_SIZE:
            _jina_requests_queue.popleft()
            
        if len(_jina_requests_queue) >= MAX_REQUESTS:
            # Calculate sleep time required to let the oldest request expire
            sleep_time = WINDOW_SIZE - (now - _jina_requests_queue[0])
            if sleep_time > 0:
                print(f"⏳ Jina API rate limit approaching ({MAX_REQUESTS}/min). Pausing for {sleep_time:.1f} seconds to cool down...")
                time.sleep(sleep_time)
                
            # After sleeping, the oldest request should have expired, so we record the new "now"
            now = time.time()
            while _jina_requests_queue and now - _jina_requests_queue[0] > WINDOW_SIZE:
                _jina_requests_queue.popleft()
                
        _jina_requests_queue.append(now)

    print(f"Fetching: {target_url}...")
    jina_url = f"https://r.jina.ai/{target_url}"
    
    for attempt in range(3):
        try:
            response = requests.get(jina_url, timeout=60)
            if response.status_code == 429:
                print(f"⚠️ Jina 發生 429 頻率限制 (嘗試 {attempt+1}/3). 暫停 1 秒後重試...")
                time.sleep(1)
                continue
                
            response.raise_for_status()
            return response.text
            
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 429:
                print(f"⚠️ Jina 發生 429 頻率限制 (嘗試 {attempt+1}/3). 暫停 1 秒後重試...")
                time.sleep(1)
                continue
                
            print(f"Fetch error for {target_url}: {e}")
            return ""
            
    return ""

def get_exchange_rate():
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD")
        data = resp.json()
        return data['rates']['JPY']
    except:
        return 150.0

def extract_price(price_str):
    cleaned = re.sub(r'[^\d.]', '', price_str)
    try:
        return float(cleaned)
    except:
        return 0.0

def search_pricecharting(name, number, set_code, is_alt_art=False):
    # Strip prefix like "No." (e.g. "No.025" -> "25"), then apply lstrip('0')
    _num_raw = number.split('/')[0]
    _digits_only = re.search(r'\d+', _num_raw)
    number_clean = _digits_only.group(0).lstrip('0') if _digits_only else _num_raw.lstrip('0')
    if not number_clean: number_clean = '0'
    
    # Try with set code first, if available
    queries_to_try = []
    if set_code:
        queries_to_try.append(f"{name} {set_code} {number_clean}".replace(" ", "+"))
        queries_to_try.append(f"{name} {set_code}".replace(" ", "+"))
    queries_to_try.append(f"{name} {number_clean}".replace(" ", "+"))

    md_content = ""
    search_url = ""
    
    for query in queries_to_try:
        search_url = f"https://www.pricecharting.com/search-products?q={query}&type=prices"
        md_content = fetch_jina_markdown(search_url)
        if md_content and "Search Results" in md_content or md_content and "Your search for" in md_content:
            break
        elif md_content and "PriceCharting" in md_content:
            # might have landed on product directly
            break
            
    if not md_content:
        return None, None
    
    product_url = None
    
    if "Your search for" in md_content or "Search Results" in md_content:
        urls = re.findall(r'(https://www\.pricecharting\.com/game/[^/]+/[^" )\]]+)', md_content)
        # Deduplicate while preserving order
        urls = list(dict.fromkeys(urls))
        
        valid_urls = []
        for u in urls:
            u_end = u.split('/')[-1].lower()
            # If the card name itself is in the URL, that's a good primary indicator.
            name_slug = re.sub(r'[^a-zA-Z0-9]', '-', name.lower())
            
            # Match the number strictly (e.g., "-226" at the end, or "-226-")
            if re.search(rf'(?<!\d){number_clean}(?!\d)', u_end):
                valid_urls.append(u)
            elif name_slug in u_end:
                # Less strict fallback: if the character name is in the url, but we might get the wrong set. 
                # Let's demand the set_code if number is missing.
                if set_code and set_code.lower() in u_end:
                    valid_urls.append(u)
                
        if not valid_urls:
            print(f"DEBUG: No PC product URL stringently matched the card number {number_clean} or set.")
            return None, None
            
        product_url = valid_urls[0]
        
        # Filter based on is_alt_art
        if not is_alt_art:
            for u in valid_urls:
                lower_u = u.lower()
                if "manga" not in lower_u and "parallel" not in lower_u and "alt-art" not in lower_u and "-sp" not in lower_u:
                    product_url = u
                    break
        else:
            for u in valid_urls:
                lower_u = u.lower()
                if "manga" in lower_u or "parallel" in lower_u or "alt-art" in lower_u or "-sp" in lower_u:
                    product_url = u
                    break
        
    # Final verification: Some completely unrelated cards get snagged if their ID happens to contain "226" inside it.
    if product_url:
        print(f"DEBUG: Selected PC product URL: {product_url}")
        md_content = fetch_jina_markdown(product_url)
    else:
        print(f"DEBUG: Landed directly on PC product page")
        product_url = search_url
    
    lines = md_content.split('\n')
    records = []
    
    date_regex = r'\|\s*(\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2}\s\d{1,2},\s\d{4})\s*\|'
    
    for line in lines:
        if re.search(date_regex, line):
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 5:
                date_str = parts[1]
                # Find all prices in the line; use the LAST one (the actual sale price)
                # The $6/month subscribe fee may appear first in locked rows
                all_prices = re.findall(r'\$([\d,]+\.\d{2})', line)
                if not all_prices:
                    continue
                # Skip if only the subscribe fee ($6.00) found
                real_prices = [p for p in all_prices if p not in ('6.00',)]
                if not real_prices:
                    continue
                price_str = real_prices[-1]
                price_usd = float(price_str.replace(',', ''))
                
                title_clean = line.replace(" ", "").lower()
                detected_grade = None
                if "psa10" in title_clean:
                    detected_grade = "PSA 10"
                elif "psa9" in title_clean:
                    detected_grade = "PSA 9"
                elif "psa8" in title_clean:
                    detected_grade = "PSA 8"
                elif not re.search(r'(psa|bgs|cgc|grade|gem)', title_clean):
                    # Ungraded: no grading company keywords
                    # Note: 'mint' removed from exclusion since NM/Near Mint describes raw card condition
                    detected_grade = "Ungraded"
                        
                if detected_grade:
                    records.append({
                        "date": date_str,
                        "price": price_usd,
                        "grade": detected_grade
                    })

    
    # Also parse the PC bottom summary prices (e.g. "Ungraded$33.46", "PSA 10$125.00")
    # These are summary/avg prices shown at the bottom of the page
    from datetime import datetime
    today_str = datetime.now().strftime('%Y-%m-%d')
    grade_summary_map = {
        'Ungraded': 'Ungraded',
        'PSA 10': 'PSA 10',
        'PSA 9': 'PSA 9',
        'PSA 8': 'PSA 8',
    }
    existing_grades = set(r['grade'] for r in records)
    
    for line in lines:
        for grade_label, grade_key in grade_summary_map.items():
            label_nospace = grade_label.replace(' ', '')
            # Match "Ungraded$33.46" or "PSA10$125.00" style summary lines
            if re.match(rf'^{re.escape(label_nospace)}\$[\d,]+\.\d{{2}}$', line.replace(' ', '')):
                # Only add if we have no date-based records for this grade
                if grade_key not in existing_grades:
                    price_match = re.search(r'\$[\d,]+\.\d{2}', line)
                    if price_match:
                        price_usd = extract_price(price_match.group(0))
                        # Add as a single synthetic record with today's date
                        records.append({
                            "date": today_str,
                            "price": price_usd,
                            "grade": grade_key,
                            "note": "PC avg price (sold listings locked)"
                        })
                        print(f"DEBUG: Added PC summary price for {grade_key}: ${price_usd:.2f}")
    
    records.sort(key=lambda x: x['date'], reverse=True)
    resolved_url = product_url if product_url else search_url
    
    # Try to extract the card image URL from the PC product page markdown
    # Jina renders it as: ![Image N: ...](https://product-images.s3.amazonaws.com/...)
    pc_img_url = None
    img_patterns = [
        r'!\[.*?\]\((https://product-images\.s3\.amazonaws\.com/[^\)]+)\)',
        r'!\[.*?\]\((https://[^)]+\.jpg[^\)]*)\)',
        r'!\[.*?\]\((https://[^)]+\.png[^\)]*)\)',
        r'!\[.*?\]\((https://[^)]+\.webp[^\)]*)\)',
    ]
    for pat in img_patterns:
        m = re.search(pat, md_content)
        if m:
            pc_img_url = m.group(1)
            print(f"DEBUG: Found PC card image: {pc_img_url}")
            break
    
    return records, resolved_url, pc_img_url


def search_snkrdunk(en_name, jp_name, number, set_code, is_alt_art=False):
    # Strip prefix like "No." (e.g. "No.025" -> "25"), then apply lstrip('0')
    _num_raw = number.split('/')[0]
    _digits_only = re.search(r'\d+', _num_raw)
    number_clean = _digits_only.group(0).lstrip('0') if _digits_only else _num_raw.lstrip('0')
    if not number_clean: number_clean = '0'
    number_padded = number_clean.zfill(3)

    terms_to_try = []
    
    # SNKRDUNK search is highly accurate with Set Code (e.g. "ピカチュウ S8a-G", "ピカチュウ SV-P")
    if set_code and jp_name:
        terms_to_try.append(f"{jp_name} {set_code}")
    if set_code:
        terms_to_try.append(f"{en_name} {set_code}")
        
    if jp_name:
        terms_to_try.extend([
            f"{jp_name} {number_clean}",
            f"{jp_name} {number_padded}"
        ])
        
    terms_to_try.extend([
        f"{en_name} {number_clean}",
        f"{en_name} {number_padded}"
    ])
    
    product_id = None
    
    for term in terms_to_try:
        q = urllib.parse.quote_plus(term)
        search_url = f"https://snkrdunk.com/search?keywords={q}"
        md_content = fetch_jina_markdown(search_url)
        
        matches = re.findall(r'\[(.*?)\]\([^\)]*?/apparels/(\d+)[^\)]*?\)', md_content)
        
        seen = set()
        unique_matches = []
        for title, pid in matches:
            if pid not in seen:
                seen.add(pid)
                unique_matches.append((title, pid))
                
        filtered_by_number = []
        for title, pid in unique_matches:
            # Drop Jina image prefixes
            title_clean = re.sub(r'(?i)image\s*\d+:\s*', '', title).lower()
            # Drop all https CDN links to prevent their timestamp digits from matching the card number
            title_clean = re.sub(r'https?://[^\s()\]]+', '', title_clean)
            
            # SNKRDUNK always pads Pokemon/One Piece numbers to at least 3 digits
            # We strictly enforce the padded number to prevent matching Jina listing indices (e.g. " 4 Pikachu")
            if number_padded in title_clean or f"{number_clean}/" in title_clean:
                # If a set_code was extracted by AI, ensure it appears in the SNKRDUNK title (which always includes set codes like [SV-P 004])
                if set_code and set_code.lower() not in title_clean:
                    continue
                filtered_by_number.append((title, pid))
                
        if not filtered_by_number:
            continue # If no titles specifically have the card number, do not guess
            
        unique_matches = filtered_by_number
                
        if unique_matches:
            product_id = unique_matches[0][1] # default to first result
            
            # Filter logic
            if not is_alt_art:
                for title, pid in unique_matches:
                    lower_t = title.lower()
                    if "コミパラ" not in lower_t and "manga" not in lower_t and "パラレル" not in lower_t \
                       and "-p" not in lower_t and "-sp" not in lower_t and "parallel" not in lower_t:
                        product_id = pid
                        break
            else:
                for title, pid in unique_matches:
                    lower_t = title.lower()
                    if "コミパラ" in lower_t or "manga" in lower_t or "パラレル" in lower_t \
                       or "-p" in lower_t or "-sp" in lower_t or "parallel" in lower_t:
                        product_id = pid
                        break
            
            break
        
        time.sleep(1)
        
    if not product_id:
        return None, None, None
        
    print(f"Found SNKRDUNK Product ID: {product_id}")
    
    sales_url = f"https://snkrdunk.com/apparels/{product_id}/sales-histories"
    sales_md = fetch_jina_markdown(sales_url)
    
    img_match = re.search(r'!\[.*?\]\((https://cdn.snkrdunk.com/.*?)\)', sales_md)
    img_url = img_match.group(1) if img_match else ""
    
    records = []
    lines = sales_md.split('\n')
    date_regex = r'^(\d{4}/\d{2}/\d{2}|\d+\s*(分|時間|日)前|\d+\s+(minute|hour|day)s?\s+ago)$'
    
    for i in range(len(lines)):
        line_clean = lines[i].strip()
        
        if re.match(date_regex, line_clean, re.IGNORECASE):
            date_found = line_clean
            grade_found = ""
            price_jpy = 0
            
            for j in range(i+1, min(i+10, len(lines))):
                l_j = lines[j].strip()
                if not l_j:
                    continue
                
                if not grade_found and not re.search(r'^\d', l_j.replace(',', '')):
                    grade_found = l_j
                    continue
                    
                if grade_found and re.search(r'^\d{1,3}(,\d{3})*$', l_j):
                    price_jpy = extract_price(l_j)
                    break
                    
            if grade_found and price_jpy > 0:
                parsed_grade = grade_found.strip()
                if parsed_grade:
                    records.append({
                        "date": date_found,
                        "price": price_jpy,
                        "grade": parsed_grade
                    })
                
    resolved_url = f"https://snkrdunk.com/apparels/{product_id}" if product_id else None
                
    return records, img_url, resolved_url

def analyze_image_with_minimax(image_path, api_key):
    # 清理 API Key，避免複製貼上時混入隱藏的換行或特殊字元 (\u2028 等) 導致 \u2028 latin-1 編碼錯誤
    api_key = api_key.strip().replace('\u2028', '').replace('\n', '').replace('\r', '')
    # Determine MIME type
    mime = "image/jpeg"
    ext = image_path.lower().split(".")[-1]
    if ext == "png":
        mime = "image/png"
    elif ext == "webp":
        mime = "image/webp"

    # Encode image
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

    url = "https://api.minimax.io/v1/coding_plan/vlm"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    prompt = """請以純 JSON 格式回覆，不要包含任何 markdown 語法 (如 ```json 起始碼)，只需輸出 JSON 本體。
你是一位於寶可夢卡牌 (Pokemon TCG) 領域專精的鑑定與估價專家。請分析這張卡片圖片，並精準提取以下 13 個欄位的資訊：
{
  "name": "英文名稱 (必填，例如 Venusaur ex 或 Lillie 等)",
  "set_code": "系列代號 (選填，位於卡牌左下或右下角，如 SV1a, S8a-G, SV-P, 151 等。如果沒有印則留空字串)",
  "number": "卡片編號 (必填，請提取「完整」字串，包含斜線與前後文字，絕度不要自己去除 0！例如 001/015, 004/SV-P, 114/100, 077/067 等)",
  "grade": "卡片等級 (必填，如果有PSA/BGS等鑑定盒，印有10就填如 PSA 10, 否則如果是裸卡就填 Ungraded)",
  "jp_name": "日文名稱 (選填，沒有請留空字串)",
  "c_name": "中文名稱 (選填，沒有請留空字串)",
  "category": "卡片類別 (填寫 Pokemon 或 One Piece，預設 Pokemon)",
  "release_info": "發行年份與系列 (必填，從卡牌標誌或特徵推斷，如 2023 - 151)",
  "illustrator": "插畫家 (必填，左下角或右下角的英文名，看不清可寫 Unknown)",
  "market_heat": "市場熱度描述 (必填，開頭填寫 High / Medium / Low，後面白話文理由請務必使用『繁體中文』撰寫)",
  "features": "卡片特點 (必填，包含全圖、特殊工藝等，每一行請用 \\n 換行區隔重點，請務必使用『繁體中文』撰寫)",
  "collection_value": "收藏價值評估 (必填，開頭填寫 High / Medium / Low，後面白話文評論請務必使用『繁體中文』撰寫)",
  "competitive_freq": "競技頻率評估 (必填，開頭填寫 High / Medium / Low，後面白話文評論請務必使用『繁體中文』撰寫)",
  "is_alt_art": "是否為漫畫背景(Manga/Comic)或異圖(Parallel)？布林值 true/false。請極度仔細觀察卡片的『背景』：如果背景是一格一格的【黑白漫畫分鏡】，請填 true；如果背景只有閃電、特效、或單純場景，就算它是 SEC 也是普通版，『必須』填 false！"
}"""

    payload = {
        "prompt": prompt,
        "image_url": f"data:{mime};base64,{encoded_string}"
    }

    print("--------------------------------------------------")
    print(f"👁️‍🗨️ [Minimax Vision AI] 正在解析卡片影像: {image_path}...")
    
    for attempt in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Minimax API 網路錯誤 (嘗試 {attempt+1}/3): {e}")
            if attempt == 2:
                return {}
            time.sleep(2)
    if response.status_code != 200:
        print(f"API Error: 請求失敗 ({response.status_code})\n{response.text}")
        return None

    data = response.json()
    try:
        content = data.get('content', '')
        if not content:
            raise KeyError("content key not found or empty")
        # Clean up markdown JSON block if model still outputs it
        content = content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        print(f"✅ 解析成功！提取到卡片：{result.get('name')} #{result.get('number')}\n")
        print("--- DEBUG JSON ---")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("------------------\n")
        return result

    except Exception as e:
        print(f"❌ Failed to parse JSON response: {e}")
        print(f"Raw response: {data}")
        return None

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image_path", nargs='+', required=True, help="卡片圖片的本機路徑 (可傳入多張圖片)")
    parser.add_argument("--api_key", required=False, help="Minimax API Key (若未指定，則從環境變數 MINIMAX_API_KEY 讀取)")
    parser.add_argument("--out_dir", required=False, help="若指定，會將結果儲存至給定的資料夾")
    parser.add_argument("--report_only", action="store_true", help="若加入此參數，將只輸出最終 Markdown 報告，隱藏抓取與除錯日誌")
    
    args = parser.parse_args()
    
    global REPORT_ONLY
    REPORT_ONLY = args.report_only
    
    api_key = args.api_key or os.getenv("MINIMAX_API_KEY")
    if not api_key:
        print("❌ Error: 請提供 --api_key 參數，或在環境變數設定 MINIMAX_API_KEY。", force=True)
        return
        
    for img_path in args.image_path:
        print(f"\n==================================================")
        print(f"🔄 開始處理圖片: {img_path}")
        print(f"==================================================")
        await process_single_image(img_path, api_key, args.out_dir)

async def process_single_image(image_path, api_key, out_dir=None):
    if not os.path.exists(image_path):
        print(f"❌ Error: 找不到圖片檔案 -> {image_path}", force=True)
        return
        
    # 第一階段：透過大模型辨識圖片資訊
    card_info = analyze_image_with_minimax(image_path, api_key)
    
    if not card_info:
        print("❌ 卡片影像辨識失敗，中止處理此圖片。", force=True)
        return
    
    # 從 AI 回傳的 JSON 提取必備資訊
    name = card_info.get("name", "Unknown")
    set_code = card_info.get("set_code", "")
    jp_name = card_info.get("jp_name", "")
    c_name = card_info.get("c_name", "")
    number = str(card_info.get("number", "0"))
    grade = card_info.get("grade", "Ungraded")
    category = card_info.get("category", "Pokemon")
    release_info = card_info.get("release_info", "Unknown")
    illustrator = card_info.get("illustrator", "Unknown")
    market_heat = card_info.get("market_heat", "Unknown")
    features = card_info.get("features", "Unknown")
    collection_value = card_info.get("collection_value", "Unknown")
    competitive_freq = card_info.get("competitive_freq", "Unknown")
    is_alt_art = card_info.get("is_alt_art", False)
    
    # 第二階段：執行爬蟲抓取資料
    print("--------------------------------------------------")
    print(f"🌐 正在從網路(PC & SNKRDUNK)抓取市場行情 (異圖/特殊版: {is_alt_art})...")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_pc = executor.submit(search_pricecharting, name, number, set_code, is_alt_art)
        future_snkr = executor.submit(search_snkrdunk, name, jp_name, number, set_code, is_alt_art)
        
        pc_result = future_pc.result()
        snkr_result = future_snkr.result()
        
        pc_records = pc_result[0] if pc_result else None
        pc_url = pc_result[1] if pc_result else None
        pc_img_url = pc_result[2] if pc_result and len(pc_result) > 2 else None
        
        snkr_records = snkr_result[0] if snkr_result else None
        img_url = snkr_result[1] if snkr_result else None
        snkr_url = snkr_result[2] if snkr_result else None
    
    # Fallback: if SNKRDUNK has no image, use PriceCharting image
    if not img_url and pc_img_url:
        print(f"ℹ️ SNKRDUNK 無圖片，改用 PriceCharting 圖片作為 fallback: {pc_img_url}")
        img_url = pc_img_url
    
    jpy_rate = get_exchange_rate()
    
    # 第三階段：產生 Markdown 報告
    
    c_name_display = c_name if c_name else jp_name if jp_name else name
    
    report_lines = []
    report_lines.append(f"# MARKET REPORT GENERATED")
    report_lines.append("")
    report_lines.append(f"⚡ {c_name_display} ({name}) #{number}")
    report_lines.append(f"💎 等級：{grade}")
    
    category_display = "寶可夢卡牌" if category.lower() == "pokemon" else "航海王卡牌" if category.lower() == "one piece" else category
    report_lines.append(f"🏷️ 版本：{category_display}")
    
    report_lines.append(f"🔢 編號：{number}")
    if release_info:
        report_lines.append(f"📅 發行：{release_info}")
    if illustrator:
        report_lines.append(f"🎨 插畫家：{illustrator}")
    
    report_lines.append("---")
    report_lines.append("\n🔥 市場與收藏分析\n")
    report_lines.append(f"🔥 市場熱度\n{market_heat}\n")
    if features:
        feat_formatted = features.replace('\\n', '\n')
        report_lines.append(f"✨ 卡片特點\n{feat_formatted}\n")
    if collection_value:
        report_lines.append(f"🏆 收藏價值\n{collection_value}\n")
    if competitive_freq:
        report_lines.append(f"⚔️ 競技頻率\n{competitive_freq}\n")
        
    report_lines.append("---")
    
    report_lines.append("📊 近期成交紀錄 (由新到舊)\n🏦 PriceCharting 成交紀錄")
    async def count_30_days(records_list, tgt_grade):
        cutoff = datetime.now() - timedelta(days=30)
        return len([r for r in (records_list or []) if r.get('grade') == tgt_grade and (await _parse_d(r['date'])) > cutoff])
    if pc_records:
        pc_target_records = [r for r in pc_records if r['grade'] == grade]
        if pc_target_records:
            for r in pc_target_records[:10]:
                report_lines.append(f"📅 {r['date']}      💰 ${r['price']:.2f} USD      📝 狀態：{r['grade']}")
            prices = [r['price'] for r in pc_target_records]
            report_lines.append("📊 統計資料")
            report_lines.append(f"　💰 最高成交價：${max(prices):.2f} USD")
            report_lines.append(f"　💰 最低成交價：${min(prices):.2f} USD")
            report_lines.append(f"　💰 平均成交價：${sum(prices)/len(prices):.2f} USD")
            report_lines.append(f"　📈 資料筆數：{len(prices)} 筆")
        else:
            report_lines.append(f"PriceCharting: 無 {grade} 等級的卡片資料")
    else:
        report_lines.append("PriceCharting: 無此卡片資料")
    
    report_lines.append("\n---\n🏯 SNKRDUNK 成交紀錄")
    if snkr_records:
        if '10' in grade:
            valid_snkr_grades = ['S', 'PSA10', 'PSA 10']
            target_disp = 'S (PSA 10)'
        elif grade.lower() == 'ungraded':
            valid_snkr_grades = ['A']
            target_disp = 'A (Raw)'
        else:
            valid_snkr_grades = [grade, grade.replace(' ', '')]
            target_disp = grade
            
        snkr_target_records = [r for r in snkr_records if r['grade'] in valid_snkr_grades]
        if snkr_target_records:
            for r in snkr_target_records[:10]:
                usd_price = r['price'] / jpy_rate
                report_lines.append(f"📅 {r['date']}      💰 ¥{int(r['price']):,} (~${usd_price:.0f} USD)      📝 狀態：{r['grade']}")
            prices = [r['price'] for r in snkr_target_records]
            avg_price = sum(prices)/len(prices)
            report_lines.append("📊 統計資料")
            report_lines.append(f"　💰 最高成交價：¥{int(max(prices)):,} (~${max(prices)/jpy_rate:.0f} USD)")
            report_lines.append(f"　💰 最低成交價：¥{int(min(prices)):,} (~${min(prices)/jpy_rate:.0f} USD)")
            report_lines.append(f"　💰 平均成交價：¥{int(avg_price):,} (~${avg_price/jpy_rate:.0f} USD)")
            report_lines.append(f"　📈 資料筆數：{len(prices)} 筆")
        else:
            report_lines.append(f"SNKRDUNK: 無 {target_disp} 等級的卡片資料")
    else:
        report_lines.append("SNKRDUNK: 無此卡片資料")
        
    report_lines.append("\n---")
    if pc_url:
        report_lines.append(f"🔗 [查看 PriceCharting]({pc_url})")
    if snkr_url:
        report_lines.append(f"🔗 [查看 SNKRDUNK]({snkr_url})")
        report_lines.append(f"🔗 [查看 SNKRDUNK 銷售歷史]({snkr_url}/sales-histories)")

    final_report = '\n'.join(report_lines)
    print(final_report, force=True)
    
    if out_dir:
        safe_name = re.sub(r'[^A-Za-z0-9]', '_', name)
        safe_num = re.sub(r'[^A-Za-z0-9]', '_', str(number))
        
        # Create dedicated folder for the card
        card_dir_name = f"{safe_name}_{safe_num}"
        dest_dir = os.path.join(out_dir, card_dir_name)
        os.makedirs(dest_dir, exist_ok=True)
        
        filename = f"PKM_Vision_{safe_name}_{safe_num}.md"
        filepath = os.path.join(dest_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(final_report)
        print(f"✅ 報告已儲存至: {filepath}")
        
    if REPORT_ONLY:
        # Inject the snkrdunk image URL into the card info dictionary for Pillow to fetch
        card_info['img_url'] = img_url
        final_dest_dir = dest_dir if out_dir else '.'
        
        # We output all the scraped data to report_data.json
        data_dump = {
            "card_info": card_info,
            "snkr_records": snkr_records if snkr_records else [],
            "pc_records": pc_records if pc_records else []
        }
        json_path = os.path.join(final_dest_dir, "report_data.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data_dump, f, ensure_ascii=False, indent=2)
            
        # Generate the two separate HTML-based posters (Now with FULL history)
        out_paths = await image_generator.generate_report(card_info, snkr_records, pc_records, out_dir=final_dest_dir)
        
        return (final_report, out_paths)
        
    return final_report

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
