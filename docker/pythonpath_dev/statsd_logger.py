from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from flask import g
import threading
import requests
import time

from superset.extensions import stats_logger_manager
from superset.utils import json
from superset.utils.log import AbstractEventLogger
from superset.utils.core import get_user_id, LoggerLevel, to_int

from superset.stats_logger import StatsdStatsLogger
from Superset_security_manager import DBConnector

s_logger = StatsdStatsLogger(host='host.docker.internal', port=8125, prefix='superset')

class StastDEventLogger(AbstractEventLogger):
    """Event logger that commits logs to StatsD with background healthchecks."""

    def __init__(self, *args, **kwargs):
        self.healthcheck()

    def log(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        user_id: int | None,
        action: str,
        dashboard_id: int | None,
        duration_ms: int | None,
        slice_id: int | None,
        referrer: str | None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        # pylint: disable=import-outside-toplevel
        from superset.models.core import Log
        from superset import db
        
        records = kwargs.get("records", [])
        logs = []
        for record in records:
            json_string: str | None
            try:
                json_string = json.dumps(record)
            except Exception:  # pylint: disable=broad-except
                json_string = None
            log = Log(
                action=action,
                json=json_string,
                dashboard_id=dashboard_id or record.get("dashboard_id"),
                slice_id=slice_id or record.get("slice_id"),
                duration_ms=duration_ms,
                referrer=referrer,
                user_id=user_id,
            )
            logs.append(log)
            try:
                if action == 'welcome':
                    s_logger.incr(f'superset.welcome')
                    s_logger.timing(f'superset.welcome.timer', duration_ms)
                elif action == 'dashboard' or action == 'dashboardRestApi.get':
                    s_logger.incr(f'superset.dashboard.dashboard_{dashboard_id}')
                    s_logger.timing(f'superset.dashboard.dashboard_{dashboard_id}.timer',duration_ms)
                elif action == 'execute_sql':
                    s_logger.timing(f'superset.sql.execute_sql.timer', duration_ms)
                elif action == 'SqlLabRestApi.get_results' and "/api/v1/sqllab/execute/" in json_string:
                    s_logger.timing(f'superset.sql.sqlLab.execute_sql.timer', duration_ms)
            
                db.session.bulk_save_objects(logs)
                db.session.commit()  # pylint: disable=consider-using-transaction
    
            except SQLAlchemyError as ex:
                logging.error("DBEventLogger failed to log event(s)")
                logging.exception(ex)
            except Exception as ex:
                print("StatsDEventLogger exception: ", ex)
            

    def healthcheck(self): # В данный момент отключено
        def db_healthcheck(dbname: str = "depot_db", host: str = "192.168.1.56", user: str = "postgres", password: str = "admin", port: str = "5432"): # Данные для подключения к второй базе
            db = DBConnector()
            db.close_connection()
            while True:
                try:
                    db.connect()
                    db.cursor.execute("select 1")
                    result = db.cursor.fetchone()
                    s_logger.gauge(f'health.superset_DB', 200)
                except Exception as e:
                    print("DB1 error",e)
                    s_logger_db.gauge(f'health.superset_DB', 503)
                finally:
                    db.close_connection()

                try:
                    db.connect(dbname=dbname, host=host, user=user, password=password, port=port)
                    db.cursor.execute("select 1")
                    result = db.cursor.fetchone()
                    s_logger_db.gauge(f'health.superset_DB_second', 200)
                except Exception as e:
                    print("DB2 error", e)
                    s_logger_db.gauge(f'health.superset_DB_second', 503)
                finally:
                    db.close_connection()
                    time.sleep(60)


        #thread = threading.Thread(target=db_healthcheck)
        #thread.daemon = True
        #thread.start()
