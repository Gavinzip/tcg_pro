import os
import urllib.request
import base64
import io
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from datetime import datetime
from playwright.async_api import async_playwright
import re
import asyncio

# Font loading for different environments
font_path_mac = '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
font_path_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'NotoSansCJK-Bold.ttc')

if os.path.exists(font_path_local):
    fm.fontManager.addfont(font_path_local)
    font_prop = fm.FontProperties(fname=font_path_local)
    plt.rcParams['font.family'] = font_prop.get_name()
    print(f"✅ 使用本地字體: {font_path_local}")
elif os.path.exists(font_path_mac):
    fm.fontManager.addfont(font_path_mac)
    plt.rcParams['font.family'] = 'Arial Unicode MS'
    print("✅ 使用系統字體: Arial Unicode MS")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Global semaphore to prevent OOM when multiple people send images simultaneously
# 2GB RAM can safe handle 3-4 simultaneous browser tabs while the bot is running
RENDER_SEMAPHORE = asyncio.Semaphore(3)

class AsyncBrowserManager:
    _instance = None
    _browser = None
    _playwright = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_browser(cls):
        async with cls._lock:
            if cls._browser is None:
                cls._playwright = await async_playwright().start()
                cls._browser = await cls._playwright.chromium.launch(headless=True)
            return cls._browser

    @classmethod
    async def close(cls):
        async with cls._lock:
            if cls._browser:
                await cls._browser.close()
                cls._browser = None
            if cls._playwright:
                await cls._playwright.stop()
                cls._playwright = None

def get_image_base64_from_url(url):
    if not url: return ""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
        with urllib.request.urlopen(req) as response:
            img_data = response.read()
            b64 = base64.b64encode(img_data).decode('utf-8')
            mime = "image/png"
            if url.lower().endswith(".jpg") or url.lower().endswith(".jpeg"):
                mime = "image/jpeg"
            elif url.lower().endswith(".webp"):
                mime = "image/webp"
            return f"data:{mime};base64,{b64}"
    except Exception as e:
        print(f"Failed to fetch image from {url}: {e}")
        return ""

def parse_level_and_desc(text):
    text = str(text).strip()
    match = re.match(r'^([A-Za-z]+)[，,：:\s]+(.*)', text)
    if match:
        return match.group(1).capitalize(), match.group(2).strip()
    return "Medium", text

def get_width_from_level(level):
    l = level.lower()
    if 'high' in l or 'outstanding' in l: return 90
    if 'medium' in l: return 60
    if 'low' in l: return 30
    return 50

def generate_features_html(features_text):
    lines = [L.strip().lstrip('•').strip() for L in str(features_text).split('\n') if L.strip()]
    icons = ['verified', 'hotel_class', 'bolt', 'star', 'diamond']
    html = ""
    for i, line in enumerate(lines[:2]):
        title = line
        desc = ""
        if '：' in line:
            parts = line.split('：', 1)
            title = parts[0]
            desc = parts[1]
        elif len(line) > 15:
            title = "Special Feature"
            desc = line
        else:
            title = line
            desc = ""
            
        icon = icons[i % len(icons)]
        col_span = " md:col-span-2" if len(lines) == 3 and i == 2 else ""
        
        desc_html = f'<p class="text-slate-100 text-[14px] mt-1.5 leading-relaxed">{desc}</p>' if desc else ''
        
        html += f"""
<div class="glass-panel p-5 rounded-xl flex items-start gap-4{col_span} relative overflow-hidden group">
<div class="absolute inset-0 bg-primary/5 group-hover:bg-primary/10 transition-colors pointer-events-none"></div>
<span class="material-symbols-outlined text-primary-light drop-shadow-[0_0_5px_rgba(212,175,55,1)] mt-0.5 text-[26px]">{icon}</span>
<div class="relative z-10 flex flex-col justify-center">
<h4 class="text-white font-bold text-[16px] tracking-wide">{title}</h4>
{desc_html}
</div>
</div>
"""
    return html

