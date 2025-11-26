# Last updated: Paper Trading Tab Fixed - Removed blocking time.sleep() and debug messages
import streamlit as st
import math
import numpy as np
import matplotlib.pyplot as plt
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import time
import threading
import json

# ==================== Core math ====================
def calculate_levels(price: float):
    s = math.sqrt(price)

    buy = round((s + 1/12)**2, 2)
    sell = round((s - 1/12)**2, 2)

    bull_targets = [round((s + k/9)**2, 2) for k in range(1, 10)]
    bear_targets = [round((s - k/9)**2, 2) for k in range(1, 10)]

    b = math.ceil(s)
    breakout = round(b**2, 2)
    resistances = [round((b + x)**2, 2) for x in (0.5, 1.0, 1.5)]
    supports = [round((b - x)**2, 2) for x in (0.5, 1.0, 1.5)]

    return {
        "buy": buy,
        "sell": sell,
        "bull_targets": bull_targets,
        "bear_targets": bear_targets,
        "breakout": breakout,
        "resistances": resistances,
        "supports": supports,
    }

# ==================== Risk to Reward helpers ====================
def rr_long(entry, stop, targets):
    risk = max(entry - stop, 1e-9)
    return [round(max(t - entry, 0.0) / risk, 2) for t in targets]

def rr_short(entry, stop, targets):
    risk = max(stop - entry, 1e-9)
    return [round(max(entry - t, 0.0) / risk, 2) for t in targets]

# ==================== Trading Cost Calculation ====================
def calculate_trading_costs(entry_price, exit_price, quantity, brokerage_per_order, stt_pct, txn_charges_pct, gst_pct):
    """
    Calculate total trading costs including brokerage, STT, transaction charges, and GST
    """
    turnover = (entry_price + exit_price) * quantity
    
    # Brokerage (buy + sell)
    brokerage_buy = brokerage_per_order
    brokerage_sell = brokerage_per_order
    total_brokerage = brokerage_buy + brokerage_sell
    
    # STT (only on sell side for equity delivery/intraday)
    stt = (exit_price * quantity) * (stt_pct / 100)
    
    # Transaction charges (both sides)
    txn_charges = turnover * (txn_charges_pct / 100)
    
    # GST on brokerage and transaction charges
    gst_base = total_brokerage + txn_charges
    gst = gst_base * (gst_pct / 100)
    
    # Total costs
    total_cost = total_brokerage + stt + txn_charges + gst
    
    return {
        'brokerage': total_brokerage,
        'stt': stt,
        'transaction_charges': txn_charges,
        'gst': gst,
        'total': total_cost
    }

# ==================== Donut chart ====================
def donut_chart(values, labels, center_label, cmap_name):
    fig, ax = plt.subplots(figsize=(5, 5), facecolor='white')
    ax.axis('equal')
    cmap = plt.cm.get_cmap(cmap_name)
    colors = [cmap(i) for i in np.linspace(0.4, 0.85, len(values))]

    wedges, texts = ax.pie(
        [1] * len(values),
        labels=labels,
        labeldistance=1.08,
        startangle=90,
        counterclock=False,
        colors=colors,
        wedgeprops=dict(width=0.3, edgecolor='white', linewidth=2.5),
    )
    
    # Style the labels
    for text in texts:
        text.set_fontsize(9)
        text.set_fontweight('bold')

    centre_circle = plt.Circle((0, 0), 0.58, color='white', fc='white', linewidth=0)
    ax.add_artist(centre_circle)

    # Center text with better styling
    ax.text(0, 0, center_label.replace("\\n", "\n"), 
            ha='center', va='center', 
            fontsize=13, fontweight='bold',
            color='#2d3748')

    plt.tight_layout(pad=0.5)
    st.pyplot(fig, use_container_width=True)

# ==================== Page ====================
st.set_page_config(page_title="Square-of-9 Level Calculator", page_icon="📈", layout="wide")

# ==================== Popular Stocks (Suggestions) ====================
POPULAR_STOCKS_INDIA = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "HINDUNILVR.NS",
    "ICICIBANK.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
    "WIPRO.NS", "BAJFINANCE.NS", "TATASTEEL.NS", "ADANIGREEN.NS", "M&M.NS"
]

POPULAR_STOCKS_US = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "JPM", "V", "WMT",
    "JNJ", "PG", "MA", "UNH", "HD", "DIS", "NFLX", "BAC", "KO", "PFE"
]

