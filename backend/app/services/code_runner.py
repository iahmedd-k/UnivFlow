import os
import subprocess
import tempfile
import shutil
import logging
import sys
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SingleFileCodeRunner:
    """
    Executes short, single-file student code tasks (Python, Java, C++, JS)
    with execution timeouts and captures stdout/stderr terminal output.
    """

    # Allow normal scientific Python imports/training to finish while keeping
    # each generated file bounded against runaway loops.
    DEFAULT_TIMEOUT_SECONDS = 20

    @classmethod
    def execute_code(cls, code: str, language: str = "python", stdin_input: str = "") -> Dict[str, Any]:
        """
        Main entrypoint: executes single-file code according to language.
        """
        lang = (language or "python").lower().strip()
        if not stdin_input:
            stdin_input = "5\n10\n15\n20\n"
        
        try:
            if lang in ["python", "py", "python3"]:
                return cls.run_python(code, stdin_input)
            elif lang in ["sql", "sqlite", "sqlite3", "mysql", "postgres", "postgresql"]:
                return cls.run_sql(code)
            elif lang in ["asm", "assembly", "nasm", "masm", "emu8086", "x86", "8086", "mips", "riscv"]:
                return cls.run_assembly(code, stdin_input)
            elif lang in ["java"]:
                return cls.run_java(code, stdin_input)
            elif lang in ["cpp", "c++", "c"]:
                return cls.run_cpp(code, stdin_input)
            elif lang in ["javascript", "js", "node"]:
                return cls.run_node(code, stdin_input)
            else:
                return {
                    "stdout": "",
                    "stderr": f"No execution runtime is configured for {lang}.",
                    "exit_code": None,
                    "command": "",
                    "success": False,
                    "runner_supported": False,
                }
        except Exception as e:
            logger.error(f"Code execution error for {language}: {e}")
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1,
                "command": f"{lang} task_file",
                "success": False
            }

    @classmethod
    def run_python(cls, code: str, stdin_input: str = "") -> Dict[str, Any]:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write(code)
            temp_path = f.name
        
        command_str = f"python -X utf8 {os.path.basename(temp_path)}"
        try:
            res = subprocess.run(
                [sys.executable, "-X", "utf8", temp_path],
                input=stdin_input,
                capture_output=True,
                text=True,
                timeout=cls.DEFAULT_TIMEOUT_SECONDS,
                cwd=os.path.dirname(temp_path),
                encoding="utf-8",
                errors="replace"
            )
            return {
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode,
                "command": command_str.replace(os.path.basename(temp_path), "lab_solution.py"),
                "success": res.returncode == 0
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"Error: Execution timed out (Limit: {cls.DEFAULT_TIMEOUT_SECONDS} seconds).",
                "exit_code": 124,
                "command": command_str.replace(os.path.basename(temp_path), "lab_solution.py"),
                "success": False
            }
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @classmethod
    def run_java(cls, code: str, stdin_input: str = "") -> Dict[str, Any]:
        temp_dir = tempfile.mkdtemp()
        class_name = cls._extract_java_class_name(code) or "Main"
        file_path = os.path.join(temp_dir, f"{class_name}.java")
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            # Step 1: javac compile
            comp = subprocess.run(
                ["javac", file_path],
                capture_output=True,
                text=True,
                timeout=cls.DEFAULT_TIMEOUT_SECONDS,
                cwd=temp_dir,
                encoding="utf-8",
                errors="replace"
            )
            if comp.returncode != 0:
                return {
                    "stdout": "",
                    "stderr": comp.stderr,
                    "exit_code": comp.returncode,
                    "command": f"javac {class_name}.java && java {class_name}",
                    "success": False
                }

            # Step 2: java run
            run = subprocess.run(
                ["java", "-cp", temp_dir, class_name],
                input=stdin_input,
                capture_output=True,
                text=True,
                timeout=cls.DEFAULT_TIMEOUT_SECONDS,
                cwd=temp_dir,
                encoding="utf-8",
                errors="replace"
            )
            return {
                "stdout": run.stdout,
                "stderr": run.stderr,
                "exit_code": run.returncode,
                "command": f"java {class_name}",
                "success": run.returncode == 0
            }
        except FileNotFoundError:
                return {
                    "stdout": "",
                    "stderr": "Java runtime is not installed; this file was not executed.",
                    "exit_code": None,
                    "command": f"java {class_name}",
                    "success": False,
                    "runner_supported": False,
                }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @classmethod
    def run_cpp(cls, code: str, stdin_input: str = "") -> Dict[str, Any]:
        temp_dir = tempfile.mkdtemp()
        src_path = os.path.join(temp_dir, "solution.cpp")
        exe_path = os.path.join(temp_dir, "solution.exe" if os.name == "nt" else "solution")
        
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            # Compile with g++
            comp = subprocess.run(
                ["g++", src_path, "-o", exe_path],
                capture_output=True,
                text=True,
                timeout=cls.DEFAULT_TIMEOUT_SECONDS,
                cwd=temp_dir,
            )
            if comp.returncode != 0:
                return {
                    "stdout": "",
                    "stderr": comp.stderr,
                    "exit_code": comp.returncode,
                    "command": "g++ solution.cpp && ./solution",
                    "success": False
                }

            run = subprocess.run(
                [exe_path],
                input=stdin_input,
                capture_output=True,
                text=True,
                timeout=cls.DEFAULT_TIMEOUT_SECONDS,
                cwd=temp_dir,
            )
            return {
                "stdout": run.stdout,
                "stderr": run.stderr,
                "exit_code": run.returncode,
                "command": "./solution",
                "success": run.returncode == 0
            }
        except FileNotFoundError:
                return {
                    "stdout": "",
                    "stderr": "C++ compiler (g++) is not installed; this file was not executed.",
                    "exit_code": None,
                    "command": "./solution",
                    "success": False,
                    "runner_supported": False,
                }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @classmethod
    def run_node(cls, code: str, stdin_input: str = "") -> Dict[str, Any]:
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False, encoding="utf-8") as f:
            f.write(code)
            temp_path = f.name
        try:
            res = subprocess.run(
                ["node", temp_path],
                input=stdin_input,
                capture_output=True,
                text=True,
                timeout=cls.DEFAULT_TIMEOUT_SECONDS,
                cwd=os.path.dirname(temp_path),
            )
            return {
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode,
                "command": "node solution.js",
                "success": res.returncode == 0
            }
        except FileNotFoundError:
            return {
                "stdout": "",
                "stderr": "Node.js runtime is not installed; this file was not executed.",
                "exit_code": None,
                "command": "node solution.js",
                "success": False,
                "runner_supported": False,
            }
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @classmethod
    def run_sql(cls, code: str) -> Dict[str, Any]:
        """
        Executes SQL DDL/DML/Queries against an isolated in-memory SQLite database,
        capturing tabular result sets and execution status.
        """
        import sqlite3
        try:
            conn = sqlite3.connect(":memory:")
            cursor = conn.cursor()
            
            statements = [s.strip() for s in code.split(";") if s.strip()]
            outputs = []
            for stmt in statements:
                # Skip pure comments
                clean_lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
                clean_stmt = "\n".join(clean_lines).strip()
                if not clean_stmt:
                    continue
                try:
                    cursor.execute(stmt)
                    if stmt.upper().startswith("SELECT") or "SELECT " in stmt.upper():
                        rows = cursor.fetchall()
                        cols = [desc[0] for desc in cursor.description] if cursor.description else []
                        if cols and rows:
                            header = " | ".join(cols)
                            divider = "-+-".join("-" * max(len(c), 6) for c in cols)
                            row_strs = [" | ".join(str(val) for val in r) for r in rows]
                            table = f"{header}\n{divider}\n" + "\n".join(row_strs)
                            outputs.append(f"SQL> {stmt[:60]}...\n{table}\n({len(rows)} rows returned)")
                        elif cols:
                            outputs.append(f"SQL> {stmt[:60]}...\n(0 rows returned)")
                    else:
                        outputs.append(f"SQL> {stmt[:60]}... [SUCCESS]")
                except Exception as stmt_err:
                    outputs.append(f"SQL Error in '{stmt[:40]}...': {stmt_err}")
            
            conn.close()
            return {
                "stdout": "\n\n".join(outputs) if outputs else "SQL script executed successfully.",
                "stderr": "",
                "exit_code": 0,
                "command": "sqlite3 :memory: < solution.sql",
                "success": True
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": 1,
                "command": "sqlite3 :memory: < solution.sql",
                "success": False
            }

    @classmethod
    def run_assembly(cls, code: str, stdin_input: str = "5\n4\n6\n") -> Dict[str, Any]:
        """
        Executes x86 16-bit real mode / DOS / EMU8086 programs using the in-process simulator,
        capturing real register arithmetic, strings, and DOS INT 21h terminal outputs.
        """
        from app.services.emu8086_runner import EMU8086Simulator
        return EMU8086Simulator.execute_asm(code, stdin_input=stdin_input)

    @staticmethod
    def _extract_java_class_name(code: str) -> Optional[str]:
        import re
        match = re.search(r'public\s+class\s+([A-Za-z0-9_]+)', code)
        if match:
            return match.group(1)
        match = re.search(r'class\s+([A-Za-z0-9_]+)', code)
        if match:
            return match.group(1)
        return "Main"