def generate_table_rows(records, is_jpy=False, target_grade=None):
    if not records:
        return '<tr><td colspan="3" class="p-3 pl-4 text-slate-300 text-center">No transactions found</td></tr>'
        
    filtered_records = []
    if target_grade:
        for r in records:
            if is_jpy:
                filtered_records.append(r)
            else:
                if r.get('grade') == target_grade:
                    filtered_records.append(r)
        
        if not filtered_records:
            filtered_records = records
    else:
        filtered_records = records

    html = ""
    for r in filtered_records[:10]:
        date = r['date']
        grade = r.get('grade', 'Ungraded')
        if is_jpy:
            jpy = int(r['price'])
            usd = int(jpy / 150) # Rough exchange reference
            price_str = f"¥{jpy:,} (~${usd})"
        else:
            price_str = f"${float(r['price']):.2f}"
            
        html += f"""
<tr class="hover:bg-primary/5 transition-colors">
<td class="p-4 pl-4 text-slate-300 text-base">{date}</td>
<td class="p-4 text-slate-400 text-base">{grade}</td>
<td class="p-4 pr-4 text-right font-medium text-primary text-base">{price_str}</td>
</tr>
"""
    return html

def get_badge_html(grade):
    grade_upper = grade.upper()
    if 'PSA' in grade_upper:
        company = 'PSA'
        num = grade_upper.replace('PSA', '').strip()
        label = 'GEM MT' if num == '10' else ('MINT' if num == '9' else 'NM-MT')
        return f"""
<div class="w-24 h-24 bg-gradient-to-br from-primary via-[#e6c21f] to-[#b39616] rounded-full flex items-center justify-center shadow-[0_4px_20px_rgba(0,0,0,0.5)] z-30 border-4 border-[#4a4220]">
<div class="text-center">
<span class="block text-[#4a4220] font-black text-xs tracking-wider">{label}</span>
<span class="block text-[#221f10] font-bold text-3xl leading-none">{num}</span>
<span class="block text-[#4a4220] font-bold text-[10px] tracking-widest mt-0.5">{company}</span>
</div>
</div>"""
    elif 'BGS' in grade_upper:
        return f"""
<div class="w-24 h-24 bg-gradient-to-br from-slate-300 via-slate-100 to-slate-400 rounded-lg flex items-center justify-center shadow-[0_4px_20px_rgba(0,0,0,0.5)] z-30 border-4 border-slate-500 transform rotate-3">
<div class="text-center">
<span class="block text-slate-800 font-bold text-3xl leading-none">{grade_upper.replace('BGS','').strip()}</span>
<span class="block text-slate-600 font-bold text-[10px] tracking-widest mt-0.5">BGS</span>
</div>
</div>"""
    else:
        return f"""
<div class="badge-ungraded px-4 py-2 rounded-full shadow-xl z-30">
<span class="text-slate-200 font-bold text-sm">{grade}</span>
</div>"""


