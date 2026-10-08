from agents.marketpulse_mapping_agent_v2_2 import (
    IDENTITY_COMPANY_NAME,
    IdentityGroup,
    Security,
    build_indexes,
    distinctive_tokens,
    retrieve_candidates,
)


class _EmptyCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchall(self):
        return []


class _EmptyConnection:
    def cursor(self):
        return _EmptyCursor()


def _security(
    security_id: int,
    instrument_name: str,
) -> Security:
    return Security(
        security_id=security_id,
        isin=None,
        symbol=None,
        instrument_name=instrument_name,
        exchange="NSE",
        nse_symbol=None,
        nse_name=None,
        nse_short_name=None,
        nse_alias=None,
        bse_symbol=None,
        bse_name=None,
        bse_short_name=None,
        bse_alias=None,
        bse_scrip_code=None,
        exchange_tag="NSE",
        asset_category="EQUITY",
        is_active=True,
    )


def test_dme_company_name_has_only_dme_as_distinctive_token():
    tokens = distinctive_tokens(
        "Dme Development Limited",
        IDENTITY_COMPANY_NAME,
    )

    assert tokens == ("DME",)


def test_dme_does_not_generate_development_token_candidates():
    securities = [
        _security(757, "DEE DEVELOPMENT ENG LTD"),
        _security(924, "ENERGY DEVE. CO.LTD"),
        _security(1236, "GUJARAT MINERAL DEV CORP"),
        _security(1341, "HOUSING DEV & INFRA LTD"),
        _security(1346, "HSG & URBAN DEV CORPN LTD"),
        _security(1433, "INDIA TOUR. DEV. CO. LTD."),
        _security(1757, "LANDMARK PR.DEV.CO.LTD"),
        _security(2243, "ORISSA MIN DEV CO LTD"),
    ]

    indexes = build_indexes(securities)

    group = IdentityGroup(
        group_key="NSE|DME DEVELOPMENT LIMITED||",
        company_name="Dme Development Limited",
        normalized_name="DME DEVELOPMENT LIMITED",
        exchange="NSE",
        symbol="",
        isin="",
        news_ids=(6,),
        sample_title="Dme Development Limited",
    )

    candidates = retrieve_candidates(
        conn=_EmptyConnection(),
        group=group,
        indexes=indexes,
        max_candidates=20,
    )

    assert candidates == []