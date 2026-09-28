import time
import logging
import json
from typing import List, Any, Optional, Dict
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
    from pymongo import MongoClient
    from pymongo.database import Database
    from pymongo.collection import Collection
    from pymongo.errors import PyMongoError
    PYMONGO_AVAILABLE = True
except ImportError:
    PYMONGO_AVAILABLE = False
    MongoClient = None
    Database = None
    Collection = None
    PyMongoError = Exception


class MongoDBExecutor(BaseDatabaseExecutor):
    def __init__(self):
        if not PYMONGO_AVAILABLE:
            raise RuntimeError("PyMongo is not installed. Install with: pip install pymongo")

        self.uri = settings.mongodb_uri
        self.database_name = settings.mongodb_database

        if not self.uri or not self.database_name:
            raise ValueError("MongoDB configuration incomplete. Set MONGODB_URI and MONGODB_DATABASE")

        self._client = None

    @property
    def database_type(self) -> DatabaseType:
        return DatabaseType.MONGODB

    @contextmanager
    def _get_database(self):
        if self._client is None:
            self._client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
        db = self._client[self.database_name]
        try:
            yield db
        except Exception:
            raise

    def _parse_operation(self, query: str) -> Dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("Empty query")

        if query.startswith("db."):
            return {"type": "shell", "query": query}

        try:
            return {"type": "json", "data": json.loads(query)}
        except json.JSONDecodeError:
            return {"type": "shell", "query": query}

    async def execute(self, request: DatabaseExecutionRequest) -> DatabaseExecutionResult:
        start_time = time.perf_counter()
        database_name = request.database_name or self.database_name

        try:
            with self._get_database() as db:
                parsed = self._parse_operation(request.query)

                if parsed["type"] == "json":
                    return await self._execute_json_operation(db, parsed["data"], database_name, start_time)
                else:
                    return await self._execute_shell_operation(db, parsed["query"], database_name, start_time)

        except PyMongoError as e:
            execution_time = time.perf_counter() - start_time
            logger.warning(f"MongoDB error: {e}")
            return DatabaseExecutionResult(
                success=False,
                status=ExecutionStatus.ERROR,
                database_type=self.database_type,
                database_name=database_name,
                error_type="DatabaseError",
                error_message=str(e),
                execution_time=execution_time,
            )
        except Exception as e:
            execution_time = time.perf_counter() - start_time
            logger.error(f"MongoDB execution error: {e}")
            return DatabaseExecutionResult(
                success=False,
                status=ExecutionStatus.ERROR,
                database_type=self.database_type,
                database_name=database_name,
                error_type="ExecutionError",
                error_message=str(e),
                execution_time=execution_time,
            )

    async def _execute_json_operation(self, db: Database, operation: Dict, database_name: str, start_time: float) -> DatabaseExecutionResult:
        op_type = operation.get("operation", "find")
        collection_name = operation.get("collection")
        filter_query = operation.get("filter", {})
        projection = operation.get("projection")
        limit = operation.get("limit", 100)
        skip = operation.get("skip", 0)
        sort = operation.get("sort")

        if not collection_name:
            return DatabaseExecutionResult(
                success=False,
                status=ExecutionStatus.ERROR,
                database_type=self.database_type,
                database_name=database_name,
                error_type="ValidationError",
                error_message="Collection name is required",
                execution_time=time.perf_counter() - start_time,
            )

        collection = db[collection_name]

        if op_type == "find":
            cursor = collection.find(filter_query, projection)
            if sort:
                cursor = cursor.sort(sort)
            cursor = cursor.skip(skip).limit(limit)
            docs = list(cursor)

        elif op_type == "find_one":
            doc = collection.find_one(filter_query, projection)
            docs = [doc] if doc else []

        elif op_type == "count":
            count = collection.count_documents(filter_query)
            docs = [{"count": count}]

        elif op_type == "aggregate":
            pipeline = operation.get("pipeline", [])
            docs = list(collection.aggregate(pipeline))

        elif op_type == "insert_one":
            document = operation.get("document", {})
            result = collection.insert_one(document)
            docs = [{"inserted_id": str(result.inserted_id)}]

        elif op_type == "insert_many":
            documents = operation.get("documents", [])
            result = collection.insert_many(documents)
            docs = [{"inserted_ids": [str(id) for id in result.inserted_ids]}]

        elif op_type == "update_one":
            update = operation.get("update", {})
            result = collection.update_one(filter_query, update)
            docs = [{"matched_count": result.matched_count, "modified_count": result.modified_count}]

        elif op_type == "update_many":
            update = operation.get("update", {})
            result = collection.update_many(filter_query, update)
            docs = [{"matched_count": result.matched_count, "modified_count": result.modified_count}]

        elif op_type == "delete_one":
            result = collection.delete_one(filter_query)
            docs = [{"deleted_count": result.deleted_count}]

        elif op_type == "delete_many":
            result = collection.delete_many(filter_query)
            docs = [{"deleted_count": result.deleted_count}]

        elif op_type == "create_index":
            keys = operation.get("keys", [])
            options = operation.get("options", {})
            index_name = collection.create_index(keys, **options)
            docs = [{"index_name": index_name}]

        else:
            return DatabaseExecutionResult(
                success=False,
                status=ExecutionStatus.ERROR,
                database_type=self.database_type,
                database_name=database_name,
                error_type="ValidationError",
                error_message=f"Unsupported operation: {op_type}",
                execution_time=time.perf_counter() - start_time,
            )

        execution_time = time.perf_counter() - start_time

        if docs:
            columns = list(docs[0].keys()) if docs else []
            rows = [[doc.get(col) for col in columns] for doc in docs]
        else:
            columns = []
            rows = []

        return DatabaseExecutionResult(
            success=True,
            status=ExecutionStatus.SUCCESS,
            database_type=self.database_type,
            database_name=database_name,
            columns=columns,
            rows=rows,
            affected_rows=len(rows),
            stdout=f"Operation '{op_type}' executed successfully. Documents: {len(rows)}",
            execution_time=execution_time,
        )

    async def _execute_shell_operation(self, db: Database, query: str, database_name: str, start_time: float) -> DatabaseExecutionResult:
        return DatabaseExecutionResult(
            success=False,
            status=ExecutionStatus.ERROR,
            database_type=self.database_type,
            database_name=database_name,
            error_type="NotImplementedError",
            error_message="Shell-style MongoDB queries not yet supported. Use JSON format.",
            execution_time=time.perf_counter() - start_time,
        )

    async def health_check(self) -> bool:
        try:
            if self._client is None:
                self._client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
            self._client.admin.command("ping")
            return True
        except Exception:
            return False

    def close(self):
        if self._client:
            self._client.close()
            self._client = None