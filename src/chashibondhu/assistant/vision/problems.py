"""Per-crop closed list of problems the photo model may choose from (Phase 14).

File: data/reference/crop_problems.csv
  crop_id, problem_id, name_bn, name_en, search_terms_bn, kind, status, source_note
status: todo | draft | verified. Only draft/verified rows are used, draft only when allowed
(CHASHIBONDHU_ALLOW_DRAFT_PROBLEMS, default 1 for the prototype).
Crop names come from data/reference/crop_catalogue.csv (crop_id, name_en, name_bn).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROBLEM_COLUMNS = ["crop_id", "problem_id", "name_bn", "name_en", "search_terms_bn", "kind",
                   "status", "source_note"]
STATUSES = {"todo", "draft", "verified"}
HEALTHY_ID = "healthy"


@dataclass(frozen=True)
class Problem:
    crop_id: str
    problem_id: str
    name_bn: str
    name_en: str
    search_terms_bn: str
    kind: str
    status: str


@dataclass(frozen=True)
class Crop:
    crop_id: str
    name_bn: str
    name_en: str


class ProblemCatalogue:
    def __init__(self, crops: dict[str, Crop], problems: list[Problem], allow_draft: bool = True):
        self.crops = crops
        self.allow_draft = allow_draft
        ok = {"verified", "draft"} if allow_draft else {"verified"}
        self._by_crop: dict[str, list[Problem]] = {}
        for p in problems:
            if p.status in ok:
                self._by_crop.setdefault(p.crop_id, []).append(p)

    @classmethod
    def load(cls, reference_dir: Path, allow_draft: bool | None = None) -> "ProblemCatalogue":
        if allow_draft is None:
            allow_draft = os.environ.get("CHASHIBONDHU_ALLOW_DRAFT_PROBLEMS", "1") != "0"
        cat = pd.read_csv(Path(reference_dir) / "crop_catalogue.csv", dtype=str).fillna("")
        missing = {"crop_id", "name_en", "name_bn"} - set(cat.columns)
        if missing:
            raise ValueError(f"crop_catalogue.csv is missing columns: {sorted(missing)}")
        crops = {r.crop_id.strip(): Crop(r.crop_id.strip(), r.name_bn.strip(), r.name_en.strip())
                 for r in cat.itertuples()}
        df = pd.read_csv(Path(reference_dir) / "crop_problems.csv", dtype=str).fillna("")
        missing = set(PROBLEM_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"crop_problems.csv is missing columns: {sorted(missing)}")
        problems = []
        for r in df.itertuples():
            row = {c: str(getattr(r, c)).strip() for c in PROBLEM_COLUMNS}
            if row["status"] not in STATUSES:
                raise ValueError(f"bad status '{row['status']}' for {row['problem_id']}")
            if row["crop_id"] not in crops:
                raise ValueError(f"crop_problems.csv: unknown crop_id '{row['crop_id']}'")
            if row["problem_id"] == HEALTHY_ID:
                raise ValueError("'healthy' is built in; do not add it to crop_problems.csv")
            problems.append(Problem(**{k: row[k] for k in Problem.__dataclass_fields__}))
        keys = [(p.crop_id, p.problem_id) for p in problems]
        if len(keys) != len(set(keys)):
            raise ValueError("crop_problems.csv has duplicate (crop_id, problem_id) rows")
        return cls(crops, problems, allow_draft)

    def crop(self, crop_id: str) -> Crop:
        if crop_id not in self.crops:
            raise KeyError(f"unknown crop_id '{crop_id}'")
        return self.crops[crop_id]

    def for_crop(self, crop_id: str) -> list[Problem]:
        self.crop(crop_id)
        return list(self._by_crop.get(crop_id, []))
