import pytest
from app.execution import (
    resolve_language,
    normalize_language_input,
    UnsupportedLanguageError,
    get_execution_backend,
    get_execution_type,
    get_all_languages,
    get_languages_by_type,
    get_languages_by_backend,
    LANGUAGE_REGISTRY,
    ExecutionType,
    ExecutionBackend,
)
from app.execution.models import (
    ExecutionResult,
    DatabaseExecutionResult,
    ExecutionStatus,
    ExecutionType as ModelExecutionType,
    DatabaseType,
)


class TestLanguageNormalization:
    def test_lowercase(self):
        assert normalize_language_input("PYTHON") == "python"
        assert normalize_language_input("JavaScript") == "javascript"
        assert normalize_language_input("  GO  ") == "go"

    def test_whitespace_removal(self):
        assert normalize_language_input("C++") == "c++"
        assert normalize_language_input("c ++") == "c++"


class TestLanguageResolution:
    def test_python_aliases(self):
        config = resolve_language("python")
        assert config.id == "python"
        assert config.runtime == "python"
        assert config.execution_type == ExecutionType.PROGRAMMING
        assert config.backend == ExecutionBackend.PISTON

        config = resolve_language("py")
        assert config.id == "python"

        config = resolve_language("python3")
        assert config.id == "python"

    def test_javascript_aliases(self):
        config = resolve_language("javascript")
        assert config.id == "javascript"

        config = resolve_language("js")
        assert config.id == "javascript"

        config = resolve_language("node")
        assert config.id == "javascript"

        config = resolve_language("nodejs")
        assert config.id == "javascript"

    def test_typescript(self):
        config = resolve_language("typescript")
        assert config.id == "typescript"
        assert config.runtime == "typescript"

        config = resolve_language("ts")
        assert config.id == "typescript"

    def test_c_cpp(self):
        config = resolve_language("c")
        assert config.id == "c"
        assert config.runtime == "c"

        config = resolve_language("cpp")
        assert config.id == "cpp"

        config = resolve_language("c++")
        assert config.id == "cpp"

    def test_java(self):
        config = resolve_language("java")
        assert config.id == "java"
        assert config.runtime == "java"

        config = resolve_language("openjdk")
        assert config.id == "java"

    def test_go(self):
        config = resolve_language("go")
        assert config.id == "go"
        assert config.runtime == "go"

        config = resolve_language("golang")
        assert config.id == "go"

    def test_assembly(self):
        config = resolve_language("assembly")
        assert config.id == "assembly"
        assert config.runtime == "nasm"

        config = resolve_language("asm")
        assert config.id == "assembly"

        config = resolve_language("nasm")
        assert config.id == "assembly"

    def test_sqlite(self):
        config = resolve_language("sqlite")
        assert config.id == "sqlite"
        assert config.execution_type == ExecutionType.DATABASE
        assert config.backend == ExecutionBackend.SQLITE

        config = resolve_language("sql")
        assert config.id == "sqlite"

    def test_mysql(self):
        config = resolve_language("mysql")
        assert config.id == "mysql"
        assert config.execution_type == ExecutionType.DATABASE
        assert config.backend == ExecutionBackend.MYSQL

    def test_mongodb(self):
        config = resolve_language("mongodb")
        assert config.id == "mongodb"
        assert config.execution_type == ExecutionType.DATABASE
        assert config.backend == ExecutionBackend.MONGODB

        config = resolve_language("mongo")
        assert config.id == "mongodb"

        config = resolve_language("nosql")
        assert config.id == "mongodb"

    def test_case_insensitive(self):
        config = resolve_language("PYTHON")
        assert config.id == "python"

        config = resolve_language("JavaScript")
        assert config.id == "javascript"

    def test_unsupported_language(self):
        with pytest.raises(UnsupportedLanguageError):
            resolve_language("brainfuck")

        with pytest.raises(UnsupportedLanguageError):
            resolve_language("unknown")

        with pytest.raises(UnsupportedLanguageError):
            resolve_language("random-language")


class TestExecutionBackendDetection:
    def test_programming_backend(self):
        assert get_execution_backend("python") == "piston"
        assert get_execution_backend("javascript") == "piston"
        assert get_execution_backend("cpp") == "piston"
        assert get_execution_backend("assembly") == "piston"

    def test_database_backend(self):
        assert get_execution_backend("sqlite") == "sqlite"
        assert get_execution_backend("mysql") == "mysql"
        assert get_execution_backend("mongodb") == "mongodb"


