import time
import logging
from typing import List, Any, Optional
from contextlib import contextmanager

from app.execution.base import BaseDatabaseExecutor, DatabaseExecutionRequest
from app.execution.models import (
    DatabaseExecutionResult,
    DatabaseType,
    ExecutionStatus,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import pymysql
    from pymysql.cursors import DictCursor
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    pymysql = None
    DictCursor = None


class MySQLExecutor(BaseDatabaseExecutor):
    def __init__(self):
        if not PYMYSQL_AVAILABLE:
            raise RuntimeError("PyMySQL is not installed. Install with: pip install pymysql")

        self.host = settings.mysql_host
        self.port = settings.mysql_port
        self.database = settings.mysql_database
        self.user = settings.mysql_user
        self.password = settings.mysql_password

        if not all([self.host, self.database, self.user]):
            raise ValueError("MySQL configuration incomplete. Set MYSQL_HOST, MYSQL_DATABASE, MYSQL_USER")

    @property
    def database_type(self) -> DatabaseType:
        return DatabaseType.MYSQL

    @contextmanager
    def _get_connection(self):
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
        try:
            yield conn
        finally:
            conn.close()

    async def execute(self, request: DatabaseExecutionRequest) -> DatabaseExecutionResult:
        start_time = time.perf_counter()
        database_name = request.database_name or self.database

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                query = request.query.strip()
                if not query:
                    return DatabaseExecutionResult(
                        success=False,
                        status=ExecutionStatus.ERROR,
                        database_type=self.database_type,
                        database_name=database_name,
                        error_type="ValidationError",
                        error_message="Empty query",
                        execution_time=time.perf_counter() - start_time,
                    )

                statements = self._split_statements(query)

                all_columns = []
                all_rows = []
                total_affected = 0
                last_columns = []
                last_rows = []

                for stmt in statements:
                    stmt = stmt.strip()
                    if not stmt:
                        continue

                    cursor.execute(stmt, request.params or ())

                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        rows = cursor.fetchall()
                        rows_list = [list(row.values()) for row in rows]

                        last_columns = columns
                        last_rows = rows_list
                        all_columns = columns
                        all_rows = rows_list
                    else:
                        total_affected += cursor.rowcount

                    conn.commit()

                execution_time = time.perf_counter() - start_time

                return DatabaseExecutionResult(
                    success=True,
                    status=ExecutionStatus.SUCCESS,
                    database_type=self.database_type,
                    database_name=database_name,
                    columns=last_columns,
                    rows=last_rows,
                    affected_rows=total_affected,
                    stdout=f"Query executed successfully. Rows returned: {len(last_rows)}, Affected: {total_affected}",
                    execution_time=execution_time,
                )

        except pymysql.MySQLError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"MySQL error: {e}")
            return DatabaseExecutionResult(
                success=False,
                status=ExecutionStatus.ERROR,
                database_type=self.database_type,
                database_name=database_name,
                error_type="SQLError",
                error_message=str(e),
                execution_time=execution_time,
            )
        except Exception as e:
            execution_time = time.perf_counter() - start_time
            logger.error(f"MySQL execution error: {e}")
            return DatabaseExecutionResult(
                success=False,
                status=ExecutionStatus.ERROR,
                database_type=self.database_type,
                database_name=database_name,
                error_type="ExecutionError",
                error_message=str(e),
                execution_time=execution_time,
            )

    def _split_statements(self, query: str) -> List[str]:
        statements = []
        current = []
        in_string = False
        string_char = None
        i = 0

        while i < len(query):
            char = query[i]

            if char in ('"', "'", "`") and (i == 0 or query[i - 1] != "\\"):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None

            current.append(char)

            if char == ";" and not in_string:
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []

            i += 1

        if current:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)

        return statements if statements else [query]

    async def health_check(self) -> bool:
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            return True
        except Exception:
            return False