def create_premium_matplotlib_chart_b64(records, color_line='#f4d125', target_grade="PSA 10", is_jpy=False):
    import re
    from datetime import datetime, timedelta
    import matplotlib.dates as mdates
    from collections import defaultdict
    import matplotlib.pyplot as plt
    import io, base64

    if records is None: records = []

    def parse_d(d_str):
        try:
            if '日前' in d_str: return datetime.now() - timedelta(days=int(re.search(r'\d+', d_str).group()))
            if '小時前' in d_str or '時間前' in d_str: return datetime.now() - timedelta(hours=int(re.search(r'\d+', d_str).group()))
            if '分前' in d_str: return datetime.now() - timedelta(minutes=int(re.search(r'\d+', d_str).group()))
            if '-' in d_str: return datetime.strptime(d_str.strip(), '%Y-%m-%d')
            if '/' in d_str: return datetime.strptime(d_str.strip(), '%Y/%m/%d')
            if ',' in d_str: return datetime.strptime(d_str.strip(), '%b %d, %Y')
        except: pass
        return datetime.now()

    if is_jpy:
        if '10' in str(target_grade) or str(target_grade).upper() == 'S': valid_grades = ['S', 'PSA10', 'PSA 10']
        elif str(target_grade).lower() in ['ungraded', 'a']: valid_grades = ['A']
        else: valid_grades = [target_grade, target_grade.replace(' ', '')]

    else:
        if '10' in str(target_grade): valid_grades = ['PSA 10']
        else: valid_grades = None  # None means: show all non-PSA10 records


    if valid_grades is None:
        # Show all non-PSA10 records (PSA 9, Raw, Ungraded, etc.)
        filt = [r for r in records if r.get('grade', 'Ungraded') != 'PSA 10']
    else:
        filt = [r for r in records if r.get('grade', 'Ungraded') in valid_grades]

    
    date_to_prices = defaultdict(list)
    for r in filt:
        d = parse_d(r['date']).date() 
        price_val = float(r['price'])
        if is_jpy:
            price_val = price_val / 150.0
        date_to_prices[d].append(price_val)
        
    sorted_dates = sorted(list(date_to_prices.keys()))

    # Trim leading gap: if consecutive data points have a gap >= 60 days (2 months),
    # only show data from after the last such gap (avoids ugly blank stretches)
    if len(sorted_dates) > 1:
        cutoff_idx = 0
        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i] - sorted_dates[i - 1]).days >= 60:
                cutoff_idx = i
        if cutoff_idx > 0:
            sorted_dates = sorted_dates[cutoff_idx:]

    fig, ax1 = plt.subplots(figsize=(6, 2.5), facecolor='none')
    ax1.set_facecolor('none')

    if not sorted_dates:
        ax1.axis('off')
        buf = io.BytesIO()
        plt.savefig(buf, format='png', transparent=True)
        buf.seek(0)
        plt.close(fig)
        return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"
        
    prices = [sum(date_to_prices[d])/len(date_to_prices[d]) for d in sorted_dates]
    volumes = [len(date_to_prices[d]) for d in sorted_dates]
    
    # Legend labels
    price_label = "Price (Daily Avg)" if not is_jpy else "Price (Daily Avg, USD)"
    vol_label = "Quantity"

    if len(sorted_dates) == 1:
        sorted_dates = [sorted_dates[0] - timedelta(days=1), sorted_dates[0], sorted_dates[0] + timedelta(days=1)]
        prices = [prices[0], prices[0], prices[0]]
        volumes = [0, volumes[0], 0]

    ax2 = ax1.twinx()
    
    # 1. Bar Chart (Volume / Quantity) on Right Axis
    bar_color = '#fed7aa' # Light orange
    ax2.bar(sorted_dates, volumes, color=bar_color, alpha=0.85, width=0.7, zorder=1, label="Quantity")
    
    # 2. Line Chart (Price) on Left Axis
    ax1.plot(sorted_dates, prices, color=color_line, linewidth=3.0, zorder=4, label=price_label)
    ax1.scatter(sorted_dates, prices, color=color_line, s=50, edgecolors='#ffffff', linewidths=1.5, zorder=5)

    # Styles
    for ax in [ax1, ax2]:
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
    ax1.spines['bottom'].set_color('#685f31')
    ax2.spines['bottom'].set_visible(False)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    
    ax1.tick_params(axis='x', colors='#cbc190', labelsize=13)
    ax1.tick_params(axis='y', colors='#cbc190', labelsize=13)
    ax2.tick_params(axis='y', colors='#a1a1aa', labelsize=13)
    
    # Bold labels
    for t in ax1.get_xticklabels() + ax1.get_yticklabels():
        t.set_fontweight('bold')
    for t in ax2.get_yticklabels():
        t.set_fontweight('bold')

    plt.tight_layout()
    # Stretch X-axis
    plt.margins(x=0.08)

    ax1.yaxis.grid(color='#f4d125', linestyle=':', linewidth=1, alpha=0.2)
    ax1.xaxis.grid(color='#f4d125', linestyle=':', linewidth=1, alpha=0.1)

    # Ensure Line draws over Bars
    ax1.set_zorder(ax2.get_zorder()+1)
    ax1.patch.set_visible(False)
    
    # Scale ax2 so bars only occupy bottom half
    ax2.set_ylim(0, max(volumes) * 2.2)

    # Legend
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, [price_label, vol_label], loc='upper left', prop={'size': 11}, frameon=False, labelcolor='white')

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', transparent=True, dpi=200)
    buf.seek(0)
    plt.close(fig)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"

