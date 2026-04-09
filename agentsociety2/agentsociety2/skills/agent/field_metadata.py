"""
字段元数据定义

用于定义Agent字段的结构、含义和可能的取值
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field


class FieldType(str, Enum):
    """字段类型"""
    DISCRETE = "discrete"  # 离散值（如选项列表）
    CONTINUOUS = "continuous"  # 连续值（如数值范围）
    STRING = "string"  # 字符串


class FieldOption(BaseModel):
    """字段选项（用于离散值字段）"""
    value: Union[str, int, float]  # 选项值
    label: Optional[str] = None  # 选项标签/描述


class FieldMetadata(BaseModel):
    """字段元数据"""
    name: str  # 字段名
    label: str  # 字段含义/标签
    field_type: FieldType  # 字段类型

    # 对于离散值字段
    options: List[FieldOption] = Field(default_factory=list)  # 可能的取值选项

    # 对于连续值字段
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    # 其他元数据
    description: Optional[str] = None  # 详细描述
    is_filterable: bool = True  # 是否可用于筛选

    def get_option_values(self) -> List[Union[str, int, float]]:
        """获取所有选项值"""
        return [opt.value for opt in self.options]

    def validate_value(self, value: Any) -> bool:
        """验证值是否有效"""
        if self.field_type == FieldType.DISCRETE:
            return value in self.get_option_values()
        elif self.field_type == FieldType.CONTINUOUS:
            if not isinstance(value, (int, float)):
                return False
            if self.min_value is not None and value < self.min_value:
                return False
            if self.max_value is not None and value > self.max_value:
                return False
            return True
        elif self.field_type == FieldType.STRING:
            return isinstance(value, str)
        return True


class FieldMetadataSchema(BaseModel):
    """字段元数据模式（包含所有字段的定义）"""
    fields: List[FieldMetadata] = Field(default_factory=list)

    def get_field(self, name: str) -> Optional[FieldMetadata]:
        """根据字段名获取元数据"""
        for field_meta in self.fields:
            if field_meta.name == name:
                return field_meta
        return None

    def get_filterable_fields(self) -> List[FieldMetadata]:
        """获取所有可筛选的字段"""
        return [f for f in self.fields if f.is_filterable]


__all__ = [
    "FieldType",
    "FieldOption",
    "FieldMetadata",
    "FieldMetadataSchema",
]
