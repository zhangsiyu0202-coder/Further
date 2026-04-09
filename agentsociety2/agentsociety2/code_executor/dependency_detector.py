"""
依赖检测器：使用 AST 静态分析 import 语句，推断需要安装的第三方依赖。
"""

import ast
import sys
from typing import List, Set, Dict

from agentsociety2.logger import get_logger

logger = get_logger()


class DependencyDetector:
    """依赖检测器，仅基于 AST 分析 import 语句。"""

    # 标准库模块列表
    STANDARD_LIBRARY = {
        *sys.builtin_module_names,
        "os",
        "sys",
        "json",
        "datetime",
        "time",
        "math",
        "random",
        "collections",
        "itertools",
        "functools",
        "operator",
        "pathlib",
        "shutil",
        "subprocess",
        "threading",
        "multiprocessing",
        "concurrent",
        "asyncio",
        "typing",
        "dataclasses",
        "enum",
        "abc",
        "contextlib",
        "copy",
        "hashlib",
        "base64",
        "urllib",
        "http",
        "email",
        "csv",
        "xml",
        "sqlite3",
        "pickle",
        "gzip",
        "zipfile",
        "tarfile",
        "io",
        "tempfile",
        "logging",
        "warnings",
        "traceback",
        "inspect",
        "importlib",
        "pkgutil",
        "unittest",
        "doctest",
        "argparse",
        "getopt",
        "configparser",
        "re",
        "string",
        "textwrap",
        "unicodedata",
        "codecs",
        "locale",
        "__future__",
    }

    # 导入名到安装包名的映射
    IMPORT_TO_PACKAGE: Dict[str, str] = {
        "PIL": "Pillow",
        "cv2": "opencv-python",
        "sklearn": "scikit-learn",
        "yaml": "PyYAML",
        "lxml": "lxml",
        "dateutil": "python-dateutil",
        "json_repair": "json-repair",
        "numpy": "numpy",
        "pandas": "pandas",
        "openpyxl": "openpyxl",
        "xlrd": "xlrd",
        "xlwt": "xlwt",
        "xlutils": "xlutils",
        "pyarrow": "pyarrow",
        "h5py": "h5py",
        "matplotlib": "matplotlib",
        "seaborn": "seaborn",
        "scipy": "scipy",
        "pyodbc": "pyodbc",
        "requests": "requests",
        "httpx": "httpx",
        "tqdm": "tqdm",
        "json5": "json5",
        "pyyaml": "PyYAML",
    }

    def __init__(self):
        """初始化依赖检测器（当前无状态）。"""
        ...

    def _is_standard_library(self, module_name: str) -> bool:
        """
        判断模块是否属于标准库

        Args:
            module_name: 模块名

        Returns:
            如果是标准库返回True，否则返回False
        """
        # 处理相对导入
        if module_name.startswith("."):
            return False

        # 处理 __future__ 等特殊导入
        if module_name == "__future__":
            return True

        # 检查是否在标准库列表中
        root_module = module_name.split(".")[0]
        return root_module in self.STANDARD_LIBRARY

    def _normalize_package_name(self, module_name: str) -> str:
        """
        将导入名转换为pip安装包名

        Args:
            module_name: 导入的模块名

        Returns:
            pip安装时的包名
        """
        # 获取根模块名
        root_module = module_name.split(".")[0]

        # 如果存在映射，使用映射后的名称
        if root_module in self.IMPORT_TO_PACKAGE:
            return self.IMPORT_TO_PACKAGE[root_module]

        return root_module

    def _extract_imports_from_ast(self, code: str) -> Set[str]:
        """
        使用AST解析提取import语句

        Args:
            code: Python代码字符串

        Returns:
            检测到的模块名集合
        """
        imports: Set[str] = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_module = alias.name.split(".")[0]
                        if not self._is_standard_library(root_module):
                            imports.add(root_module)
                elif isinstance(node, ast.ImportFrom):
                    # 处理相对导入（node.level > 0）
                    if node.level > 0:
                        # 相对导入通常不需要外部依赖，跳过
                        continue
                    if node.module:
                        root_module = node.module.split(".")[0]
                        if not self._is_standard_library(root_module):
                            imports.add(root_module)
        except SyntaxError as e:
            logger.warning(f"AST解析失败: {e}")
        except Exception as e:
            logger.warning(f"AST解析时出现异常: {e}")

        return imports

    def detect(self, code: str) -> List[str]:
        """
        从代码中检测依赖包（基于 AST 分析 import 语句）。

        Args:
            code: Python代码字符串

        Returns:
            检测到的依赖包列表（已转换为pip安装包名）
        """
        imports = self._extract_imports_from_ast(code)

        normalized_dependencies: Set[str] = set()
        for module_name in imports:
            normalized_name = self._normalize_package_name(module_name)
            normalized_dependencies.add(normalized_name)

        return sorted(list(normalized_dependencies))
