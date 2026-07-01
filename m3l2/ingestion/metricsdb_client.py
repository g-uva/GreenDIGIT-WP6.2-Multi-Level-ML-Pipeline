from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from m3l2.app.config import get_settings

FACTS_TABLE = os.getenv("M3L2_FACTS_TABLE", "facts")
CLOUD_DETAIL_TABLE = os.getenv("M3L2_CLOUD_DETAIL_TABLE", "cloud_details")
NETWORK_DETAIL_TABLE = os.getenv("M3L2_NETWORK_DETAIL_TABLE", "network_details")

RAW_FIELD_CANDIDATES = [
    "ExecUnitID",
    "exec_unit_id",
    "Site",
    "site",
    "site_name",
    "Energy_wh",
    "energy_wh",
    "Work",
    "work",
    "StartExecTime",
    "start_exec_time",
    "start_ts",
    "StopExecTime",
    "stop_exec_time",
    "stop_ts",
    "Status",
    "status",
    "Owner",
    "owner",
    "ExecUnitFinished",
    "exec_unit_finished",
    "NetworkType",
    "network_type",
    "cloud_type",
    "compute_service",
    "AmountOfDataTransferred",
]

logger = logging.getLogger(__name__)


def _quote_identifier(identifier: str) -> str:
    return ".".join(f'"{part.replace(chr(34), chr(34) + chr(34))}"' for part in identifier.split("."))


class MetricsDBClient:
    def __init__(self, engine: Engine | None = None) -> None:
        self.settings = get_settings()
        self.engine = engine

    def _get_engine(self) -> Engine | None:
        if self.engine is not None:
            return self.engine
        url = self.settings.cnr_database_url
        if not url:
            logger.warning("CNR MetricsDB connection is not configured; returning no rows")
            return None
        self.engine = create_engine(url, future=True)
        return self.engine

    def _table_columns(self, inspector: Any, table_name: str) -> set[str]:
        schema, _, name = table_name.rpartition(".")
        try:
            columns = inspector.get_columns(name, schema=schema or None)
        except Exception:
            return set()
        return {column["name"] for column in columns}

    def _build_query(self, inspector: Any, sites: list[str] | None) -> tuple[str, dict[str, Any]]:
        facts_columns = self._table_columns(inspector, FACTS_TABLE)
        if not facts_columns:
            raise RuntimeError(f"MetricsDB facts table not found or unreadable: {FACTS_TABLE}")

        cloud_columns = self._table_columns(inspector, CLOUD_DETAIL_TABLE)
        network_columns = self._table_columns(inspector, NETWORK_DETAIL_TABLE)

        select_parts: list[str] = []
        for column in RAW_FIELD_CANDIDATES:
            if column in facts_columns:
                select_parts.append(f'f.{_quote_identifier(column)} AS "{column}"')
            elif column in cloud_columns:
                select_parts.append(f'c.{_quote_identifier(column)} AS "{column}"')
            elif column in network_columns:
                select_parts.append(f'n.{_quote_identifier(column)} AS "{column}"')
        if not select_parts:
            select_parts = ["f.*"]

        joins: list[str] = []
        exec_column = "ExecUnitID" if "ExecUnitID" in facts_columns else "exec_unit_id" if "exec_unit_id" in facts_columns else None
        if exec_column and cloud_columns and exec_column in cloud_columns:
            joins.append(
                f"LEFT JOIN {_quote_identifier(CLOUD_DETAIL_TABLE)} c "
                f"ON c.{_quote_identifier(exec_column)} = f.{_quote_identifier(exec_column)}"
            )
        if exec_column and network_columns and exec_column in network_columns:
            joins.append(
                f"LEFT JOIN {_quote_identifier(NETWORK_DETAIL_TABLE)} n "
                f"ON n.{_quote_identifier(exec_column)} = f.{_quote_identifier(exec_column)}"
            )

        predicates: list[str] = []
        start_column = next((c for c in ["StartExecTime", "start_exec_time", "start_ts"] if c in facts_columns), None)
        if start_column:
            predicates.append(f"f.{_quote_identifier(start_column)} >= :start_ts")
            predicates.append(f"f.{_quote_identifier(start_column)} < :end_ts")

        site_column = next((c for c in ["Site", "site", "site_name"] if c in facts_columns), None)
        params: dict[str, Any] = {}
        if sites and site_column:
            site_params = []
            for idx, site in enumerate(sites):
                name = f"site_{idx}"
                params[name] = site
                site_params.append(f":{name}")
            predicates.append(f"f.{_quote_identifier(site_column)} IN ({', '.join(site_params)})")

        where_clause = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        sql = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {_quote_identifier(FACTS_TABLE)} f "
            f"{' '.join(joins)} {where_clause}"
        )
        return sql, params

    def fetch_execution_records(
        self,
        start_ts: datetime,
        end_ts: datetime,
        sites: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        engine = self._get_engine()
        if engine is None:
            return []
        with engine.connect() as connection:
            inspector = inspect(connection)
            sql, params = self._build_query(inspector, sites)
            params.update({"start_ts": start_ts, "end_ts": end_ts})
            rows = connection.execute(text(sql), params).mappings().all()
        records = [dict(row) for row in rows]
        logger.info(
            "Fetched %s MetricsDB execution rows from %s to %s",
            len(records),
            start_ts.isoformat(),
            end_ts.isoformat(),
        )
        return records

