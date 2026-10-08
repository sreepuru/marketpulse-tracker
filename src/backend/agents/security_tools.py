from __future__ import annotations

import re
from typing import Any


def norm(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).upper().replace("&", " AND ")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", value)).strip()


def search_security_by_symbol(conn, symbol: str, exchange: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    s = norm(symbol).replace(" ", "")
    if not s:
        return []
    sql = """
        SELECT security_id, instrument_name, symbol, nse_symbol, bse_symbol,
               exchange, exchange_tag, isin, bse_scrip_code,
               asset_category, instrument_type, security_category, is_active
        FROM security_master
        WHERE is_active = TRUE
          AND (%s IN (UPPER(COALESCE(symbol,'')), UPPER(COALESCE(nse_symbol,'')), UPPER(COALESCE(bse_symbol,''))))
        ORDER BY security_id
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (s, int(limit)))
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    result = [dict(zip(cols, row)) for row in rows]
    return _filter_exchange(result, exchange)


def search_security_by_name(conn, name: str, exchange: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    n = norm(name)
    if not n:
        return []
    sql = """
        SELECT security_id, instrument_name, symbol, nse_symbol, bse_symbol,
               nse_name, nse_short_name, nse_alias,
               bse_name, bse_short_name, bse_alias, bse_scrip_code,
               exchange, exchange_tag, isin, asset_category,
               instrument_type, security_category, is_active
        FROM security_master
        WHERE is_active = TRUE
          AND (
            UPPER(regexp_replace(COALESCE(instrument_name,''), '[^A-Za-z0-9]+', ' ', 'g')) = %s
            OR UPPER(regexp_replace(COALESCE(nse_name,''), '[^A-Za-z0-9]+', ' ', 'g')) = %s
            OR UPPER(regexp_replace(COALESCE(bse_name,''), '[^A-Za-z0-9]+', ' ', 'g')) = %s
          )
        ORDER BY security_id
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (n, n, n, int(limit)))
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    result = [dict(zip(cols, row)) for row in rows]
    return _filter_exchange(result, exchange)


def _filter_exchange(rows: list[dict[str, Any]], exchange: str | None) -> list[dict[str, Any]]:
    if not exchange:
        return rows
    ex = exchange.upper().strip()
    return [r for r in rows if str(r.get("exchange") or "").upper() == ex or str(r.get("exchange_tag") or "").upper() in {ex, "BOTH"}]
