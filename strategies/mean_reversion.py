# strategies/mean_reversion.py
import pandas as pd
import pandas_ta as ta
from loguru import logger
from config.settings import MR_BOLLINGER_PERIOD, MR_BOLLINGER_STD, MR_MIN_SQUEEZE_PCT, MAX_CAPITAL_PER_TRADE, INDICES
from utils.option_chain import get_best_option
from utils.paper_engine import PaperEngine


class MeanReversionStrategy:
    NAME = "MeanReversion"

    def __init__(self, kite, paper_engine: PaperEngine):
        self.kite = kite
        self.engine = paper_engine

    def generate_signal(self, index: str, df: pd.DataFrame) -> str:
        if len(df) < MR_BOLLINGER_PERIOD + 5:
            return "NONE"
        df = df.copy()
        bb = ta.bbands(df["close"], length=MR_BOLLINGER_PERIOD, std=MR_BOLLINGER_STD)
        # pandas-ta generates a double-suffix when std is float: BBU_20_2.0_2.0
        std_str = f"{float(MR_BOLLINGER_STD)}"
        bb_prefix = f"{MR_BOLLINGER_PERIOD}_{std_str}"
        # find actual column names dynamically to avoid version mismatch
        upper_col = next(c for c in bb.columns if c.startswith(f"BBU_{bb_prefix}"))
        lower_col = next(c for c in bb.columns if c.startswith(f"BBL_{bb_prefix}"))
        mid_col   = next(c for c in bb.columns if c.startswith(f"BBM_{bb_prefix}"))
        df["bb_upper"] = bb[upper_col]
        df["bb_lower"] = bb[lower_col]
        df["bb_mid"]   = bb[mid_col]
        df["rsi"]      = ta.rsi(df["close"], length=9)
        last = df.iloc[-1]
        band_width  = (last["bb_upper"] - last["bb_lower"]) / last["bb_mid"]
        is_squeeze  = band_width < MR_MIN_SQUEEZE_PCT
        touched_lower  = last["close"] <= last["bb_lower"] * 1.002
        touched_upper  = last["close"] >= last["bb_upper"] * 0.998
        rsi_oversold   = last["rsi"] < 38
        rsi_overbought = last["rsi"] > 62
        signal = "NONE"
        if is_squeeze and touched_lower and rsi_oversold:
            signal = "BUY_CE"
            logger.info(f"[{index}] MeanRev: Lower band touch + RSI={last['rsi']:.1f} | BUY_CE | BW={band_width:.4f}")
        elif is_squeeze and touched_upper and rsi_overbought:
            signal = "BUY_PE"
            logger.info(f"[{index}] MeanRev: Upper band touch + RSI={last['rsi']:.1f} | BUY_PE | BW={band_width:.4f}")
        return signal

    def execute(self, index: str, signal: str, spot_price: float):
        if signal == "NONE":
            return
        option_type = "CE" if signal == "BUY_CE" else "PE"
        idx_cfg = INDICES[index]
        option = get_best_option(
            kite=self.kite, index=index, spot_price=spot_price,
            option_type=option_type,
            max_premium=(MAX_CAPITAL_PER_TRADE * 0.7) / idx_cfg["lot_size"],
            otm_offset=1,
        )
        if option is None:
            logger.warning(f"[{index}] MeanRev: No suitable option found")
            return
        lots = max(1, int((MAX_CAPITAL_PER_TRADE * 0.7) / (option["ltp"] * idx_cfg["lot_size"])))
        self.engine.enter_trade(
            symbol=option["symbol"], index=index, option_type=option_type,
            strike=option["strike"], expiry=option["expiry"],
            lots=lots, lot_size=idx_cfg["lot_size"], strategy=self.NAME,
        )
