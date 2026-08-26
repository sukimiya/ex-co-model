from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Finite float: rejects inf/nan. Applied per element inside tuples.
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class NodeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[str] = []


class PrimitiveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["box", "cylinder"]
    size: tuple[FiniteFloat, FiniteFloat, FiniteFloat] = (2.0, 2.0, 2.0)  # box full extents, meters
    radius: FiniteFloat = 1.0    # cylinder only
    depth: FiniteFloat = 2.0     # cylinder only
    vertices: int = 32           # cylinder only
    location: tuple[FiniteFloat, FiniteFloat, FiniteFloat] = (0.0, 0.0, 0.0)


class BevelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: FiniteFloat = 0.1
    segments: int = 3


class ScaleToParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    length_m: float = Field(gt=0, allow_inf_nan=False)


class ExportFbxParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = "model.fbx"

    @field_validator("filename")
    @classmethod
    def _filename_is_plain_fbx_basename(cls, v: str) -> str:
        if Path(v).is_absolute():
            raise ValueError("filename must be a plain basename, not an absolute path")
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("filename must not contain '..' or path separators")
        if not v.lower().endswith(".fbx"):
            raise ValueError("filename must end with .fbx")
        return v


class PrimitiveNode(NodeBase):
    op: Literal["primitive"]
    params: PrimitiveParams


class BevelNode(NodeBase):
    op: Literal["bevel"]
    inputs: list[str] = Field(min_length=1, max_length=1)
    params: BevelParams = BevelParams()


class BooleanSubtractNode(NodeBase):
    op: Literal["boolean_subtract"]
    # inputs[0] = target, inputs[1] = cutter
    inputs: list[str] = Field(min_length=2, max_length=2)


class ScaleToNode(NodeBase):
    op: Literal["scale_to"]
    inputs: list[str] = Field(min_length=1, max_length=1)
    params: ScaleToParams


class ExportFbxNode(NodeBase):
    op: Literal["export_fbx"]
    inputs: list[str] = Field(min_length=1, max_length=1)
    params: ExportFbxParams = ExportFbxParams()


Node = Annotated[
    Union[PrimitiveNode, BevelNode, BooleanSubtractNode, ScaleToNode, ExportFbxNode],
    Field(discriminator="op"),
]


class OpTree(BaseModel):
    nodes: dict[str, Node]

    @model_validator(mode="after")
    def _refs_exist(self) -> "OpTree":
        for name, node in self.nodes.items():
            for ref in node.inputs:
                if ref not in self.nodes:
                    raise ValueError(f"node {name!r} references unknown node {ref!r}")
        return self


def load_optree(path: str | Path) -> OpTree:
    return OpTree.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