def calculate_arbitrage_stats(pc_records, snkr_records):
    pc_safe = pc_records or []
    snkr_safe = snkr_records or []
    
    # Calculate stats for the bottom section
    prices_10 = [float(r['price']) for r in pc_safe if '10' in str(r.get('grade', ''))]
    prices_raw = [float(r['price']) for r in pc_safe if 'Ungraded' in str(r.get('grade', ''))]
    prices_9 = [float(r['price']) for r in pc_safe if '9' in str(r.get('grade', ''))]
    
    avg_10 = sum(prices_10)/len(prices_10) if len(prices_10) > 0 else 0
    max_10 = max(prices_10) if len(prices_10) > 0 else 0
    avg_raw = sum(prices_raw)/len(prices_raw) if len(prices_raw) > 0 else 0
    avg_9 = sum(prices_9)/len(prices_9) if len(prices_9) > 0 else 0
    
    snkr_10 = [float(r['price']) for r in snkr_safe if r.get('grade', '') in ['S', 'PSA10', 'PSA 10']]
    snkr_raw = [float(r['price']) for r in snkr_safe if 'A' in str(r.get('grade', ''))]
    
    # Arbitrage Profit estimation for Raw -> PSA 10 (Targeting Max Price)
    # Grading fee estimated around 1100 TWD (~$35 USD) + 10% value upcharge
    profit = 0
    if max_10 > 0 and avg_raw > 0:
        grading_cost = 35.0 + (max_10 * 0.10)
        profit = max_10 - (avg_raw + grading_cost)
        
    return avg_10, avg_9, avg_raw, profit, max_10

