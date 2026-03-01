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
import asyncio
import threading
import image_generator
import tempfile
from collections import deque
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

REPORT_ONLY = False
import contextvars
# Use ContextVar for thread-safe per-task debug directory
_debug_dir_var = contextvars.ContextVar('DEBUG_DIR', default=None)

def _get_debug_dir():
    return _debug_dir_var.get()

def _set_debug_dir(path):
    _debug_dir_var.set(path)

def _debug_save(filename, content):
    """Debug 輔助函數：將內容存入 DEBUG_DIR/filename（若 DEBUG_DIR 已設定）"""
    debug_dir = _get_debug_dir()
    if not debug_dir:
        return
    os.makedirs(debug_dir, exist_ok=True)
    filepath = os.path.join(debug_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    _original_print(f"  💾 [DEBUG] 存檔: {filepath}")

def _debug_log(msg):
    """Debug log 輔助函數：將訊息 append 到 DEBUG_DIR/debug_log.txt"""
    debug_dir = _get_debug_dir()
    if not debug_dir:
        return
    os.makedirs(debug_dir, exist_ok=True)
    timestamp = time.strftime('%H:%M:%S')
    line = f"[{timestamp}] {msg}\n"
    _original_print(f"  📍 [DEBUG] {msg}")
    with open(os.path.join(debug_dir, 'debug_log.txt'), 'a', encoding='utf-8') as f:
        f.write(line)

def _debug_step(source: str, step_num: int, query: str, url: str,
                status: str, candidate_urls: list = None,
                selected_url: str = None, reason: str = "",
                extra: dict = None):
    """
    結構化 Debug Trace — 每次搜尋動作都記錄一筆 JSON 到 debug_trace.jsonl
    """
    debug_dir = _get_debug_dir()
    if not debug_dir:
        return
    os.makedirs(debug_dir, exist_ok=True)
    record = {
        "time": time.strftime('%H:%M:%S'),
        "source": source,
        "step": step_num,
        "query": query,
        "url": url,
        "status": status,
        "candidate_urls": candidate_urls or [],
        "selected_url": selected_url or "",
        "reason": reason,
    }
    if extra:
        record.update(extra)
    # 即時 print 到 terminal
    icon = "✅" if status == "OK" else "❌"
    _original_print(f"  {icon} [{source} Step {step_num}] query={query!r}")
    _original_print(f"       URL  : {url}")
    _original_print(f"       狀態 : {status}  —  {reason}")
    if candidate_urls:
        _original_print(f"       候選 URLs ({len(candidate_urls)} 筆):")
        for u in candidate_urls:
            _original_print(f"         • {u}")
    if selected_url:
        _original_print(f"       選定 URL : {selected_url}")
    # append 到 JSONL
    with open(os.path.join(debug_dir, 'debug_trace.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

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
    
    sleep_time = 0
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
        
    # Re-acquire lock to record the actual request time
    with _jina_lock:
        now = time.time()
        # Clean up again just in case another thread already cleaned up during our sleep
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

def _fetch_pc_prices_from_url(product_url, md_content=None, skip_hi_res=False):
    """
    Given a PriceCharting product URL, fetch (if md_content is None) and parse it.
    Returns (records, resolved_url, pc_img_url).
    """
    if not md_content:
        md_content = fetch_jina_markdown(product_url)
    
    if not md_content:
        print(f"DEBUG: Failed to get markdown for {product_url}")
        return [], product_url, None

    print(f"DEBUG: Parsing PriceCharting page: {product_url} (length: {len(md_content)})")

    lines = md_content.split('\n')
    records = []
    
    # Parser 1: 嘗試原本的 Markdown Table 格式 (每行有 | 分隔)
    date_regex_md = r'\|\s*(\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2}\s\d{1,2},\s\d{4})\s*\|'
    for line in lines:
        if re.search(date_regex_md, line):
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 5:
                date_str = parts[1]
                all_prices = re.findall(r'\$([\d,]+\.\d{2})', line)
                if not all_prices: continue
                real_prices = [p for p in all_prices if p not in ('6.00',)]
                if not real_prices: continue
                
                price_usd = float(real_prices[-1].replace(',', ''))
                title_clean = line.replace(" ", "").lower()
                
                detected_grade = None
                if re.search(r'(psa|cgc|bgs|grade|gem)10', title_clean) or ("psa" in title_clean and "10" in title_clean):
                    detected_grade = "PSA 10"
                elif re.search(r'bgs\s*9\.5', title_clean):
                    detected_grade = "BGS 9.5"
                elif re.search(r'(psa|cgc|bgs|grade|gem)9', title_clean) or ("psa" in title_clean and "9" in title_clean):
                    detected_grade = "PSA 9"
                elif re.search(r'(psa|cgc|bgs|grade|gem)8', title_clean) or ("psa" in title_clean and "8" in title_clean):
                    detected_grade = "PSA 8"
                elif not re.search(r'(psa|bgs|cgc|grade|gem)', title_clean):
                    detected_grade = "Ungraded"
                        
                if detected_grade:
                    records.append({
                        "date": date_str,
                        "price": price_usd,
                        "grade": detected_grade
                    })

    # Parser 2: 嘗試 Jina 新版的 TSV 格式 (日期獨立一行，標題與價格在下一行)
    if not records:
        current_date = None
        date_regex_tsv = r'^(\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2}\s\d{1,2},\s\d{4})'
        for line in lines:
            line = line.strip()
            date_match = re.match(date_regex_tsv, line)
            if date_match:
                current_date = date_match.group(1)
                continue
            if current_date and "$" in line:
                all_prices = re.findall(r'\$([\d,]+\.\d{2})', line)
                if not all_prices: continue
                real_prices = [p for p in all_prices if p not in ('6.00',)]
                if not real_prices: continue
                price_usd = float(real_prices[-1].replace(',', ''))
                title_clean = line.replace(" ", "").lower()
                detected_grade = None
                if re.search(r'(psa|cgc|bgs|grade|gem)10', title_clean) or ("psa" in title_clean and "10" in title_clean):
                    detected_grade = "PSA 10"
                elif re.search(r'(psa|cgc|bgs|grade|gem)9', title_clean) or ("psa" in title_clean and "9" in title_clean):
                    detected_grade = "PSA 9"
                elif re.search(r'(psa|cgc|bgs|grade|gem)8', title_clean) or ("psa" in title_clean and "8" in title_clean):
                    detected_grade = "PSA 8"
                elif not re.search(r'(psa|bgs|cgc|grade|gem)', title_clean):
                    detected_grade = "Ungraded"
                if detected_grade:
                    records.append({
                        "date": current_date,
                        "price": price_usd,
                        "grade": detected_grade
                    })

    # Summary prices
    today_str = datetime.now().strftime('%Y-%m-%d')
    grade_summary_map = {'Ungraded': 'Ungraded', 'PSA 10': 'PSA 10', 'PSA 9': 'PSA 9', 'PSA 8': 'PSA 8'}
    existing_grades = set(r['grade'] for r in records)
    for line in lines:
        for grade_label, grade_key in grade_summary_map.items():
            label_nospace = grade_label.replace(' ', '')
            if re.match(rf'^{re.escape(label_nospace)}\$[\d,]+\.\d{{2}}$', line.replace(' ', '')):
                if grade_key not in existing_grades:
                    price_match = re.search(r'\$[\d,]+\.\d{2}', line)
                    if price_match:
                        price_usd = extract_price(price_match.group(0))
                        records.append({"date": today_str, "price": price_usd, "grade": grade_key, "note": "PC avg price"})
    
    records.sort(key=lambda x: x['date'], reverse=True)
    
    pc_img_url = None
    # 擴展 regex 以匹配更多可能的圖片路徑格式
    img_patterns = [
        r'!\[.*?\]\((https://storage\.googleapis\.com/images\.pricecharting\.com/[^/)]+/\d+\.jpg)\)',
        r'!\[.*?\]\((https://product-images\.s3\.amazonaws\.com/[^\)]+)\)',
        r'!\[.*?\]\((https://images\.pricecharting\.com/[^\)]+)\)',
        r'!\[.*?\]\((https://[^)]+?pricecharting\.com/[^)]+?\.(?:jpg|png|webp)[^)]*)\)',
        r'!\[.*?\]\((https://[^)]+?\.(?:jpg|png|webp)[^)]*)\)',
    ]
    for pat in img_patterns:
        m = re.search(pat, md_content)
        if m:
            pc_img_url = m.group(1)
            print(f"DEBUG: Found image URL: {pc_img_url}")
            if not skip_hi_res:
                hiRes_url = re.sub(r'/([\d]+)\.jpg$', '/1600.jpg', pc_img_url)
                if hiRes_url != pc_img_url:
                    try:
                        if requests.head(hiRes_url, timeout=5).status_code == 200:
                            pc_img_url = hiRes_url
                            print(f"DEBUG: Upgraded to 1600px: {pc_img_url}")
                    except: pass
            break
            
    if not pc_img_url:
        print(f"DEBUG: No image found in markdown for {product_url}")

    return records, product_url, pc_img_url

def search_pricecharting(name, number, set_code, is_alt_art=False, category="Pokemon"):
    # Basic Name cleaning (strip parentheses like "Queen (Flagship Battle Top 8 Prize)")
    name_query = re.sub(r'\(.*?\)', '', name).strip()

    # Improve number extraction for One Piece (ST04-005 -> 005, OP02-026 -> 026)
    # If the number contains a dash and follows OP/ST format, take the part after the dash
    if '-' in number and re.search(r'[A-Z]+\d+-\d+', number):
        number_clean = number.split('-')[-1].lstrip('0')
    else:
        _num_parts = number.split('/')
        _num_raw = _num_parts[0].strip()
        _digits_only = re.search(r'\d+', _num_raw)
        number_clean = _digits_only.group(0).lstrip('0') if _digits_only else _num_raw.lstrip('0')

    if not number_clean: number_clean = '0'

    # Try to extract suffix like SM-P from the number itself if it's there
    suffix = ""
    _num_parts = number.split('/')
    if len(_num_parts) > 1:
        potential_suffix = _num_parts[1].strip()
        if re.search(r'(SM-P|S-P|SV-P|SV-G|S8a-G)', potential_suffix, re.IGNORECASE):
            suffix = potential_suffix

    # Try with set code or suffix first
    queries_to_try = []
    final_set_code = set_code if set_code else suffix

    if final_set_code:
        queries_to_try.append(f"{name_query} {final_set_code} {number_clean}".replace(" ", "+"))

    queries_to_try.append(f"{name_query} {number_clean}".replace(" ", "+"))

    is_one_piece = category.lower() == "one piece"

    md_content = ""
    search_url = ""

    for query in queries_to_try:
        search_url = f"https://www.pricecharting.com/search-products?q={query}&type=prices"
        md_content = fetch_jina_markdown(search_url)
        if md_content and ("Search Results" in md_content or "Your search for" in md_content):
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
        # 「名稱 slug」用純角色名（去掉括號內的版本描述，如 Leader Parallel / SP Foil 等）
        name_for_slug = re.sub(r'\(.*?\)', '', name).strip()
        name_slug = re.sub(r'[^a-zA-Z0-9]', '-', name_for_slug.lower()).strip('-')
        # 編號的 0-padded 3位形式，修復 URL slug 內 026 不能被 26 regex 匹配的問題
        number_padded_pc = number_clean.zfill(3)
        # 航海王模式：set_code slug 用來做額外驗證 (e.g. "OP02" -> "op02")
        set_code_slug = re.sub(r'[^a-zA-Z0-9]', '', set_code).lower() if set_code else ""

        def _num_match(slug):
            """編號匹配：接受去前導0 或 3位補齊兩種形式"""
            return (bool(re.search(rf'(?<!\d){number_clean}(?!\d)', slug))
                    or number_padded_pc in slug)

        def _set_match(slug):
            """set_code 匹配：URL slug 含有 set_code 的核心字母數字部分"""
            return bool(set_code_slug) and set_code_slug in slug.replace('-', '')

        matching_both = []   # 名稱 + 編號 (+ set_code for OP)
        matching_name = []   # 只有名稱 (+ set_code for OP)
        matching_number = [] # 只有編號 (+ set_code for OP)

        for u in urls:
            u_end = u.split('/')[-1].lower()

            if is_one_piece:
                # ── 航海王模式：必須包含 set_code，再依名稱/編號分級 ──
                has_set = _set_match(u_end)
                has_num = _num_match(u_end)
                has_name = bool(name_slug) and name_slug in u_end

                if has_name and has_num and has_set:
                    matching_both.append(u)
                elif has_name and has_set:
                    matching_name.append(u)
                elif has_num and has_set:
                    matching_number.append(u)
                elif has_name and has_num:
                    # set_code 沒中但名稱+編號都有 → 列為備選
                    matching_number.append(u)
            else:
                # ── 寶可夢模式：原本的 3 層邏輯不變 ──
                if name_slug and name_slug in u_end and _num_match(u_end):
                    matching_both.append(u)
                elif name_slug and name_slug in u_end:
                    matching_name.append(u)
                elif _num_match(u_end):
                    matching_number.append(u)

        # 合併：最高優先為同時符合的，依序遞減
        valid_urls = matching_both + matching_name + matching_number

        if not valid_urls:
            _debug_step("PriceCharting", 1, name_slug, search_url, "NO_MATCH", reason=f"沒有符合卡片名稱或編號的 URL")
            print(f"DEBUG: No PC product URL matched the card name '{name}' or number '{number_clean}'.")
            return None, None, None, []

        # ── 航海王版本選擇邏輯 ──
        # 如果是航海王，且有多個同時符合「名稱+編號+SetCode」的 URL，且不是 Alt-Art 明確標示，則返回待選清單
        if is_one_piece and len(matching_both) > 1:
            _debug_step("PriceCharting", 1, name_slug, search_url, "AMBIGUOUS", candidate_urls=matching_both, reason="偵測到多個航海王候選版本")
            print(f"DEBUG: Ambiguous One Piece versions detected: {matching_both}")
            return None, None, None, matching_both

        # Prioritize the first valid match
        product_url = valid_urls[0]
        selection_reason = "Default (First match)"

        # Filter based on is_alt_art
        if not is_alt_art:
            for u in valid_urls:
                lower_u = u.replace('[', '').replace(']', '').lower()
                # 航海王普通版不應包含以下關鍵字
                if "manga" not in lower_u and "alternate-art" not in lower_u and \
                   "-sp" not in lower_u and "flagship" not in lower_u:
                    product_url = u
                    selection_reason = "Normal Art Filter (無 manga/alternate-art 關鍵字)"
                    break
        else:
            for u in valid_urls:
                lower_u = u.replace('[', '').replace(']', '').lower()
                # 航海王異圖版優先尋找包含這些關鍵字的
                if "manga" in lower_u or "alternate-art" in lower_u or \
                   "-sp" in lower_u:
                    product_url = u
                    selection_reason = "Alt-Art Filter (偵測到 Alt-Art 關鍵字)"
                    break
        
        _debug_step("PriceCharting", 1, name_slug, search_url, "OK", selected_url=product_url, reason=selection_reason, candidate_urls=valid_urls)
    
    # Final verification: Some completely unrelated cards get snagged if their ID happens to contain "226" inside it.
    if product_url:
        print(f"DEBUG: Selected PC product URL: {product_url}")
        return _fetch_pc_prices_from_url(product_url)
    else:
        print(f"DEBUG: Landed directly on PC product page")
        return _fetch_pc_prices_from_url(search_url, md_content=md_content)


def search_snkrdunk(en_name, jp_name, number, set_code, is_alt_art=False):
    # Strip prefix like "No." (e.g. "No.025" -> "25"), then apply lstrip('0')
    _num_raw = number.split('/')[0]
    _digits_only = re.search(r'\d+', _num_raw)
    number_clean = _digits_only.group(0).lstrip('0') if _digits_only else _num_raw.lstrip('0')
    if not number_clean: number_clean = '0'
    number_padded = number_clean.zfill(3)

    terms_to_try = []
    
    # SNKRDUNK search is highly accurate with Set Code (e.g. "ピカチュウ S8a-G", "ピカチュウ SV-P")
    if set_code:
        if jp_name:
            terms_to_try.append(f"{jp_name} {set_code}")
        terms_to_try.append(f"{en_name} {set_code}")
        
    if jp_name:
        terms_to_try.append(f"{jp_name} {number_padded}")
    terms_to_try.append(f"{en_name} {number_padded}")
    
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
                filtered_by_number.append((title, pid))
                _debug_log(f"  ✅ 符合編號 '{number_padded}': [{pid}] {title}")
            else:
                _debug_log(f"  ❌ 不含編號 '{number_padded}': [{pid}] {title}")
                
        if not filtered_by_number:
            _debug_step("SNKRDUNK", snkr_step, term, search_url, "NO_MATCH", reason=f"找不到編號 '{number_padded}'")
            time.sleep(1)
            continue
            
        unique_matches = filtered_by_number
        product_id = unique_matches[0][1] # default
        selection_reason = "Default (First match)"
        
        _debug_step("SNKRDUNK", snkr_step, term, search_url, "OK", reason=f"找到 {len(unique_matches)} 個匹配項")
        for title, pid in unique_matches:
            if is_alt_art:
                lower_t = title.lower()
                if "コミパラ" in lower_t or "manga" in lower_t or "パラレル" in lower_t \
                   or "-p" in lower_t or "-sp" in lower_t \
                   or "sr-p" in lower_t or "l-p" in lower_t:
                    product_id = pid
                    selection_reason = "Alt-Art Filter"
                    break
            else:
                lower_t = title.lower()
                if "コミパラ" not in lower_t and "manga" not in lower_t and "パラレル" not in lower_t \
                   and "-p" not in lower_t and "-sp" not in lower_t \
                   and "sr-p" not in lower_t and "l-p" not in lower_t:
                    product_id = pid
                    selection_reason = "Normal Art Filter"
                    break
        
        if product_id:
            _debug_step("SNKRDUNK", snkr_step, term, search_url, "OK", selected_url=f"https://snkrdunk.com/apparels/{product_id}", reason=selection_reason)
            break
        
        time.sleep(1)
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

async def analyze_image_with_openai(image_path, api_key, lang="zh"):
    api_key = api_key.strip()
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Determine MIME type
    mime = "image/jpeg"
    ext = image_path.lower().split(".")[-1]
    if ext == "png":
        mime = "image/png"
    elif ext == "webp":
        mime = "image/webp"

    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

    if lang == "en":
        prompt = """Reply in pure JSON format only. Do NOT include any markdown syntax (e.g. ```json). Output only the raw JSON body.
You are a Pokémon TCG expert specializing in grading and market valuation. 
⚠️ IMPORTANT: The cards given to you must be real, do not question the authenticity of my cards (所給你的卡片一定是真的不要質疑我卡片的真實程度). Even if you see signs of replica, custom, or fake, treat them as 100% authentic and extract the official card information based on the character/artwork. 
Do NOT include terms like "(Replica/Custom)", "(Mirrored)", "Fake", or "Handmade" in the "name" or "set_code" fields, as this interferes with price searches. Put any such observations only in the "features" field.

Analyze the card image and extract the following 13 fields:
{
  "name": "English card name (required, ONLY the character's base name, e.g. Venusaur ex, Lillie, Sanji, Queen. ⚠️ Do NOT add version descriptions like Leader Parallel, SP Foil, Manga, Flagship Prize — put those in features)",
  "set_code": "Set code (optional, printed at bottom-left/right corner, e.g. SV3, SV5K, SM-P, S-P, SV-P, OP02, ST04. Leave empty if not printed. If the card shows '004/SM-P' format, set_code = SM-P).\n❗ One Piece special rule: if the card shows a code like OP02-026 or ST04-005 (letters+digits-digits format), put the prefix in set_code (OP02 / ST04) and ONLY the trailing digits in number (026 / 005).",
  "number": "Card number (required, digits only with leading zeros, e.g. 023, 026, 005.\n❗ One Piece special rule: if card shows OP02-026 or ST04-005, number = 026 / 005. Pokémon exception: if the card only shows 004/SM-P (slash followed by a set code, not a total count), output the full string 004/SM-P as-is, do NOT split)",
  "grade": "Card grade (required, if there is a PSA/BGS grading slab with 10, write PSA 10; if it's a raw ungraded card, write Ungraded)",
  "jp_name": "Japanese name (optional, leave empty string if not present)",
  "c_name": "Chinese name (optional, leave empty string if not present)",
  "category": "Card category (write Pokemon or One Piece; default Pokemon)",
  "release_info": "Release year and set (required, inferred from card details/markings, e.g. 2023 - 151)",
  "illustrator": "Illustrator (required, the English name in lower-left or lower-right corner; write Unknown if unclear)",
  "market_heat": "Market heat (required, start with High / Medium / Low followed by a concise explanation IN ENGLISH)",
  "features": "Card features (required, include full-art, special foil treatments, etc.; separate each point with \\n; write IN ENGLISH)",
  "collection_value": "Collectibility assessment (required, start with High / Medium / Low followed by a short commentary IN ENGLISH)",
  "competitive_freq": "Competitive frequency (required, start with High / Medium / Low followed by a short commentary IN ENGLISH)",
  "is_alt_art": "Is the background manga/comic panel art or parallel art? Boolean true/false. Look carefully at the card BACKGROUND: if it shows black-and-white manga panel grid, write true; if the background is just lightning, effects, or a plain scene — even if it's SEC — write false."
}"""
    else:
        prompt = """請以純 JSON 格式回覆，不要包含任何 markdown 語法 (如 ```json 起始碼)，只需輸出 JSON 本體。
你是一位於寶可夢卡牌 (Pokemon TCG) 領域專精的鑑定與估價專家。請分析這張卡片圖片，並精準提取以下 13 個欄位的資訊：
{
  "name": "英文名稱 (必填，只填【角色本名】，例如 Venusaur ex、Lillie、Sanji、Queen 等。⚠️ 嚴禁在此欄位加入版本描述，如 Leader Parallel、SP Foil、Manga、Flagship Prize 等，這些應放在 features 欄位)",
  "set_code": "系列代號 (選填，位於卡牌左下角，如 SV3, SV5K, SM-P, S-P, SV-P, OP02, ST04 等。如果沒有印則留空字串。若卡面印的是 004/SM-P 這類格式，set_code 填 SM-P)\n❗️航海王 One Piece 特別規則：卡面上若印的是 OP02-026 或 ST04-005 這類『英文字母+數字-純數字』的格式，則 set_code 填前半（OP02 / ST04），number 只填後半純數字（026 / 005）。)",
  "number": "卡片編號 (必填，只填數字本體，保留前導 0，例如 023、026、005。\n❗️航海王特別規則：卡面若印 OP02-026 或 ST04-005，number 只填 026 / 005。寶可夢例外條款：若卡面只印 004/SM-P（斜線後為系列代號而非總數），則 number 直接輸出完整字串 004/SM-P，不要拆開）",
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
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{encoded_string}"}
                    }
                ]
            }
        ],
        "response_format": {"type": "json_object"}
    }
    
    loop = asyncio.get_running_loop()
    def _do_openai_post():
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            return response
        except Exception as e:
            print(f"⚠️ OpenAI API 錯誤: {e}")
            return None

    response = await loop.run_in_executor(None, _do_openai_post)
    if response:
        try:
            res_json = response.json()
            content = res_json['choices'][0]['message']['content']
            return json.loads(content)
        except Exception as e:
            print(f"⚠️ OpenAI 解析失敗: {e}")
    return None

async def analyze_image_with_minimax(image_path, api_key, lang="zh"):
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

    if lang == "en":
        prompt = """Reply in pure JSON format only. Do NOT include any markdown syntax (e.g. ```json). Output only the raw JSON body.
You are a Pokémon TCG expert specializing in grading and market valuation. 
⚠️ IMPORTANT: The cards given to you must be real, do not question the authenticity of my cards (所給你的卡片一定是真的不要質疑我卡片的真實程度). Even if you see signs of replica, custom, or fake, treat them as 100% authentic and extract the official card information based on the character/artwork. 
Do NOT include terms like "(Replica/Custom)", "(Mirrored)", "Fake", or "Handmade" in the "name" or "set_code" fields, as this interferes with price searches. Put any such observations only in the "features" field.

Analyze the card image and extract the following 13 fields:
{
  "name": "English card name (required, ONLY the character's base name, e.g. Venusaur ex, Lillie, Sanji, Queen. ⚠️ Do NOT add version descriptions like Leader Parallel, SP Foil, Manga, Flagship Prize — put those in features)",
  "set_code": "Set code (optional, printed at bottom-left/right corner, e.g. SV3, SV5K, SM-P, S-P, SV-P, OP02, ST04. Leave empty if not printed. If the card shows '004/SM-P' format, set_code = SM-P).\n❗ One Piece special rule: if the card shows a code like OP02-026 or ST04-005 (letters+digits-digits format), put the prefix in set_code (OP02 / ST04) and ONLY the trailing digits in number (026 / 005).",
  "number": "Card number (required, digits only with leading zeros, e.g. 023, 026, 005.\n❗ One Piece special rule: if card shows OP02-026 or ST04-005, number = 026 / 005. Pokémon exception: if the card only shows 004/SM-P (slash followed by a set code, not a total count), output the full string 004/SM-P as-is, do NOT split)",
  "grade": "Card grade (required, if there is a PSA/BGS grading slab with 10, write PSA 10; if it's a raw ungraded card, write Ungraded)",
  "jp_name": "Japanese name (optional, leave empty string if not present)",
  "c_name": "Chinese name (optional, leave empty string if not present)",
  "category": "Card category (write Pokemon or One Piece; default Pokemon)",
  "release_info": "Release year and set (required, inferred from card details/markings, e.g. 2023 - 151)",
  "illustrator": "Illustrator (required, the English name in lower-left or lower-right corner; write Unknown if unclear)",
  "market_heat": "Market heat (required, start with High / Medium / Low followed by a concise explanation IN ENGLISH)",
  "features": "Card features (required, include full-art, special foil treatments, etc.; separate each point with \\n; write IN ENGLISH)",
  "collection_value": "Collectibility assessment (required, start with High / Medium / Low followed by a short commentary IN ENGLISH)",
  "competitive_freq": "Competitive frequency (required, start with High / Medium / Low followed by a short commentary IN ENGLISH)",
  "is_alt_art": "Is the background manga/comic panel art or parallel art? Boolean true/false. Look carefully at the card BACKGROUND: if it shows black-and-white manga panel grid, write true; if the background is just lightning, effects, or a plain scene — even if it's SEC — write false."
}"""
    else:
        prompt = """請以純 JSON 格式回覆，不要包含任何 markdown 語法 (如 ```json 起始碼)，只需輸出 JSON 本體。
你是一位於寶可夢卡牌 (Pokemon TCG) 領域專精的鑑定與估價專家。請分析這張卡片圖片，並精準提取以下 13 個欄位的資訊：
{
  "name": "英文名稱 (必填，只填【角色本名】，例如 Venusaur ex、Lillie、Sanji、Queen 等。⚠️ 嚴禁在此欄位加入版本描述，如 Leader Parallel、SP Foil、Manga、Flagship Prize 等，這些應放在 features 欄位)",
  "set_code": "系列代號 (選填，位於卡牌左下角，如 SV3, SV5K, SM-P, S-P, SV-P, OP02, ST04 等。如果沒有印則留空字串。若卡面印的是 004/SM-P 這類格式，set_code 填 SM-P)\n❗️航海王 One Piece 特別規則：卡面上若印的是 OP02-026 或 ST04-005 這類『英文字母+數字-純數字』的格式，則 set_code 填前半（OP02 / ST04），number 只填後半純數字（026 / 005）。)",
  "number": "卡片編號 (必填，只填數字本體，保留前導 0，例如 023、026、005。\n❗️航海王特別規則：卡面若印 OP02-026 或 ST04-005，number 只填 026 / 005。寶可夢例外條款：若卡面只印 004/SM-P（斜線後為系列代號而非總數），則 number 直接輸出完整字串 004/SM-P，不要拆開）",
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
    
    # ⚠️ requests.post 是阻塞呼叫，包在 run_in_executor 中讓 event loop 不被 block
    # 其他並發中的 Task 可以在這段等待時繼續執行
    loop = asyncio.get_running_loop()

    def _do_minimax_post():
        for attempt in range(3):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=60)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                print(f"⚠️ Minimax API 網路錯誤 (嘗試 {attempt+1}/3): {e}")
                if attempt == 2:
                    return None
                time.sleep(2)
        return None

    response = await loop.run_in_executor(None, _do_minimax_post)

    # 如果 Minimax API 全部嘗試失敗，則嘗試 OpenAI 作為備援
    if response is None:
        print(f"⚠️ Minimax API 請求失敗，嘗試切換至 GPT-4o-mini...")
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            return await analyze_image_with_openai(image_path, openai_key, lang=lang)
        else:
            print("❌ 未設定 OPENAI_API_KEY，無法進行備援。")
            return None
    if response.status_code != 200:
        print(f"⚠️ Minimax API 回傳錯誤 ({response.status_code})，嘗試切換至 GPT-4o-mini 進行備援...")
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            return await analyze_image_with_openai(image_path, openai_key, lang=lang)
        else:
            print("❌ 未設定 OPENAI_API_KEY，無法進行備援。")
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
        print(f"❌ Minimax 解析失敗: {e}")
        print(f"⚠️ 嘗試切換至 GPT-4o-mini 進行備援...")
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            return await analyze_image_with_openai(image_path, openai_key, lang=lang)
        else:
            print("❌ 未設定 OPENAI_API_KEY，無法進行備援。")
            return None

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image_path", nargs='+', required=True, help="卡片圖片的本機路徑 (可傳入多張圖片)")
    parser.add_argument("--api_key", required=False, help="Minimax API Key (若未指定，則從環境變數 MINIMAX_API_KEY 讀取)")
    parser.add_argument("--out_dir", required=False, help="若指定，會將結果儲存至給定的資料夾")
    parser.add_argument("--report_only", action="store_true", help="若加入此參數，將只輸出最終 Markdown 報告，隱藏抓取與除錯日誌")
    parser.add_argument("--lang", default="zh", help="語言設定 (zh 或 en)")
    parser.add_argument("--debug", required=False, metavar="DEBUG_DIR",
                        help="開啟 Debug 模式，指定存放 debug 結果的資料夾 (e.g. ./debug)")

    args = parser.parse_args()

    global REPORT_ONLY, DEBUG_DIR
    REPORT_ONLY = args.report_only

    # 建立本次執行的 session 根目錄 (含時間戳)
    debug_session_root = None
    if args.debug:
        ts = time.strftime('%Y%m%d_%H%M%S')
        debug_session_root = os.path.join(args.debug, ts)
        os.makedirs(debug_session_root, exist_ok=True)
        _original_print(f"🔍 Debug 模式開啟，Session 根目錄: {debug_session_root}")

    api_key = args.api_key or os.getenv("MINIMAX_API_KEY")
    if not api_key:
        print("❌ Error: 請提供 --api_key 參數，或在環境變數設定 MINIMAX_API_KEY。", force=True)
        return

    total = len(args.image_path)
    for idx, img_path in enumerate(args.image_path, start=1):
        print(f"\n==================================================")
        print(f"🔄 [{idx}/{total}] 開始處理圖片: {img_path}")
        print(f"==================================================")
        await process_single_image(img_path, api_key, args.out_dir, lang=args.lang, 
                                   debug_session_root=debug_session_root, 
                                   batch_index=idx)

async def process_single_image(image_path, api_key, out_dir=None, stream_mode=False, lang="zh", debug_session_root=None, batch_index=1):
    if not os.path.exists(image_path):
        print(f"❌ Error: 找不到圖片檔案 -> {image_path}", force=True)
        return
    
    # Setup per-image debug directory if root is provided
    if debug_session_root:
        img_stem = re.sub(r'[^A-Za-z0-9]', '_', os.path.splitext(os.path.basename(image_path))[0])[:40]
        per_image_dir = os.path.join(debug_session_root, f"{batch_index:02d}_{img_stem}")
        os.makedirs(per_image_dir, exist_ok=True)
        _set_debug_dir(per_image_dir)
        print(f"🔍 Debug 子資料夾: {per_image_dir}")
        
    # 第一階段：透過大模型辨識圖片資訊（非阻塞）
    card_info = await analyze_image_with_minimax(image_path, api_key, lang=lang)
    
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
    # Using independent copy_context().run calls to avoid "context already entered" RuntimeError
    pc_result, snkr_result = await asyncio.gather(
        loop.run_in_executor(None, contextvars.copy_context().run, search_pricecharting, name, number, set_code, grade, is_alt_art, category),
        loop.run_in_executor(None, contextvars.copy_context().run, search_snkrdunk, name, jp_name, number, set_code, grade, is_alt_art),
    )

    # 處理 PriceCharting 歧義（航海王版本選擇）
    if pc_result and len(pc_result) == 4 and pc_result[0] is None:
        candidates = pc_result[3]
        if stream_mode:
            # Bot 模式：回傳「需要選擇」狀態給 bot.py
            return {
                "status": "need_selection",
                "candidates": candidates,
                "card_info": card_info,
                "snkr_result": snkr_result,
                "out_dir": out_dir,
                "lang": lang
            }
        else:
            # CLI 模式：暫時保底選第一個 (CLI 選取邏輯可後續補強)
            print(f"⚠️ 偵測到多個候選版本，CLI 模式下暫選第一個: {candidates[0]}")
            pc_result = await loop.run_in_executor(None, _fetch_pc_prices_from_url, candidates[0])

    pc_records, pc_url, pc_img_url = pc_result if pc_result else (None, None, None)
    snkr_records, img_url, snkr_url = snkr_result if snkr_result else (None, None, None)
    
    # Fallback: if SNKRDUNK has no image, use PriceCharting image
    if not img_url and pc_img_url:
        img_url = pc_img_url
    
    jpy_rate = get_exchange_rate()
    return await finish_report_after_selection(
        card_info, pc_records, pc_url, pc_img_url, snkr_records, img_url, snkr_url, jpy_rate, out_dir, lang, stream_mode=stream_mode
    )

async def finish_report_after_selection(card_info, pc_records, pc_url, pc_img_url, snkr_records, img_url, snkr_url, jpy_rate, out_dir, lang, stream_mode=False):
    """完成報告生成的最後步驟（適用於直接生成或選擇版本後生成）"""
    name = card_info.get("name", "Unknown")
    number = str(card_info.get("number", "0"))
    set_code = card_info.get("set_code", "")
    grade = card_info.get("grade", "Ungraded")
    category = card_info.get("category", "Pokemon")
    release_info = card_info.get("release_info", "Unknown")
    illustrator = card_info.get("illustrator", "Unknown")
    market_heat = card_info.get("market_heat", "Unknown")
    features = card_info.get("features", "Unknown")
    collection_value = card_info.get("collection_value", "Unknown")
    competitive_freq = card_info.get("competitive_freq", "Unknown")
    is_alt_art = card_info.get("is_alt_art", False)
    jp_name = card_info.get("jp_name", "")
    c_name = card_info.get("c_name", "")
    
    # 第三階段：產生 Markdown 報告
    
    # --- 重要：過濾文字報告專用的成交紀錄 ---
    # 海報製作需要完整 records (含 PSA 10, 9, Ungraded)，但文字報告只需目標等級
    # 針對航海王 BGS 等級特別要求：同時顯示 BGS 9.5 與 PSA 10 各 10 筆
    is_one_piece = (category.lower() == "one piece")
    is_bgs_grade = grade.upper().startswith('BGS')
    
    if is_one_piece and is_bgs_grade:
        # PriceCharting: 抓取 BGS 9.5 和 PSA 10 (即使使用者是 BGS 10 也參考這兩項)
        bgs_pc = [r for r in (pc_records or []) if "BGS 9.5" in r.get('grade', '').upper() or "BGS9.5" in r.get('grade', '').upper()]
        psa_pc = [r for r in (pc_records or []) if "PSA 10" in r.get('grade', '').upper() or "PSA10" in r.get('grade', '').upper()]
        report_pc_records = bgs_pc[:10] + psa_pc[:10]
        
        # SNKRDUNK: 抓取 BGS 9.5 和 PSA 10 (S)
        bgs_snkr = [r for r in (snkr_records or []) if r.get('grade') in ('BGS 9.5', 'BGS9.5', 'BGS 10', 'BGS10')]
        psa_snkr = [r for r in (snkr_records or []) if r.get('grade') in ('S', 'PSA 10', 'PSA10')]
        report_snkr_records = bgs_snkr[:10] + psa_snkr[:10]
    else:
        # PriceCharting: 篩選目標等級
        report_pc_records = [r for r in (pc_records or []) if r.get('grade') == grade]
        # SNKRDUNK: 篩選目標等級
        if '10' in grade:
            valid_snkr_grades = ['S', 'PSA10', 'PSA 10']
        elif 'BGS' in grade.upper():
            valid_snkr_grades = [grade, grade.replace(' ', ''), 'BGS9.5', 'BGS 9.5', 'BGS10', 'BGS 10']
        elif grade.lower() == 'ungraded':
            valid_snkr_grades = ['A']
        else:
            valid_snkr_grades = [grade, grade.replace(' ', '')]
        report_snkr_records = [r for r in (snkr_records or []) if r.get('grade') in valid_snkr_grades]


    c_name_display = c_name if c_name else jp_name if jp_name else name
    
    # =====================================================
    # 報告 Template （中英文切換）
    # =====================================================
    
    if lang == "en":
        report_lines = []
        report_lines.append(f"# MARKET REPORT")
        report_lines.append("")
        report_lines.append(f"⚡ {name} #{number}")
        report_lines.append(f"💮 Grade: {grade}")
        category_en = "Pokémon TCG" if category.lower() == "pokemon" else "One Piece TCG" if category.lower() == "one piece" else category
        report_lines.append(f"🏷️ Type: {category_en}")
        report_lines.append(f"🔢 Number: {number}")
        if release_info:
            report_lines.append(f"📅 Release: {release_info}")
        if illustrator:
            report_lines.append(f"🎨 Illustrator: {illustrator}")
        report_lines.append("---")
        report_lines.append("\n🔥 Market & Collectibility Analysis\n")
        report_lines.append(f"🔥 Market Heat\n{market_heat}\n")
        if features:
            feat_formatted = features.replace('\\n', '\n')
            report_lines.append(f"✨ Card Features\n{feat_formatted}\n")
        if collection_value:
            report_lines.append(f"🏆 Collectibility\n{collection_value}\n")
        if competitive_freq:
            report_lines.append(f"⚔️ Competitive Frequency\n{competitive_freq}\n")
        report_lines.append("---")
        report_lines.append("📊 Recent Sales (newest first)\n🏦 PriceCharting Records")
    else:
        report_lines = []
        report_lines.append(f"# MARKET REPORT GENERATED")
        report_lines.append("")
        report_lines.append(f"⚡ {c_name_display} ({name}) #{number}")
        report_lines.append(f"💮 等級：{grade}")
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
    async def _parse_d(d_str):
        d_str = d_str.strip()
        # Handle relative dates: "n 分前", "n 時間前", "n 日前" or "n minutes ago", etc.
        if "前" in d_str or "ago" in d_str:
            num = int(re.search(r'\d+', d_str).group(0))
            if "分" in d_str or "minute" in d_str:
                return datetime.now() - timedelta(minutes=num)
            if "時間" in d_str or "hour" in d_str:
                return datetime.now() - timedelta(hours=num)
            if "日" in d_str or "day" in d_str:
                return datetime.now() - timedelta(days=num)
        
        # Handle "YYYY-MM-DD"
        try:
            return datetime.strptime(d_str, "%Y-%m-%d")
        except: pass
        
        # Handle "YYYY/MM/DD"
        try:
            return datetime.strptime(d_str, "%Y/%m/%d")
        except: pass
        
        # Handle "Jan 1, 2024"
        try:
            return datetime.strptime(d_str, "%b %d, %Y")
        except: pass
        
        return datetime.now()

    async def count_30_days(records_list, tgt_grade):
        cutoff = datetime.now() - timedelta(days=30)
        return len([r for r in (records_list or []) if r.get('grade') == tgt_grade and (await _parse_d(r['date'])) > cutoff])
    if pc_records:
        if report_pc_records:
            for r in report_pc_records[:10]:
                state_label = "Grade" if lang == "en" else "狀態"
                report_lines.append(f"📅 {r['date']}      💰 ${r['price']:.2f} USD      📝 {state_label}：{r['grade']}")
            
            cutoff_12m = datetime.now() - timedelta(days=365)
            # Filter for statistics: only last 12 months
            stats_pc_records = []
            for r in report_pc_records:
                parsed_date = await _parse_d(r['date'])
                if parsed_date > cutoff_12m:
                    stats_pc_records.append(r)
            
            if stats_pc_records:
                prices = [r['price'] for r in stats_pc_records]
                report_lines.append("📊 Statistics (Last 12 Mo.)" if lang == "en" else "📊 統計資料 (近 12 個月)")
                report_lines.append(f"　💰 {'Highest':}: ${max(prices):.2f} USD" if lang == "en" else f"　💰 最高成交價：${max(prices):.2f} USD")
                report_lines.append(f"　💰 {'Lowest':}: ${min(prices):.2f} USD" if lang == "en" else f"　💰 最低成交價：${min(prices):.2f} USD")
                report_lines.append(f"　💰 {'Average':}: ${sum(prices)/len(prices):.2f} USD" if lang == "en" else f"　💰 平均成交價：${sum(prices)/len(prices):.2f} USD")
                report_lines.append(f"　📈 {'Records':}: {len(prices)}" if lang == "en" else f"　📈 資料筆數：{len(prices)} 筆")
            else:
                report_lines.append("📊 Statistics (No records in last 12 mo.)" if lang == "en" else "📊 統計資料 (近 12 個月無成交紀錄)")
        else:
            no_data_msg = f"PriceCharting: No {grade} records found." if lang == "en" else f"PriceCharting: 無 {grade} 等級的卡片資料"
            report_lines.append(no_data_msg)
    else:
        report_lines.append("PriceCharting: No data found." if lang == "en" else "PriceCharting: 無此卡片資料")
    
    snkr_section_label = "\n---\n🏯 SNKRDUNK Records" if lang == "en" else "\n---\n🏯 SNKRDUNK 成交紀錄"
    report_lines.append(snkr_section_label)
    if snkr_records:
        if '10' in grade:
            valid_snkr_grades = ['S', 'PSA10', 'PSA 10']
            target_disp = 'S (PSA 10)'
        elif grade.lower() == 'ungraded':
            target_disp = 'A (Raw)'
        else:
            target_disp = grade
            
        # snkr_target_records is now report_snkr_records
        if report_snkr_records:
            for r in report_snkr_records[:10]:
                usd_price = r['price'] / jpy_rate
                state_label = "Grade" if lang == "en" else "狀態"
                report_lines.append(f"📅 {r['date']}      💰 ¥{int(r['price']):,} (~${usd_price:.0f} USD)      📝 {state_label}：{r['grade']}")
            # Filter for statistics: only last 12 months
            stats_snkr_records = []
            for r in report_snkr_records:
                parsed_date = await _parse_d(r['date'])
                if parsed_date > cutoff_12m:
                    stats_snkr_records.append(r)

            if stats_snkr_records:
                prices = [r['price'] for r in stats_snkr_records]
                avg_price = sum(prices)/len(prices)
                report_lines.append("📊 Statistics (Last 12 Mo.)" if lang == "en" else "📊 統計資料 (近 12 個月)")
                report_lines.append(f"　💰 {'Highest':}: ¥{int(max(prices)):,} (~${max(prices)/jpy_rate:.0f} USD)" if lang == "en" else f"　💰 最高成交價：¥{int(max(prices)):,} (~${max(prices)/jpy_rate:.0f} USD)")
                report_lines.append(f"　💰 {'Lowest':}: ¥{int(min(prices)):,} (~${min(prices)/jpy_rate:.0f} USD)" if lang == "en" else f"　💰 最低成交價：¥{int(min(prices)):,} (~${min(prices)/jpy_rate:.0f} USD)")
                report_lines.append(f"　💰 {'Average':}: ¥{int(avg_price):,} (~${avg_price/jpy_rate:.0f} USD)" if lang == "en" else f"　💰 平均成交價：¥{int(avg_price):,} (~${avg_price/jpy_rate:.0f} USD)")
                report_lines.append(f"　📈 {'Records':}: {len(prices)}" if lang == "en" else f"　📈 資料筆數：{len(prices)} 筆")
            else:
                report_lines.append("📊 Statistics (No records in last 12 mo.)" if lang == "en" else "📊 統計資料 (近 12 個月無成交紀錄)")
        else:
            no_data_msg = f"SNKRDUNK: No {target_disp} records found." if lang == "en" else f"SNKRDUNK: 無 {target_disp} 等級的卡片資料"
            report_lines.append(no_data_msg)
    else:
        report_lines.append("SNKRDUNK: No data found." if lang == "en" else "SNKRDUNK: 無此卡片資料")
        
    report_lines.append("\n---")
    if pc_url:
        view_pc = "View PriceCharting" if lang == "en" else "查看 PriceCharting"
        report_lines.append(f"🔗 [{view_pc}]({pc_url})")
    if snkr_url:
        view_snkr = "View SNKRDUNK" if lang == "en" else "查看 SNKRDUNK"
        view_hist = "View Sales History" if lang == "en" else "查看 SNKRDUNK 銷售歷史"
        report_lines.append(f"🔗 [{view_snkr}]({snkr_url})")
        report_lines.append(f"🔗 [{view_hist}]({snkr_url}/sales-histories)")

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
        # Debug step2: 儲存爬蟲結果
        _debug_log(f"Step 2 PC: {len(pc_records) if pc_records else 0} 筆")
        _debug_log(f"Step 2 SNKR: {len(snkr_records) if snkr_records else 0} 筆")
        _debug_save("step2_pc.json", json.dumps(pc_records or [], indent=2, ensure_ascii=False))
        _debug_save("step2_snkr.json", json.dumps(snkr_records or [], indent=2, ensure_ascii=False))

        data_dump = {
            "card_info": card_info,
            "snkr_records": snkr_records if snkr_records else [],
            "pc_records": pc_records if pc_records else []
        }
        json_path = os.path.join(final_dest_dir, "report_data.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data_dump, f, ensure_ascii=False, indent=2)
            
        # Generate the two separate HTML-based posters (Now with FULL history)
        if stream_mode:
            # ℹ️ Stream Mode：不在這裡等待海報生成，回傳文字報告 + 海報生成所需的資料
            # Bot 收到後會先傳送文字報告，再呼叫 generate_posters() 生成海報
            poster_data = {
                "card_info": card_info,
                "snkr_records": snkr_records,
                "pc_records": pc_records,
                "out_dir": final_dest_dir,
            }
            return (final_report, poster_data)
        else:
            out_paths = await image_generator.generate_report(card_info, snkr_records, pc_records, out_dir=final_dest_dir)
            return (final_report, out_paths)
        
    # Debug step3: 儲存最終報告
    _debug_log("Step 3: 報告生成完成")
    _debug_save("step3_report.md", final_report)
    
    return final_report

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

async def generate_posters(poster_data):
    """
    將 process_single_image(stream_mode=True) 回傳的 poster_data dict
    傳入，生成 profile + data 兩張海報並回傳路徑清單。
    
    Bot 用法（在傳完文字報告之後呼叫）：
        out_paths = await market_report_vision.generate_posters(poster_data)
    """
    return await image_generator.generate_report(
        poster_data["card_info"],
        poster_data["snkr_records"],
        poster_data["pc_records"],
        out_dir=poster_data["out_dir"],
    )