class TestExecutionTypeDetection:
    def test_programming_type(self):
        assert get_execution_type("python") == ExecutionType.PROGRAMMING
        assert get_execution_type("javascript") == ExecutionType.PROGRAMMING
        assert get_execution_type("java") == ExecutionType.PROGRAMMING

    def test_database_type(self):
        assert get_execution_type("sqlite") == ExecutionType.DATABASE
        assert get_execution_type("mysql") == ExecutionType.DATABASE
        assert get_execution_type("mongodb") == ExecutionType.DATABASE


class TestLanguageRegistry:
    def test_all_languages(self):
        languages = get_all_languages()
        assert len(languages) >= 11

        ids = {lang.id for lang in languages}
        assert "python" in ids
        assert "javascript" in ids
        assert "typescript" in ids
        assert "c" in ids
        assert "cpp" in ids
        assert "java" in ids
        assert "go" in ids
        assert "assembly" in ids
        assert "sqlite" in ids
        assert "mysql" in ids
        assert "mongodb" in ids

    def test_programming_languages(self):
        langs = get_languages_by_type(ExecutionType.PROGRAMMING)
        assert len(langs) == 8
        ids = {lang.id for lang in langs}
        assert ids == {"python", "javascript", "typescript", "c", "cpp", "java", "go", "assembly"}

    def test_database_languages(self):
        langs = get_languages_by_type(ExecutionType.DATABASE)
        assert len(langs) == 3
        ids = {lang.id for lang in langs}
        assert ids == {"sqlite", "mysql", "mongodb"}

    def test_piston_backend_languages(self):
        langs = get_languages_by_backend(ExecutionBackend.PISTON)
        assert len(langs) == 8

    def test_sqlite_backend(self):
        langs = get_languages_by_backend(ExecutionBackend.SQLITE)
        assert len(langs) == 1
        assert langs[0].id == "sqlite"


class TestExecutionResultModel:
    def test_execution_result_creation(self):
        result = ExecutionResult(
            success=True,
            status=ExecutionStatus.SUCCESS,
            execution_type=ModelExecutionType.PROGRAMMING,
            language="python",
            version="3.11",
            runtime="python",
            stdout="Hello\n",
            stderr="",
            output="Hello\n",
            exit_code=0,
            execution_time=0.5,
            attempt=1,
        )

        assert result.success is True
        assert result.status == ExecutionStatus.SUCCESS
        assert result.language == "python"
        assert result.exit_code == 0

        d = result.to_dict()
        assert d["execution_id"].startswith("exec_")
        assert d["success"] is True

    def test_execution_result_error(self):
        result = ExecutionResult.error_result(
            language="python",
            error_type="SyntaxError",
            error_message="invalid syntax",
            status=ExecutionStatus.ERROR,
            attempt=1,
        )

        assert result.success is False
        assert result.status == ExecutionStatus.ERROR
        assert result.error_type == "SyntaxError"
        assert result.error_message == "invalid syntax"

    def test_database_execution_result(self):
        result = DatabaseExecutionResult(
            success=True,
            status=ExecutionStatus.SUCCESS,
            database_type=DatabaseType.SQLITE,
            database_name="test",
            columns=["id", "name"],
            rows=[[1, "Ahmed"], [2, "Ali"]],
            affected_rows=2,
            execution_time=0.1,
        )

        assert result.success is True
        assert result.columns == ["id", "name"]
        assert len(result.rows) == 2
        assert result.affected_rows == 2

        d = result.to_dict()
        assert d["database_type"] == "sqlite"
        assert d["columns"] == ["id", "name"]


class TestExecutionModels:
    def test_execution_status_enum(self):
        assert ExecutionStatus.SUCCESS.value == "success"
        assert ExecutionStatus.ERROR.value == "error"
        assert ExecutionStatus.TIMEOUT.value == "timeout"
        assert ExecutionStatus.UNSUPPORTED_LANGUAGE.value == "unsupported_language"
        assert ExecutionStatus.BACKEND_UNAVAILABLE.value == "backend_unavailable"
        assert ExecutionStatus.LIMIT_EXCEEDED.value == "limit_exceeded"

    def test_execution_type_enum(self):
        assert ModelExecutionType.PROGRAMMING.value == "programming"
        assert ModelExecutionType.DATABASE.value == "database"

    def test_database_type_enum(self):
        assert DatabaseType.SQLITE.value == "sqlite"
        assert DatabaseType.MYSQL.value == "mysql"
        assert DatabaseType.MONGODB.value == "mongodb"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])