import json

from auraorderflow.data.binance import BinanceProvider


def _provider():
    return BinanceProvider(["BTCUSDT"])


def test_parse_aggtrade_sell_maps_to_sell_side():
    raw = json.dumps(
        {
            "stream": "btcusdt@aggTrade",
            "data": {
                "e": "aggTrade",
                "s": "BTCUSDT",
                "p": "100.5",
                "q": "2",
                "m": True,  # buyer is maker -> aggressive SELL
                "T": 1700000000000,
            },
        }
    )
    kind, payload = _provider()._parse(raw)
    assert kind == "trade"
    assert payload.symbol == "BTCUSDT"
    assert payload.price == 100.5 and payload.qty == 2.0
    assert payload.is_buyer_maker is True and payload.is_buy is False


def test_parse_aggtrade_buy_side():
    raw = json.dumps(
        {"data": {"e": "aggTrade", "s": "ETHUSDT", "p": "10", "q": "1",
                  "m": False, "T": 1}}
    )
    _, payload = _provider()._parse(raw)
    assert payload.is_buy is True and payload.signed_qty == 1.0


def test_parse_depth_snapshot():
    raw = json.dumps(
        {
            "stream": "btcusdt@depth20@100ms",
            "data": {
                "e": "depthUpdate",
                "s": "BTCUSDT",
                "T": 1,
                "b": [["99", "5"], ["98", "0"]],   # zero-qty level dropped
                "a": [["100", "3"]],
            },
        }
    )
    kind, book = _provider()._parse(raw)
    assert kind == "book"
    assert book.best_bid == 99.0 and book.best_ask == 100.0
    assert len(book.bids) == 1  # the 0-qty level is filtered out


def test_parse_ignores_unknown():
    assert _provider()._parse('{"data": {"e": "kline"}}') is None
    assert _provider()._parse("not-json") is None
