import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is in path
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TestIntegrity")

def test_mt5():
    logger.info("--- Testing MT5 Connection ---")
    import MetaTrader5 as mt5
    if not mt5.initialize():
        logger.error(f"MT5 Init failed: {mt5.last_error()}")
        return False
    info = mt5.terminal_info()
    logger.info(f"MT5 connected. Build: {info.build}")
    
    # Test Data Fetching
    rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 100)
    if rates is None or len(rates) == 0:
        logger.error("Failed to fetch XAUUSD rates.")
        return False
    logger.info(f"Successfully fetched {len(rates)} candles for XAUUSD.")
    return True

def test_pure_hmm():
    logger.info("--- Testing Pure HMM (Regime Detection) ---")
    try:
        from simulation.ml_models.pure_hmm import GaussianHMM
        import numpy as np
        # Dummy data: 100 samples, 3 features
        X = np.random.randn(100, 3)
        model = GaussianHMM(n_states=3, n_iter=10)
        model.fit(X)
        states = model.predict(X)
        logger.info(f"Pure HMM trained successfully. States output length: {len(states)}")
        return True
    except Exception as e:
        logger.error(f"Pure HMM test failed: {e}")
        return False

def test_ml_signal():
    logger.info("--- Testing ML Signal Classifier (LightGBM fallback) ---")
    try:
        from core.ml_signal import SignalClassifier, build_features
        clf = SignalClassifier(model_path="data/ml_models/dummy_not_exist.pkl")
        features = build_features(rsi=45, atr=3.5, ema=2000, price=2005, spread=30, tick_imbalance=0.1, hour=14, weekday=2)
        score = clf.predict(features)
        logger.info(f"ML Signal prediction fallback (should be 0.5): {score}")
        return score == 0.5
    except Exception as e:
        logger.error(f"ML Signal test failed: {e}")
        return False

def test_market_context():
    logger.info("--- Testing Market Context (yfinance APIs) ---")
    try:
        from simulation.api_clients.market_context import MarketContext
        ctx = MarketContext()
        ctx._mkt_data.update()
        bias = ctx.get_bias_summary()
        logger.info(f"Market Bias Summary: {bias}")
        return True
    except Exception as e:
        logger.error(f"Market Context test failed: {e}")
        return False

def main():
    logger.info("Starting System Integrity Test...")
    tests = [
        ("MT5 Connection", test_mt5),
        ("Pure HMM", test_pure_hmm),
        ("ML Signal Fallback", test_ml_signal),
        ("Market Context", test_market_context)
    ]
    
    passed = 0
    for name, func in tests:
        if func():
            logger.info(f"✅ {name} PASSED\n")
            passed += 1
        else:
            logger.error(f"❌ {name} FAILED\n")
            
    logger.info(f"Test Summary: {passed}/{len(tests)} passed.")
    if passed == len(tests):
        logger.info("All tests passed successfully! System is robust.")
        sys.exit(0)
    else:
        logger.error("Some tests failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