st.markdown(
    """
    <style>
    /* Global Styles */
    .main {
        padding-top: 2rem;
    }
    
    /* Header */
    .app-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 8px 32px rgba(102, 126, 234, 0.25);
    }
    .app-title {
        color: white;
        font-size: 2.5rem;
        font-weight: 800;
        margin: 0;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
        display: inline-block;
    }
    .tooltip-icon {
        display: inline-block;
        position: relative;
        cursor: help;
        font-size: 2rem;
        margin-left: 0.3rem;
        transition: transform 0.3s ease;
    }
    .tooltip-icon:hover {
        transform: scale(1.2) rotate(10deg);
    }
    .tooltip-icon .tooltiptext {
        visibility: hidden;
        width: 200px;
        background: linear-gradient(135deg, #2d3748 0%, #1a202c 100%);
        color: #fff;
        text-align: center;
        border-radius: 10px;
        padding: 10px 15px;
        position: absolute;
        z-index: 1000;
        bottom: 125%;
        left: 50%;
        margin-left: -100px;
        opacity: 0;
        transition: opacity 0.3s, visibility 0.3s;
        font-size: 0.95rem;
        font-weight: 600;
        box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }
    .tooltip-icon .tooltiptext::after {
        content: "";
        position: absolute;
        top: 100%;
        left: 50%;
        margin-left: -8px;
        border-width: 8px;
        border-style: solid;
        border-color: #2d3748 transparent transparent transparent;
    }
    .tooltip-icon:hover .tooltiptext {
        visibility: visible;
        opacity: 1;
    }
    .app-subtitle {
        color: rgba(255,255,255,0.9);
        font-size: 1.1rem;
        margin: 0.5rem 0 0 0;
        font-weight: 400;
    }
    
    /* Simulation Styles */
    .sim-result-box {
        background: linear-gradient(135deg, #f7fafc 0%, #edf2f7 100%);
        border-radius: 16px;
        padding: 2rem;
        margin: 2rem 0;
        box-shadow: 0 8px 24px rgba(0,0,0,0.1);
    }
    .sim-metric {
        text-align: center;
        padding: 1.5rem;
        background: white;
        border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.06);
        margin: 0.5rem;
    }
    .sim-metric-label {
        font-size: 0.9rem;
        color: #718096;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .sim-metric-value {
        font-size: 1.8rem;
        font-weight: 800;
        color: #2d3748;
    }
    .sim-metric-value.profit {
        color: #0c6f3c;
    }
    .sim-metric-value.loss {
        color: #c53030;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    .simulating {
        animation: pulse 1.5s ease-in-out infinite;
    }
    
    /* Input Section */
    .input-container {
        background: white;
        padding: 1.5rem 2rem;
        border-radius: 12px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.06);
        margin-bottom: 2rem;
    }
    
    /* Panels */
    .panel {
        background: linear-gradient(135deg, #e9f7ef 0%, #d4f1e1 100%);
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        border: none;
        color: #143b2a;
        box-shadow: 0 4px 12px rgba(12, 111, 60, 0.08);
        margin-bottom: 1rem;
    }
    
    .panel-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.5rem 0;
        border-bottom: 1px solid rgba(205, 235, 220, 0.4);
    }
    .panel-item:last-child {
        border-bottom: none;
    }
    
    .box {
        background: linear-gradient(135deg, #eef6ff 0%, #d9e8ff 100%);
        border-radius: 12px;
        padding: 1.5rem;
        border: none;
        margin-top: 1rem;
        color: #0f2240;
        box-shadow: 0 4px 12px rgba(31, 79, 133, 0.08);
        text-align: center;
    }
    
    .support {
        background: linear-gradient(135deg, #fff5f5 0%, #ffe6e6 100%);
        border: none;
        color: #3a1b1b;
        box-shadow: 0 4px 12px rgba(138, 28, 28, 0.08);
    }
    
    .res-key {
        color: #4a5568;
        font-weight: 600;
        font-size: 0.95rem;
    }
    
    .res-val {
        font-weight: 800;
        color: #0c6f3c;
        font-size: 1.1rem;
    }
    
    .sup-val {
        font-weight: 800;
        color: #c53030;
        font-size: 1.1rem;
    }
    
    .small {
        font-size: 0.875rem;
        color: #718096;
        padding: 1rem 0;
    }
    
    .header-btn {
        background: linear-gradient(135deg, #2d5a87 0%, #1f4f85 100%);
        color: white;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        font-weight: 700;
        text-align: center;
        width: 100%;
        font-size: 1.1rem;
        box-shadow: 0 4px 12px rgba(31, 79, 133, 0.2);
        margin-bottom: 1.5rem;
        letter-spacing: 0.5px;
    }
    
    /* How to Use Section */
    .how-section-title {
        font-size: 1.75rem;
        font-weight: 700;
        color: #2d3748;
        margin: 3rem 0 1.5rem 0;
        padding-bottom: 0.75rem;
        border-bottom: 3px solid #667eea;
    }
    
    .how-box {
        border-radius: 12px;
        padding: 1.5rem 1.75rem;
        margin: 1rem 0;
        box-shadow: 0 4px 16px rgba(0,0,0,0.08);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    
    .how-box:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 24px rgba(0,0,0,0.12);
    }
    
    .how-long {
        background: linear-gradient(135deg, #e7f8ee 0%, #d4f1e1 100%);
        color: #0a2b12;
        border: 2px solid #a8e6c1;
    }
    
    .how-short {
        background: linear-gradient(135deg, #fde8e8 0%, #fcd4d4 100%);
        color: #330606;
        border: 2px solid #f5a3a3;
    }
    
    .how-title {
        font-size: 1.2rem;
        font-weight: 800;
        margin-bottom: 1rem;
        letter-spacing: 0.3px;
    }
    
    .how-text {
        font-size: 0.95rem;
        line-height: 1.7;
        margin: 0 0 0.65rem 0;
    }
    
    .note-box {
        background: #f7fafc;
        border-left: 4px solid #667eea;
        padding: 1rem 1.5rem;
        margin-top: 2rem;
        border-radius: 8px;
        font-size: 0.9rem;
        color: #4a5568;
    }
    
    /* Streamlit Elements Override */
    div[data-testid="stNumberInput"] {
        margin-top: 0 !important;
    }
    
    .stSelectbox label {
        font-weight: 600 !important;
        font-size: 1rem !important;
        color: #2d3748 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==================== Header ====================
st.markdown(
    """
    <div class="app-header">
        <h1 class="app-title">
            📈 TradeGann<span class="tooltip-icon">!
                <span class="tooltiptext">Square-of-9</span>
            </span>
        </h1>
        <p class="app-subtitle">Advanced trading levels calculator using Gann's Square-of-9 technique</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ==================== Tab Navigation ====================
tab1, tab2, tab3, tab4 = st.tabs(["📊 Calculator", "🎮 Simulation", "📈 Paper Trading", "📋 Reports"])

# ====================================
# TAB 1: CALCULATOR
# ====================================
with tab1:
    # ==================== Input Row ====================
    st.markdown("### 📊 Select Stock or Enter Price")

    # Stock selection with tabs for popular stocks and custom entry
    col_stock_tabs, col_divider, col_price = st.columns([2, 0.3, 2])
    
    # Initialize tracking for which input changed
    if 'prev_calc_india' not in st.session_state:
        st.session_state.prev_calc_india = ""
    if 'prev_calc_us' not in st.session_state:
        st.session_state.prev_calc_us = ""
    if 'prev_calc_custom' not in st.session_state:
        st.session_state.prev_calc_custom = ""
    
    with col_stock_tabs:
        stock_tab1, stock_tab2, stock_tab3 = st.tabs(["🇮🇳 Indian Stocks", "🇺🇸 US Stocks", "✏️ Custom"])
        
        with stock_tab1:
            selected_stock_india = st.selectbox(
                "Popular Indian Stocks", 
                [""] + POPULAR_STOCKS_INDIA, 
                index=0,
                key="calc_stock_india",
                label_visibility="collapsed"
            )
        
        with stock_tab2:
            selected_stock_us = st.selectbox(
                "Popular US Stocks", 
                [""] + POPULAR_STOCKS_US, 
                index=0,
                key="calc_stock_us",
                label_visibility="collapsed"
            )
        
        with stock_tab3:
            custom_stock = st.text_input(
                "Enter Stock Symbol",
                placeholder="e.g., AAPL, GOOGL, RELIANCE.NS, etc.",
                key="calc_stock_custom",
                help="Enter any valid stock ticker (add .NS for Indian stocks, .BO for BSE)"
            )
    
    # Determine which input changed and set selected_stock accordingly
    selected_stock = ""
    
    # Check which value changed from its previous state
    india_changed = selected_stock_india != st.session_state.prev_calc_india
    us_changed = selected_stock_us != st.session_state.prev_calc_us
    custom_changed = custom_stock != st.session_state.prev_calc_custom
    
    # Priority: use the one that changed (custom has lowest priority if multiple changed)
    if india_changed and selected_stock_india:
        selected_stock = selected_stock_india
        st.session_state.prev_calc_india = selected_stock_india
    elif us_changed and selected_stock_us:
        selected_stock = selected_stock_us
        st.session_state.prev_calc_us = selected_stock_us
    elif custom_changed and custom_stock:
        selected_stock = custom_stock.upper()
        st.session_state.prev_calc_custom = custom_stock
    else:
        # No change detected, use the last non-empty value
        if selected_stock_india:
            selected_stock = selected_stock_india
        elif selected_stock_us:
            selected_stock = selected_stock_us
        elif custom_stock:
            selected_stock = custom_stock.upper()
    
    with col_divider:
        st.markdown("<div style='text-align:center;padding-top:2.5rem;font-size:1.2rem;color:#a0aec0;font-weight:600;'>OR</div>", unsafe_allow_html=True)
    
    # Fetch price first if stock is selected
    price = 214.0  # Default price
    if selected_stock and selected_stock != "":
        with st.spinner(f"Fetching live data for {selected_stock}..."):
            try:
                ticker = yf.Ticker(selected_stock)
                hist = ticker.history(period="1d")
                if not hist.empty:
                    price = float(hist['Close'].iloc[-1])
                    st.success(f"✅ Live Price Loaded: **{selected_stock}** = **₹{price:.2f}**")
                else:
                    st.warning(f"⚠️ Could not fetch data for **{selected_stock}**. Please check the ticker symbol.")
                    st.info("💡 **Tip:** Indian stocks need .NS (NSE) or .BO (BSE) suffix. Example: RELIANCE.NS")
            except Exception as e:
                st.error(f"❌ Invalid stock symbol: **{selected_stock}**")
                st.info("💡 **Common formats:** AAPL (US), RELIANCE.NS (Indian NSE), SBIN.BO (Indian BSE)")
    
    # Now create the number input with the fetched price
    with col_price:
        price = st.number_input("Enter Price Manually", value=price, step=0.05, key="manual_price")

    st.markdown("<br>", unsafe_allow_html=True)

    # Store in session state for simulation tab
    if 'current_price' not in st.session_state:
        st.session_state.current_price = price
    if 'current_stock' not in st.session_state:
        st.session_state.current_stock = selected_stock if selected_stock else None
    
    st.session_state.current_price = price
    st.session_state.current_stock = selected_stock if selected_stock else None

    res = calculate_levels(price)
    
    # Store in session state for simulation tab
    st.session_state.levels = res

    # ==================== Charts ====================
    st.markdown("---")
    left_block, right_block = st.columns([1.5, 1], gap="large")

    with left_block:
        st.markdown('<div class="header-btn">📊 Intraday Targets</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            st.markdown("<div style='text-align:center;font-size:0.9rem;font-weight:600;color:#0c6f3c;margin-bottom:0.5rem;'>🟢 LONG POSITION</div>", unsafe_allow_html=True)
            bull_labels = [f"T{i}\n{val:.2f}" for i, val in enumerate(res['bull_targets'], 1)]
            bull_center = f"Buy@\n{res['buy']:.2f}"
            donut_chart(res['bull_targets'], bull_labels, bull_center, cmap_name='Greens')
        with c2:
            st.markdown("<div style='text-align:center;font-size:0.9rem;font-weight:600;color:#c53030;margin-bottom:0.5rem;'>🔴 SHORT POSITION</div>", unsafe_allow_html=True)
            bear_labels = [f"T{i}\n{val:.2f}" for i, val in enumerate(res['bear_targets'], 1)]
            bear_center = f"Sell@\n{res['sell']:.2f}"
            donut_chart(res['bear_targets'], bear_labels, bear_center, cmap_name='Reds')

    with right_block:
        st.markdown('<div class="header-btn">For Position/Swing</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class='panel'>
                <div class='panel-item'>
                    <span class='res-key'>Resistance 3</span>
                    <span class='res-val'>{res['resistances'][2]:.2f}</span>
                </div>
                <div class='panel-item'>
                    <span class='res-key'>Resistance 2</span>
                    <span class='res-val'>{res['resistances'][1]:.2f}</span>
                </div>
                <div class='panel-item'>
                    <span class='res-key'>Resistance 1</span>
                    <span class='res-val'>{res['resistances'][0]:.2f}</span>
                </div>
            </div>
            <div class='panel support'>
                <div class='panel-item'>
                    <span class='res-key'>Support 1</span>
                    <span class='sup-val'>{res['supports'][0]:.2f}</span>
                </div>
                <div class='panel-item'>
                    <span class='res-key'>Support 2</span>
                    <span class='sup-val'>{res['supports'][1]:.2f}</span>
                </div>
                <div class='panel-item'>
                    <span class='res-key'>Support 3</span>
                    <span class='sup-val'>{res['supports'][2]:.2f}</span>
                </div>
            </div>
            <div class='box'>
                <div style='font-size:0.9rem;color:#4a5568;margin-bottom:0.5rem;font-weight:600;'>Breakout / Breakdown Level</div>
                <div style='font-size:2rem;font-weight:900;color:#2d5a87;'>{res['breakout']:.0f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ==================== Beginner Guide with Risk/Reward ====================
    st.markdown('<div class="how-section-title">📚 How to Use These Levels</div>', unsafe_allow_html=True)

    rr_intraday_long = rr_long(res['buy'], res['sell'], res['bull_targets'][:3])
    rr_intraday_short = rr_short(res['sell'], res['buy'], res['bear_targets'][:3])
    rr_swing_long = rr_long(res['breakout'], res['supports'][0], res['resistances'][:3])
    rr_swing_short = rr_short(res['breakout'], res['resistances'][0], res['supports'][:3])

    # Intraday strategies
    col_intra1, col_intra2 = st.columns(2, gap="medium")

    with col_intra1:
        st.markdown(
            f"""
            <div class='how-box how-long'>
                <div class='how-title'>📈 Intraday - Long</div>
                <div class='how-text'>🎯 <strong>Entry:</strong> Buy at <b>{res['buy']:.2f}</b> (set GTT/trigger)</div>
                <div class='how-text'>🛑 <strong>Stop Loss:</strong> <b>{res['sell']:.2f}</b></div>
                <div class='how-text'>🎯 <strong>Targets:</strong> T1: <b>{res['bull_targets'][0]:.2f}</b> | T2: <b>{res['bull_targets'][1]:.2f}</b> | T3: <b>{res['bull_targets'][2]:.2f}</b></div>
                <div class='how-text'>💰 <strong>Risk/Reward:</strong> <b>1:{rr_intraday_long[0]:.2f}</b> | <b>1:{rr_intraday_long[1]:.2f}</b> | <b>1:{rr_intraday_long[2]:.2f}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_intra2:
        st.markdown(
            f"""
            <div class='how-box how-short'>
                <div class='how-title'>📉 Intraday - Short</div>
                <div class='how-text'>🎯 <strong>Entry:</strong> Sell at <b>{res['sell']:.2f}</b> (set GTT/trigger)</div>
                <div class='how-text'>🛑 <strong>Stop Loss:</strong> <b>{res['buy']:.2f}</b></div>
                <div class='how-text'>🎯 <strong>Targets:</strong> T1: <b>{res['bear_targets'][0]:.2f}</b> | T2: <b>{res['bear_targets'][1]:.2f}</b> | T3: <b>{res['bear_targets'][2]:.2f}</b></div>
                <div class='how-text'>💰 <strong>Risk/Reward:</strong> <b>1:{rr_intraday_short[0]:.2f}</b> | <b>1:{rr_intraday_short[1]:.2f}</b> | <b>1:{rr_intraday_short[2]:.2f}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Position/Swing strategies
    st.markdown("<br>", unsafe_allow_html=True)
    col_swing1, col_swing2 = st.columns(2, gap="medium")

    with col_swing1:
        st.markdown(
            f"""
            <div class='how-box how-long'>
                <div class='how-title'>🚀 Position/Swing - Long</div>
                <div class='how-text'>🎯 <strong>Entry:</strong> Buy at <b>{res['breakout']:.0f}</b> (breakout trigger)</div>
                <div class='how-text'>🛑 <strong>Stop Loss:</strong> <b>{res['supports'][0]:.2f}</b> (S1)</div>
                <div class='how-text'>🎯 <strong>Targets:</strong> R1: <b>{res['resistances'][0]:.2f}</b> | R2: <b>{res['resistances'][1]:.2f}</b> | R3: <b>{res['resistances'][2]:.2f}</b></div>
                <div class='how-text'>💰 <strong>Risk/Reward:</strong> <b>1:{rr_swing_long[0]:.2f}</b> | <b>1:{rr_swing_long[1]:.2f}</b> | <b>1:{rr_swing_long[2]:.2f}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_swing2:
        st.markdown(
            f"""
            <div class='how-box how-short'>
                <div class='how-title'>⚡ Position/Swing - Short</div>
                <div class='how-text'>🎯 <strong>Entry:</strong> Sell at <b>{res['breakout']:.0f}</b> (breakdown trigger)</div>
                <div class='how-text'>🛑 <strong>Stop Loss:</strong> <b>{res['resistances'][0]:.2f}</b> (R1)</div>
                <div class='how-text'>🎯 <strong>Targets:</strong> S1: <b>{res['supports'][0]:.2f}</b> | S2: <b>{res['supports'][1]:.2f}</b> | S3: <b>{res['supports'][2]:.2f}</b></div>
                <div class='how-text'>💰 <strong>Risk/Reward:</strong> <b>1:{rr_swing_short[0]:.2f}</b> | <b>1:{rr_swing_short[1]:.2f}</b> | <b>1:{rr_swing_short[2]:.2f}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div class='note-box'>
            <strong>⚠️ Important Note:</strong> Values refresh automatically when you change the input price. Always use small quantities and manage risk carefully. These levels are for educational purposes only.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style='text-align:center;padding:2rem 0 1rem 0;border-top:1px solid #e2e8f0;margin-top:2rem;'>
            <div style='color:#718096;font-size:0.85rem;'>
                💡 <strong>Pro Tip:</strong> For Futures, International Shares, Commodities, Forex, and Cryptocurrencies, enter the last traded price
            </div>
            <div style='color:#a0aec0;font-size:0.75rem;margin-top:0.75rem;'>
                Built with ❤️ using Streamlit • Square-of-9 Calculator
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ====================================
# TAB 2: SIMULATION
# ====================================
with tab2:
    st.markdown("### 🎮 Backtest Your Strategy")
    st.markdown("Test how Square-of-9 levels would have performed on historical data")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==================== Stock Selection for Simulation ====================
    st.markdown("#### 📊 Select Stock for Simulation")
    
    col_stock, col_price_display = st.columns([2, 1])
    
    with col_stock:
        # Pre-select stock from calculator if available
        default_stock = st.session_state.get('current_stock', '')
        
        # Initialize tracking for which input changed in simulation
        if 'prev_sim_india' not in st.session_state:
            st.session_state.prev_sim_india = ""
        if 'prev_sim_us' not in st.session_state:
            st.session_state.prev_sim_us = ""
        if 'prev_sim_custom' not in st.session_state:
            st.session_state.prev_sim_custom = ""
        
        sim_tab1, sim_tab2, sim_tab3 = st.tabs(["🇮🇳 Indian", "🇺🇸 US", "✏️ Custom"])
        
        with sim_tab1:
            default_idx = 0
            if default_stock and default_stock in POPULAR_STOCKS_INDIA:
                default_idx = POPULAR_STOCKS_INDIA.index(default_stock) + 1
            
            sim_stock_india = st.selectbox(
                "Indian Stocks",
                [""] + POPULAR_STOCKS_INDIA,
                index=default_idx,
                key="sim_stock_india",
                label_visibility="collapsed"
            )
        
        with sim_tab2:
            default_idx = 0
            if default_stock and default_stock in POPULAR_STOCKS_US:
                default_idx = POPULAR_STOCKS_US.index(default_stock) + 1
            
            sim_stock_us = st.selectbox(
                "US Stocks",
                [""] + POPULAR_STOCKS_US,
                index=default_idx,
                key="sim_stock_us",
                label_visibility="collapsed"
            )
        
        with sim_tab3:
            custom_sim_stock = st.text_input(
                "Enter Any Stock Symbol",
                value=default_stock if default_stock and default_stock not in POPULAR_STOCKS_INDIA + POPULAR_STOCKS_US else "",
                placeholder="e.g., TSLA, ADANIENT.NS, etc.",
                key="sim_stock_custom",
                help="Enter any valid stock ticker from any exchange"
            )
    
    # Determine which input changed and set sim_stock accordingly
    sim_stock = ""
    
    # Check which value changed from its previous state
    sim_india_changed = sim_stock_india != st.session_state.prev_sim_india
    sim_us_changed = sim_stock_us != st.session_state.prev_sim_us
    sim_custom_changed = custom_sim_stock != st.session_state.prev_sim_custom
    
    # Priority: use the one that changed
    if sim_india_changed and sim_stock_india:
        sim_stock = sim_stock_india
        st.session_state.prev_sim_india = sim_stock_india
    elif sim_us_changed and sim_stock_us:
        sim_stock = sim_stock_us
        st.session_state.prev_sim_us = sim_stock_us
    elif sim_custom_changed and custom_sim_stock:
        sim_stock = custom_sim_stock.upper()
        st.session_state.prev_sim_custom = custom_sim_stock
    else:
        # No change detected, use the last non-empty value
        if sim_stock_india:
            sim_stock = sim_stock_india
        elif sim_stock_us:
            sim_stock = sim_stock_us
        elif custom_sim_stock:
            sim_stock = custom_sim_stock.upper()
    
    with col_price_display:
        if sim_stock:
            # Fetch current price for reference
            try:
                ticker = yf.Ticker(sim_stock)
                current_data = ticker.history(period="1d")
                if not current_data.empty:
                    current_price = float(current_data['Close'].iloc[-1])
                    st.metric("Current Price", f"₹{current_price:.2f}")
                else:
                    st.info("Price unavailable")
            except:
                st.info("Price unavailable")
    
    if not sim_stock:
        st.info("👆 Please select a stock to run the simulation")
        st.markdown(
            """
            <div class='note-box'>
                <strong>💡 Stock Symbol Format:</strong><br>
                • <strong>Indian (NSE):</strong> Add .NS suffix (e.g., RELIANCE.NS, TCS.NS)<br>
                • <strong>Indian (BSE):</strong> Add .BO suffix (e.g., RELIANCE.BO)<br>
                • <strong>US Stocks:</strong> Use plain ticker (e.g., AAPL, MSFT, TSLA)<br>
                • <strong>Other Markets:</strong> Check Yahoo Finance for correct suffix
            </div>
            """,
            unsafe_allow_html=True
        )
        st.stop()
    
    # Show current price for reference only
    try:
        ticker = yf.Ticker(sim_stock)
        current_hist = ticker.history(period="1d")
        if not current_hist.empty:
            current_ref_price = float(current_hist['Close'].iloc[-1])
        else:
            current_ref_price = None
    except:
        current_ref_price = None
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==================== Simulation Inputs ====================
    st.markdown("#### ⚙️ Simulation Parameters")
    col_type, col_date, col_amount = st.columns([1, 2, 1])
    
    with col_type:
        trade_type = st.radio(
            "Trade Type",
            ["Intraday", "Position/Swing"],
            key="sim_trade_type"
        )
    
    with col_date:
        if trade_type == "Intraday":
            st.write("**Intraday Period & Interval**")
            col_start, col_end = st.columns(2)
            with col_start:
                start_date = st.date_input(
                    "Start Date",
                    value=datetime.now() - timedelta(days=7),
                    max_value=datetime.now() - timedelta(days=1),
                    key="sim_intraday_start_date"
                )
            with col_end:
                end_date = st.date_input(
                    "End Date",
                    value=datetime.now() - timedelta(days=1),
                    max_value=datetime.now() - timedelta(days=1),
                    key="sim_intraday_end_date"
                )
            intraday_interval = st.selectbox(
                "Time Interval",
                ["5m", "15m", "30m", "60m"],
                index=1,
                key="intraday_interval",
                help="Smaller intervals = more trades but limited to last 60 days (yfinance restriction). 5m=5min, 15m=15min, 30m=30min, 60m=1hr"
            )
        else:
            st.write("**Select Date Range**")
            col_start, col_end = st.columns(2)
            with col_start:
                start_date = st.date_input(
                    "Start Date",
                    value=datetime.now() - timedelta(days=30),
                    max_value=datetime.now() - timedelta(days=1),
                    key="sim_start_date"
                )
            with col_end:
                end_date = st.date_input(
                    "End Date",
                    value=datetime.now() - timedelta(days=1),
                    max_value=datetime.now() - timedelta(days=1),
                    key="sim_end_date"
                )
            intraday_interval = None
    
    with col_amount:
        investment = st.number_input(
            "Total Capital (₹)",
            min_value=1000,
            value=10000,
            step=1000,
            key="sim_capital",
            help="Total amount available for trading"
        )
    
    # Risk Management and Costs Parameters
    st.markdown("#### ⚠️ Risk Management & Trading Costs")
    col_risk1, col_risk2, col_risk3, col_risk4 = st.columns(4)
    
    with col_risk1:
        max_loss_pct = st.number_input(
            "Max Loss per Trade (%)",
            min_value=0.5,
            max_value=10.0,
            value=2.0,
            step=0.5,
            key="max_loss_pct",
            help="Maximum % of capital you're willing to lose per trade"
        )
    
    with col_risk2:
        max_total_loss_pct = st.number_input(
            "Max Total Loss (%)",
            min_value=5.0,
            max_value=50.0,
            value=20.0,
            step=5.0,
            key="max_total_loss_pct",
            help="Stop trading if total losses reach this % of initial capital"
        )
    
    with col_risk3:
        if trade_type == "Intraday":
            # For intraday, always allow multiple trades
            allow_multiple_trades = True
            st.markdown("""
                <div style='padding: 0.5rem; background: #e6f7ff; border-radius: 4px; border-left: 3px solid #1890ff;'>
                    <strong style='color: #096dd9;'>Multiple Trades: ON</strong><br>
                    <span style='font-size: 0.85rem; color: #0050b3;'>Intraday mode allows multiple trades per day</span>
                </div>
            """, unsafe_allow_html=True)
        else:
            allow_multiple_trades = st.checkbox(
                "Multiple Trades",
                value=True,
                key="multiple_trades",
                help="Look for new entries after each trade closes"
            )
    
    with col_risk4:
        brokerage_per_trade = st.number_input(
            "Brokerage per Trade (₹)",
            min_value=0.0,
            max_value=100.0,
            value=20.0,
            step=5.0,
            key="brokerage",
            help="Flat brokerage charge per trade (buy + sell = 2 charges)"
        )
    
    # Additional charges
    with st.expander("⚙️ Advanced Cost Settings", expanded=False):
        col_c1, col_c2, col_c3 = st.columns(3)
        
        with col_c1:
            stt_rate = st.number_input(
                "STT Rate (%)",
                min_value=0.0,
                max_value=1.0,
                value=0.025,
                step=0.001,
                format="%.3f",
                key="stt_rate",
                help="Securities Transaction Tax on sell side"
            )
        
        with col_c2:
            transaction_charges = st.number_input(
                "Transaction Charges (%)",
                min_value=0.0,
                max_value=0.1,
                value=0.00325,
                step=0.00001,
                format="%.5f",
                key="txn_charges",
                help="Exchange transaction charges"
            )
        
        with col_c3:
            gst_rate = st.number_input(
                "GST Rate (%)",
                min_value=0.0,
                max_value=20.0,
                value=18.0,
                step=1.0,
                key="gst_rate",
                help="GST on brokerage and transaction charges"
            )
    
    # Position type and additional options
    col_pos, col_entry, col_recalc = st.columns(3)
    with col_pos:
        position = st.radio(
            "Position",
            ["Long", "Short"],
            horizontal=True,
            key="sim_position"
        )
    
    with col_entry:
        entry_mode = st.radio(
            "Entry Mode",
            ["Wait for Level", "Immediate Entry"],
            horizontal=False,
            key="entry_mode",
            help="Wait for Level: Enter only when price reaches calculated buy/sell level. Immediate Entry: Enter at market open/close if not in trade"
        )
    
    with col_recalc:
        if trade_type == "Position/Swing":
            recalc_levels = st.checkbox(
                "Recalculate Levels Daily",
                value=False,
                key="recalc_levels",
                help="If checked, Square-of-9 levels will be recalculated each day based on previous close price"
            )
        else:
            recalc_levels = False
    
    st.info(f"""
        💡 **Entry Mode Guide**:
        - **Wait for Level**: More conservative. Waits for price to touch the calculated buy/sell level. May result in fewer trades if levels are not reached.
        - **Immediate Entry**: More aggressive. Enters at market price if conditions are favorable. Allows more trading opportunities.
        
        {"**Intraday Mode**: Multiple trades per day based on time intervals! Levels recalculate at start of each trading day." if trade_type == "Intraday" else "**Position/Swing Mode**: Holds positions across multiple days with partial exits at targets."}
        
        {"If you're seeing fewer trades than expected, try **Immediate Entry** mode or a smaller time interval." if trade_type == "Intraday" else "If you're seeing only 1 trade over a long period, try switching to **Immediate Entry** mode."}
    """)
    
    run_simulation = st.button("🚀 Run Simulation", type="primary", use_container_width=True)
    
    st.markdown("---")
    
    # ==================== Run Simulation ====================
    if run_simulation:
        stock_symbol = sim_stock
        
        # Show simulation animation
        sim_placeholder = st.empty()
        with sim_placeholder.container():
            st.markdown(
                """
                <div class='sim-result-box simulating' style='text-align:center;'>
                    <h3>⚙️ Running Simulation...</h3>
                    <p>Fetching historical data and analyzing patterns...</p>
                </div>
                """,
                unsafe_allow_html=True
            )
        time.sleep(1.5)
        
        # Fetch historical data
        try:
            ticker = yf.Ticker(stock_symbol)
            # Convert dates to datetime and add one day to end_date to include it
            start_dt = pd.Timestamp(start_date)
            end_dt = pd.Timestamp(end_date) + pd.Timedelta(days=1)
            
            # Fetch data with appropriate interval
            if trade_type == "Intraday":
                # For intraday, fetch with specified interval
                hist_data = ticker.history(start=start_dt, end=end_dt, interval=intraday_interval)
                st.info(f"📊 Fetching intraday data with {intraday_interval} interval. This allows multiple trades per day based on time!")
            else:
                # For Position/Swing, use daily data
                hist_data = ticker.history(start=start_dt, end=end_dt)
            
            if hist_data.empty:
                st.error("❌ No historical data available for selected dates!")
                st.stop()
            
            sim_placeholder.empty()
            
            # ==================== Calculate Initial Levels ====================
            # Use the OPENING price of the first day to calculate initial levels
            start_price = float(hist_data.iloc[0]['Open'])
            initial_levels = calculate_levels(start_price)
            
            if trade_type == "Intraday" or not recalc_levels:
                st.info(f"📊 Square-of-9 levels calculated from opening price on {hist_data.index[0].strftime('%Y-%m-%d')}: ₹{start_price:.2f}")
            else:
                st.info(f"📊 Square-of-9 levels will be recalculated daily based on previous close price. Initial calculation from: ₹{start_price:.2f}")
            
            # Display the initial calculated levels
            with st.expander("📊 View Initial Calculated Levels", expanded=True):
                col_lvl1, col_lvl2 = st.columns(2)
                
                with col_lvl1:
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(135deg, #e7f8ee 0%, #d4f1e1 100%); padding: 1rem; border-radius: 8px;'>
                            <strong style='color: #0a2b12;'>Entry Levels (Initial)</strong><br>
                            <span style='font-size: 0.9rem; color: #0a2b12;'>
                                Buy Entry: <strong>₹{initial_levels['buy']:.2f}</strong><br>
                                Sell Entry: <strong>₹{initial_levels['sell']:.2f}</strong><br>
                                <em style='font-size: 0.85rem; color: #0a5e2b;'>{"Will be recalculated daily" if trade_type == "Position/Swing" and recalc_levels else "Fixed for simulation"}</em>
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                
                with col_lvl2:
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(135deg, #eef6ff 0%, #d9e8ff 100%); padding: 1rem; border-radius: 8px;'>
                            <strong style='color: #0f2240;'>Targets & Stop Loss (Initial)</strong><br>
                            <span style='font-size: 0.9rem; color: #0f2240;'>
                                <strong>Intraday:</strong> T1-T3: {initial_levels['bull_targets'][0]:.2f}, {initial_levels['bull_targets'][1]:.2f}, {initial_levels['bull_targets'][2]:.2f}<br>
                                <strong>Position/Swing:</strong><br>
                                &nbsp;&nbsp;• Supports: {initial_levels['supports'][0]:.2f}, {initial_levels['supports'][1]:.2f}, {initial_levels['supports'][2]:.2f}<br>
                                &nbsp;&nbsp;• Resistances: {initial_levels['resistances'][0]:.2f}, {initial_levels['resistances'][1]:.2f}, {initial_levels['resistances'][2]:.2f}<br>
                                <strong>Breakout:</strong> ₹{initial_levels['breakout']:.0f} <em style='font-size: 0.85rem;'>(Info only)</em>
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            
            # Explanation for strategy
            if trade_type == "Position/Swing":
                st.info(f"""
                    📌 **Position/Swing Strategy**: 
                    - **Entry**: {"Buy" if position == "Long" else "Sell"} level (Initial: ₹{initial_levels['buy' if position == 'Long' else 'sell']:.2f})
                    - **Stop Loss**: {"Support 1" if position == "Long" else "Resistance 1"} (Initial: ₹{initial_levels['supports'][0] if position == 'Long' else initial_levels['resistances'][0]:.2f})
                    - **Targets**: {"Resistances" if position == "Long" else "Supports"} (Initial: {', '.join([f'₹{t:.2f}' for t in (initial_levels['resistances'][:3] if position == 'Long' else initial_levels['supports'][:3])])})
                    - **Breakout Level** (₹{initial_levels['breakout']:.0f}) is informational - indicates potential circuit movement
                    {"- **Dynamic Mode**: Levels will be recalculated daily until entry" if recalc_levels else "- **Static Mode**: Levels fixed from start"}
                """)
            else:  # Intraday
                st.info(f"""
                    ⚡ **Intraday Strategy** ({intraday_interval} intervals): 
                    - **Multiple trades per day** based on {intraday_interval} candles (High Risk, High Reward)
                    - **Entry**: {"Buy" if position == "Long" else "Sell"} level (Initial: ₹{initial_levels['buy' if position == 'Long' else 'sell']:.2f})
                    - **Stop Loss**: {"Sell" if position == "Long" else "Buy"} level (Initial: ₹{initial_levels['sell' if position == 'Long' else 'buy']:.2f})
                    - **Targets**: {"Bull Targets" if position == "Long" else "Bear Targets"} (Initial: {', '.join([f'₹{t:.2f}' for t in (initial_levels['bull_targets'][:3] if position == 'Long' else initial_levels['bear_targets'][:3])])})
                    - **Auto Exit**: All open positions close at end of trading day
                    - **Levels Recalc**: Square-of-9 levels recalculated at start of each new trading day
                """)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # ==================== Risk-Based Multi-Trade Simulation ====================
            
            # Initialize capital tracking
            initial_capital = investment
            current_capital = investment
            max_total_loss_amount = investment * (max_total_loss_pct / 100)
            min_capital = investment - max_total_loss_amount
            
            # Track all trades and costs
            all_trades = []
            trade_count = 0
            cumulative_pnl = 0
            total_brokerage_paid = 0
            total_costs_paid = 0
            
            # Track level changes for visualization
            level_history = []
            
            # Previous close for recalculation
            prev_close = start_price
            
            # Current trade state
            in_trade = False
            current_trade = {}
            
            # Helper function to close trade with costs
            def close_trade_with_costs(entry_p, exit_p, qty, gross_pnl):
                costs = calculate_trading_costs(entry_p, exit_p, qty, 
                                               brokerage_per_trade, stt_rate, transaction_charges, gst_rate)
                net_pnl = gross_pnl - costs['total']
                return net_pnl, costs['total'], costs['brokerage']
            
            for day_idx, (idx, row) in enumerate(hist_data.iterrows()):
                open_price = row['Open']
                high = row['High']
                low = row['Low']
                close_price = row['Close']
                
                # Check if we've hit max loss limit
                if current_capital <= min_capital:
                    break
                
                # Recalculate levels if needed
                if day_idx == 0:
                    current_levels = initial_levels
                    calc_price = start_price
                    current_trading_day = idx.date() if hasattr(idx, 'date') else idx
                elif trade_type == "Position/Swing" and recalc_levels and not in_trade:
                    current_levels = calculate_levels(prev_close)
                    calc_price = prev_close
                elif not in_trade:
                    if trade_type == "Intraday":
                        # For intraday with minute data, recalculate levels only at start of new trading day
                        timestamp_date = idx.date() if hasattr(idx, 'date') else idx
                        if timestamp_date != current_trading_day:
                            # New trading day started
                            current_levels = calculate_levels(open_price)
                            calc_price = open_price
                            current_trading_day = timestamp_date
                        # else: use existing levels for the same trading day
                    else:
                        current_levels = calculate_levels(prev_close) if day_idx > 0 else initial_levels
                        calc_price = prev_close if day_idx > 0 else start_price
                
                # Determine entry, SL, targets if not in trade
                if not in_trade:
                    if trade_type == "Intraday":
                        if position == "Long":
                            entry_price = current_levels['buy']
                            stop_loss = current_levels['sell']
                            targets = current_levels['bull_targets'][:3]
                        else:
                            entry_price = current_levels['sell']
                            stop_loss = current_levels['buy']
                            targets = current_levels['bear_targets'][:3]
                    else:  # Position/Swing
                        if position == "Long":
                            entry_price = current_levels['buy']
                            stop_loss = current_levels['supports'][0]
                            targets = current_levels['resistances'][:3]
                        else:
                            entry_price = current_levels['sell']
                            stop_loss = current_levels['resistances'][0]
                            targets = current_levels['supports'][:3]
                    
                    # Calculate position size based on risk
                    risk_per_share = abs(entry_price - stop_loss)
                    if risk_per_share > 0:
                        max_risk_amount = current_capital * (max_loss_pct / 100)
                        position_size = int(max_risk_amount / risk_per_share)
                        position_size = max(1, min(position_size, int(current_capital / entry_price)))
                    else:
                        position_size = int(current_capital / entry_price)
                    
                    level_history.append({
                        'date': idx,
                        'calc_price': calc_price,
                        'entry': entry_price,
                        'sl': stop_loss,
                        'targets': targets.copy()
                    })
                
                # Check if entry was triggered
                if not in_trade:
                    entry_triggered = False
                    actual_entry_price = entry_price
                    
                    if entry_mode == "Wait for Level":
                        # Traditional: Wait for price to reach the calculated level
                        if low <= entry_price <= high:
                            entry_triggered = True
                            actual_entry_price = entry_price
                    else:
                        # Immediate Entry: Enter at market if conditions allow
                        # For Long: enter if current price is below entry level (good entry)
                        # For Short: enter if current price is above entry level (good entry)
                        if position == "Long":
                            if open_price <= entry_price:
                                entry_triggered = True
                                actual_entry_price = open_price
                        else:  # Short
                            if open_price >= entry_price:
                                entry_triggered = True
                                actual_entry_price = open_price
                    
                    if entry_triggered:
                        # Recalculate position size with actual entry price
                        risk_per_share = abs(actual_entry_price - stop_loss)
                        if risk_per_share > 0:
                            max_risk_amount = current_capital * (max_loss_pct / 100)
                            position_size = int(max_risk_amount / risk_per_share)
                            position_size = max(1, min(position_size, int(current_capital / actual_entry_price)))
                        else:
                            position_size = int(current_capital / actual_entry_price)
                        
                        in_trade = True
                        trade_count += 1
                        current_trade = {
                            'trade_num': trade_count,
                            'entry_date': idx,
                            'entry_price': actual_entry_price,
                            'stop_loss': stop_loss,
                            'targets': targets.copy(),
                            'position_size': position_size,
                            'position_type': position,
                            'remaining_size': position_size,  # Track remaining position
                            'partial_exits': []  # Track partial exits
                        }
                        
                        # For Position/Swing, don't check same candle exit - hold position
                        # For Intraday, check same candle
                        if trade_type == "Intraday":
                            if position == "Long":
                                if low <= stop_loss:
                                    exit_price = stop_loss
                                    result = "Stop Loss Hit"
                                    pnl_per_share = exit_price - entry_price
                                    gross_pnl = pnl_per_share * position_size
                                    
                                    # Calculate trading costs
                                    costs = calculate_trading_costs(entry_price, exit_price, position_size, 
                                                                   brokerage_per_trade, stt_rate, transaction_charges, gst_rate)
                                    net_pnl = gross_pnl - costs['total']
                                    
                                    current_capital += net_pnl
                                    cumulative_pnl += net_pnl
                                    total_costs_paid += costs['total']
                                    total_brokerage_paid += costs['brokerage']
                                    
                                    current_trade.update({
                                        'exit_date': idx,
                                        'exit_price': exit_price,
                                        'result': result,
                                        'gross_pnl': gross_pnl,
                                        'costs': costs['total'],
                                        'pnl': net_pnl,
                                        'capital_after': current_capital
                                    })
                                    all_trades.append(current_trade.copy())
                                    in_trade = False
                                else:
                                    # Check for highest target hit on intraday
                                    for i in range(len(targets)-1, -1, -1):
                                        if high >= targets[i]:
                                            exit_price = targets[i]
                                            result = f"Target {i+1} Hit"
                                            pnl_per_share = exit_price - entry_price
                                            gross_pnl = pnl_per_share * position_size
                                            net_pnl, total_cost, brokerage = close_trade_with_costs(entry_price, exit_price, position_size, gross_pnl)
                                            
                                            current_capital += net_pnl
                                            cumulative_pnl += net_pnl
                                            total_costs_paid += total_cost
                                            total_brokerage_paid += brokerage
                                            
                                            current_trade.update({
                                                'exit_date': idx,
                                                'exit_price': exit_price,
                                                'result': result,
                                                'gross_pnl': gross_pnl,
                                                'costs': total_cost,
                                                'pnl': net_pnl,
                                                'capital_after': current_capital
                                            })
                                            all_trades.append(current_trade.copy())
                                            in_trade = False
                                            break
                            else:  # Short intraday
                                if high >= stop_loss:
                                    exit_price = stop_loss
                                    result = "Stop Loss Hit"
                                    pnl_per_share = entry_price - exit_price
                                    gross_pnl = pnl_per_share * position_size
                                    net_pnl, total_cost, brokerage = close_trade_with_costs(entry_price, exit_price, position_size, gross_pnl)
                                    
                                    current_capital += net_pnl
                                    cumulative_pnl += net_pnl
                                    total_costs_paid += total_cost
                                    total_brokerage_paid += brokerage
                                    
                                    current_trade.update({
                                        'exit_date': idx,
                                        'exit_price': exit_price,
                                        'result': result,
                                        'gross_pnl': gross_pnl,
                                        'costs': total_cost,
                                        'pnl': net_pnl,
                                        'capital_after': current_capital
                                    })
                                    all_trades.append(current_trade.copy())
                                    in_trade = False
                                else:
                                    # Check for lowest target hit on intraday
                                    for i in range(len(targets)-1, -1, -1):
                                        if low <= targets[i]:
                                            exit_price = targets[i]
                                            result = f"Target {i+1} Hit"
                                            pnl_per_share = entry_price - exit_price
                                            gross_pnl = pnl_per_share * position_size
                                            net_pnl, total_cost, brokerage = close_trade_with_costs(entry_price, exit_price, position_size, gross_pnl)
                                            
                                            current_capital += net_pnl
                                            cumulative_pnl += net_pnl
                                            total_costs_paid += total_cost
                                            total_brokerage_paid += brokerage
                                            
                                            current_trade.update({
                                                'exit_date': idx,
                                                'exit_price': exit_price,
                                                'result': result,
                                                'gross_pnl': gross_pnl,
                                                'costs': total_cost,
                                                'pnl': net_pnl,
                                                'capital_after': current_capital
                                            })
                                            all_trades.append(current_trade.copy())
                                            in_trade = False
                                            break
                else:
                    # In trade - check for exit (Position/Swing holds across days)
                    if position == "Long":
                        # Check stop loss first
                        if low <= current_trade['stop_loss']:
                            exit_price = current_trade['stop_loss']
                            result = "Stop Loss Hit"
                            remaining = current_trade['remaining_size']
                            pnl_per_share = exit_price - current_trade['entry_price']
                            gross_pnl = pnl_per_share * remaining
                            net_pnl, total_cost, brokerage = close_trade_with_costs(current_trade['entry_price'], exit_price, remaining, gross_pnl)
                            
                            current_capital += net_pnl
                            cumulative_pnl += net_pnl
                            total_costs_paid += total_cost
                            total_brokerage_paid += brokerage
                            
                            current_trade.update({
                                'exit_date': idx,
                                'exit_price': exit_price,
                                'result': result,
                                'gross_pnl': gross_pnl,
                                'costs': total_cost,
                                'pnl': net_pnl,
                                'capital_after': current_capital
                            })
                            all_trades.append(current_trade.copy())
                            in_trade = False
                        else:
                            # Check targets - take partial profits
                            for i, target in enumerate(current_trade['targets']):
                                if high >= target and current_trade['remaining_size'] > 0:
                                    # Partial exit: sell 1/3 of remaining position at each target
                                    exit_size = max(1, current_trade['remaining_size'] // 3) if i < len(current_trade['targets'])-1 else current_trade['remaining_size']
                                    pnl_per_share = target - current_trade['entry_price']
                                    gross_partial_pnl = pnl_per_share * exit_size
                                    net_partial_pnl, partial_cost, partial_broker = close_trade_with_costs(current_trade['entry_price'], target, exit_size, gross_partial_pnl)
                                    
                                    current_capital += net_partial_pnl
                                    cumulative_pnl += net_partial_pnl
                                    total_costs_paid += partial_cost
                                    total_brokerage_paid += partial_broker
                                    
                                    current_trade['remaining_size'] -= exit_size
                                    current_trade['partial_exits'].append({
                                        'date': idx,
                                        'target': i+1,
                                        'price': target,
                                        'size': exit_size,
                                        'gross_pnl': gross_partial_pnl,
                                        'costs': partial_cost,
                                        'pnl': net_partial_pnl
                                    })
                                    
                                    # If all position closed
                                    if current_trade['remaining_size'] <= 0:
                                        total_gross = sum([pe['gross_pnl'] for pe in current_trade['partial_exits']])
                                        total_costs_sum = sum([pe['costs'] for pe in current_trade['partial_exits']])
                                        current_trade.update({
                                            'exit_date': idx,
                                            'exit_price': target,
                                            'result': f"All Targets Hit (Final: T{i+1})",
                                            'gross_pnl': total_gross,
                                            'costs': total_costs_sum,
                                            'pnl': sum([pe['pnl'] for pe in current_trade['partial_exits']]),
                                            'capital_after': current_capital
                                        })
                                        all_trades.append(current_trade.copy())
                                        in_trade = False
                                        break
                    else:  # Short position
                        # Check stop loss first
                        if high >= current_trade['stop_loss']:
                            exit_price = current_trade['stop_loss']
                            result = "Stop Loss Hit"
                            remaining = current_trade['remaining_size']
                            pnl_per_share = current_trade['entry_price'] - exit_price
                            gross_pnl = pnl_per_share * remaining
                            net_pnl, total_cost, brokerage = close_trade_with_costs(current_trade['entry_price'], exit_price, remaining, gross_pnl)
                            
                            current_capital += net_pnl
                            cumulative_pnl += net_pnl
                            total_costs_paid += total_cost
                            total_brokerage_paid += brokerage
                            
                            current_trade.update({
                                'exit_date': idx,
                                'exit_price': exit_price,
                                'result': result,
                                'gross_pnl': gross_pnl,
                                'costs': total_cost,
                                'pnl': net_pnl,
                                'capital_after': current_capital
                            })
                            all_trades.append(current_trade.copy())
                            in_trade = False
                        else:
                            # Check targets - take partial profits
                            for i, target in enumerate(current_trade['targets']):
                                if low <= target and current_trade['remaining_size'] > 0:
                                    # Partial exit: cover 1/3 of remaining position at each target
                                    exit_size = max(1, current_trade['remaining_size'] // 3) if i < len(current_trade['targets'])-1 else current_trade['remaining_size']
                                    pnl_per_share = current_trade['entry_price'] - target
                                    gross_partial_pnl = pnl_per_share * exit_size
                                    net_partial_pnl, partial_cost, partial_broker = close_trade_with_costs(current_trade['entry_price'], target, exit_size, gross_partial_pnl)
                                    
                                    current_capital += net_partial_pnl
                                    cumulative_pnl += net_partial_pnl
                                    total_costs_paid += partial_cost
                                    total_brokerage_paid += partial_broker
                                    
                                    current_trade['remaining_size'] -= exit_size
                                    current_trade['partial_exits'].append({
                                        'date': idx,
                                        'target': i+1,
                                        'price': target,
                                        'size': exit_size,
                                        'gross_pnl': gross_partial_pnl,
                                        'costs': partial_cost,
                                        'pnl': net_partial_pnl
                                    })
                                    
                                    # If all position closed
                                    if current_trade['remaining_size'] <= 0:
                                        total_gross = sum([pe['gross_pnl'] for pe in current_trade['partial_exits']])
                                        total_costs_sum = sum([pe['costs'] for pe in current_trade['partial_exits']])
                                        current_trade.update({
                                            'exit_date': idx,
                                            'exit_price': target,
                                            'result': f"All Targets Hit (Final: T{i+1})",
                                            'gross_pnl': total_gross,
                                            'costs': total_costs_sum,
                                            'pnl': sum([pe['pnl'] for pe in current_trade['partial_exits']]),
                                            'capital_after': current_capital
                                        })
                                        all_trades.append(current_trade.copy())
                                        in_trade = False
                                        break
                    
                    # For intraday, must exit by end of trading day
                    if trade_type == "Intraday" and in_trade:
                        # Check if this is the last candle of the trading day
                        is_last_candle_of_day = False
                        if day_idx < len(hist_data) - 1:
                            current_date = idx.date() if hasattr(idx, 'date') else idx
                            next_date = hist_data.index[day_idx + 1].date() if hasattr(hist_data.index[day_idx + 1], 'date') else hist_data.index[day_idx + 1]
                            is_last_candle_of_day = (current_date != next_date)
                        else:
                            is_last_candle_of_day = True  # Last candle in entire dataset
                        
                        if is_last_candle_of_day:
                            exit_price = close_price
                            remaining = current_trade['remaining_size']
                            pnl_per_share = (exit_price - current_trade['entry_price']) if position == "Long" else (current_trade['entry_price'] - exit_price)
                            gross_pnl = pnl_per_share * remaining
                            net_pnl, total_cost, brokerage = close_trade_with_costs(current_trade['entry_price'], exit_price, remaining, gross_pnl)
                            
                            # Add to any partial profits already taken (they already have costs deducted)
                            if current_trade['partial_exits']:
                                net_pnl += sum([pe['pnl'] for pe in current_trade['partial_exits']])
                            
                            current_capital += net_pnl
                            cumulative_pnl += net_pnl
                            total_costs_paid += total_cost
                            total_brokerage_paid += brokerage
                            
                            current_trade.update({
                                'exit_date': idx,
                                'exit_price': exit_price,
                                'result': "EOD Exit" if current_trade['partial_exits'] else "Position Open (Exited at Close)",
                                'gross_pnl': gross_pnl + (sum([pe['gross_pnl'] for pe in current_trade['partial_exits']]) if current_trade['partial_exits'] else 0),
                                'costs': total_cost + (sum([pe['costs'] for pe in current_trade['partial_exits']]) if current_trade['partial_exits'] else 0),
                                'pnl': net_pnl,
                                'capital_after': current_capital
                            })
                            all_trades.append(current_trade.copy())
                            in_trade = False
                    
                    # For Position/Swing, continue if multiple trades allowed
                    # Don't break the loop - let it continue to look for new entries
                
                # Update previous close
                prev_close = close_price
            
            # Close any open position at end
            if in_trade:
                exit_price = hist_data.iloc[-1]['Close']
                pnl_per_share = (exit_price - current_trade['entry_price']) if position == "Long" else (current_trade['entry_price'] - exit_price)
                remaining = current_trade['remaining_size']
                gross_pnl = pnl_per_share * remaining
                net_pnl, total_cost, brokerage = close_trade_with_costs(current_trade['entry_price'], exit_price, remaining, gross_pnl)
                
                # Add partial exit profits
                if current_trade.get('partial_exits'):
                    net_pnl += sum([pe['pnl'] for pe in current_trade['partial_exits']])
                    gross_pnl += sum([pe['gross_pnl'] for pe in current_trade['partial_exits']])
                    total_cost += sum([pe['costs'] for pe in current_trade['partial_exits']])
                
                current_capital += net_pnl
                cumulative_pnl += net_pnl
                total_costs_paid += total_cost
                total_brokerage_paid += brokerage
                
                current_trade.update({
                    'exit_date': hist_data.index[-1],
                    'exit_price': exit_price,
                    'result': "Position Open (Exited at Close)",
                    'gross_pnl': gross_pnl,
                    'costs': total_cost,
                    'pnl': net_pnl,
                    'capital_after': current_capital
                })
                all_trades.append(current_trade.copy())
            
            # Store final levels used
            final_levels = current_levels if 'current_levels' in locals() else initial_levels
            
            # Calculate overall statistics
            total_trades = len(all_trades)
            winning_trades = len([t for t in all_trades if t['pnl'] > 0])
            losing_trades = len([t for t in all_trades if t['pnl'] < 0])
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            final_return_pct = ((current_capital - initial_capital) / initial_capital) * 100
            
            # Calculate Buy & Hold comparison
            buy_hold_start_price = float(hist_data.iloc[0]['Open'])
            buy_hold_end_price = float(hist_data.iloc[-1]['Close'])
            buy_hold_shares = int(initial_capital / buy_hold_start_price)
            buy_hold_investment = buy_hold_shares * buy_hold_start_price
            buy_hold_final_value_gross = buy_hold_shares * buy_hold_end_price
            buy_hold_gross_pnl = buy_hold_final_value_gross - buy_hold_investment
            
            # Calculate Buy & Hold costs (only 2 transactions: buy + sell)
            buy_hold_costs = calculate_trading_costs(buy_hold_start_price, buy_hold_end_price, buy_hold_shares,
                                                     brokerage_per_trade, stt_rate, transaction_charges, gst_rate)
            buy_hold_net_pnl = buy_hold_gross_pnl - buy_hold_costs['total']
            buy_hold_final_value = buy_hold_investment + buy_hold_net_pnl
            buy_hold_return_pct = (buy_hold_net_pnl / buy_hold_investment) * 100
            
            # Compare strategies
            strategy_outperformed = final_return_pct > buy_hold_return_pct
            return_difference = final_return_pct - buy_hold_return_pct
            
            # ==================== Display Results ====================
            result_color = "profit" if cumulative_pnl > 0 else "loss"
            result_text_color = "#0c6f3c" if cumulative_pnl > 0 else "#c53030" if total_trades > 0 else "#718096"
            
            st.markdown(
                f"""
                <div class='sim-result-box'>
                    <h3 style='text-align:center;color:#2d3748;margin-bottom:1rem;'>📊 Simulation Results - Risk-Based Strategy</h3>
                    <div style='text-align:center;margin-bottom:0.5rem;'>
                        <span style='font-size:1.4rem;font-weight:800;color:{result_text_color};'>
                            {total_trades} Trade{"s" if total_trades != 1 else ""} Executed
                        </span>
                    </div>
                    <div style='text-align:center;color:#4a5568;font-size:0.95rem;margin-bottom:0.5rem;'>
                        Win Rate: <strong>{win_rate:.1f}%</strong> ({winning_trades}W / {losing_trades}L)
                    </div>
                    <div style='text-align:center;color:#718096;font-size:0.85rem;'>
                        Risk per trade: <strong>{max_loss_pct}%</strong> | Max total loss: <strong>{max_total_loss_pct}%</strong>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            # Overall Performance Metrics
            col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
            
            with col_m1:
                st.markdown(
                    f"""
                    <div class='sim-metric'>
                        <div class='sim-metric-label'>Initial Capital</div>
                        <div class='sim-metric-value'>₹{initial_capital:.0f}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with col_m2:
                st.markdown(
                    f"""
                    <div class='sim-metric'>
                        <div class='sim-metric-label'>Final Capital</div>
                        <div class='sim-metric-value {result_color}'>₹{current_capital:.0f}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with col_m3:
                st.markdown(
                    f"""
                    <div class='sim-metric'>
                        <div class='sim-metric-label'>Total P&L</div>
                        <div class='sim-metric-value {result_color}'>₹{cumulative_pnl:.2f}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with col_m4:
                st.markdown(
                    f"""
                    <div class='sim-metric'>
                        <div class='sim-metric-label'>Strategy Return</div>
                        <div class='sim-metric-value {result_color}'>{final_return_pct:+.2f}%</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with col_m5:
                vs_color = "profit" if strategy_outperformed else "loss"
                st.markdown(
                    f"""
                    <div class='sim-metric'>
                        <div class='sim-metric-label'>vs Buy & Hold</div>
                        <div class='sim-metric-value {vs_color}'>{return_difference:+.2f}%</div>
                        <div style='font-size:0.75rem;margin-top:0.25rem;color:#718096;'>({buy_hold_return_pct:+.1f}% B&H)</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # ==================== Diagnostic Info (if few trades) ====================
            if total_trades < 3 and allow_multiple_trades:
                candles_simulated = len(hist_data)
                time_unit = "candles" if trade_type == "Intraday" else "days"
                avg_duration = candles_simulated / max(1, total_trades)
                
                st.warning(f"""
                    ⚠️ **Low Trade Count Alert**: Only **{total_trades} trade(s)** in **{candles_simulated} {time_unit}** (avg {avg_duration:.0f} {time_unit} per trade).
                    
                    **Possible reasons**:
                    - {"**Entry Mode**: Currently using 'Wait for Level'. The price might not be reaching your calculated buy/sell levels often. Try switching to **'Immediate Entry'** mode." if entry_mode == "Wait for Level" else "**Price Movement**: The stop-loss and targets might be set too far from entry, causing trades to hold for extended periods."}
                    - **Risk Settings**: Risk per trade ({max_loss_pct}%) might be limiting position sizes, causing capital to sit idle.
                    - **Market Conditions**: The stock might be in a tight range, not triggering many entries or exits.
                    {"- **Intraday Interval**: Try a smaller interval (5m or 15m) for more trading opportunities." if trade_type == "Intraday" else ""}
                    
                    **Suggestions**:
                    {f"- Switch to **'Immediate Entry'** mode to increase trading opportunities" if entry_mode == "Wait for Level" else "- Try **'Wait for Level'** mode for more selective entries"}
                    {"- Try a smaller time interval (5m or 15m) for more frequent trading signals" if trade_type == "Intraday" else "- Enable **'Recalculate Levels Daily'** to adapt to changing market conditions"}
                    - Adjust risk per trade percentage
                """)
            
            # ==================== Buy & Hold Comparison ====================
            st.markdown("### 📊 Strategy vs Buy & Hold Comparison")
            
            comp_col1, comp_col2, comp_col3 = st.columns(3)
            
            with comp_col1:
                st.markdown(
                    f"""
                    <div class='sim-metric' style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;'>
                        <div class='sim-metric-label' style='color: rgba(255,255,255,0.9);'>Square-of-9 Strategy</div>
                        <div class='sim-metric-value' style='color: white;'>₹{current_capital:.0f}</div>
                        <div style='font-size: 1rem; margin-top: 0.5rem; color: rgba(255,255,255,0.95);'>{final_return_pct:+.2f}%</div>
                        <div style='font-size: 0.85rem; margin-top: 0.25rem; color: rgba(255,255,255,0.8);'>{total_trades} trades | {win_rate:.0f}% win rate</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with comp_col2:
                st.markdown(
                    f"""
                    <div class='sim-metric' style='background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white;'>
                        <div class='sim-metric-label' style='color: rgba(255,255,255,0.9);'>Buy & Hold</div>
                        <div class='sim-metric-value' style='color: white;'>₹{buy_hold_final_value:.0f}</div>
                        <div style='font-size: 1rem; margin-top: 0.5rem; color: rgba(255,255,255,0.95);'>{buy_hold_return_pct:+.2f}%</div>
                        <div style='font-size: 0.85rem; margin-top: 0.25rem; color: rgba(255,255,255,0.8);'>{buy_hold_shares} shares @ ₹{buy_hold_start_price:.2f}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with comp_col3:
                winner_color = "#0c6f3c" if strategy_outperformed else "#c53030"
                winner_bg = "linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%)" if strategy_outperformed else "linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%)"
                winner_text = "Strategy Wins!" if strategy_outperformed else "Buy & Hold Wins!"
                winner_icon = "🏆" if strategy_outperformed else "📉"
                
                st.markdown(
                    f"""
                    <div class='sim-metric' style='background: {winner_bg};'>
                        <div class='sim-metric-label' style='color: {winner_color};'>{winner_icon} Performance</div>
                        <div class='sim-metric-value' style='color: {winner_color}; font-size: 1.5rem;'>{winner_text}</div>
                        <div style='font-size: 1rem; margin-top: 0.5rem; color: {winner_color}; font-weight: 700;'>{abs(return_difference):+.2f}% {"better" if strategy_outperformed else "worse"}</div>
                        <div style='font-size: 0.85rem; margin-top: 0.25rem; color: {winner_color};'>₹{abs(current_capital - buy_hold_final_value):.0f} difference</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            # Detailed comparison
            st.markdown(
                f"""
                <div class='note-box' style='margin-top: 1rem;'>
                    <strong>💡 Analysis:</strong><br>
                    • <strong>Buy & Hold:</strong> Bought {buy_hold_shares} shares at ₹{buy_hold_start_price:.2f} on {hist_data.index[0].strftime('%Y-%m-%d')}, held until {hist_data.index[-1].strftime('%Y-%m-%d')} @ ₹{buy_hold_end_price:.2f}<br>
                    • <strong>Active Strategy:</strong> Executed {total_trades} trades with {max_loss_pct}% risk management, winning {winning_trades} and losing {losing_trades}<br>
                    • <strong>Result:</strong> {"✅ The Square-of-9 active trading strategy outperformed buy & hold by " + f"{return_difference:.2f}%" if strategy_outperformed else "❌ Buy & hold would have been better by " + f"{abs(return_difference):.2f}%. Consider holding long-term or adjusting strategy parameters."}<br>
                    • <strong>Risk Consideration:</strong> {"Active strategy took more risk with " + str(total_trades) + " trades, but delivered better returns" if strategy_outperformed else "Despite " + str(total_trades) + " active trades, simple holding was more profitable with zero effort"}
                </div>
                """,
                unsafe_allow_html=True
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # ==================== Cost Analysis Card ====================
            st.markdown("### 💸 Trading Costs Breakdown")
            
            cost_col1, cost_col2, cost_col3 = st.columns(3)
            
            with cost_col1:
                st.markdown(
                    f"""
                    <div class='sim-metric' style='background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%); color: white;'>
                        <div class='sim-metric-label' style='color: rgba(255,255,255,0.9);'>Strategy Total Costs</div>
                        <div class='sim-metric-value' style='color: white; font-size: 1.4rem;'>₹{total_costs_paid:.2f}</div>
                        <div style='font-size: 0.8rem; margin-top: 0.3rem; color: rgba(255,255,255,0.85);'>
                            Brokerage: ₹{total_brokerage_paid:.2f}<br>
                            {total_trades} trades × 2 = {total_trades * 2} orders
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with cost_col2:
                st.markdown(
                    f"""
                    <div class='sim-metric' style='background: linear-gradient(135deg, #34d399 0%, #10b981 100%); color: white;'>
                        <div class='sim-metric-label' style='color: rgba(255,255,255,0.9);'>Buy & Hold Costs</div>
                        <div class='sim-metric-value' style='color: white; font-size: 1.4rem;'>₹{buy_hold_costs['total']:.2f}</div>
                        <div style='font-size: 0.8rem; margin-top: 0.3rem; color: rgba(255,255,255,0.85);'>
                            Brokerage: ₹{buy_hold_costs['brokerage']:.2f}<br>
                            2 orders (buy + sell)
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with cost_col3:
                cost_diff = total_costs_paid - buy_hold_costs['total']
                st.markdown(
                    f"""
                    <div class='sim-metric'>
                        <div class='sim-metric-label'>Extra Costs (Strategy)</div>
                        <div class='sim-metric-value loss'>₹{cost_diff:.2f}</div>
                        <div style='font-size: 0.8rem; margin-top: 0.3rem; color: #718096;'>
                            {(cost_diff / buy_hold_costs['total'] * 100):.0f}x more than B&H
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            # Net Profit Comparison
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("### 📊 Net Profit (After Costs)")
            
            net_col1, net_col2, net_col3 = st.columns(3)
            
            with net_col1:
                st.markdown(
                    f"""
                    <div class='sim-metric' style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;'>
                        <div class='sim-metric-label' style='color: rgba(255,255,255,0.9);'>Strategy Net Profit</div>
                        <div class='sim-metric-value' style='color: white; font-size: 1.6rem;'>₹{cumulative_pnl:.2f}</div>
                        <div style='font-size: 0.8rem; margin-top: 0.3rem; color: rgba(255,255,255,0.85);'>
                            Gross: ₹{cumulative_pnl + total_costs_paid:.2f} - Costs: ₹{total_costs_paid:.2f}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with net_col2:
                st.markdown(
                    f"""
                    <div class='sim-metric' style='background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white;'>
                        <div class='sim-metric-label' style='color: rgba(255,255,255,0.9);'>Buy & Hold Net Profit</div>
                        <div class='sim-metric-value' style='color: white; font-size: 1.6rem;'>₹{buy_hold_net_pnl:.2f}</div>
                        <div style='font-size: 0.8rem; margin-top: 0.3rem; color: rgba(255,255,255,0.85);'>
                            Gross: ₹{buy_hold_gross_pnl:.2f} - Costs: ₹{buy_hold_costs['total']:.2f}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            with net_col3:
                net_benefit = (cumulative_pnl - buy_hold_net_pnl)
                st.markdown(
                    f"""
                    <div class='sim-metric'>
                        <div class='sim-metric-label'>Difference (Strategy - B&H)</div>
                        <div class='sim-metric-value {"profit" if net_benefit > 0 else "loss"}'>₹{net_benefit:.2f}</div>
                        <div style='font-size: 0.8rem; margin-top: 0.3rem; color: #718096;'>
                            {"✅ Strategy wins!" if net_benefit > 0 else "❌ B&H better"}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            
            # Detailed cost breakdown
            st.markdown(
                f"""
                <div class='note-box' style='margin-top: 1rem; background: #fef3c7; border-color: #fbbf24;'>
                    <strong>💡 Cost Impact Analysis:</strong><br>
                    • <strong>Cost Breakdown (Strategy):</strong> Brokerage: ₹{total_brokerage_paid:.2f} | STT + Txn + GST: ₹{total_costs_paid - total_brokerage_paid:.2f}<br>
                    • <strong>Winner:</strong> {"✅ Strategy Net Profit (₹" + f"{cumulative_pnl:.2f}" + ") beats Buy & Hold (₹" + f"{buy_hold_net_pnl:.2f}" + ") by ₹" + f"{net_benefit:.2f}" if net_benefit > 0 else "❌ Buy & Hold Net Profit (₹" + f"{buy_hold_net_pnl:.2f}" + ") beats Strategy (₹" + f"{cumulative_pnl:.2f}" + ") by ₹" + f"{abs(net_benefit):.2f}"}<br>
                    • {"✅ Despite higher trading costs (₹" + f"{total_costs_paid:.2f}" + " vs ₹" + f"{buy_hold_costs['total']:.2f}" + "), the strategy's better returns justify active trading" if net_benefit > 0 else "❌ Extra trading costs (₹" + f"{cost_diff:.2f}" + " more) eat into profits - buy & hold is more cost-effective"}
                </div>
                """,
                unsafe_allow_html=True
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # ==================== Trade History Table ====================
            if total_trades > 0:
                st.markdown("### 📋 Trade History")
                
                trade_df = pd.DataFrame(all_trades)
                trade_df['Entry Date'] = trade_df['entry_date'].dt.strftime('%Y-%m-%d')
                trade_df['Exit Date'] = trade_df['exit_date'].dt.strftime('%Y-%m-%d')
                trade_df['Entry Price'] = trade_df['entry_price'].apply(lambda x: f"₹{x:.2f}")
                trade_df['Exit Price'] = trade_df['exit_price'].apply(lambda x: f"₹{x:.2f}")
                trade_df['Position Size'] = trade_df['position_size']
                trade_df['Days Held'] = (trade_df['exit_date'] - trade_df['entry_date']).dt.days
                trade_df['Gross P&L'] = trade_df.get('gross_pnl', trade_df['pnl']).apply(lambda x: f"₹{x:.2f}")
                trade_df['Costs'] = trade_df.get('costs', 0).apply(lambda x: f"₹{x:.2f}")
                trade_df['Net P&L'] = trade_df['pnl'].apply(lambda x: f"₹{x:.2f}")
                trade_df['Result'] = trade_df['result']
                trade_df['Capital After'] = trade_df['capital_after'].apply(lambda x: f"₹{x:.0f}")
                
                # Add partial exits indicator
                trade_df['Exits'] = trade_df['partial_exits'].apply(lambda x: f"{len(x)} partial" if x else "Full")
                
                display_df = trade_df[['trade_num', 'Entry Date', 'Exit Date', 'Days Held', 'Entry Price', 'Exit Price', 'Position Size', 'Exits', 'Gross P&L', 'Costs', 'Net P&L', 'Result', 'Capital After']]
                display_df.columns = ['#', 'Entry', 'Exit', 'Days', 'Entry ₹', 'Exit ₹', 'Shares', 'Exits', 'Gross P&L', 'Costs', 'Net P&L', 'Result', 'Capital']
                
                st.dataframe(display_df, use_container_width=True, hide_index=True)
                
                # Show partial exits details for trades that had them
                trades_with_partials = [t for t in all_trades if t.get('partial_exits')]
                if trades_with_partials and trade_type == "Position/Swing":
                    with st.expander(f"📊 View Partial Exit Details ({len(trades_with_partials)} trades)", expanded=False):
                        for trade in trades_with_partials:
                            st.markdown(f"**Trade #{trade['trade_num']}** - Entry: {trade['entry_date'].strftime('%Y-%m-%d')} @ ₹{trade['entry_price']:.2f}")
                            partial_data = []
                            for pe in trade['partial_exits']:
                                partial_data.append({
                                    'Date': pe['date'].strftime('%Y-%m-%d'),
                                    'Target': f"T{pe['target']}",
                                    'Price': f"₹{pe['price']:.2f}",
                                    'Shares': pe['size'],
                                    'Gross P&L': f"₹{pe.get('gross_pnl', pe['pnl']):.2f}",
                                    'Costs': f"₹{pe.get('costs', 0):.2f}",
                                    'Net P&L': f"₹{pe['pnl']:.2f}"
                                })
                            st.dataframe(pd.DataFrame(partial_data), use_container_width=True, hide_index=True)
                            st.markdown("---")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # ==================== Candlestick Chart ====================
            st.markdown("### 📈 Price Chart with All Trades")
            
            fig = go.Figure()
            
            # Candlestick
            fig.add_trace(go.Candlestick(
                x=hist_data.index,
                open=hist_data['Open'],
                high=hist_data['High'],
                low=hist_data['Low'],
                close=hist_data['Close'],
                name='Price',
                increasing_line_color='#0c6f3c',
                decreasing_line_color='#c53030'
            ))
            
            # Add entry level
            entry_label = f"Entry ({'Buy' if position == 'Long' else 'Sell'}): ₹{entry_price:.2f}"
            fig.add_hline(
                y=entry_price,
                line_dash="dash",
                line_color="#667eea",
                line_width=2,
                annotation_text=entry_label,
                annotation_position="right"
            )
            
            # Mark all entries and exits
            if total_trades > 0:
                entry_dates = [t['entry_date'] for t in all_trades]
                entry_prices_list = [t['entry_price'] for t in all_trades]
                exit_dates = [t['exit_date'] for t in all_trades]
                exit_prices_list = [t['exit_price'] for t in all_trades]
                
                # Add entry points
                fig.add_scatter(
                    x=entry_dates,
                    y=entry_prices_list,
                    mode='markers',
                    marker=dict(size=12, color='#10b981', symbol='triangle-up', line=dict(width=2, color='white')),
                    name='Entries',
                    hovertemplate='Entry<br>Date: %{x}<br>Price: ₹%{y:.2f}<extra></extra>'
                )
                
                # Add final exit points
                exit_colors = ['#ef4444' if t['pnl'] < 0 else '#22c55e' for t in all_trades]
                fig.add_scatter(
                    x=exit_dates,
                    y=exit_prices_list,
                    mode='markers',
                    marker=dict(size=12, color=exit_colors, symbol='triangle-down', line=dict(width=2, color='white')),
                    name='Final Exits',
                    hovertemplate='Final Exit<br>Date: %{x}<br>Price: ₹%{y:.2f}<extra></extra>'
                )
                
                # Add partial exits for Position/Swing
                if trade_type == "Position/Swing":
                    partial_dates = []
                    partial_prices = []
                    partial_hover = []
                    
                    for trade in all_trades:
                        if trade.get('partial_exits'):
                            for pe in trade['partial_exits']:
                                partial_dates.append(pe['date'])
                                partial_prices.append(pe['price'])
                                partial_hover.append(f"Partial Exit (T{pe['target']})<br>Shares: {pe['size']}<br>P&L: ₹{pe['pnl']:.2f}")
                    
                    if partial_dates:
                        fig.add_scatter(
                            x=partial_dates,
                            y=partial_prices,
                            mode='markers',
                            marker=dict(size=8, color='#f59e0b', symbol='circle', line=dict(width=1, color='white')),
                            name='Partial Exits',
                            text=partial_hover,
                            hovertemplate='%{text}<extra></extra>'
                        )
            
            # Add stop loss
            if trade_type == "Intraday":
                sl_label = f"SL ({'Sell' if position == 'Long' else 'Buy'}): ₹{stop_loss:.2f}"
            else:
                sl_label = f"SL ({'S1' if position == 'Long' else 'R1'}): ₹{stop_loss:.2f}"
            
            fig.add_hline(
                y=stop_loss,
                line_dash="dot",
                line_color="#c53030",
                line_width=2,
                annotation_text=sl_label,
                annotation_position="right"
            )
            
            # Add targets
            for i, target in enumerate(targets):
                if trade_type == "Intraday":
                    target_label = f"T{i+1}: ₹{target:.2f}"
                else:
                    target_label = f"{'R' if position == 'Long' else 'S'}{i+1}: ₹{target:.2f}"
                
                fig.add_hline(
                    y=target,
                    line_dash="dot",
                    line_color="#0c6f3c",
                    line_width=1.5,
                    annotation_text=target_label,
                    annotation_position="right"
                )
            
            # Add start price reference line
            fig.add_hline(
                y=start_price,
                line_dash="dashdot",
                line_color="#9f7aea",
                line_width=1.5,
                opacity=0.5,
                annotation_text=f"Start Price: ₹{start_price:.2f}",
                annotation_position="left"
            )
            
            # Add breakout level for reference (informational only)
            if trade_type == "Position/Swing":
                fig.add_hline(
                    y=final_levels['breakout'],
                    line_dash="longdashdot",
                    line_color="#f59e0b",
                    line_width=2,
                    opacity=0.7,
                    annotation_text=f"Breakout: ₹{final_levels['breakout']:.0f} (Info)",
                    annotation_position="left"
                )
            
            # Show level changes if dynamic recalculation was used
            if trade_type == "Position/Swing" and recalc_levels and len(level_history) > 1:
                st.markdown(f"**📊 Level Updates:** Levels were recalculated {len(level_history)} times before entry")
                
                # Add chart showing how entry level changed over time
                entry_levels_over_time = [h['entry'] for h in level_history]
                dates_for_levels = [h['date'] for h in level_history]
                
                fig_levels = go.Figure()
                fig_levels.add_trace(go.Scatter(
                    x=dates_for_levels,
                    y=entry_levels_over_time,
                    mode='lines+markers',
                    name='Entry Level',
                    line=dict(color='#667eea', width=2),
                    marker=dict(size=6),
                    hovertemplate='Date: %{x}<br>Entry Level: ₹%{y:.2f}<extra></extra>'
                ))
                
                fig_levels.update_layout(
                    title="Dynamic Entry Level Changes (Before Entry)",
                    yaxis_title="Entry Price (₹)",
                    xaxis_title="Date",
                    template="plotly_white",
                    height=300,
                    showlegend=False
                )
                
                st.plotly_chart(fig_levels, use_container_width=True)
            
            fig.update_layout(
                title=f"{stock_symbol} - {position} Position ({trade_type})<br><sub>Levels calculated from start price: ₹{start_price:.2f}</sub>",
                yaxis_title="Price (₹)",
                xaxis_title="Date",
                template="plotly_white",
                height=600,
                showlegend=True,
                hovermode='x unified',
                xaxis_rangeslider_visible=False
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # ==================== Strategy Comparison Chart ====================
            st.markdown("### 💰 Strategy vs Buy & Hold Performance")
            
            # Build buy & hold value over time
            buy_hold_dates = hist_data.index.tolist()
            buy_hold_values = [buy_hold_shares * row['Close'] for _, row in hist_data.iterrows()]
            
            # Build strategy capital history (interpolated for all dates)
            strategy_dates = hist_data.index.tolist()
            strategy_values = []
            
            current_val = initial_capital
            trade_idx = 0
            
            for date in hist_data.index:
                # Check if any trade closed on or before this date
                while trade_idx < len(all_trades) and all_trades[trade_idx]['exit_date'] <= date:
                    current_val = all_trades[trade_idx]['capital_after']
                    trade_idx += 1
                strategy_values.append(current_val)
            
            fig_comparison = go.Figure()
            
            # Buy & Hold line
            fig_comparison.add_trace(go.Scatter(
                x=buy_hold_dates,
                y=buy_hold_values,
                mode='lines',
                name='Buy & Hold',
                line=dict(color='#00f2fe', width=3),
                hovertemplate='Buy & Hold<br>Date: %{x}<br>Value: ₹%{y:.0f}<extra></extra>'
            ))
            
            # Strategy line
            fig_comparison.add_trace(go.Scatter(
                x=strategy_dates,
                y=strategy_values,
                mode='lines',
                name='Square-of-9 Strategy',
                line=dict(color='#667eea', width=3),
                hovertemplate='Strategy<br>Date: %{x}<br>Capital: ₹%{y:.0f}<extra></extra>'
            ))
            
            # Initial capital line
            fig_comparison.add_hline(
                y=initial_capital,
                line_dash="dash",
                line_color="gray",
                line_width=1,
                annotation_text=f"Initial: ₹{initial_capital:.0f}",
                annotation_position="left"
            )
            
            # Mark trade exits on strategy line
            if total_trades > 0:
                for trade in all_trades:
                    color = '#22c55e' if trade['pnl'] > 0 else '#ef4444'
                    fig_comparison.add_scatter(
                        x=[trade['exit_date']],
                        y=[trade['capital_after']],
                        mode='markers',
                        marker=dict(size=8, color=color, symbol='circle', line=dict(width=2, color='white')),
                        showlegend=False,
                        hovertemplate=f"Trade {trade['trade_num']}<br>P&L: ₹{trade['pnl']:.2f}<extra></extra>"
                    )
            
            fig_comparison.update_layout(
                title=f"Performance Comparison: Strategy ({final_return_pct:+.2f}%) vs Buy & Hold ({buy_hold_return_pct:+.2f}%)",
                yaxis_title="Portfolio Value (₹)",
                xaxis_title="Date",
                template="plotly_white",
                height=450,
                hovermode='x unified',
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            st.plotly_chart(fig_comparison, use_container_width=True)
            
            # ==================== Strategy Summary ====================
            st.markdown("### 📋 Strategy Summary")
            
            # Add strategy explanation
            profit_strategy = "Intraday: Exit at highest target reached" if trade_type == "Intraday" else "Position/Swing: Partial exits (33% at each target to maximize gains)"
            multiple_trades_text = f"{'✅ Multiple trades enabled' if allow_multiple_trades else '❌ Single trade only'} - {'New entries after each close' if allow_multiple_trades and trade_type == 'Position/Swing' else 'One trade per day' if trade_type == 'Intraday' else 'Only one trade for entire period'}"
            
            st.markdown(
                f"""
                <div class='note-box'>
                    <strong>💡 Risk-Based Strategy with Profit Maximization:</strong><br>
                    • <strong>Position Type:</strong> {position} | <strong>Trade Type:</strong> {trade_type}<br>
                    • <strong>Entry:</strong> {"Buy" if position == "Long" else "Sell"} level, <strong>SL:</strong> {"Sell/Support 1" if position == "Long" else "Buy/Resistance 1"}, <strong>Targets:</strong> {"Resistances/Bull Targets" if position == "Long" else "Supports/Bear Targets"}<br>
                    • <strong>Position Sizing:</strong> Based on {max_loss_pct}% risk per trade (auto-calculated)<br>
                    • <strong>Risk Management:</strong> Stop all trading if total loss reaches {max_total_loss_pct}%<br>
                    • <strong>Profit Strategy:</strong> {profit_strategy}<br>
                    • <strong>Position Holding:</strong> {"Single day only" if trade_type == "Intraday" else "Hold across multiple days until target/SL"}<br>
                    • <strong>Multiple Trades:</strong> {multiple_trades_text}<br>
                    {"• <strong>Level Recalculation:</strong> Dynamic (daily updates before entry)" if trade_type == "Position/Swing" and recalc_levels else "• <strong>Level Recalculation:</strong> Static (fixed from start)"}
                </div>
                """,
                unsafe_allow_html=True
            )
            
            if total_trades == 0:
                st.warning("⚠️ No trades were executed. Entry levels were never reached during the simulation period.")
            
        except Exception as e:
            st.error(f"❌ Error running simulation: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

# ====================================
# TAB 3: PAPER TRADING
# ====================================
with tab3:
    st.header("📈 Paper Trading")
    
    st.info("💡 **Paper Trading Mode**: Uses yfinance data (15-20 min delayed) - Completely virtual, NO real money involved!")
    
    # Initialize session state
    if 'paper_trading_active' not in st.session_state:
        st.session_state.paper_trading_active = False
    if 'paper_portfolio' not in st.session_state:
        st.session_state.paper_portfolio = {
            'capital': 100000,
            'initial_capital': 100000,
            'positions': [],
            'trades_history': [],
            'current_price': None,
            'last_update': None
        }
    if 'paper_levels' not in st.session_state:
        st.session_state.paper_levels = None
    if 'paper_session_reports' not in st.session_state:
        st.session_state.paper_session_reports = []
    
    st.markdown("---")
    st.subheader("⚙️ Configuration")
    
    # Row 1: Stock Symbol and Trade Type
    col1, col2 = st.columns(2)
    
    with col1:
        paper_symbol_input = st.text_input(
            "Enter Stock Symbol",
            value="RELIANCE.NS",
            help="For Indian stocks, use format: SYMBOL.NS (e.g., RELIANCE.NS). For US stocks, just the symbol (e.g., AAPL)",
            key="paper_symbol_input"
        )
        paper_symbol = paper_symbol_input
    
    with col2:
        paper_trade_type = st.radio(
            "Trade Type",
            ["Intraday", "Swing/Positional"],
            horizontal=True,
            key="paper_trade_type",
            help="Intraday: Positions closed same day. Swing: Positions held multiple days"
        )
    
    # Row 2: Time/Date Range based on Trade Type
    if paper_trade_type == "Intraday":
        st.markdown("**⏰ Intraday Time Range** (Optional - Leave default for full market hours)")
        col1, col2 = st.columns(2)
        
        with col1:
            paper_start_time = st.time_input(
                "Start Time",
                value=dt_time(9, 15),
                key="paper_start_time",
                help="Trading starts at this time"
            )
        
        with col2:
            paper_end_time = st.time_input(
                "End Time",
                value=dt_time(15, 30),
                key="paper_end_time",
                help="All positions auto-closed at this time"
            )
    else:
        st.markdown("**📅 Swing/Positional Date Range** (Optional)")
        col1, col2 = st.columns(2)
        
        with col1:
            paper_start_date = st.date_input(
                "Start Date",
                value=datetime.now().date(),
                key="paper_start_date",
                help="Paper trading starts from this date"
            )
        
        with col2:
            paper_end_date = st.date_input(
                "End Date",
                value=datetime.now().date() + timedelta(days=30),
                key="paper_end_date",
                help="Paper trading ends on this date"
            )
    
    # Row 3: Trading Parameters
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        paper_position = st.radio(
            "Position Type",
            ["Long", "Short"],
            horizontal=True,
            key="paper_position"
        )
    
    with col2:
        paper_entry_mode = st.radio(
            "Entry Mode",
            ["Wait for Level", "Immediate Entry"],
            horizontal=False,
            key="paper_entry_mode"
        )
    
    with col3:
        paper_capital = st.number_input(
            "Virtual Capital (₹)",
            min_value=10000,
            max_value=10000000,
            value=10000,
            step=10000,
            key="paper_capital_input"
        )
    
    with col4:
        paper_risk_pct = st.number_input(
            "Risk per Trade (%)",
            min_value=0.5,
            max_value=10.0,
            value=2.0,
            step=0.5,
            key="paper_risk_pct"
        )
    
    with col5:
        paper_max_loss_pct = st.number_input(
            "Max Total Loss (%)",
            min_value=5.0,
            max_value=50.0,
            value=20.0,
            step=5.0,
            key="paper_max_loss_pct",
            help="Stop all trading if portfolio drops by this percentage"
        )
    
    # Row 4: Advanced Options
    st.markdown("**⚙️ Advanced Options**")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if paper_trade_type == "Intraday":
            # For intraday, always allow multiple trades
            paper_multiple_trades = True
            st.markdown("""
                <div style='padding: 0.5rem; background: #e6f7ff; border-radius: 4px; border-left: 3px solid #1890ff;'>
                    <strong style='color: #096dd9;'>✅ Multiple Trades: ON</strong><br>
                    <span style='font-size: 0.85rem; color: #0050b3;'>Intraday mode allows multiple trades per day</span>
                </div>
            """, unsafe_allow_html=True)
        else:
            paper_multiple_trades = st.checkbox(
                "Multiple Trades",
                value=False,
                key="paper_multiple_trades",
                help="Allow new entries after each trade closes. If unchecked, only one trade for entire period."
            )
    
    with col2:
        paper_recalc_levels = st.checkbox(
            "Recalculate Levels Daily",
            value=True,
            key="paper_recalc_levels",
            help="Recalculate Square-of-9 levels based on previous day's close (for Swing) or day's open (for Intraday)"
        )
    
    with col3:
        # Data refresh interval based on trade type
        if paper_trade_type == "Intraday":
            default_interval = 90
            min_interval = 60
            help_text = "Min 60s to avoid yfinance rate limits. Data is 15-20 min delayed."
        else:
            default_interval = 300
            min_interval = 180
            help_text = "Min 180s for swing trading. Data is 15-20 min delayed."
        
        paper_refresh_interval = st.number_input(
            "Auto-Refresh Interval (sec)",
            min_value=min_interval,
            max_value=600,
            value=default_interval,
            step=30,
            key="paper_refresh_interval",
            help=help_text
        )
    
    # Market Hours Detection
    def is_market_hours():
        """Check if current time is within Indian market hours (9:15 AM - 3:30 PM IST)"""
        now = datetime.now()
        # Simple check - can be enhanced with timezone handling
        market_start = dt_time(9, 15)
        market_end = dt_time(15, 30)
        current_time = now.time()
        
        # Check if weekday (Monday=0, Sunday=6)
        is_weekday = now.weekday() < 5
        
        return is_weekday and market_start <= current_time <= market_end
    
    # Session Report Generator
    def generate_session_report(portfolio):
        """Generate a comprehensive session report"""
        end_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_timestamp = portfolio.get('start_timestamp', end_timestamp)
        
        # Calculate metrics
        total_pnl = portfolio['capital'] - portfolio['initial_capital']
        pnl_pct = (total_pnl / portfolio['initial_capital']) * 100
        total_trades = len(portfolio['trades_history'])
        
        winning_trades = len([t for t in portfolio['trades_history'] if t['pnl'] > 0])
        losing_trades = total_trades - winning_trades
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        avg_win = np.mean([t['pnl'] for t in portfolio['trades_history'] if t['pnl'] > 0]) if winning_trades > 0 else 0
        avg_loss = np.mean([t['pnl'] for t in portfolio['trades_history'] if t['pnl'] < 0]) if losing_trades > 0 else 0
        
        max_win = max([t['pnl'] for t in portfolio['trades_history']], default=0)
        max_loss = min([t['pnl'] for t in portfolio['trades_history']], default=0)
        
        # Create report
        report = {
            'session_id': f"{portfolio.get('symbol', 'UNKNOWN')}_{start_timestamp.replace(':', '-').replace(' ', '_')}",
            'start_time': start_timestamp,
            'end_time': end_timestamp,
            'symbol': portfolio.get('symbol', 'N/A'),
            'trade_type': portfolio.get('trade_type', 'N/A'),
            'position_type': portfolio.get('position_type', 'N/A'),
            'initial_capital': portfolio['initial_capital'],
            'final_capital': portfolio['capital'],
            'total_pnl': total_pnl,
            'pnl_percentage': pnl_pct,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_win': max_win,
            'max_loss': max_loss,
            'risk_per_trade': portfolio.get('risk_pct', 0),
            'max_loss_limit': portfolio.get('max_loss_pct', 0),
            'multiple_trades_enabled': portfolio.get('multiple_trades', False),
            'recalc_levels_daily': portfolio.get('recalc_levels', False),
            'trades_history': portfolio['trades_history'],
            'open_positions': len(portfolio.get('positions', []))
        }
        
        return report
    
    # Control Buttons
    st.markdown("---")
    col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
    
    with col_btn1:
        if st.button("🚀 Start Trading", type="primary", disabled=st.session_state.paper_trading_active or not paper_symbol):
            # Initialize/Reset portfolio
            portfolio_init = {
                'capital': paper_capital,
                'initial_capital': paper_capital,
                'positions': [],
                'trades_history': [],
                'current_price': None,
                'last_update': None,
                'last_data_fetch': None,
                'last_level_calc_date': None,
                'symbol': paper_symbol,
                'position_type': paper_position,
                'entry_mode': paper_entry_mode,
                'risk_pct': paper_risk_pct,
                'max_loss_pct': paper_max_loss_pct,
                'trade_type': paper_trade_type,
                'multiple_trades': paper_multiple_trades,
                'recalc_levels': paper_recalc_levels,
                'refresh_interval': paper_refresh_interval,
                'start_timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'session_active': True
            }
            
            # Add time/date range based on trade type
            if paper_trade_type == "Intraday":
                portfolio_init['start_time'] = paper_start_time
                portfolio_init['end_time'] = paper_end_time
            else:
                portfolio_init['start_date'] = paper_start_date
                portfolio_init['end_date'] = paper_end_date
            
            st.session_state.paper_portfolio = portfolio_init
            st.session_state.paper_trading_active = True
            st.success(f"✅ Paper trading started for {paper_symbol} ({paper_trade_type} mode)")
            st.rerun()
    
    with col_btn2:
        if st.button("⏸️ Stop Trading", disabled=not st.session_state.paper_trading_active):
            # Generate and save session report
            portfolio = st.session_state.paper_portfolio
            if len(portfolio.get('trades_history', [])) > 0 or len(portfolio.get('positions', [])) > 0:
                report = generate_session_report(portfolio)
                st.session_state.paper_session_reports.append(report)
                st.success("✅ Session report saved! View in Reports tab.")
            
            st.session_state.paper_trading_active = False
            st.warning("⏸️ Paper trading stopped")
            st.rerun()
    
    with col_btn3:
        if st.button("🔄 Reset Portfolio"):
            st.session_state.paper_portfolio = {
                'capital': paper_capital,
                'initial_capital': paper_capital,
                'positions': [],
                'trades_history': [],
                'current_price': None,
                'last_update': None
            }
            st.session_state.paper_levels = None
            st.success("✅ Portfolio reset")
            st.rerun()
    
    with col_btn4:
        if st.button("🔴 Close All Positions", disabled=len(st.session_state.paper_portfolio.get('positions', [])) == 0):
            # Close all open positions at current market price
            portfolio = st.session_state.paper_portfolio
            if portfolio.get('current_price'):
                for pos in portfolio['positions']:
                    exit_price = portfolio['current_price']
                    pnl = (exit_price - pos['entry_price']) * pos['quantity'] if pos['type'] == 'Long' else (pos['entry_price'] - exit_price) * pos['quantity']
                    
                    # Add to history
                    portfolio['trades_history'].append({
                        'entry_time': pos['entry_time'],
                        'exit_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'type': pos['type'],
                        'entry_price': pos['entry_price'],
                        'exit_price': exit_price,
                        'quantity': pos['quantity'],
                        'pnl': pnl,
                        'result': 'Manual Close'
                    })
                    
                    # Update capital
                    portfolio['capital'] += pnl
                
                # Clear positions
                portfolio['positions'] = []
                st.success(f"✅ All positions closed at ₹{exit_price:.2f}")
                st.rerun()
    
    # Main Trading Logic
    if st.session_state.paper_trading_active:
        st.markdown("---")
        
        # Get portfolio settings
        portfolio = st.session_state.paper_portfolio
        symbol = portfolio.get('symbol', paper_symbol)
        trade_type = portfolio.get('trade_type', 'Intraday')
        recalc_levels = portfolio.get('recalc_levels', True)
        max_trades = portfolio.get('max_trades', 1)
        
        # Check if within trading period
        now = datetime.now()
        current_time = now.time()
        current_date = now.date()
        
        # Trading period validation
        trading_allowed = True
        period_status = ""
        
        if trade_type == "Intraday":
            start_time = portfolio.get('start_time', dt_time(9, 15))
            end_time = portfolio.get('end_time', dt_time(15, 30))
            
            if current_time < start_time:
                trading_allowed = False
                period_status = f"⏰ Trading starts at {start_time.strftime('%H:%M')}"
            elif current_time > end_time:
                trading_allowed = False
                period_status = f"⏰ Trading ended at {end_time.strftime('%H:%M')}"
                # Auto-close all positions after end time
                if len(portfolio['positions']) > 0:
                    st.warning("End of day - All intraday positions will be closed")
            else:
                period_status = f"🟢 Intraday trading active ({start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')})"
        else:
            start_date = portfolio.get('start_date', current_date)
            end_date = portfolio.get('end_date', current_date + timedelta(days=30))
            
            if current_date < start_date:
                trading_allowed = False
                period_status = f"📅 Trading starts on {start_date}"
            elif current_date > end_date:
                trading_allowed = False
                period_status = f"📅 Trading ended on {end_date}"
            else:
                period_status = f"🟢 Swing trading active (Until {end_date})"
        
        # Display trading status
        if trading_allowed:
            st.success(period_status)
        else:
            st.warning(period_status)
        
        # Market Hours Check
        market_open = is_market_hours()
        if not market_open and trade_type == "Intraday":
            st.info("🟡 Market is CLOSED - No new trades")
        
        try:
            # Smart data fetching with rate limit protection
            refresh_interval = portfolio.get('refresh_interval', 90)
            last_fetch = portfolio.get('last_data_fetch')
            
            # Check if we should fetch new data
            should_fetch = False
            if last_fetch is None:
                should_fetch = True
            else:
                # Parse last fetch time
                try:
                    last_fetch_time = datetime.strptime(last_fetch, "%Y-%m-%d %H:%M:%S")
                    time_since_fetch = (datetime.now() - last_fetch_time).total_seconds()
                    if time_since_fetch >= refresh_interval:
                        should_fetch = True
                except:
                    should_fetch = True
            
            # Fetch data if needed
            if should_fetch:
                ticker = yf.Ticker(symbol)
                
                # Use appropriate interval based on trade type
                if trade_type == "Intraday":
                    hist = ticker.history(period='1d', interval='1m')
                else:
                    # For swing trading, use 5-minute intervals to reduce API calls
                    hist = ticker.history(period='5d', interval='5m')
                
                if not hist.empty:
                    current_price = hist['Close'].iloc[-1]
                    portfolio['current_price'] = current_price
                    portfolio['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    portfolio['last_data_fetch'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    st.warning("⚠️ No data received from yfinance. Using last known price.")
                    current_price = portfolio.get('current_price', 0)
            else:
                # Use cached price
                current_price = portfolio.get('current_price', 0)
                time_until_refresh = refresh_interval - time_since_fetch
                st.info(f"⏱️ Using cached data. Next refresh in {int(time_until_refresh)}s (Rate limit protection)")
                
                # Check if we need to recalculate levels
                should_recalc = False
                last_calc_date = portfolio.get('last_level_calc_date')
                
                if st.session_state.paper_levels is None:
                    # First time - calculate levels
                    should_recalc = True
                    calc_price = current_price
                elif recalc_levels:
                    # Check if it's a new day
                    if last_calc_date is None or last_calc_date != current_date:
                        should_recalc = True
                        # For new day, use previous close or today's open
                        hist_daily = ticker.history(period='5d', interval='1d')
                        if not hist_daily.empty and len(hist_daily) > 1:
                            if trade_type == "Intraday":
                                calc_price = hist_daily['Open'].iloc[-1]
                                st.info(f"📊 Recalculated levels using today's open: ₹{calc_price:.2f}")
                            else:
                                calc_price = hist_daily['Close'].iloc[-2]
                                st.info(f"📊 Recalculated levels using previous day's close: ₹{calc_price:.2f}")
                        else:
                            calc_price = current_price
                
                # Calculate or use existing levels
                if should_recalc:
                    current_levels = calculate_levels(calc_price)
                    st.session_state.paper_levels = current_levels
                    portfolio['last_level_calc_date'] = current_date
                else:
                    current_levels = st.session_state.paper_levels
                
                # Check Max Loss limit
                max_loss_pct = portfolio.get('max_loss_pct', 20.0)
                current_loss_pct = ((portfolio['capital'] - portfolio['initial_capital']) / portfolio['initial_capital']) * 100
                
                if current_loss_pct <= -max_loss_pct:
                    st.error(f"🛑 MAX LOSS LIMIT REACHED! Portfolio down {abs(current_loss_pct):.2f}%. Trading halted.")
                    # Generate and save session report
                    report = generate_session_report(portfolio)
                    st.session_state.paper_session_reports.append(report)
                    st.session_state.paper_trading_active = False
                    st.info("Session report saved. Check Reports tab.")
                    st.rerun()
                
                # Determine entry, SL, and targets based on position type
                position_type = portfolio.get('position_type', 'Long')
                entry_mode = portfolio.get('entry_mode', 'Wait for Level')
                
                if position_type == "Long":
                    entry_price = current_levels['buy']
                    stop_loss = current_levels['sell']
                    targets = current_levels['bull_targets'][:3]
                else:
                    entry_price = current_levels['sell']
                    stop_loss = current_levels['buy']
                    targets = current_levels['bear_targets'][:3]
                
                # Check for entry based on multiple trades setting
                current_positions = len(portfolio['positions'])
                multiple_trades = portfolio.get('multiple_trades', False)
                total_trades_taken = len(portfolio.get('trades_history', []))
                
                # Allow entry if:
                # 1. No current position AND
                # 2. (multiple_trades is True OR no trades taken yet) AND
                # 3. Trading is allowed AND
                # 4. Market is open (for intraday) or it's swing trading
                can_enter = (
                    current_positions == 0 and
                    (multiple_trades or total_trades_taken == 0) and
                    trading_allowed and
                    (market_open or trade_type == "Swing/Positional")
                )
                
                if can_enter:
                    entry_triggered = False
                    actual_entry = entry_price
                    
                    if entry_mode == "Wait for Level":
                        # Check if current price is near entry level (within 0.5%)
                        if abs(current_price - entry_price) / entry_price <= 0.005:
                            entry_triggered = True
                            actual_entry = current_price
                    else:  # Immediate Entry
                        if position_type == "Long":
                            if current_price <= entry_price:
                                entry_triggered = True
                                actual_entry = current_price
                        else:
                            if current_price >= entry_price:
                                entry_triggered = True
                                actual_entry = current_price
                    
                    # Execute entry
                    if entry_triggered:
                        risk_per_share = abs(actual_entry - stop_loss)
                        if risk_per_share > 0:
                            max_risk_amount = portfolio['capital'] * (portfolio['risk_pct'] / 100)
                            quantity = int(max_risk_amount / risk_per_share)
                            quantity = max(1, min(quantity, int(portfolio['capital'] / actual_entry)))
                            
                            # Create position
                            new_position = {
                                'type': position_type,
                                'entry_price': actual_entry,
                                'entry_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                'quantity': quantity,
                                'stop_loss': stop_loss,
                                'targets': targets,
                                'capital_at_entry': portfolio['capital']
                            }
                            
                            portfolio['positions'].append(new_position)
                            st.success(f"🎯 {position_type} position opened: {quantity} shares @ ₹{actual_entry:.2f}")
                
                # Check exit conditions for open positions
                for i, pos in enumerate(portfolio['positions'][:]):
                    # Check Stop Loss
                    sl_hit = False
                    if pos['type'] == 'Long' and current_price <= pos['stop_loss']:
                        sl_hit = True
                    elif pos['type'] == 'Short' and current_price >= pos['stop_loss']:
                        sl_hit = True
                    
                    # Check Targets
                    target_hit = False
                    target_num = 0
                    for j, target in enumerate(pos['targets']):
                        if pos['type'] == 'Long' and current_price >= target:
                            target_hit = True
                            target_num = j + 1
                        elif pos['type'] == 'Short' and current_price <= target:
                            target_hit = True
                            target_num = j + 1
                    
                    # Execute exit
                    if sl_hit or target_hit:
                        exit_price = current_price
                        pnl = (exit_price - pos['entry_price']) * pos['quantity'] if pos['type'] == 'Long' else (pos['entry_price'] - exit_price) * pos['quantity']
                        
                        # Add to history
                        portfolio['trades_history'].append({
                            'entry_time': pos['entry_time'],
                            'exit_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            'type': pos['type'],
                            'entry_price': pos['entry_price'],
                            'exit_price': exit_price,
                            'quantity': pos['quantity'],
                            'pnl': pnl,
                            'result': f"Target {target_num}" if target_hit else "Stop Loss"
                        })
                        
                        # Update capital
                        portfolio['capital'] += pnl
                        
                        # Remove position
                        portfolio['positions'].pop(i)
                        
                        result_emoji = "✅" if pnl > 0 else "❌"
                        st.success(f"{result_emoji} Position closed: P&L = ₹{pnl:.2f} ({'Target ' + str(target_num) if target_hit else 'Stop Loss'})")
                
        except Exception as e:
            st.error(f"❌ Error fetching data: {str(e)}")
        
        # Display Dashboard
        st.markdown("---")
        st.markdown("### 📊 Live Dashboard")
        
        # Metrics Row
        col1, col2, col3, col4, col5 = st.columns(5)
        
        total_pnl = portfolio['capital'] - portfolio['initial_capital']
        pnl_pct = (total_pnl / portfolio['initial_capital']) * 100
        
        with col1:
            st.metric("Current Price", f"₹{portfolio.get('current_price', 0):.2f}" if portfolio.get('current_price') else "N/A")
        
        with col2:
            st.metric("Portfolio Value", f"₹{portfolio['capital']:.2f}")
        
        with col3:
            st.metric("Total P&L", f"₹{total_pnl:.2f}", f"{pnl_pct:.2f}%")
        
        with col4:
            st.metric("Open Positions", len(portfolio['positions']))
        
        with col5:
            st.metric("Total Trades", len(portfolio['trades_history']))
        
        # Strategy Status Info
        st.markdown("---")
        multiple_trades = portfolio.get('multiple_trades', False)
        recalc_levels = portfolio.get('recalc_levels', False)
        
        if trade_type == "Intraday":
            multiple_trades_text = "✅ Multiple trades enabled - New entries allowed after each close"
        else:
            multiple_trades_text = f"{'✅ Multiple trades enabled - New entries after each close' if multiple_trades else '❌ Single trade only - No new entries after first trade closes'}"
        
        st.info(f"""
            **📋 Active Strategy:** {trade_type} | {portfolio.get('position_type', 'Long')} Position | {portfolio.get('entry_mode', 'Wait for Level')} Entry
            
            • **Multiple Trades:** {multiple_trades_text}
            • **Level Recalculation:** {'✅ Daily (recalculates each day)' if recalc_levels else '❌ Static (fixed from start)'}
            • **Max Loss Limit:** {portfolio.get('max_loss_pct', 20)}% (Current: {abs(pnl_pct):.2f}%)
            • **Risk per Trade:** {portfolio.get('risk_pct', 2)}% of capital
        """)
        
        # Current Levels Display
        if st.session_state.paper_levels:
            st.markdown("### 📈 Current Square-of-9 Levels")
            levels = st.session_state.paper_levels
            current_position_type = portfolio.get('position_type', paper_position)
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown(f"""
                **Entry Levels:**
                - Buy: ₹{levels['buy']:.2f}
                - Sell: ₹{levels['sell']:.2f}
                """)
            
            with col2:
                if current_position_type == "Long":
                    st.markdown(f"""
                    **Targets (Bull):**
                    - T1: ₹{levels['bull_targets'][0]:.2f}
                    - T2: ₹{levels['bull_targets'][1]:.2f}
                    - T3: ₹{levels['bull_targets'][2]:.2f}
                    """)
                else:
                    st.markdown(f"""
                    **Targets (Bear):**
                    - T1: ₹{levels['bear_targets'][0]:.2f}
                    - T2: ₹{levels['bear_targets'][1]:.2f}
                    - T3: ₹{levels['bear_targets'][2]:.2f}
                    """)
            
            with col3:
                st.markdown(f"""
                **Support/Resistance:**
                - R1: ₹{levels['resistances'][0]:.2f}
                - S1: ₹{levels['supports'][0]:.2f}
                - Breakout: ₹{levels['breakout']:.2f}
                """)
        
        # Open Positions Table
        if len(portfolio['positions']) > 0:
            st.markdown("### 📌 Open Positions")
            
            positions_data = []
            for pos in portfolio['positions']:
                current_pnl = (portfolio['current_price'] - pos['entry_price']) * pos['quantity'] if pos['type'] == 'Long' else (pos['entry_price'] - portfolio['current_price']) * pos['quantity']
                pnl_pct = (current_pnl / (pos['entry_price'] * pos['quantity'])) * 100
                
                positions_data.append({
                    'Type': pos['type'],
                    'Entry Time': pos['entry_time'],
                    'Entry Price': f"₹{pos['entry_price']:.2f}",
                    'Current Price': f"₹{portfolio['current_price']:.2f}",
                    'Quantity': pos['quantity'],
                    'Stop Loss': f"₹{pos['stop_loss']:.2f}",
                    'Target 1': f"₹{pos['targets'][0]:.2f}",
                    'Unrealized P&L': f"₹{current_pnl:.2f} ({pnl_pct:.2f}%)"
                })
            
            st.dataframe(pd.DataFrame(positions_data), use_container_width=True)
        
        # Trade History
        if len(portfolio['trades_history']) > 0:
            st.markdown("### 📜 Trade History")
            
            trades_df = pd.DataFrame(portfolio['trades_history'])
            trades_df['P&L %'] = (trades_df['pnl'] / (trades_df['entry_price'] * trades_df['quantity'])) * 100
            trades_df['Entry Price'] = trades_df['entry_price'].apply(lambda x: f"₹{x:.2f}")
            trades_df['Exit Price'] = trades_df['exit_price'].apply(lambda x: f"₹{x:.2f}")
            trades_df['P&L'] = trades_df['pnl'].apply(lambda x: f"₹{x:.2f}")
            
            display_cols = ['entry_time', 'exit_time', 'type', 'Entry Price', 'Exit Price', 'quantity', 'P&L', 'P&L %', 'result']
            st.dataframe(trades_df[display_cols], use_container_width=True)
            
            # Summary Stats
            st.markdown("### 📊 Performance Summary")
            
            col1, col2, col3, col4 = st.columns(4)
            
            winning_trades = len([t for t in portfolio['trades_history'] if t['pnl'] > 0])
            total_trades_count = len(portfolio['trades_history'])
            win_rate = (winning_trades / total_trades_count * 100) if total_trades_count > 0 else 0
            
            avg_win = np.mean([t['pnl'] for t in portfolio['trades_history'] if t['pnl'] > 0]) if winning_trades > 0 else 0
            avg_loss = np.mean([t['pnl'] for t in portfolio['trades_history'] if t['pnl'] < 0]) if (total_trades_count - winning_trades) > 0 else 0
            
            with col1:
                st.metric("Win Rate", f"{win_rate:.1f}%")
            
            with col2:
                st.metric("Winning Trades", f"{winning_trades}/{total_trades_count}")
            
            with col3:
                st.metric("Avg Win", f"₹{avg_win:.2f}")
            
            with col4:
                st.metric("Avg Loss", f"₹{avg_loss:.2f}")
        
        # Auto-refresh control
        st.markdown("---")
        
        # Refresh control based on trading period
        if trading_allowed and (market_open or trade_type == "Swing/Positional"):
            col_refresh1, col_refresh2 = st.columns([3, 1])
            with col_refresh1:
                refresh_interval = portfolio.get('refresh_interval', 90)
                last_fetch = portfolio.get('last_data_fetch', 'Never')
                st.info(f"🔄 Trading active. Data refreshes every {refresh_interval}s. Last fetch: {last_fetch}")
                st.write(f"💡 **Tip:** Keep this tab open and click 'Refresh Now' to update prices and check for trade signals.")
            with col_refresh2:
                if st.button("🔄 Refresh Now", key="manual_refresh"):
                    st.rerun()
        else:
            col_status1, col_status2 = st.columns([3, 1])
            with col_status1:
                st.warning("⏸️ Trading paused (outside trading hours/period).")
                st.info("💡 Click 'Refresh Now' to check if trading can resume.")
            with col_status2:
                if st.button("🔄 Refresh Now", key="manual_refresh_paused"):
                    st.rerun()
    
    else:
        st.markdown("---")
        st.info("👆 Configure your settings above and click '🚀 Start Trading' to begin paper trading!")

# ====================================
# TAB 4: REPORTS DASHBOARD
# ====================================
with tab4:
    st.header("📋 Reports Dashboard")
    
    st.info("💡 **View your completed paper trading sessions and download detailed reports**")
    
    # Check if there are any reports
    if 'paper_session_reports' not in st.session_state or len(st.session_state.paper_session_reports) == 0:
        st.markdown("---")
        st.warning("📂 No session reports available yet. Complete a paper trading session to see reports here.")
        st.markdown("""
        ### How to generate reports:
        1. Go to the **Paper Trading** tab
        2. Configure your settings and start trading
        3. Execute some trades
        4. Click **Stop Trading** to end the session
        5. Your report will automatically appear here!
        """)
    else:
        st.markdown("---")
        st.subheader(f"📊 Total Sessions: {len(st.session_state.paper_session_reports)}")
        
        # Display reports in reverse chronological order
        for idx, report in enumerate(reversed(st.session_state.paper_session_reports)):
            with st.expander(f"📈 Session {len(st.session_state.paper_session_reports) - idx}: {report['symbol']} - {report['start_time']}", expanded=(idx == 0)):
                # Session Overview
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown("**📋 Session Details**")
                    st.write(f"**Symbol:** {report['symbol']}")
                    st.write(f"**Trade Type:** {report['trade_type']}")
                    st.write(f"**Position Type:** {report['position_type']}")
                    st.write(f"**Duration:** {report['start_time']} to {report['end_time']}")
                
                with col2:
                    st.markdown("**💰 Financial Performance**")
                    pnl_color = "🟢" if report['total_pnl'] >= 0 else "🔴"
                    st.write(f"**Initial Capital:** ₹{report['initial_capital']:,.2f}")
                    st.write(f"**Final Capital:** ₹{report['final_capital']:,.2f}")
                    st.write(f"**Total P&L:** {pnl_color} ₹{report['total_pnl']:,.2f} ({report['pnl_percentage']:.2f}%)")
                
                with col3:
                    st.markdown("**📊 Trading Statistics**")
                    st.write(f"**Total Trades:** {report['total_trades']}")
                    st.write(f"**Win Rate:** {report['win_rate']:.1f}%")
                    st.write(f"**Winning Trades:** {report['winning_trades']}")
                    st.write(f"**Losing Trades:** {report['losing_trades']}")
                
                # Detailed Metrics
                st.markdown("---")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Avg Win", f"₹{report['avg_win']:.2f}")
                
                with col2:
                    st.metric("Avg Loss", f"₹{report['avg_loss']:.2f}")
                
                with col3:
                    st.metric("Max Win", f"₹{report['max_win']:.2f}")
                
                with col4:
                    st.metric("Max Loss", f"₹{report['max_loss']:.2f}")
                
                # Configuration Used
                st.markdown("---")
                st.markdown("**⚙️ Configuration Used**")
                config_col1, config_col2, config_col3 = st.columns(3)
                
                with config_col1:
                    st.write(f"**Risk per Trade:** {report['risk_per_trade']}%")
                    st.write(f"**Max Loss Limit:** {report['max_loss_limit']}%")
                
                with config_col2:
                    multiple_status = "✅ Enabled" if report.get('multiple_trades_enabled', False) else "❌ Disabled (Single trade only)"
                    st.write(f"**Multiple Trades:** {multiple_status}")
                    recalc_status = "✅ Enabled" if report.get('recalc_levels_daily', False) else "❌ Disabled"
                    st.write(f"**Daily Level Recalc:** {recalc_status}")
                
                with config_col3:
                    st.write(f"**Open Positions at End:** {report['open_positions']}")
                
                # Trade History
                if report['total_trades'] > 0:
                    st.markdown("---")
                    st.markdown("**📜 Trade History**")
                    
                    trades_df = pd.DataFrame(report['trades_history'])
                    trades_df['P&L %'] = (trades_df['pnl'] / (trades_df['entry_price'] * trades_df['quantity'])) * 100
                    trades_df['Entry Price'] = trades_df['entry_price'].apply(lambda x: f"₹{x:.2f}")
                    trades_df['Exit Price'] = trades_df['exit_price'].apply(lambda x: f"₹{x:.2f}")
                    trades_df['P&L'] = trades_df['pnl'].apply(lambda x: f"₹{x:.2f}")
                    
                    display_cols = ['entry_time', 'exit_time', 'type', 'Entry Price', 'Exit Price', 'quantity', 'P&L', 'P&L %', 'result']
                    st.dataframe(trades_df[display_cols], use_container_width=True)
                
                # Download JSON Report
                st.markdown("---")
                col_download1, col_download2 = st.columns([3, 1])
                
                with col_download1:
                    st.markdown("**📥 Download Session Report**")
                    st.write("Download the complete session data as JSON for further analysis")
                
                with col_download2:
                    report_json = json.dumps(report, indent=2, default=str)
                    st.download_button(
                        label="💾 Download JSON",
                        data=report_json,
                        file_name=f"{report['session_id']}.json",
                        mime="application/json",
                        key=f"download_{report['session_id']}"
                    )
        
        # Option to clear all reports
        st.markdown("---")
        col_clear1, col_clear2 = st.columns([3, 1])
        
        with col_clear1:
            st.markdown("**🗑️ Clear All Reports**")
            st.write("This will permanently delete all saved session reports")
        
        with col_clear2:
            if st.button("🗑️ Clear All", type="secondary"):
                st.session_state.paper_session_reports = []
                st.success("✅ All reports cleared!")
                st.rerun()
