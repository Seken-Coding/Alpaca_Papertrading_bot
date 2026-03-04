"""Tkinter GUI for the Alpaca Paper Trading Bot."""

import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Optional

from broker.client import AlpacaClient
from alpaca.trading.enums import OrderSide, TimeInForce
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.scanner import StrategyScanner, Recommendation
from analysis.scorer import ScoringEngine, StockScore
from analysis.data_loader import load_bars
from alpaca.data.timeframe import TimeFrame
from risk.manager import RiskManager, RiskConfig
from execution.engine import ExecutionEngine
from execution.position_store import PositionStore
from execution.trade_journal import TradeJournal
from config.settings import settings

logger = logging.getLogger(__name__)
trades_logger = logging.getLogger("trades")


# ── Log handler that writes to a tkinter Text widget ─────────────────────

class TextHandler(logging.Handler):
    """Route log records into a scrolledtext widget (thread-safe via .after)."""

    def __init__(self, widget: scrolledtext.ScrolledText):
        super().__init__()
        self.widget = widget

    def emit(self, record):
        msg = self.format(record) + "\n"
        self.widget.after(0, self._append, msg, record.levelno)

    def _append(self, msg: str, levelno: int):
        self.widget.configure(state=tk.NORMAL)
        tag = {
            logging.WARNING:  "warn",
            logging.ERROR:    "error",
            logging.CRITICAL: "error",
        }.get(levelno, "info")
        self.widget.insert(tk.END, msg, tag)
        self.widget.see(tk.END)
        self.widget.configure(state=tk.DISABLED)


# ── Main application ─────────────────────────────────────────────────────

