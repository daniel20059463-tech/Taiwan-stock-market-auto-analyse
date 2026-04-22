from institutional_flow_provider import (
    InstitutionalFlowProvider,
    InstitutionalFlowRow,
    parse_tpex_daily_trade_payload,
    parse_twse_t86_payload,
)


def test_parse_twse_t86_payload_extracts_foreign_and_trust_for_four_digit_stocks_only() -> None:
    payload = {
        "data": [
            [
                "2330",
                "台積電",
                "12,000",
                "8,000",
                "4,000",
                "0",
                "0",
                "0",
                "3,000",
                "1,000",
                "2,000",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "6,000",
            ],
            [
                "00940",
                "元大台灣價值高息",
                "1,000",
                "2,000",
                "-1,000",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "-1,000",
            ],
        ]
    }

    rows = parse_twse_t86_payload(payload)

    assert rows == [
        InstitutionalFlowRow(
            symbol="2330",
            name="台積電",
            foreign_net_buy=4000,
            investment_trust_net_buy=2000,
            major_net_buy=0,
        )
    ]


def test_parse_tpex_daily_trade_payload_extracts_four_digit_stock_rows_only() -> None:
    payload = {
        "tables": [
            {
                "data": [
                    ["代號", "名稱", "外資買進", "外資賣出", "外資買賣超", "x", "x", "x", "x", "x", "x", "投信買進", "投信賣出", "投信買賣超"],
                    ["3324", "雙鴻", "100", "50", "50", "0", "0", "0", "100", "50", "50", "500", "200", "300"],
                    ["00679B", "元大美債20年", "368,151", "17,784,000", "-17,415,849", "0", "0", "0", "368,151", "17,784,000", "-17,415,849", "0", "0", "0"],
                ]
            }
        ]
    }

    rows = parse_tpex_daily_trade_payload(payload)

    assert rows == [
        InstitutionalFlowRow(
            symbol="3324",
            name="雙鴻",
            foreign_net_buy=50,
            investment_trust_net_buy=300,
            major_net_buy=0,
        )
    ]


def test_provider_combines_twse_and_tpex_rows() -> None:
    provider = InstitutionalFlowProvider()
    provider._fetch_twse_payload = lambda: {  # type: ignore[method-assign]
        "data": [["2330", "台積電", "12,000", "8,000", "4,000", "0", "0", "0", "3,000", "1,000", "2,000", "0", "0", "0", "0", "0", "0", "0", "6,000"]]
    }
    provider._fetch_tpex_payload = lambda: {  # type: ignore[method-assign]
        "tables": [
            {
                "data": [
                    ["代號", "名稱"],
                    ["3324", "雙鴻", "100", "50", "50", "0", "0", "0", "100", "50", "50", "500", "200", "300"],
                ]
            }
        ]
    }

    rows = provider.fetch_rank_rows()

    assert rows == [
        InstitutionalFlowRow(
            symbol="2330",
            name="台積電",
            foreign_net_buy=4000,
            investment_trust_net_buy=2000,
            major_net_buy=0,
        ),
        InstitutionalFlowRow(
            symbol="3324",
            name="雙鴻",
            foreign_net_buy=50,
            investment_trust_net_buy=300,
            major_net_buy=0,
        ),
    ]