async def generate_report(card_data, snkr_records, pc_records, out_dir=None):
    if not out_dir:
        out_dir = BASE_DIR
        
    template1_path = os.path.join(BASE_DIR, "templates", "report_template_1.html")
    template2_path = os.path.join(BASE_DIR, "templates", "report_template_2.html")
    
    with open(template1_path, 'r', encoding='utf-8') as f:
        html1 = f.read()
    with open(template2_path, 'r', encoding='utf-8') as f:
        html2 = f.read()

    name = card_data.get('c_name') or card_data.get('jp_name') or card_data.get('name', 'Unknown Trading Card')
    safe_name = name.replace(' ', '_').replace('/', '_')
    
    mh_level, mh_desc = parse_level_and_desc(card_data.get('market_heat', 'Medium'))
    cv_level, cv_desc = parse_level_and_desc(card_data.get('collection_value', 'Medium'))
    cf_level, cf_desc = parse_level_and_desc(card_data.get('competitive_freq', 'Low'))
    
    card_img_b64 = get_image_base64_from_url(card_data.get('img_url', ''))
    
    p_prices = [r['price'] for r in pc_records] if pc_records else [0]
    total_entries = (len(snkr_records) if snkr_records else 0) + (len(pc_records) if pc_records else 0)
    
    avg_10, avg_9, avg_raw, profit, max_10 = calculate_arbitrage_stats(pc_records, snkr_records) if pc_records else (0,0,0,0,0)
    
    market_grade = str(card_data.get('grade', 'Ungraded')).upper()
    if market_grade in ['UNGRADED', 'A']:
        badge_mode = 'ungraded'
    elif 'PSA' in market_grade or 'BGS' in market_grade:
        badge_mode = 'psa10'
    else:
        badge_mode = 'both'
        
    from datetime import datetime, timedelta
    import re
    
    def parse_d(d_str):
        try:
            if '日前' in d_str: return datetime.now() - timedelta(days=int(re.search(r'\d+', d_str).group()))
            if '小時前' in d_str or '時間前' in d_str: return datetime.now() - timedelta(hours=int(re.search(r'\d+', d_str).group()))
            if '分前' in d_str: return datetime.now() - timedelta(minutes=int(re.search(r'\d+', d_str).group()))
            if '-' in d_str: return datetime.strptime(d_str.strip(), '%Y-%m-%d')
            if '/' in d_str: return datetime.strptime(d_str.strip(), '%Y/%m/%d')
            if ',' in d_str: return datetime.strptime(d_str.strip(), '%b %d, %Y')
        except: pass
        return datetime.now()

    target_grade_1 = card_data.get('grade', 'Ungraded')
    recent_prices = []
    sixty_days_ago = datetime.now() - timedelta(days=60)
    
    if pc_records:
        recent_prices.extend([float(r['price']) for r in pc_records if r.get('grade') == target_grade_1 and parse_d(r['date']) >= sixty_days_ago])
        
    if snkr_records:
        if '10' in target_grade_1:
            valid_snkr_grades = ['S', 'PSA10', 'PSA 10']
        elif target_grade_1.lower() == 'ungraded':
            valid_snkr_grades = ['A']
        else:
            valid_snkr_grades = [target_grade_1, target_grade_1.replace(' ', '')]
            
        recent_prices.extend([float(r['price']) / 150.0 for r in snkr_records if r.get('grade') in valid_snkr_grades and parse_d(r['date']) >= sixty_days_ago])
        
    recent_avg = sum(recent_prices) / len(recent_prices) if recent_prices else 0
    recent_avg_str = f"${recent_avg:.2f}" if recent_avg > 0 else "N/A"

    replacements_1 = {
        "{{ card_name }}": name,
        "{{ card_number }}": card_data.get('number', 'Unknown'),
        "{{ card_set }}": card_data.get('set_code', 'Unknown Set'),
        "{{ grade }}": card_data.get('grade', 'Ungraded'),
        "{{ badge_mode }}": badge_mode,
        "{{ category }}": card_data.get('category', 'PROMO'),
        "{{ market_heat_level }}": mh_level,
        "{{ market_heat_desc }}": mh_desc,
        "{{ market_heat_width }}": str(get_width_from_level(mh_level)),
        "{{ collection_value_level }}": cv_level,
        "{{ collection_value_desc }}": cv_desc,
        "{{ collection_value_width }}": str(get_width_from_level(cv_level)),
        "{{ competitive_freq_level }}": cf_level,
        "{{ competitive_freq_desc }}": cf_desc,
        "{{ competitive_freq_width }}": str(get_width_from_level(cf_level)),
        "{{ features_html }}": generate_features_html(card_data.get('features', '')),
        "{{ illustrator }}": card_data.get('illustrator', 'Unknown'),
        "{{ release_info }}": card_data.get('release_info', 'Unknown'),
        "{{ card_image }}": card_img_b64,
        "{{ badge_html }}": get_badge_html(card_data.get('grade', 'Ungraded')),
        "{{ recent_avg_price }}": recent_avg_str,
        "{{ target_grade }}": target_grade_1
    }
    
    import re
    for k, v in replacements_1.items():
        # Convert "{{ key }}" to pattern "\{\{\s*key\s*\}\}"
        core_key = k.replace('{{ ', '').replace(' }}', '').replace('{{', '').replace('}}', '').strip()
        pattern = r'\{\{\s*' + re.escape(core_key) + r'\s*\}\}'
        html1 = re.sub(pattern, str(v).replace('\\', r'\\') if v is not None else "", html1)
        

    # --- Dynamic Charts and Stats Construction ---
    target_grade = card_data.get('grade', 'Ungraded')
    is_raw = target_grade in ['Ungraded', 'A']

    if is_raw:
        # Generate 4 Charts (2 per column) with 30-day volume metrics overlaid
        c_pc_10 = create_premium_matplotlib_chart_b64(pc_records, color_line='#f4d125', target_grade='PSA 10', is_jpy=False)
        c_pc_raw = create_premium_matplotlib_chart_b64(pc_records, color_line='#f4d125', target_grade='Ungraded', is_jpy=False)
        c_sk_10 = create_premium_matplotlib_chart_b64(snkr_records, color_line='#f4d125', target_grade='S', is_jpy=True)
        c_sk_raw = create_premium_matplotlib_chart_b64(snkr_records, color_line='#f4d125', target_grade='A', is_jpy=True)
        
        v_pc_10 = count_30_days(pc_records, 'PSA 10')
        v_pc_raw_cutoff = datetime.now() - timedelta(days=30)
        v_pc_raw = len([r for r in (pc_records or []) if r.get('grade') != 'PSA 10' and parse_d(r['date']) > v_pc_raw_cutoff])
        
        # SNKRDUNK volume metrics (Synced with chart filters)
        v_sk_10_cutoff = datetime.now() - timedelta(days=30)
        v_sk_10 = len([r for r in (snkr_records or []) if r.get('grade') in ['S', 'PSA10', 'PSA 10'] and parse_d(r['date']) > v_sk_10_cutoff])
        v_sk_raw = count_30_days(snkr_records, 'A')

        pc_charts_html = f"""
        <div class="w-full flex flex-col gap-8 mb-4 mt-4">
            <div class="relative glass-panel rounded-xl border border-green-500/40 p-2 shadow-[0_0_20px_rgba(34,197,94,0.15)]">
                <span class="absolute top-[-14px] left-4 text-[10px] font-bold text-white tracking-widest bg-black border border-green-500/50 px-3 py-1 rounded-full z-20 shadow-lg">PSA 10 Trend</span>
                <span class="absolute top-[-14px] right-4 text-[10px] font-bold text-white bg-black/90 px-3 py-1 rounded-full border border-green-500/50 z-20 shadow-lg">30d Vol: {v_pc_10} Set</span>
                <img src="{c_pc_10}" class="w-full h-[155px] object-contain mix-blend-screen opacity-90" />
            </div>
            <div class="relative glass-panel rounded-xl border border-red-500/40 p-2 shadow-[0_0_20px_rgba(239,68,68,0.15)]">
                <span class="absolute top-[-14px] left-4 text-[10px] font-bold text-white tracking-widest bg-black border border-red-500/50 px-3 py-1 rounded-full z-20 shadow-lg">Ungraded Trend</span>
                <span class="absolute top-[-14px] right-4 text-[10px] font-bold text-white bg-black/90 px-3 py-1 rounded-full border border-red-500/50 z-20 shadow-lg">30d Vol: {v_pc_raw} Set</span>
                <img src="{c_pc_raw}" class="w-full h-[155px] object-contain mix-blend-screen opacity-90" />
            </div>
        </div>"""
        
        snkr_charts_html = f"""
        <div class="w-full flex flex-col gap-8 mb-4 mt-4">
            <div class="relative glass-panel rounded-xl border border-green-500/40 p-2 shadow-[0_0_20px_rgba(34,197,94,0.15)]">
                <span class="absolute top-[-14px] left-4 text-[10px] font-bold text-white tracking-widest bg-black border border-green-500/50 px-3 py-1 rounded-full z-20 shadow-lg">PSA 10 Trend</span>
                <span class="absolute top-[-14px] right-4 text-[10px] font-bold text-white bg-black/90 px-3 py-1 rounded-full border border-green-500/50 z-20 shadow-lg">30d Vol: {v_sk_10} Set</span>
                <img src="{c_sk_10}" class="w-full h-[155px] object-contain mix-blend-screen opacity-90" />
            </div>
            <div class="relative glass-panel rounded-xl border border-red-500/40 p-2 shadow-[0_0_20px_rgba(239,68,68,0.15)]">
                <span class="absolute top-[-14px] left-4 text-[10px] font-bold text-white tracking-widest bg-black border border-red-500/50 px-3 py-1 rounded-full z-20 shadow-lg">Ungraded Trend</span>
                <span class="absolute top-[-14px] right-4 text-[10px] font-bold text-white bg-black/90 px-3 py-1 rounded-full border border-red-500/50 z-20 shadow-lg">30d Vol: {v_sk_raw} Set</span>
                <img src="{c_sk_raw}" class="w-full h-[155px] object-contain mix-blend-screen opacity-90" />
            </div>
        </div>"""

        stat_1_t, stat_1_v = "PSA 10 Avg (完整品)", f"${avg_10:.2f}" if avg_10 > 0 else "N/A"
        stat_2_t, stat_2_v = "Ungraded Avg (裸卡)", f"${avg_raw:.2f}" if avg_raw > 0 else "N/A"
        stat_3_t, stat_3_v = "PSA 10 Max (最高成交價)", f"${max_10:.2f}" if max_10 > 0 else "N/A"
        stat_4_t, stat_4_v = f"Total Entries{days_span}", str(total_entries)
        
        pc_table_html = ""
        snkr_table_html = ""
        
    else:
        # Standard 2 Charts (For Graded Cards)
        if snkr_records:
            if '10' in target_grade:
                valid_snkr_grades = ['S', 'PSA10', 'PSA 10']
            elif target_grade.lower() == 'ungraded':
                valid_snkr_grades = ['A']
            else:
                valid_snkr_grades = [target_grade, target_grade.replace(' ', '')]
            
            snkr_target_records = [r for r in snkr_records if r['grade'] in valid_snkr_grades]
        else:
            snkr_target_records = []

        c_pc = create_premium_matplotlib_chart_b64(pc_records, color_line='#f4d125', target_grade=target_grade, is_jpy=False)
        c_sk = create_premium_matplotlib_chart_b64(snkr_target_records, color_line='#f4d125', target_grade=target_grade, is_jpy=True)
        
        pc_charts_html = f"""
        <div class="w-full h-44 mb-10 flex items-center justify-center relative">
            <div class="relative glass-panel rounded-xl border border-border-gold/30 p-2 w-full h-full">
                <span class="absolute top-[-14px] left-4 text-[10px] font-bold text-white tracking-widest bg-black border border-border-gold/50 px-3 py-1 rounded-full z-20 shadow-lg">Price Chart</span>
                <img src="{c_pc}" class="w-full h-full object-contain mix-blend-screen" />
            </div>
        </div>"""
        
        pc_table_html = f"""
                <div class="flex-1 glass-panel rounded-xl overflow-hidden p-3 border border-border-gold/30">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-border-gold/20 text-[10px] font-black uppercase tracking-widest text-primary-dark">
                                <th class="p-3">Date (日期)</th>
                                <th class="p-3">Grade (狀態)</th>
                                <th class="p-3 text-right">Price (金額)</th>
                            </tr>
                        </thead>
                        <tbody class="text-sm divide-y divide-border-gold/10">
                            {generate_table_rows(pc_records, is_jpy=False, target_grade=card_data.get('grade', ''))}
                        </tbody>
                    </table>
                </div>"""
        
        snkr_charts_html = f"""
        <div class="w-full h-44 mb-6 flex items-center justify-center">
            <img src="{c_sk}" class="w-full h-full object-contain mix-blend-screen" />
        </div>"""
        
        snkr_table_html = f"""
                <div class="flex-1 glass-panel rounded-xl overflow-hidden p-3 border border-border-gold/30">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="border-b border-border-gold/20 text-[10px] font-black uppercase tracking-widest text-primary-dark">
                                <th class="p-3">Time (時間)</th>
                                <th class="p-3">Grade (狀態)</th>
                                <th class="p-3 text-right">Price (金額)</th>
                            </tr>
                        </thead>
                        <tbody class="text-sm divide-y divide-border-gold/10">
                            {generate_table_rows(snkr_target_records, is_jpy=True)}
                        </tbody>
                    </table>
                </div>"""
                
        tgt_prices = []
        if pc_records:
            tgt_prices.extend([float(r['price']) for r in pc_records if r.get('grade') == target_grade])
        if snkr_target_records:
            tgt_prices.extend([float(r['price']) / 150.0 for r in snkr_target_records])
            
        avg_tgt = sum(tgt_prices)/len(tgt_prices) if tgt_prices else 0
        stat_1_t, stat_1_v = f"{target_grade} Avg (均價)", f"${avg_tgt:.2f}" if avg_tgt > 0 else "N/A"
        # SAFETY CHECK for empty sequences
        stat_2_t, stat_2_v = f"{target_grade} Min (最低)", f"${min(tgt_prices):.2f}" if tgt_prices else "N/A"
        stat_3_t, stat_3_v = f"{target_grade} Max (最高)", f"${max(tgt_prices):.2f}" if tgt_prices else "N/A"
        
        stat_4_t, stat_4_v = f"Total Entries{days_span}", str(total_entries)

    replacements_2 = {
        "{{ card_name }}": name,
        "{{ card_set }}": card_data.get('set_code', ''),
        "{{ grade }}": card_data.get('grade', ''),
        "{{ stat_1_title }}": stat_1_t,
        "{{ stat_1_val }}": stat_1_v,
        "{{ stat_2_title }}": stat_2_t,
        "{{ stat_2_val }}": stat_2_v,
        "{{ stat_3_title }}": stat_3_t,
        "{{ stat_3_val }}": stat_3_v,
        "{{ stat_4_title }}": stat_4_t,
        "{{ stat_4_val }}": stat_4_v,
        "{{ pc_charts_html }}": pc_charts_html,
        "{{ pc_table_html }}": pc_table_html,
        "{{ snkr_charts_html }}": snkr_charts_html,
        "{{ snkr_table_html }}": snkr_table_html
    }
    
    for k, v in replacements_2.items():
        core_key = k.replace('{{ ', '').replace(' }}', '').replace('{{', '').replace('}}', '').strip()
        pattern = r'\{\{\s*' + re.escape(core_key) + r'\s*\}\}'
        html2 = re.sub(pattern, str(v).replace('\\', r'\\') if v is not None else "", html2)

    out_path_1 = os.path.join(out_dir, f"report_{safe_name}_profile.png")
    out_path_2 = os.path.join(out_dir, f"report_{safe_name}_data.png")

    async with RENDER_SEMAPHORE:
        browser = await AsyncBrowserManager.get_browser()
        
        # We create a fresh context per request but reuse the browser instance
        # This is very memory efficient and fast
        context = await browser.new_context(viewport={'width': 1200, 'height': 900})
        
        try:
            page1 = await context.new_page()
            await page1.set_content(html1, wait_until="networkidle")
            await page1.screenshot(path=out_path_1, full_page=True)
            await page1.close()
            
            page2 = await context.new_page()
            await page2.set_content(html2, wait_until="networkidle")
            await page2.screenshot(path=out_path_2, full_page=True)
            await page2.close()
        finally:
            await context.close()

    return [out_path_1, out_path_2]