class TradingApp(tk.Tk):
    """Paper-trading dashboard with Risk Management and Score Analysis tabs."""

    def __init__(self, client: AlpacaClient, risk_config: Optional[RiskConfig] = None):
        super().__init__()
        self.client = client
        self.risk_manager = RiskManager(risk_config)
        self._recommendations: list[Recommendation] = []
        self._scores: list[StockScore] = []
        self._order_ids: dict[str, str] = {}
        self._current_equity: float = 0.0
        self._position_store = PositionStore()
        self._trade_journal = TradeJournal()

        self.title("Alpaca Paper Trading Bot")
        self.geometry("1280x820")
        self.minsize(1000, 650)

        self._build_styles()
        self._build_ui()
        self._setup_logging()
        self._initial_refresh()

    # ── Styles ───────────────────────────────────────────────────────

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Buy.TLabel",    foreground="#16a34a")
        style.configure("Sell.TLabel",   foreground="#dc2626")
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Big.TLabel",    font=("Segoe UI", 18, "bold"))
        style.configure("PL.TLabel",     font=("Segoe UI", 11, "bold"))
        style.configure("Treeview",      rowheight=24)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Green.TLabel",  foreground="#16a34a", font=("Segoe UI", 11, "bold"))
        style.configure("Red.TLabel",    foreground="#dc2626", font=("Segoe UI", 11, "bold"))
        style.configure("Halt.TLabel",   foreground="#dc2626", font=("Segoe UI", 10, "bold"))
        style.configure("OK.TLabel",     foreground="#16a34a", font=("Segoe UI", 10, "bold"))

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        top = ttk.Frame(self, padding=6)
        top.pack(fill=tk.X)

        self.lbl_equity = ttk.Label(top, text="Equity: —", style="Big.TLabel")
        self.lbl_equity.pack(side=tk.LEFT)

        self.lbl_buying_power = ttk.Label(top, text="  BP: —", style="Header.TLabel")
        self.lbl_buying_power.pack(side=tk.LEFT, padx=(12, 0))

        self.lbl_status = ttk.Label(top, text="  Status: —", style="Header.TLabel")
        self.lbl_status.pack(side=tk.LEFT, padx=(12, 0))

        self.lbl_daily_pnl = ttk.Label(top, text="  Day P/L: —", style="PL.TLabel")
        self.lbl_daily_pnl.pack(side=tk.LEFT, padx=(20, 0))

        self.lbl_drawdown = ttk.Label(top, text="  DD: —", style="Header.TLabel")
        self.lbl_drawdown.pack(side=tk.LEFT, padx=(12, 0))

        self.lbl_trading_status = ttk.Label(top, text="  ● READY", style="OK.TLabel")
        self.lbl_trading_status.pack(side=tk.LEFT, padx=(12, 0))

        self.btn_refresh = ttk.Button(top, text="↻ Refresh", command=self._on_refresh)
        self.btn_refresh.pack(side=tk.RIGHT, padx=4)

        scan_label = "▶ Scan + Execute" if settings.auto_execute else "▶ Scan for Trades"
        self.btn_scan = ttk.Button(top, text=scan_label, command=self._on_scan)
        self.btn_scan.pack(side=tk.RIGHT, padx=4)

        # Notebook
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self.tab_recs = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_recs, text="  Recommendations  ")
        self._build_recommendations_tab()

        self.tab_pos = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_pos, text="  Positions  ")
        self._build_positions_tab()

        self.tab_orders = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_orders, text="  Orders  ")
        self._build_orders_tab()

        self.tab_entry = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_entry, text="  Place Order  ")
        self._build_order_entry_tab()

        self.tab_risk = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_risk, text="  Risk Manager  ")
        self._build_risk_tab()

        self.tab_scorer = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_scorer, text="  Score Analysis  ")
        self._build_scorer_tab()

        # Log panel
        log_frame = ttk.LabelFrame(self, text="Log", padding=4)
        log_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=7, state=tk.DISABLED,
            font=("Consolas", 9), wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.X)
        self.log_text.tag_configure("warn",  foreground="#b45309")
        self.log_text.tag_configure("error", foreground="#dc2626")
        self.log_text.tag_configure("info",  foreground="#374151")

    # ── Recommendations tab ──────────────────────────────────────────

    def _build_recommendations_tab(self):
        cols = ("signal", "symbol", "price", "strength", "strategy", "reason")
        self.tree_recs = ttk.Treeview(
            self.tab_recs, columns=cols, show="headings", selectmode="browse",
        )
        for col, text, width, anchor in [
            ("signal",   "Signal",   60,  tk.CENTER),
            ("symbol",   "Symbol",   70,  tk.CENTER),
            ("price",    "Price",    90,  tk.E),
            ("strength", "Strength", 80,  tk.CENTER),
            ("strategy", "Strategy", 110, tk.CENTER),
            ("reason",   "Reason",   600, tk.W),
        ]:
            self.tree_recs.heading(col, text=text)
            self.tree_recs.column(col, width=width, anchor=anchor)

        self.tree_recs.tag_configure("buy",  foreground="#16a34a")
        self.tree_recs.tag_configure("sell", foreground="#dc2626")

        sb = ttk.Scrollbar(self.tab_recs, orient=tk.VERTICAL, command=self.tree_recs.yview)
        self.tree_recs.configure(yscrollcommand=sb.set)
        self.tree_recs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.recs_menu = tk.Menu(self, tearoff=0)
        self.recs_menu.add_command(label="Quick BUY 1 share",
                                   command=lambda: self._quick_trade(OrderSide.BUY))
        self.recs_menu.add_command(label="Quick SELL 1 share",
                                   command=lambda: self._quick_trade(OrderSide.SELL))
        self.recs_menu.add_separator()
        self.recs_menu.add_command(label="Send to Position Sizer",
                                   command=self._recs_to_sizer)
        self.tree_recs.bind("<Button-3>", self._on_recs_right_click)

    # ── Positions tab ────────────────────────────────────────────────

    def _build_positions_tab(self):
        cols = ("symbol", "qty", "side", "avg_entry", "current", "unrealized_pl", "pct")
        self.tree_pos = ttk.Treeview(
            self.tab_pos, columns=cols, show="headings", selectmode="browse",
        )
        for col, text, width, anchor in [
            ("symbol",       "Symbol",        80,  tk.CENTER),
            ("qty",          "Qty",           60,  tk.E),
            ("side",         "Side",          50,  tk.CENTER),
            ("avg_entry",    "Avg Entry",     90,  tk.E),
            ("current",      "Current",       90,  tk.E),
            ("unrealized_pl","Unrealised P/L",110, tk.E),
            ("pct",          "P/L %",         80,  tk.E),
        ]:
            self.tree_pos.heading(col, text=text)
            self.tree_pos.column(col, width=width, anchor=anchor)

        self.tree_pos.tag_configure("profit", foreground="#16a34a")
        self.tree_pos.tag_configure("loss",   foreground="#dc2626")

        sb = ttk.Scrollbar(self.tab_pos, orient=tk.VERTICAL, command=self.tree_pos.yview)
        self.tree_pos.configure(yscrollcommand=sb.set)
        self.tree_pos.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.pos_menu = tk.Menu(self, tearoff=0)
        self.pos_menu.add_command(label="Close Position", command=self._on_close_position)
        self.tree_pos.bind("<Button-3>", self._on_pos_right_click)

    # ── Orders tab ───────────────────────────────────────────────────

    def _build_orders_tab(self):
        cols = ("symbol", "side", "type", "qty", "filled", "price", "status", "submitted")
        self.tree_orders = ttk.Treeview(
            self.tab_orders, columns=cols, show="headings", selectmode="browse",
        )
        for col, text, width in [
            ("symbol",    "Symbol",    80),
            ("side",      "Side",      50),
            ("type",      "Type",      70),
            ("qty",       "Qty",       60),
            ("filled",    "Filled",    60),
            ("price",     "Price",     90),
            ("status",    "Status",    90),
            ("submitted", "Submitted", 160),
        ]:
            self.tree_orders.heading(col, text=text)
            self.tree_orders.column(col, width=width, anchor=tk.CENTER)

        sb = ttk.Scrollbar(self.tab_orders, orient=tk.VERTICAL, command=self.tree_orders.yview)
        self.tree_orders.configure(yscrollcommand=sb.set)
        self.tree_orders.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.orders_menu = tk.Menu(self, tearoff=0)
        self.orders_menu.add_command(label="Cancel Order", command=self._on_cancel_order)
        self.tree_orders.bind("<Button-3>", self._on_orders_right_click)

    # ── Order Entry tab ──────────────────────────────────────────────

    def _build_order_entry_tab(self):
        form = ttk.Frame(self.tab_entry, padding=16)
        form.pack(anchor=tk.NW)

        def lbl(text, r):
            ttk.Label(form, text=text, style="Header.TLabel").grid(
                row=r, column=0, sticky=tk.W, pady=4)

        row = 0
        lbl("Symbol:", row)
        self.entry_symbol = ttk.Entry(form, width=12)
        self.entry_symbol.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        lbl("Side:", row)
        self.entry_side = ttk.Combobox(form, values=["BUY", "SELL"], state="readonly", width=10)
        self.entry_side.set("BUY")
        self.entry_side.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        lbl("Order Type:", row)
        self.entry_type = ttk.Combobox(
            form,
            values=["Market", "Limit", "Stop", "Stop Limit", "Trailing Stop", "Bracket"],
            state="readonly", width=14,
        )
        self.entry_type.set("Market")
        self.entry_type.grid(row=row, column=1, sticky=tk.W, padx=8)
        self.entry_type.bind("<<ComboboxSelected>>", self._on_order_type_change)

        row += 1
        lbl("Qty:", row)
        self.entry_qty = ttk.Entry(form, width=12)
        self.entry_qty.insert(0, "1")
        self.entry_qty.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        self.lbl_limit = ttk.Label(form, text="Limit Price:", style="Header.TLabel")
        self.lbl_limit.grid(row=row, column=0, sticky=tk.W, pady=4)
        self.entry_limit = ttk.Entry(form, width=12)
        self.entry_limit.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        self.lbl_stop = ttk.Label(form, text="Stop Price:", style="Header.TLabel")
        self.lbl_stop.grid(row=row, column=0, sticky=tk.W, pady=4)
        self.entry_stop = ttk.Entry(form, width=12)
        self.entry_stop.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        self.lbl_trail = ttk.Label(form, text="Trail %:", style="Header.TLabel")
        self.lbl_trail.grid(row=row, column=0, sticky=tk.W, pady=4)
        self.entry_trail = ttk.Entry(form, width=12)
        self.entry_trail.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        self.lbl_tp = ttk.Label(form, text="Take Profit:", style="Header.TLabel")
        self.lbl_tp.grid(row=row, column=0, sticky=tk.W, pady=4)
        self.entry_tp = ttk.Entry(form, width=12)
        self.entry_tp.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        self.lbl_sl = ttk.Label(form, text="Stop Loss:", style="Header.TLabel")
        self.lbl_sl.grid(row=row, column=0, sticky=tk.W, pady=4)
        self.entry_sl = ttk.Entry(form, width=12)
        self.entry_sl.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        lbl("Time in Force:", row)
        self.entry_tif = ttk.Combobox(form, values=["DAY", "GTC", "IOC", "FOK"],
                                       state="readonly", width=10)
        self.entry_tif.set("DAY")
        self.entry_tif.grid(row=row, column=1, sticky=tk.W, padx=8)

        row += 1
        self.btn_submit_order = ttk.Button(form, text="Submit Order",
                                            command=self._on_submit_order)
        self.btn_submit_order.grid(row=row, column=0, columnspan=2, pady=16)

        self._on_order_type_change()

    def _on_order_type_change(self, _event=None):
        otype       = self.entry_type.get()
        limit_vis   = otype in ("Limit", "Stop Limit")
        stop_vis    = otype in ("Stop", "Stop Limit")
        trail_vis   = otype == "Trailing Stop"
        bracket_vis = otype == "Bracket"

        for widget in (self.lbl_limit, self.entry_limit):
            widget.grid() if limit_vis else widget.grid_remove()
        for widget in (self.lbl_stop, self.entry_stop):
            widget.grid() if stop_vis else widget.grid_remove()
        for widget in (self.lbl_trail, self.entry_trail):
            widget.grid() if trail_vis else widget.grid_remove()
        for widget in (self.lbl_tp, self.entry_tp, self.lbl_sl, self.entry_sl):
            widget.grid() if bracket_vis else widget.grid_remove()

    def _on_submit_order(self):
        symbol = self.entry_symbol.get().strip().upper()
        if not symbol:
            messagebox.showwarning("Validation", "Symbol is required.")
            return
        try:
            qty = float(self.entry_qty.get())
        except ValueError:
            messagebox.showwarning("Validation", "Qty must be a number.")
            return

        side  = OrderSide.BUY if self.entry_side.get() == "BUY" else OrderSide.SELL
        tif_m = {"DAY": TimeInForce.DAY, "GTC": TimeInForce.GTC,
                  "IOC": TimeInForce.IOC, "FOK": TimeInForce.FOK}
        tif   = tif_m.get(self.entry_tif.get(), TimeInForce.DAY)
        otype = self.entry_type.get()
        desc  = f"{otype.upper()} {side.value} {qty} {symbol}"

        if not messagebox.askyesno("Confirm Order", f"Submit order?\n\n{desc}"):
            return

        def work():
            try:
                if otype == "Market":
                    self.client.market_order(symbol, qty, side, tif)
                elif otype == "Limit":
                    self.client.limit_order(symbol, qty, side,
                                            float(self.entry_limit.get()), tif)
                elif otype == "Stop":
                    self.client.stop_order(symbol, qty, side,
                                           float(self.entry_stop.get()), tif)
                elif otype == "Stop Limit":
                    self.client.stop_limit_order(symbol, qty, side,
                                                  float(self.entry_stop.get()),
                                                  float(self.entry_limit.get()), tif)
                elif otype == "Trailing Stop":
                    self.client.trailing_stop_order(symbol, qty, side,
                                                    trail_percent=float(self.entry_trail.get()))
                elif otype == "Bracket":
                    self.client.bracket_order(symbol, qty, side,
                                              float(self.entry_tp.get()),
                                              float(self.entry_sl.get()),
                                              time_in_force=tif)
                trades_logger.info("ORDER SUBMITTED — %s", desc)
                logger.info("Order submitted: %s", desc)
                self.after(500, self._refresh_orders)
                self.after(1000, self._refresh_account)
            except Exception as e:
                logger.error("Order failed: %s", e)
                self.after(0, messagebox.showerror, "Order Error", str(e))

        threading.Thread(target=work, daemon=True).start()

    # ── Risk Manager tab ─────────────────────────────────────────────

    def _build_risk_tab(self):
        outer = ttk.Frame(self.tab_risk, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        # Left: config controls
        cfg_frame = ttk.LabelFrame(outer, text="Risk Parameters", padding=10)
        cfg_frame.grid(row=0, column=0, sticky=tk.NW, padx=(0, 20))

        param_defs = [
            ("Max Position % of Equity:",  "risk_max_pos",   "5.0"),
            ("Risk per Trade % of Equity:", "risk_per_trade", "1.0"),
            ("ATR Stop Multiplier:",        "risk_atr_mult",  "2.0"),
            ("Min Risk/Reward Ratio:",      "risk_rr",        "1.5"),
            ("Max Concurrent Positions:",   "risk_max_pos_n", "10"),
            ("Max Daily Loss %:",           "risk_daily_lim", "3.0"),
            ("Max Drawdown %:",             "risk_dd_lim",    "10.0"),
            ("Min Score Threshold (0-100):","risk_min_score", "62.0"),
            ("Min Buying Power $:",         "risk_min_bp",    "500.0"),
        ]
        self._risk_vars: dict[str, tk.StringVar] = {}
        for i, (label, key, default) in enumerate(param_defs):
            ttk.Label(cfg_frame, text=label, style="Header.TLabel").grid(
                row=i, column=0, sticky=tk.W, pady=3)
            var = tk.StringVar(value=default)
            self._risk_vars[key] = var
            ttk.Entry(cfg_frame, textvariable=var, width=10).grid(
                row=i, column=1, sticky=tk.W, padx=8)

        ttk.Button(cfg_frame, text="Apply Settings",
                   command=self._apply_risk_config).grid(
            row=len(param_defs), column=0, columnspan=2, pady=12)

        # Right: status panel
        status_frame = ttk.LabelFrame(outer, text="Portfolio Risk Status", padding=10)
        status_frame.grid(row=0, column=1, sticky=tk.NW)

        def stat_lbl(parent, row, label, init="—", style="Header.TLabel"):
            ttk.Label(parent, text=label, style="Header.TLabel").grid(
                row=row, column=0, sticky=tk.W, pady=4, padx=(0, 12))
            wid = ttk.Label(parent, text=init, style=style)
            wid.grid(row=row, column=1, sticky=tk.W)
            return wid

        self.lbl_risk_trading  = stat_lbl(status_frame, 0, "Trading Status:", "● READY", "OK.TLabel")
        self.lbl_risk_daily    = stat_lbl(status_frame, 1, "Daily P/L:")
        self.lbl_risk_drawdown = stat_lbl(status_frame, 2, "Drawdown:")
        self.lbl_risk_peak     = stat_lbl(status_frame, 3, "Peak Equity:")
        self.lbl_risk_limit    = stat_lbl(status_frame, 4, "Daily Loss Limit:")
        self.lbl_risk_ddlimit  = stat_lbl(status_frame, 5, "Max Drawdown Limit:")

        ttk.Label(status_frame, text="Daily Loss Used:", style="Header.TLabel").grid(
            row=6, column=0, sticky=tk.W, pady=4)
        self.bar_daily = ttk.Progressbar(status_frame, length=200, maximum=100)
        self.bar_daily.grid(row=6, column=1, sticky=tk.W)

        ttk.Label(status_frame, text="Drawdown Used:", style="Header.TLabel").grid(
            row=7, column=0, sticky=tk.W, pady=4)
        self.bar_drawdown = ttk.Progressbar(status_frame, length=200, maximum=100)
        self.bar_drawdown.grid(row=7, column=1, sticky=tk.W)

        ttk.Button(status_frame, text="↻ Refresh Risk Status",
                   command=self._update_risk_display).grid(
            row=8, column=0, columnspan=2, pady=10)

        # Bottom: position size calculator
        sizer_frame = ttk.LabelFrame(outer, text="Position Size Calculator", padding=10)
        sizer_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(16, 0))

        sizer_inputs = [
            ("Symbol",  "_sizer_sym_var",   "AAPL"),
            ("Price $", "_sizer_price_var", "150.00"),
            ("ATR $",   "_sizer_atr_var",   "3.50"),
        ]
        for col_idx, (label, attr, default) in enumerate(sizer_inputs):
            ttk.Label(sizer_frame, text=label, style="Header.TLabel").grid(
                row=0, column=col_idx * 2, padx=(0, 4))
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            ttk.Entry(sizer_frame, textvariable=var, width=10).grid(
                row=0, column=col_idx * 2 + 1, padx=(0, 12))

        ttk.Label(sizer_frame, text="Side", style="Header.TLabel").grid(
            row=0, column=6, padx=(0, 4))
        self._sizer_side_var = tk.StringVar(value="BUY")
        ttk.Combobox(sizer_frame, textvariable=self._sizer_side_var,
                     values=["BUY", "SELL"], state="readonly", width=8).grid(
            row=0, column=7, padx=(0, 12))

        ttk.Button(sizer_frame, text="Calculate",
                   command=self._run_sizer).grid(row=0, column=8, padx=8)

        self.lbl_sizer_result = ttk.Label(
            sizer_frame,
            text="Enter parameters and click Calculate.",
            font=("Consolas", 10), foreground="#374151")
        self.lbl_sizer_result.grid(row=1, column=0, columnspan=9, sticky=tk.W, pady=(8, 0))

    def _apply_risk_config(self):
        try:
            cfg = RiskConfig(
                max_position_pct    = float(self._risk_vars["risk_max_pos"].get()) / 100,
                risk_per_trade_pct  = float(self._risk_vars["risk_per_trade"].get()) / 100,
                atr_stop_multiplier = float(self._risk_vars["risk_atr_mult"].get()),
                min_risk_reward     = float(self._risk_vars["risk_rr"].get()),
                max_positions       = int(float(self._risk_vars["risk_max_pos_n"].get())),
                max_daily_loss_pct  = float(self._risk_vars["risk_daily_lim"].get()) / 100,
                max_drawdown_pct    = float(self._risk_vars["risk_dd_lim"].get()) / 100,
                min_score_threshold = float(self._risk_vars["risk_min_score"].get()),
                min_buying_power    = float(self._risk_vars["risk_min_bp"].get()),
            )
            prev_equity = self._current_equity
            self.risk_manager = RiskManager(cfg)
            if prev_equity > 0:
                self.risk_manager.set_session_equity(prev_equity)
                self.risk_manager.update_equity(prev_equity)
            logger.info("Risk config applied — %s", cfg)
            messagebox.showinfo("Risk Manager", "Risk settings applied successfully.")
        except (ValueError, TypeError) as e:
            messagebox.showerror("Validation Error", f"Invalid risk parameter: {e}")

    def _update_risk_display(self):
        eq      = self._current_equity
        summary = self.risk_manager.get_risk_summary(eq)

        daily_pnl     = summary["daily_pnl"]
        daily_pnl_pct = summary["daily_pnl_pct"]
        dd_pct        = summary["drawdown_pct"]
        peak          = summary["peak_equity"]
        allowed       = summary["trading_allowed"]
        sign          = "+" if daily_pnl >= 0 else ""
        colour        = "Green.TLabel" if daily_pnl >= 0 else "Red.TLabel"

        self.lbl_risk_daily.config(
            text=f"${daily_pnl:+,.2f}  ({sign}{daily_pnl_pct:.2%})",
            style=colour)
        self.lbl_risk_drawdown.config(text=f"{dd_pct:.2%}")
        self.lbl_risk_peak.config(text=f"${peak:,.2f}")
        self.lbl_risk_limit.config(
            text=f"{self.risk_manager.config.max_daily_loss_pct:.1%} of session start equity")
        self.lbl_risk_ddlimit.config(
            text=f"{self.risk_manager.config.max_drawdown_pct:.1%} of peak equity")

        self.bar_daily["value"]    = min(summary["daily_loss_used_pct"] * 100, 100)
        self.bar_drawdown["value"] = min(summary["drawdown_used_pct"] * 100, 100)

        self.lbl_risk_trading.config(
            text="● TRADING ALLOWED" if allowed else "● TRADING HALTED",
            style="OK.TLabel" if allowed else "Halt.TLabel")

        # Mirror to top bar
        self.lbl_daily_pnl.config(
            text=f"  Day P/L: ${daily_pnl:+,.2f} ({sign}{daily_pnl_pct:.2%})",
            style=colour)
        self.lbl_drawdown.config(text=f"  DD: {dd_pct:.2%}")
        self.lbl_trading_status.config(
            text="  ● READY" if allowed else "  ● HALTED",
            style="OK.TLabel" if allowed else "Halt.TLabel")

    def _run_sizer(self):
        try:
            sym   = self._sizer_sym_var.get().strip().upper() or "SYM"
            price = float(self._sizer_price_var.get())
            atr   = float(self._sizer_atr_var.get())
            side  = self._sizer_side_var.get()
            eq    = self._current_equity if self._current_equity > 0 else 100_000.0
        except ValueError:
            self.lbl_sizer_result.config(
                text="Invalid input — check Price and ATR fields.",
                foreground="#dc2626")
            return

        result = self.risk_manager.calculate_position_size(sym, price, atr, eq, side)
        colour = "#16a34a" if result.passes_risk else "#dc2626"
        self.lbl_sizer_result.config(text=result.summary(), foreground=colour)

    def _recs_to_sizer(self):
        sel = self.tree_recs.selection()
        if not sel:
            return
        values = self.tree_recs.item(sel[0], "values")
        self._sizer_sym_var.set(values[1])
        self._sizer_price_var.set(values[2].replace("$", "").replace(",", ""))
        self.notebook.select(self.tab_risk)
        logger.info("Position sizer pre-filled for %s", values[1])

    # ── Score Analysis tab ───────────────────────────────────────────

    def _build_scorer_tab(self):
        ctrl = ttk.Frame(self.tab_scorer, padding=8)
        ctrl.pack(fill=tk.X)

        ttk.Label(ctrl, text="Symbols (comma-separated, blank = screener):",
                  style="Header.TLabel").pack(side=tk.LEFT)
        self.scorer_symbols_var = tk.StringVar(
            value="AAPL,MSFT,AMZN,NVDA,GOOGL,META,TSLA,JPM,V,MA")
        ttk.Entry(ctrl, textvariable=self.scorer_symbols_var, width=55).pack(
            side=tk.LEFT, padx=8)
        self.btn_score = ttk.Button(
            ctrl, text="▶ Run Scorer", command=self._on_run_scorer)
        self.btn_score.pack(side=tk.LEFT, padx=4)

        cols = ("signal", "symbol", "price", "score", "regime",
                "trend", "momentum", "volume", "volatility", "pa",
                "risk_pct", "hv", "confidence")
        self.tree_scorer = ttk.Treeview(
            self.tab_scorer, columns=cols, show="headings", selectmode="browse",
        )
        col_defs = [
            ("signal",     "Signal",     58),
            ("symbol",     "Symbol",     70),
            ("price",      "Price",      80),
            ("score",      "Score",      60),
            ("regime",     "Regime",     130),
            ("trend",      "Trend",      50),
            ("momentum",   "Mom.",       50),
            ("volume",     "Vol.",       50),
            ("volatility", "Vola.",      50),
            ("pa",         "PA",         50),
            ("risk_pct",   "Risk%/day",  80),
            ("hv",         "HV20%",      65),
            ("confidence", "Confidence", 90),
        ]
        for col, text, width in col_defs:
            self.tree_scorer.heading(col, text=text,
                                     command=lambda c=col: self._sort_scorer(c))
            self.tree_scorer.column(col, width=width, anchor=tk.CENTER)

        self.tree_scorer.tag_configure("buy",  foreground="#16a34a")
        self.tree_scorer.tag_configure("sell", foreground="#dc2626")
        self.tree_scorer.tag_configure("hold", foreground="#6b7280")

        sb_v = ttk.Scrollbar(self.tab_scorer, orient=tk.VERTICAL,
                              command=self.tree_scorer.yview)
        sb_h = ttk.Scrollbar(self.tab_scorer, orient=tk.HORIZONTAL,
                              command=self.tree_scorer.xview)
        self.tree_scorer.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
        sb_v.pack(side=tk.RIGHT, fill=tk.Y)
        sb_h.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_scorer.pack(fill=tk.BOTH, expand=True)

        self._scorer_sort_col = "score"
        self._scorer_sort_rev = True

        self.scorer_menu = tk.Menu(self, tearoff=0)
        self.scorer_menu.add_command(label="Send to Position Sizer",
                                     command=self._scorer_to_sizer)
        self.tree_scorer.bind("<Button-3>", self._on_scorer_right_click)

    def _on_run_scorer(self):
        raw     = self.scorer_symbols_var.get().strip()
        symbols = [s.strip().upper() for s in raw.split(",") if s.strip()] if raw else None

        self._set_busy(True, "Scoring...")
        self.btn_score.config(state=tk.DISABLED)

        def work():
            try:
                engine = ScoringEngine()
                if not symbols:
                    from strategies.screener import StockScreener
                    screener = StockScreener(self.client)
                    syms = screener.screen()
                else:
                    syms = symbols

                logger.info("Running ScoringEngine on %d symbols...", len(syms))
                frames = load_bars(self.client, syms, TimeFrame.Day, limit=250)
                results: list[StockScore] = []
                for sym, df in frames.items():
                    if df.empty or len(df) < 60:
                        continue
                    try:
                        enriched = engine.prepare(df)
                        score    = engine.score(enriched, sym)
                        results.append(score)
                    except Exception as exc:
                        logger.warning("Scorer failed on %s: %s", sym, exc)

                results.sort(key=lambda s: s.composite, reverse=True)
                self._scores = results
                self.after(0, self._populate_scores, results)
            except Exception as e:
                logger.error("Scorer run failed: %s", e)
            finally:
                self.after(0, self._set_busy, False)
                self.after(0, lambda: self.btn_score.config(state=tk.NORMAL))

        threading.Thread(target=work, daemon=True).start()

    def _populate_scores(self, scores: list[StockScore]):
        self.tree_scorer.delete(*self.tree_scorer.get_children())
        for s in scores:
            tag   = s.signal.value.lower()
            arrow = {"BUY": "▲", "SELL": "▼", "HOLD": "—"}.get(s.signal.value, "?")
            self.tree_scorer.insert("", tk.END, values=(
                f"{arrow} {s.signal.value}",
                s.symbol,
                f"${s.price:,.2f}",
                f"{s.composite:.1f}",
                s.regime,
                f"{s.trend:.0f}",
                f"{s.momentum:.0f}",
                f"{s.volume:.0f}",
                f"{s.volatility:.0f}",
                f"{s.price_action:.0f}",
                f"{s.risk_pct:.1f}%",
                f"{s.hv_20:.0f}%",
                s.confidence,
            ), tags=(tag,))
        self.notebook.select(self.tab_scorer)
        logger.info("Score analysis complete — %d stocks scored", len(scores))

    def _sort_scorer(self, col: str):
        reverse = (self._scorer_sort_col == col and not self._scorer_sort_rev)
        self._scorer_sort_col = col
        self._scorer_sort_rev = reverse

        data = [(self.tree_scorer.set(iid, col), iid)
                for iid in self.tree_scorer.get_children()]

        def _key(x):
            raw = x[0].replace("$", "").replace("%", "").replace(",", "")
            raw = raw.split()[-1] if raw.split() else raw
            try:
                return float(raw)
            except ValueError:
                return raw

        data.sort(key=_key, reverse=reverse)
        for idx, (_, iid) in enumerate(data):
            self.tree_scorer.move(iid, "", idx)

    def _on_scorer_right_click(self, event):
        row = self.tree_scorer.identify_row(event.y)
        if row:
            self.tree_scorer.selection_set(row)
            self.scorer_menu.post(event.x_root, event.y_root)

    def _scorer_to_sizer(self):
        sel = self.tree_scorer.selection()
        if not sel:
            return
        vals  = self.tree_scorer.item(sel[0], "values")
        sym   = vals[1]
        price = vals[2].replace("$", "").replace(",", "")
        # Derive ATR from risk_pct × price (risk_pct already stored as daily %)
        atr_val = ""
        for s in self._scores:
            if s.symbol == sym and s.risk_pct > 0 and s.price > 0:
                atr_val = f"{s.risk_pct / 100 * s.price:.2f}"
                break
        self._sizer_sym_var.set(sym)
        self._sizer_price_var.set(price)
        if atr_val:
            self._sizer_atr_var.set(atr_val)
        self.notebook.select(self.tab_risk)

    # ── Logging setup ────────────────────────────────────────────────

    def _setup_logging(self):
        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(handler)

    # ── Data refresh helpers ─────────────────────────────────────────

    def _initial_refresh(self):
        def work():
            self._refresh_account()
            self._refresh_positions()
            self._refresh_orders()
        threading.Thread(target=work, daemon=True).start()

    def _refresh_account(self):
        try:
            acct   = self.client.get_account()
            equity = float(acct.equity)
            bp     = float(acct.buying_power)
            self._current_equity = equity
            self.risk_manager.set_session_equity(equity)
            self.risk_manager.update_equity(equity)

            def _update():
                self.lbl_equity.config(text=f"Equity: ${equity:,.2f}")
                self.lbl_buying_power.config(text=f"  BP: ${bp:,.2f}")
                self.lbl_status.config(text=f"  Status: {acct.status}")
                self._update_risk_display()
            self.after(0, _update)
        except Exception as e:
            logger.error("Failed to refresh account: %s", e)

    def _refresh_positions(self):
        try:
            positions = self.client.get_positions()
            def _update():
                self.tree_pos.delete(*self.tree_pos.get_children())
                for p in positions:
                    pl  = float(p.unrealized_pl)
                    pct = float(p.unrealized_plpc) * 100
                    tag = "profit" if pl >= 0 else "loss"
                    self.tree_pos.insert("", tk.END, values=(
                        p.symbol, p.qty, p.side,
                        f"${float(p.avg_entry_price):,.2f}",
                        f"${float(p.current_price):,.2f}",
                        f"${pl:,.2f}",
                        f"{pct:+.2f}%",
                    ), tags=(tag,))
            self.after(0, _update)
        except Exception as e:
            logger.error("Failed to refresh positions: %s", e)

    def _refresh_orders(self):
        try:
            orders = self.client.get_orders()
            def _update():
                self.tree_orders.delete(*self.tree_orders.get_children())
                self._order_ids.clear()
                for o in orders:
                    price = ""
                    if o.limit_price:
                        price = f"${float(o.limit_price):,.2f}"
                    elif o.filled_avg_price:
                        price = f"${float(o.filled_avg_price):,.2f}"
                    submitted = str(o.submitted_at)[:19] if o.submitted_at else ""
                    iid = self.tree_orders.insert("", tk.END, values=(
                        o.symbol, o.side, o.type, o.qty,
                        o.filled_qty or 0, price, o.status, submitted,
                    ))
                    self._order_ids[iid] = str(o.id)
            self.after(0, _update)
        except Exception as e:
            logger.error("Failed to refresh orders: %s", e)

    # ── Button handlers ──────────────────────────────────────────────

    def _on_refresh(self):
        self._set_busy(True, "Refreshing...")
        def work():
            try:
                self._refresh_account()
                self._refresh_positions()
                self._refresh_orders()
                logger.info("Dashboard refreshed")
            finally:
                self.after(0, self._set_busy, False)
        threading.Thread(target=work, daemon=True).start()

    def _on_scan(self):
        self._set_busy(True, "Scanning...")
        def work():
            try:
                scanner = StrategyScanner(
                    client=self.client,
                    strategies=[MomentumStrategy(), MeanReversionStrategy()],
                    universe_mode=settings.universe_mode,
                    universe_cache_ttl=settings.universe_cache_ttl,
                )
                recs = scanner.scan()
                self.after(0, self._populate_recommendations, recs)

                # Auto-execution (only when AUTO_EXECUTE=true in .env)
                if settings.auto_execute and recs:
                    logger.info("AUTO_EXECUTE enabled — passing to ExecutionEngine")
                    engine = ExecutionEngine(
                        client=self.client,
                        risk_manager=self.risk_manager,
                        max_orders=settings.max_orders_per_scan,
                        require_market_open=True,
                    )
                    summary = engine.execute(recs)
                    self.after(0, self._on_execution_complete, summary)

            except Exception as e:
                logger.error("Scan failed: %s", e)
            finally:
                self.after(0, self._set_busy, False)
        threading.Thread(target=work, daemon=True).start()

    def _on_execution_complete(self, summary):
        """Update UI after ExecutionEngine finishes (called on main thread)."""
        if summary.any_placed:
            logger.info("Auto-executed: %s", summary)
            # Refresh positions and orders after a short delay (orders need time to propagate)
            self.after(1500, self._refresh_positions)
            self.after(1500, self._refresh_orders)
            self.after(1500, self._refresh_account)
        elif summary.errors:
            logger.error("Execution errors: %s", summary.errors)
        else:
            logger.info("Auto-execute: no orders placed (%s blocked, %s skipped)",
                        len(summary.blocked), len(summary.skipped))

    def _populate_recommendations(self, recs: list[Recommendation]):
        self._recommendations = recs
        self.tree_recs.delete(*self.tree_recs.get_children())
        for rec in recs:
            tag = "buy" if rec.signal.value == "BUY" else "sell"
            self.tree_recs.insert("", tk.END, values=(
                rec.signal.value, rec.symbol,
                f"${rec.price:,.2f}", f"{rec.strength:.0%}",
                rec.strategy, rec.reason,
            ), tags=(tag,))
        self.notebook.select(self.tab_recs)
        logger.info("Displayed %d recommendations", len(recs))

    # ── Quick trade (risk-gated) ──────────────────────────────────────

    def _on_recs_right_click(self, event):
        row = self.tree_recs.identify_row(event.y)
        if row:
            self.tree_recs.selection_set(row)
            self.recs_menu.post(event.x_root, event.y_root)

    def _quick_trade(self, side: OrderSide):
        sel = self.tree_recs.selection()
        if not sel:
            return
        values = self.tree_recs.item(sel[0], "values")
        symbol = values[1]

        # Run portfolio risk gate synchronously before confirming
        try:
            positions    = self.client.get_positions()
            acct         = self.client.get_account()
            equity       = float(acct.equity)
            buying_power = float(acct.buying_power)
        except Exception as e:
            messagebox.showerror("Risk Check Failed", str(e))
            return

        gate = self.risk_manager.check_portfolio_limits(
            len(positions), equity, buying_power)
        if not gate.allowed:
            messagebox.showwarning(
                "Risk Manager — Trade Blocked",
                f"This trade was blocked by the risk manager:\n\n{gate.reason}")
            return

        if not messagebox.askyesno(
            "Confirm Trade",
            f"Submit MARKET {side.value} 1 share of {symbol}?\n\n"
            f"Risk check: PASSED  "
            f"({len(positions)}/{self.risk_manager.config.max_positions} positions open)",
        ):
            return

        def work():
            try:
                self.client.market_order(symbol, qty=1, side=side,
                                         time_in_force=TimeInForce.DAY)
                trades_logger.info("QUICK TRADE — %s 1x %s", side.value, symbol)
                logger.info("Quick trade: %s 1x %s", side.value, symbol)
                self.after(500,  self._refresh_orders)
                self.after(1000, self._refresh_positions)
                self.after(1000, self._refresh_account)
            except Exception as e:
                logger.error("Quick trade failed: %s", e)
                self.after(0, messagebox.showerror, "Trade Error", str(e))

        threading.Thread(target=work, daemon=True).start()

    # ── Position context menu ─────────────────────────────────────────

    def _on_pos_right_click(self, event):
        row = self.tree_pos.identify_row(event.y)
        if row:
            self.tree_pos.selection_set(row)
            self.pos_menu.post(event.x_root, event.y_root)

    def _on_close_position(self):
        sel = self.tree_pos.selection()
        if not sel:
            return
        symbol = self.tree_pos.item(sel[0], "values")[0]
        if not messagebox.askyesno("Close Position",
                                   f"Close entire position in {symbol}?"):
            return
        def work():
            try:
                # Fetch position details for P/L before closing
                positions = self.client.get_positions()
                pos = next((p for p in positions if p.symbol == symbol), None)

                self.client.close_position(symbol)
                trades_logger.info("CLOSE POSITION — %s", symbol)
                logger.info("Closed position: %s", symbol)

                # Journal the exit
                if pos is not None:
                    from datetime import datetime, timezone
                    current_price = float(pos.current_price)
                    qty = int(float(pos.qty))
                    avg_entry = float(pos.avg_entry_price)
                    pnl = (current_price - avg_entry) * qty

                    meta = self._position_store.get(symbol)
                    hold_hours = 0.0
                    entry_order_id = ""
                    strategy = "manual"
                    if meta:
                        entry_order_id = meta.get("order_id", "")
                        strategy = meta.get("strategy", "manual")
                        entry_time_str = meta.get("entry_time", "")
                        if entry_time_str:
                            try:
                                entry_time = datetime.fromisoformat(entry_time_str)
                                hold_hours = (
                                    datetime.now(timezone.utc) - entry_time
                                ).total_seconds() / 3600
                            except (ValueError, TypeError):
                                pass

                    self._trade_journal.record_exit(
                        symbol=symbol,
                        qty=qty,
                        price=current_price,
                        strategy=strategy,
                        reason="manual_gui_close",
                        pnl=pnl,
                        hold_duration_hours=hold_hours,
                        entry_order_id=entry_order_id,
                    )
                    self._position_store.remove(symbol)

                self.after(500, self._refresh_positions)
                self.after(500, self._refresh_account)
            except Exception as e:
                logger.error("Failed to close position %s: %s", symbol, e)
                self.after(0, messagebox.showerror, "Error", str(e))
        threading.Thread(target=work, daemon=True).start()

    # ── Orders context menu ───────────────────────────────────────────

    def _on_orders_right_click(self, event):
        row = self.tree_orders.identify_row(event.y)
        if row:
            self.tree_orders.selection_set(row)
            self.orders_menu.post(event.x_root, event.y_root)

    def _on_cancel_order(self):
        sel = self.tree_orders.selection()
        if not sel:
            return
        values   = self.tree_orders.item(sel[0], "values")
        symbol   = values[0]
        order_id = self._order_ids.get(sel[0])
        if not order_id:
            messagebox.showwarning("Error", "Could not find order ID.")
            return
        if not messagebox.askyesno("Cancel Order",
                                   f"Cancel open order for {symbol}?"):
            return
        def work():
            try:
                self.client.cancel_order(order_id)
                trades_logger.info("ORDER CANCELLED — %s (id=%s)", symbol, order_id)
                logger.info("Cancelled order for %s", symbol)
                self.after(500, self._refresh_orders)
                self.after(500, self._refresh_account)
            except Exception as e:
                logger.error("Failed to cancel order: %s", e)
                self.after(0, messagebox.showerror, "Error", str(e))
        threading.Thread(target=work, daemon=True).start()

    # ── UI helpers ───────────────────────────────────────────────────

    def _set_busy(self, busy: bool, text: str = ""):
        if busy:
            self.btn_scan.config(state=tk.DISABLED, text=text or "Working...")
            self.btn_refresh.config(state=tk.DISABLED)
        else:
            self.btn_scan.config(state=tk.NORMAL, text="▶ Scan for Trades")
            self.btn_refresh.config(state=tk.NORMAL)