if __name__ == "__main__":
    import random
    from datetime import timedelta
    test_data = {
        'c_name': '皮卡丘 V (Pikachu V)',
        'set_code': '25th Anniversary Golden Box',
        'number': '005/015',
        'category': 'Promo',
        'grade': 'PSA 10',
        'release_info': '2021 Pokemon Japanese',
        'illustrator': 'Ryota Murayama',
        'img_url': 'https://s3.ap-northeast-1.amazonaws.com/image.snkrdunk.com/trading-cards/products/202501/7/8ce38fc1-f761-4606-aec0-d3e9c5edc507.jpg',
        'market_heat': 'High，此卡來自於全球熱搶的 25 週年黃金紀念箱，皮卡丘作為招牌角色，其限定版本在二手中市場具有極高的流動性與熱度。',
        'collection_value': 'High，黃金盒限定卡片且具備 PSA 10 的滿分等級，在收藏市場中屬於頂級配置，具備非常穩定的長期持有價值。',
        'competitive_freq': 'Low，雖然可以在官方賽事中使用，但這張卡片主要被視為收藏品，在主流競技套牌中的出現頻率較低。',
        'features': '• 25 週年紀念限定版本\n• 卡面印有 25th Anniversary 專屬標誌\n• 全圖閃卡工藝配合生動的電擊特效背景'
    }
    
    snkr_test = []
    base_date = datetime(2025, 2, 8)
    current_price = 150000
    for i in range(10):
        d = (base_date - timedelta(days=i)).strftime('%Y/%m/%d')
        current_price = current_price + random.randint(-5000, 6000)
        snkr_test.append({'date': d, 'price': current_price, 'grade': 'PSA 10'})
            
    pc_test = []
    current_usd = 1100
    for i in range(10):
        d = (base_date - timedelta(days=i*1.2)).strftime('%Y-%m-%d')
        current_usd = current_usd + random.randint(-20, 25)
        pc_test.append({'date': d, 'price': current_usd, 'grade': 'PSA 10'})
    
    print("Generating HTML/Playwright Two-Poster Report...")
    out_imgs = generate_report(test_data, snkr_test, pc_test)
    print(f"Posters saved to {out_imgs}")
