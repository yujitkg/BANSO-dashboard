from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import numbers
import os
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import chardet
except ImportError:
    chardet = None

try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None


MAIN_PATTERNS = {"成約": "*成約済み*.csv", "未成約": "*未成約*.csv"}
DETAIL_PATTERNS = {"成約": "*成約済み_明細*.csv", "未成約": "*未成約_明細*.csv"}

COLUMN_ALIASES = {
    "data_no": ["データNo", "データNO", "データ番号", "案件No", "案件番号", "ID", "id"],
    "assessment_date": ["初回登録日時", "登録日時", "査定日時", "査定日", "申込日時", "受付日時"],
    "amount": ["査定合計金額", "査定金額", "査定額", "合計金額", "買取金額", "見積金額"],
    "repeat": ["買取歴", "利用回数", "買取回数", "リピート回数", "取引回数"],
    "method": ["査定方法", "受付方法", "申込方法", "問い合わせ方法"],
    "item_count": ["アイテム数", "点数", "商品点数", "数量", "品数"],
    "item": ["アイテム", "商品カテゴリ", "カテゴリ"],
    "detail_category": ["カテゴリ", "商品カテゴリ", "分類", "ジャンル"],
    "detail_quantity": ["数量", "点数", "個数"],
}

AMOUNT_BANDS = [
    ("0〜2,999円", 0, 2999),
    ("3,000〜4,999円", 3000, 4999),
    ("5,000〜6,999円", 5000, 6999),
    ("7,000〜9,999円", 7000, 9999),
    ("10,000〜19,999円", 10000, 19999),
    ("20,000円以上", 20000, float("inf")),
]
CATEGORIES = ["コスメ", "香水", "サプリ", "家電", "その他"]
METHODS = ["LINE", "メール", "その他"]
REPEAT_GROUPS = ["初回ユーザー", "2回目以上ユーザー", "5回以上ユーザー"]


def log(message: str) -> None:
    print(message, flush=True)


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()
    candidates: list[str] = []
    if chardet:
        detected = chardet.detect(raw[:65536])
        if detected.get("encoding"):
            candidates.append(detected["encoding"])
    candidates.extend(["utf-8-sig", "utf-8", "cp932", "shift_jis"])
    tried = set()
    for encoding in candidates:
        key = encoding.lower()
        if key in tried:
            continue
        tried.add(key)
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            pass
    raise ValueError(f"文字コードを判定できません: file={path}")


def read_csv(path: Path) -> pd.DataFrame:
    encoding = detect_encoding(path)
    try:
        return pd.read_csv(path, encoding=encoding, dtype=str, keep_default_na=False)
    except Exception as exc:
        raise RuntimeError(f"CSV読み込みに失敗しました: file={path}, encoding={encoding}, error={exc}") from exc


def normalize_month(folder: Path) -> str | None:
    name = folder.name
    if re.fullmatch(r"20\d{2}-\d{2}", name):
        return name
    if re.fullmatch(r"20\d{4}", name):
        return f"{name[:4]}-{name[4:]}"
    return None


def iter_month_dirs(root: Path) -> list[tuple[str, Path]]:
    bases = [root / "data", root] if (root / "data").exists() else [root]
    found: dict[str, Path] = {}
    for base in bases:
        if not base.exists():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            month = normalize_month(folder)
            if month:
                found[month] = folder
    return sorted(found.items())


def file_number(path: Path) -> int:
    nums = [int(x) for x in re.findall(r"\((\d+)\)", path.stem)]
    return max(nums) if nums else -1


def pick_latest(files: Iterable[Path]) -> Path | None:
    files = list(files)
    if not files:
        return None
    return max(files, key=lambda p: (file_number(p), p.stat().st_mtime, p.name))


def find_column(df: pd.DataFrame, logical_name: str, path: Path, required: bool = True) -> str | None:
    aliases = COLUMN_ALIASES[logical_name]
    stripped = {str(col).strip(): col for col in df.columns}
    for alias in aliases:
        if alias in stripped:
            return stripped[alias]
    for alias in aliases:
        for col in df.columns:
            if alias in str(col):
                return col
    if required:
        raise KeyError(f"必要な列が見つかりません: file={path}, logical={logical_name}, aliases={aliases}, columns={list(df.columns)}")
    return None


def parse_number(value: object, path: Path, column: str) -> float:
    original = value
    text = "" if value is None else str(value).strip()
    if text in {"", "--", "-", "未設定", "なし", "nan"}:
        return 0.0
    text = text.translate(str.maketrans("０１２３４５６７８９，．", "0123456789,."))
    text = re.sub(r"[,\s円個点PTpt]", "", text)
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError(f"数値変換に失敗しました: file={path}, column={column}, value={original!r}")
    return float(match.group(0))


def repeat_count(value: object) -> int:
    text = "" if value is None else str(value)
    if "初" in text:
        return 1
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if nums:
        return max(nums)
    if "有" in text or "リピ" in text:
        return 2
    return 1


def repeat_group_from_count(count: int) -> str:
    if count >= 5:
        return "5回以上ユーザー"
    if count >= 2:
        return "2回目以上ユーザー"
    return "初回ユーザー"


def classify_method(value: object) -> str:
    text = "" if value is None else str(value).upper()
    if "LINE" in text:
        return "LINE"
    if "メール" in text or "MAIL" in text or "E-MAIL" in text:
        return "メール"
    return "その他"


def classify_category(value: object) -> str:
    text = "" if value is None else str(value)
    if "香水" in text or "フレグランス" in text:
        return "香水"
    if "家電" in text or "美容機器" in text:
        return "家電"
    if "サプリ" in text or "食品" in text:
        return "サプリ"
    if "コスメ" in text or "化粧" in text or "美容" in text:
        return "コスメ"
    return "その他"


def amount_band(amount: float) -> str:
    for label, low, high in AMOUNT_BANDS:
        if low <= amount <= high:
            return label
    return "その他"


def category_mode(values: pd.Series) -> str:
    values = values.dropna().tolist()
    if not values:
        return "その他"
    counts = pd.Series(values).value_counts()
    top = set(counts[counts == counts.max()].index)
    for cat in ["香水", "家電", "サプリ", "コスメ", "その他"]:
        if cat in top:
            return cat
    return "その他"


def select_month_files(month: str, folder: Path) -> list[tuple[str, str, Path]]:
    selected: list[tuple[str, str, Path]] = []
    for status, pattern in MAIN_PATTERNS.items():
        path = pick_latest(p for p in folder.glob(pattern) if "明細" not in p.stem)
        if path:
            log(f"[INFO] using file:\n{folder.name}/{path.name}")
            selected.append(("main", status, path))
        else:
            log(f"[WARN] main file not found: month={month}, status={status}, pattern={pattern}")
    for status, pattern in DETAIL_PATTERNS.items():
        path = pick_latest(folder.glob(pattern))
        if path:
            log(f"[INFO] using file:\n{folder.name}/{path.name}")
            selected.append(("detail", status, path))
        else:
            log(f"[WARN] detail file not found: month={month}, status={status}, pattern={pattern}")
    return selected


def load_main(month: str, status: str, path: Path) -> pd.DataFrame:
    df = read_csv(path)
    data_no_col = find_column(df, "data_no", path)
    date_col = find_column(df, "assessment_date", path, required=False)
    amount_col = find_column(df, "amount", path)
    repeat_col = find_column(df, "repeat", path, required=False)
    method_col = find_column(df, "method", path, required=False)
    item_count_col = find_column(df, "item_count", path, required=False)
    item_col = find_column(df, "item", path, required=False)

    out = pd.DataFrame(index=df.index)
    out["month"] = month
    out["status"] = status
    out["data_no"] = df[data_no_col].astype(str).str.strip()
    out["assessment_date"] = df[date_col] if date_col else ""
    out["amount"] = [parse_number(v, path, amount_col) for v in df[amount_col]]
    out["repeat_raw"] = df[repeat_col] if repeat_col else ""
    out["repeat_count"] = out["repeat_raw"].map(repeat_count)
    out["repeat_group"] = out["repeat_count"].map(repeat_group_from_count)
    out["method"] = (df[method_col] if method_col else "").map(classify_method) if method_col else "その他"
    out["main_category"] = (df[item_col] if item_col else "").map(classify_category) if item_col else "その他"
    out["item_count_main"] = [parse_number(v, path, item_count_col) for v in df[item_count_col]] if item_count_col else 0.0
    out["source_file"] = path.name
    return out


def load_detail(month: str, status: str, path: Path) -> pd.DataFrame:
    df = read_csv(path)
    data_no_col = find_column(df, "data_no", path)
    category_col = find_column(df, "detail_category", path, required=False)
    quantity_col = find_column(df, "detail_quantity", path, required=False)
    out = pd.DataFrame(index=df.index)
    out["month"] = month
    out["status"] = status
    out["data_no"] = df[data_no_col].astype(str).str.strip()
    out["detail_category"] = (df[category_col] if category_col else "").map(classify_category) if category_col else "その他"
    out["detail_quantity"] = [parse_number(v, path, quantity_col) for v in df[quantity_col]] if quantity_col else 1.0
    out["detail_rows"] = 1
    return out


def build_dataset(root: Path) -> pd.DataFrame:
    main_frames: list[pd.DataFrame] = []
    detail_frames: list[pd.DataFrame] = []
    month_dirs = iter_month_dirs(root)
    if not month_dirs:
        raise FileNotFoundError("月フォルダが見つかりません。例: data/2026-01 または 202601")

    for month, folder in month_dirs:
        for kind, status, path in select_month_files(month, folder):
            if kind == "main":
                main_frames.append(load_main(month, status, path))
            else:
                detail_frames.append(load_detail(month, status, path))

    if not main_frames:
        raise FileNotFoundError("成約済み/未成約の本体CSVが見つかりません。")

    main = pd.concat(main_frames, ignore_index=True)
    if detail_frames:
        detail = pd.concat(detail_frames, ignore_index=True)
        detail_summary = (
            detail.groupby(["month", "status", "data_no"], as_index=False)
            .agg(
                detail_points=("detail_quantity", "sum"),
                detail_rows=("detail_rows", "sum"),
                category=("detail_category", category_mode),
                has_perfume=("detail_category", lambda s: bool((s == "香水").any())),
            )
        )
        df = main.merge(detail_summary, how="left", on=["month", "status", "data_no"])
    else:
        df = main.copy()
        df["detail_points"] = 0
        df["detail_rows"] = 0
        df["category"] = df["main_category"]
        df["has_perfume"] = df["category"].eq("香水")

    df["category"] = df["category"].fillna(df["main_category"]).map(lambda x: x if x in CATEGORIES else "その他")
    df["has_perfume"] = df["has_perfume"].fillna(df["category"].eq("香水")).astype(bool)
    df["points"] = df["item_count_main"].where(df["item_count_main"] > 0, df["detail_points"].fillna(0))
    df["is_single_item"] = df["points"].eq(1)
    df["amount_band"] = df["amount"].map(amount_band)
    return df


def conversion_rate(converted: int, total: int) -> float:
    return round(converted / total, 4) if total else 0.0


def summarize_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    for keys, g in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        converted = int((g["status"] == "成約").sum())
        unconverted = int((g["status"] == "未成約").sum())
        row = dict(zip(group_cols, keys))
        row.update(
            {
                "成約件数": converted,
                "未成約件数": unconverted,
                "全査定件数": converted + unconverted,
                "成約率": conversion_rate(converted, converted + unconverted),
                "成約金額合計": int(g.loc[g["status"] == "成約", "amount"].sum()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def make_monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month, g in df.groupby("month"):
        converted = g[g["status"] == "成約"]
        unconverted = g[g["status"] == "未成約"]
        total_amount = g["amount"].sum()
        rows.append(
            {
                "month": month,
                "成約件数": len(converted),
                "未成約件数": len(unconverted),
                "全査定件数": len(g),
                "成約率": conversion_rate(len(converted), len(g)),
                "成約査定額 平均": round(converted["amount"].mean(), 1) if len(converted) else 0,
                "未成約査定額 平均": round(unconverted["amount"].mean(), 1) if len(unconverted) else 0,
                "未成約中央値": round(unconverted["amount"].median(), 1) if len(unconverted) else 0,
                "成約査定金額 合計": int(converted["amount"].sum()),
                "未成約査定金額 合計": int(unconverted["amount"].sum()),
                "全査定金額 合計": int(total_amount),
                "成約金額率": round(converted["amount"].sum() / total_amount, 4) if total_amount else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values("month")


def make_repeat_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month in sorted(df["month"].unique()):
        month_df = df[df["month"] == month]
        for label, mask in [
            ("初回ユーザー", month_df["repeat_count"] <= 1),
            ("2回目以上ユーザー", month_df["repeat_count"] >= 2),
            ("5回以上ユーザー", month_df["repeat_count"] >= 5),
        ]:
            g = month_df[mask]
            converted = int((g["status"] == "成約").sum())
            unconverted = int((g["status"] == "未成約").sum())
            rows.append(
                {
                    "month": month,
                    "repeat_group": label,
                    "成約件数": converted,
                    "未成約件数": unconverted,
                    "全査定件数": converted + unconverted,
                    "成約率": conversion_rate(converted, converted + unconverted),
                    "成約金額合計": int(g.loc[g["status"] == "成約", "amount"].sum()),
                }
            )
    return pd.DataFrame(rows)


def ensure_all_groups(summary: pd.DataFrame, group_col: str, values: list[str], months: list[str]) -> pd.DataFrame:
    rows = []
    existing = {(row["month"], row[group_col]) for _, row in summary.iterrows()} if not summary.empty else set()
    for month in months:
        for value in values:
            if (month, value) not in existing:
                rows.append({"month": month, group_col: value, "成約件数": 0, "未成約件数": 0, "全査定件数": 0, "成約率": 0.0, "成約金額合計": 0})
    if rows:
        summary = pd.concat([summary, pd.DataFrame(rows)], ignore_index=True)
    summary["_order"] = summary[group_col].map({value: i for i, value in enumerate(values)}).fillna(999)
    return summary.sort_values(["month", "_order", group_col]).drop(columns="_order")


def make_deep_dive(df: pd.DataFrame) -> pd.DataFrame:
    unconverted = df[df["status"] == "未成約"].copy()
    reasons = []
    for _, row in unconverted.iterrows():
        items = []
        amount = row["amount"]
        if 7000 <= amount <= 12000:
            items.append("7,000〜12,000円の未成約")
        if 9000 <= amount <= 11000:
            items.append("10,000円前後なのに未成約")
        if row["repeat_count"] <= 1 and amount >= 7000:
            items.append("初回かつ7,000円以上の未成約")
        if bool(row["has_perfume"]) or row["category"] == "香水":
            items.append("香水カテゴリの未成約")
        if amount < 5000:
            items.append("5,000円未満の未成約")
        reasons.append(" / ".join(items))
    unconverted["該当条件"] = reasons
    cols = ["month", "data_no", "assessment_date", "amount", "amount_band", "category", "method", "points", "repeat_group", "repeat_count", "is_single_item", "該当条件", "source_file"]
    return unconverted[unconverted["該当条件"] != ""][cols].sort_values(["month", "amount"], ascending=[True, False])


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def yen(value: float) -> str:
    return f"{int(round(value)):,}円"


def diff_pt(current: float, previous: float | None) -> str:
    if previous is None:
        return "-"
    return f"{(current - previous) * 100:+.1f}pt"


def diff_num(current: float, previous: float | None, suffix: str = "") -> str:
    if previous is None:
        return "-"
    value = current - previous
    if suffix == "円":
        return f"{int(value):+,}円"
    return f"{int(value):+,d}{suffix}"


def row_for(df: pd.DataFrame, month: str, col: str | None = None, value: str | None = None) -> pd.Series | None:
    g = df[df["month"] == month]
    if col is not None:
        g = g[g[col] == value]
    if g.empty:
        return None
    return g.iloc[0]


def val(row: pd.Series | None, column: str, default: float = 0) -> float:
    if row is None:
        return default
    return row[column]


def md_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return lines


def top_unconverted(current_df: pd.DataFrame) -> pd.DataFrame:
    df = current_df[current_df["status"] == "未成約"].copy()
    df["priority"] = 99
    df.loc[(df["repeat_count"] <= 1) & (df["amount"] >= 10000), "priority"] = 1
    df.loc[(df["repeat_count"] <= 1) & (df["amount"].between(7000, 9999)), "priority"] = 2
    df.loc[(df["priority"] == 99) & (df["category"] == "香水"), "priority"] = 3
    df.loc[(df["priority"] == 99) & (df["is_single_item"]) & (df["amount"] >= 7000), "priority"] = 4
    df = df[df["priority"] < 99].copy()
    labels = {1: "初回かつ10,000円以上", 2: "初回かつ7,000〜9,999円", 3: "香水カテゴリ", 4: "単品高額"}
    df["優先理由"] = df["priority"].map(labels)
    return df.sort_values(["priority", "amount"], ascending=[True, False]).head(20)


def recent_months(monthly: pd.DataFrame, count: int = 6) -> list[str]:
    return monthly["month"].tolist()[-count:]


def unconverted_count(df: pd.DataFrame, month: str, condition: str) -> int:
    g = df[(df["month"] == month) & (df["status"] == "未成約")]
    if condition == "初回7000以上":
        return int(((g["repeat_count"] <= 1) & (g["amount"] >= 7000)).sum())
    if condition == "10000前後":
        return int(g["amount"].between(9000, 11000).sum())
    if condition == "5000未満":
        return int((g["amount"] < 5000).sum())
    if condition == "10000以上":
        return int((g["amount"] >= 10000).sum())
    if condition == "8000_12000":
        return int(g["amount"].between(8000, 11999).sum())
    if condition == "12000_20000":
        return int(g["amount"].between(12000, 19999).sum())
    if condition == "20000以上":
        return int((g["amount"] >= 20000).sum())
    if condition == "香水":
        return int((g["category"] == "香水").sum())
    return 0


def unconverted_amount(df: pd.DataFrame, month: str, condition: str) -> int:
    g = df[(df["month"] == month) & (df["status"] == "未成約")]
    if condition == "初回7000以上":
        g = g[(g["repeat_count"] <= 1) & (g["amount"] >= 7000)]
    elif condition == "初回7000_9999":
        g = g[(g["repeat_count"] <= 1) & (g["amount"].between(7000, 9999))]
    elif condition == "初回10000前後":
        g = g[(g["repeat_count"] <= 1) & (g["amount"].between(9000, 11000))]
    elif condition == "香水":
        g = g[g["category"] == "香水"]
    elif condition == "5000未満":
        g = g[g["amount"] < 5000]
    elif condition == "10000以上":
        g = g[g["amount"] >= 10000]
    elif condition == "8000_12000":
        g = g[g["amount"].between(8000, 11999)]
    elif condition == "12000_20000":
        g = g[g["amount"].between(12000, 19999)]
    elif condition == "20000以上":
        g = g[g["amount"] >= 20000]
    return int(g["amount"].sum())


def segment_count(df: pd.DataFrame, month: str, condition: str) -> int:
    g = df[(df["month"] == month) & (df["status"] == "未成約")]
    if condition == "初回7000以上":
        return int(((g["repeat_count"] <= 1) & (g["amount"] >= 7000)).sum())
    if condition == "初回7000_9999":
        return int(((g["repeat_count"] <= 1) & (g["amount"].between(7000, 9999))).sum())
    if condition == "初回10000前後":
        return int(((g["repeat_count"] <= 1) & (g["amount"].between(9000, 11000))).sum())
    if condition == "香水":
        return int((g["category"] == "香水").sum())
    if condition == "5000未満":
        return int((g["amount"] < 5000).sum())
    if condition == "10000以上":
        return int((g["amount"] >= 10000).sum())
    if condition == "8000_12000":
        return int(g["amount"].between(8000, 11999).sum())
    if condition == "12000_20000":
        return int(g["amount"].between(12000, 19999).sum())
    if condition == "20000以上":
        return int((g["amount"] >= 20000).sum())
    return 0


def low_amount_share(df: pd.DataFrame, month: str) -> float:
    g = df[df["month"] == month]
    return round((g["amount"] < 5000).mean(), 4) if len(g) else 0.0


def high_unconverted_count(df: pd.DataFrame, month: str) -> int:
    g = df[(df["month"] == month) & (df["status"] == "未成約")]
    return int((g["amount"] >= 20000).sum())


def make_recent_trend_rows(
    df: pd.DataFrame,
    monthly: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    category_summary: pd.DataFrame,
) -> list[list[object]]:
    rows = []
    for month in recent_months(monthly):
        m = row_for(monthly, month)
        first = row_for(repeat_summary, month, "repeat_group", "初回ユーザー")
        repeat5 = row_for(repeat_summary, month, "repeat_group", "5回以上ユーザー")
        perfume = row_for(category_summary, month, "category", "香水")
        supplement = row_for(category_summary, month, "category", "サプリ")
        rows.append(
            [
                month,
                f"{int(val(m, '成約件数'))}件",
                f"{int(val(m, '未成約件数'))}件",
                f"{int(val(m, '全査定件数'))}件",
                yen(val(m, "全査定金額 合計")),
                pct(val(m, "成約率")),
                yen(val(m, "成約査定金額 合計")),
                yen(val(m, "未成約査定金額 合計")),
                pct(val(m, "成約金額率")),
                pct(val(first, "成約率")),
                pct(val(repeat5, "成約率")),
                f"{unconverted_count(df, month, '初回7000_9999')}件",
                f"{unconverted_count(df, month, '8000_12000')}件",
                f"{unconverted_count(df, month, '12000_20000')}件",
                f"{unconverted_count(df, month, '20000以上')}件",
                pct(val(perfume, "成約率")),
                pct(val(supplement, "成約率")),
            ]
        )
    return rows


def make_analysis_comments(
    df: pd.DataFrame,
    monthly: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    category_summary: pd.DataFrame,
) -> list[str]:
    months = monthly["month"].tolist()
    if len(months) < 2:
        return ["前月データがないため、前月比較は未表示です。"]
    current, previous = months[-1], months[-2]
    cur_m = row_for(monthly, current)
    prev_m = row_for(monthly, previous)
    cur_first = row_for(repeat_summary, current, "repeat_group", "初回ユーザー")
    prev_first = row_for(repeat_summary, previous, "repeat_group", "初回ユーザー")
    cur_repeat5 = row_for(repeat_summary, current, "repeat_group", "5回以上ユーザー")
    prev_repeat5 = row_for(repeat_summary, previous, "repeat_group", "5回以上ユーザー")
    cur_perfume = row_for(category_summary, current, "category", "香水")
    prev_perfume = row_for(category_summary, previous, "category", "香水")
    cur_supplement = row_for(category_summary, current, "category", "サプリ")
    prev_supplement = row_for(category_summary, previous, "category", "サプリ")

    return [
        f"成約率は {pct(val(prev_m, '成約率'))} → {pct(val(cur_m, '成約率'))} でした。",
        f"成約査定金額合計は {yen(val(prev_m, '成約査定金額 合計'))} → {yen(val(cur_m, '成約査定金額 合計'))} でした。",
        f"初回成約率は {pct(val(prev_first, '成約率'))} → {pct(val(cur_first, '成約率'))} でした。",
        f"5回以上ユーザー成約率は {pct(val(prev_repeat5, '成約率'))} → {pct(val(cur_repeat5, '成約率'))} でした。",
        f"初回7,000〜9,999円未成約は {unconverted_count(df, previous, '初回7000_9999')}件 → {unconverted_count(df, current, '初回7000_9999')}件 でした。",
        f"8,000〜12,000円未成約は {unconverted_count(df, previous, '8000_12000')}件 → {unconverted_count(df, current, '8000_12000')}件 でした。",
        f"12,000〜20,000円未成約は {unconverted_count(df, previous, '12000_20000')}件 → {unconverted_count(df, current, '12000_20000')}件 でした。",
        f"20,000円以上未成約は {unconverted_count(df, previous, '20000以上')}件 → {unconverted_count(df, current, '20000以上')}件 でした。",
        f"香水カテゴリ成約率は {pct(val(prev_perfume, '成約率'))} → {pct(val(cur_perfume, '成約率'))} でした。",
        f"サプリカテゴリ成約率は {pct(val(prev_supplement, '成約率'))} → {pct(val(cur_supplement, '成約率'))} でした。",
    ]


def make_cause_candidates(
    df: pd.DataFrame,
    monthly: pd.DataFrame,
    repeat_summary: pd.DataFrame,
) -> list[str]:
    months = monthly["month"].tolist()
    if len(months) < 2:
        return []
    current, previous = months[-1], months[-2]
    cur_m = row_for(monthly, current)
    prev_m = row_for(monthly, previous)
    cur_first = row_for(repeat_summary, current, "repeat_group", "初回ユーザー")
    prev_first = row_for(repeat_summary, previous, "repeat_group", "初回ユーザー")
    rows = []

    if val(cur_m, "成約率") < val(prev_m, "成約率"):
        rows.append(f"全体成約率は {pct(val(prev_m, '成約率'))} → {pct(val(cur_m, '成約率'))} でした。")
        rows.append(f"初回成約率は {pct(val(prev_first, '成約率'))} → {pct(val(cur_first, '成約率'))} でした。")
        rows.append(f"5,000円未満構成比は {pct(low_amount_share(df, previous))} → {pct(low_amount_share(df, current))} でした。")
        rows.append(f"香水未成約は {unconverted_count(df, previous, '香水')}件 → {unconverted_count(df, current, '香水')}件 でした。")
        rows.append(f"成約査定金額合計は {yen(val(prev_m, '成約査定金額 合計'))} → {yen(val(cur_m, '成約査定金額 合計'))} でした。")

    if val(cur_m, "成約金額率") < val(prev_m, "成約金額率"):
        rows.append(f"成約金額率は {pct(val(prev_m, '成約金額率'))} → {pct(val(cur_m, '成約金額率'))} でした。")
        rows.append(f"20,000円以上未成約は {high_unconverted_count(df, previous)}件 → {high_unconverted_count(df, current)}件 でした。")
        rows.append(f"10,000円以上未成約は {unconverted_count(df, previous, '10000以上')}件 → {unconverted_count(df, current, '10000以上')}件 でした。")
        rows.append(f"初回7,000〜9,999円未成約は {unconverted_count(df, previous, '初回7000_9999')}件 → {unconverted_count(df, current, '初回7000_9999')}件 でした。")

    if not rows:
        rows.append("成約率と成約金額率は前月を下回っていません。")
    return rows


def make_improvement_segments(df: pd.DataFrame, latest_month: str, prev_month: str | None) -> list[list[object]]:
    definitions = [
        ("初回かつ7,000〜9,999円未成約", "初回7000_9999", "初回7,000〜9,999円の未成約確認"),
        ("8,000〜12,000円未成約", "8000_12000", "中高額帯の未成約確認"),
        ("12,000〜20,000円未成約", "12000_20000", "高額帯の未成約確認"),
        ("20,000円以上未成約", "20000以上", "高額未成約の個別確認"),
        ("香水カテゴリ未成約", "香水", "香水カテゴリの査定理由確認"),
        ("5,000円未満未成約", "5000未満", "低単価案件の対応方針確認"),
        ("10,000円以上未成約", "10000以上", "高額未成約の個別確認"),
    ]
    rows = []
    for label, key, comment in definitions:
        current_count = segment_count(df, latest_month, key)
        previous_count = segment_count(df, prev_month, key) if prev_month else None
        current_amount = unconverted_amount(df, latest_month, key)
        previous_amount = unconverted_amount(df, prev_month, key) if prev_month else None
        rows.append(
            [
                label,
                f"{current_count}件",
                yen(current_amount),
                diff_num(current_count, previous_count, "件") if previous_count is not None else "-",
                diff_num(current_amount, previous_amount, "円") if previous_amount is not None else "-",
                comment,
            ]
        )
    return rows


def evaluate_delta(current: float, previous: float | None, higher_is_better: bool = True, flat_threshold: float = 0.0001) -> str:
    if previous is None or abs(current - previous) <= flat_threshold:
        return "横ばい"
    improved = current > previous if higher_is_better else current < previous
    return "改善" if improved else "悪化"


def unconverted_segment_frame(df: pd.DataFrame, month: str, key: str) -> pd.DataFrame:
    g = df[(df["month"] == month) & (df["status"] == "未成約")]
    if key == "初回10000以上":
        return g[(g["repeat_count"] <= 1) & (g["amount"] >= 10000)]
    if key == "初回7000以上":
        return g[(g["repeat_count"] <= 1) & (g["amount"] >= 7000)]
    if key == "初回7000_9999":
        return g[(g["repeat_count"] <= 1) & (g["amount"].between(7000, 9999))]
    if key == "10000前後":
        return g[g["amount"].between(9000, 11000)]
    if key == "8000_12000":
        return g[g["amount"].between(8000, 11999)]
    if key == "12000_20000":
        return g[g["amount"].between(12000, 19999)]
    if key == "20000以上":
        return g[g["amount"] >= 20000]
    if key == "香水":
        return g[g["category"] == "香水"]
    if key == "5000未満":
        return g[g["amount"] < 5000]
    if key == "10000以上":
        return g[g["amount"] >= 10000]
    return g.iloc[0:0]


def unconverted_segment_stats(df: pd.DataFrame, month: str, key: str) -> dict[str, float]:
    g = unconverted_segment_frame(df, month, key)
    amount = float(g["amount"].sum()) if len(g) else 0.0
    return {
        "count": int(len(g)),
        "amount": amount,
        "avg": round(amount / len(g), 1) if len(g) else 0.0,
    }


def make_dashboard_summary(
    df: pd.DataFrame,
    monthly: pd.DataFrame,
    amount_summary: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    category_summary: pd.DataFrame,
    method_summary: pd.DataFrame,
) -> str:
    latest_month = monthly["month"].max()
    months = monthly["month"].tolist()
    prev_month = months[-2] if len(months) >= 2 else None
    current_df = df[df["month"] == latest_month]
    current_unconverted = current_df[current_df["status"] == "未成約"]
    prev_unconverted = df[(df["month"] == prev_month) & (df["status"] == "未成約")] if prev_month else pd.DataFrame(columns=df.columns)

    cur_m = row_for(monthly, latest_month)
    prev_m = row_for(monthly, prev_month) if prev_month else None
    cur_first = row_for(repeat_summary, latest_month, "repeat_group", "初回ユーザー")
    prev_first = row_for(repeat_summary, prev_month, "repeat_group", "初回ユーザー") if prev_month else None
    cur_repeat2 = row_for(repeat_summary, latest_month, "repeat_group", "2回目以上ユーザー")
    prev_repeat2 = row_for(repeat_summary, prev_month, "repeat_group", "2回目以上ユーザー") if prev_month else None
    cur_repeat5 = row_for(repeat_summary, latest_month, "repeat_group", "5回以上ユーザー")
    prev_repeat5 = row_for(repeat_summary, prev_month, "repeat_group", "5回以上ユーザー") if prev_month else None

    first_7000 = current_unconverted[(current_unconverted["repeat_count"] <= 1) & (current_unconverted["amount"] >= 7000)]
    first_around_10000 = current_unconverted[(current_unconverted["repeat_count"] <= 1) & (current_unconverted["amount"].between(9000, 11000))]
    perfume_unconverted = current_unconverted[current_unconverted["category"] == "香水"]
    under_5000 = current_unconverted[current_unconverted["amount"] < 5000]
    around_10000 = current_unconverted[current_unconverted["amount"].between(9000, 11000)]
    band_7000_12000 = current_unconverted[current_unconverted["amount"].between(7000, 12000)]
    prev_band_7000_12000 = prev_unconverted[prev_unconverted["amount"].between(7000, 12000)] if prev_month else prev_unconverted

    points: list[tuple[float, str]] = []
    points.append((abs(val(cur_m, "成約率") - val(prev_m, "成約率", val(cur_m, "成約率"))), f"全体成約率 {pct(val(prev_m, '成約率')) if prev_m is not None else '-'} → {pct(val(cur_m, '成約率'))}"))
    points.append((abs(val(cur_first, "成約率") - val(prev_first, "成約率", val(cur_first, "成約率"))), f"初回成約率 {pct(val(prev_first, '成約率')) if prev_first is not None else '-'} → {pct(val(cur_first, '成約率'))}"))
    points.append((abs(val(cur_repeat2, "成約率") - val(prev_repeat2, "成約率", val(cur_repeat2, "成約率"))), f"2回目以上成約率 {pct(val(prev_repeat2, '成約率')) if prev_repeat2 is not None else '-'} → {pct(val(cur_repeat2, '成約率'))}"))
    points.append((abs(len(band_7000_12000) - len(prev_band_7000_12000)), f"7,000〜12,000円未成約 {len(prev_band_7000_12000)}件 → {len(band_7000_12000)}件"))
    points.append((abs(val(cur_m, "成約査定金額 合計") - val(prev_m, "成約査定金額 合計", val(cur_m, "成約査定金額 合計"))) / 1000000, f"成約査定金額 {yen(val(prev_m, '成約査定金額 合計')) if prev_m is not None else '-'} → {yen(val(cur_m, '成約査定金額 合計'))}"))

    lines: list[str] = []
    lines.append(f"# 分析ダッシュボード（{latest_month}）")
    lines.append("")
    lines.append("## 注目ポイント")
    for _, text in sorted(points, reverse=True)[:5]:
        lines.append(f"- {text}")
    lines.append("")

    lines.append("## 1. 全体")
    lines += md_table(
        ["項目", latest_month, f"前月比({prev_month})" if prev_month else "前月比"],
        [
            ["成約件数", f"{int(val(cur_m, '成約件数'))}件", diff_num(val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, "件")],
            ["未成約件数", f"{int(val(cur_m, '未成約件数'))}件", diff_num(val(cur_m, "未成約件数"), val(prev_m, "未成約件数") if prev_m is not None else None, "件")],
            ["全査定件数", f"{int(val(cur_m, '全査定件数'))}件", diff_num(val(cur_m, "全査定件数"), val(prev_m, "全査定件数") if prev_m is not None else None, "件")],
            ["成約率", pct(val(cur_m, "成約率")), diff_pt(val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None)],
        ],
    )
    lines.append("")

    lines.append("## 2. 成約金額")
    lines += md_table(
        ["項目", latest_month, f"前月比({prev_month})" if prev_month else "前月比"],
        [
            ["成約査定金額合計", yen(val(cur_m, "成約査定金額 合計")), diff_num(val(cur_m, "成約査定金額 合計"), val(prev_m, "成約査定金額 合計") if prev_m is not None else None, "円")],
            ["未成約査定金額合計", yen(val(cur_m, "未成約査定金額 合計")), diff_num(val(cur_m, "未成約査定金額 合計"), val(prev_m, "未成約査定金額 合計") if prev_m is not None else None, "円")],
            ["全査定金額合計", yen(val(cur_m, "全査定金額 合計")), diff_num(val(cur_m, "全査定金額 合計"), val(prev_m, "全査定金額 合計") if prev_m is not None else None, "円")],
            ["成約金額率", pct(val(cur_m, "成約金額率")), diff_pt(val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None)],
        ],
    )
    lines.append("")

    lines.append("## 3. 初回ユーザー")
    lines += md_table(
        ["項目", latest_month, f"前月比({prev_month})" if prev_month else "前月比"],
        [
            ["初回成約件数", f"{int(val(cur_first, '成約件数'))}件", diff_num(val(cur_first, "成約件数"), val(prev_first, "成約件数") if prev_first is not None else None, "件")],
            ["初回未成約件数", f"{int(val(cur_first, '未成約件数'))}件", diff_num(val(cur_first, "未成約件数"), val(prev_first, "未成約件数") if prev_first is not None else None, "件")],
            ["初回成約率", pct(val(cur_first, "成約率")), diff_pt(val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None)],
            ["初回かつ7,000円以上未成約", f"{len(first_7000)}件", ""],
            ["初回かつ10,000円前後未成約", f"{len(first_around_10000)}件", ""],
        ],
    )
    lines.append("")

    lines.append("## 4. リピーター")
    lines += md_table(
        ["項目", latest_month, f"前月比({prev_month})" if prev_month else "前月比"],
        [
            ["2回目以上成約率", pct(val(cur_repeat2, "成約率")), diff_pt(val(cur_repeat2, "成約率"), val(prev_repeat2, "成約率") if prev_repeat2 is not None else None)],
            ["5回以上成約率", pct(val(cur_repeat5, "成約率")), diff_pt(val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None)],
        ],
    )
    lines.append("")

    lines.append("## 5. 金額帯分析")
    rows = []
    for band, _, _ in AMOUNT_BANDS:
        cur = row_for(amount_summary, latest_month, "amount_band", band)
        prev = row_for(amount_summary, prev_month, "amount_band", band) if prev_month else None
        rows.append([band, f"{int(val(cur, '成約件数'))}件", f"{int(val(cur, '未成約件数'))}件", pct(val(cur, "成約率")), diff_pt(val(cur, "成約率"), val(prev, "成約率") if prev is not None else None), diff_num(val(cur, "全査定件数"), val(prev, "全査定件数") if prev is not None else None, "件")])
    lines += md_table(["金額帯", "成約", "未成約", "成約率", "前月比", "件数変化"], rows)
    lines.append("")

    lines.append("## 6. カテゴリ分析")
    rows = []
    for cat in CATEGORIES:
        cur = row_for(category_summary, latest_month, "category", cat)
        prev = row_for(category_summary, prev_month, "category", cat) if prev_month else None
        rows.append([cat, f"{int(val(cur, '成約件数'))}件", f"{int(val(cur, '未成約件数'))}件", pct(val(cur, "成約率")), diff_pt(val(cur, "成約率"), val(prev, "成約率") if prev is not None else None)])
    lines += md_table(["カテゴリ", "成約", "未成約", "成約率", "前月比較"], rows)
    lines.append("")

    lines.append("## 7. 査定方法分析")
    rows = []
    for method in METHODS:
        cur = row_for(method_summary, latest_month, "method", method)
        prev = row_for(method_summary, prev_month, "method", method) if prev_month else None
        rows.append([method, pct(val(cur, "成約率")), yen(val(cur, "成約金額合計")), diff_pt(val(cur, "成約率"), val(prev, "成約率") if prev is not None else None)])
    lines += md_table(["査定方法", "成約率", "成約金額", "前月比較"], rows)
    lines.append("")

    lines.append("## 未成約の特徴")
    total_unconverted = len(current_unconverted)
    first_ratio = (current_unconverted["repeat_count"] <= 1).mean() if total_unconverted else 0
    single_ratio = current_unconverted["is_single_item"].mean() if total_unconverted else 0
    perfume_ratio = current_unconverted["category"].eq("香水").mean() if total_unconverted else 0
    lines.append(f"- 未成約{total_unconverted}件のうち、初回{int((current_unconverted['repeat_count'] <= 1).sum())}件、初回比率{pct(first_ratio)}")
    lines.append(f"- 未成約{total_unconverted}件のうち、単品{int(current_unconverted['is_single_item'].sum())}件、単品比率{pct(single_ratio)}")
    lines.append(f"- 未成約{total_unconverted}件のうち、香水{len(perfume_unconverted)}件、香水比率{pct(perfume_ratio)}")
    if len(around_10000):
        lines.append(f"- 10,000円前後未成約{len(around_10000)}件、初回{int((around_10000['repeat_count'] <= 1).sum())}件、単品{int(around_10000['is_single_item'].sum())}件、香水{int(around_10000['category'].eq('香水').sum())}件")
    else:
        lines.append("- 10,000円前後未成約0件")
    if len(band_7000_12000):
        lines.append(f"- 7,000〜12,000円未成約{len(band_7000_12000)}件、初回{int((band_7000_12000['repeat_count'] <= 1).sum())}件、単品{int(band_7000_12000['is_single_item'].sum())}件、香水{int(band_7000_12000['category'].eq('香水').sum())}件")
    else:
        lines.append("- 7,000〜12,000円未成約0件")
    lines.append("")

    lines.append("## 改善仮説")
    lines.append(f"- 初回7,000円以上の未成約 {len(first_7000)}件")
    lines.append(f"- 5,000円未満の成約率 {pct(val(row_for(amount_summary, latest_month, 'amount_band', '0〜2,999円'), '成約率'))} / {pct(val(row_for(amount_summary, latest_month, 'amount_band', '3,000〜4,999円'), '成約率'))}")
    lines.append(f"- 香水未成約 {len(perfume_unconverted)}件、香水成約率 {pct(val(row_for(category_summary, latest_month, 'category', '香水'), '成約率'))}")
    lines.append(f"- 5回以上ユーザー成約率 {pct(val(cur_repeat5, '成約率'))}")
    lines.append("")

    lines.append("## 深掘りリスト")
    lines += md_table(
        ["条件", "件数"],
        [
            ["初回かつ7,000円以上未成約", f"{len(first_7000)}件"],
            ["初回かつ10,000円前後未成約", f"{len(first_around_10000)}件"],
            ["香水未成約", f"{len(perfume_unconverted)}件"],
            ["5,000円未満未成約", f"{len(under_5000)}件"],
        ],
    )
    lines.append("")

    lines.append("## 分析コメント")
    for comment in make_analysis_comments(df, monthly, repeat_summary, category_summary):
        lines.append(f"- {comment}")
    lines.append("")

    lines.append("## 原因候補")
    for comment in make_cause_candidates(df, monthly, repeat_summary):
        lines.append(f"- {comment}")
    lines.append("")

    lines.append("## 過去半年推移")
    lines += md_table(
        [
            "月",
            "成約",
            "未成約",
            "全査定",
            "全査定金額",
            "成約率",
            "成約査定金額",
            "未成約査定金額",
            "成約金額率",
            "初回成約率",
            "5回以上成約率",
            "初回7,000〜9,999円未成約",
            "8,000〜12,000円未成約",
            "12,000〜20,000円未成約",
            "20,000円以上未成約",
            "香水成約率",
            "サプリ成約率",
        ],
        make_recent_trend_rows(df, monthly, repeat_summary, category_summary),
    )
    lines.append("")

    lines.append("## 改善対象セグメント")
    lines += md_table(
        ["セグメント", "件数", "査定金額合計", "件数前月比", "金額前月比", "コメント"],
        make_improvement_segments(df, latest_month, prev_month),
    )
    lines.append("")

    lines.append("## 今月確認優先の未成約案件 TOP20")
    top20 = top_unconverted(current_df)
    if top20.empty:
        lines.append("- 対象なし")
    else:
        rows = []
        for _, row in top20.iterrows():
            rows.append([row["優先理由"], row["data_no"], yen(row["amount"]), row["category"], row["method"], f"{int(row['points'])}点", row["repeat_group"]])
        lines += md_table(["優先理由", "データNo", "査定額", "カテゴリ", "方法", "点数", "利用回数"], rows)

    return "\n".join(lines) + "\n"


def make_report(monthly: pd.DataFrame, amount_summary: pd.DataFrame, repeat_summary: pd.DataFrame, category_summary: pd.DataFrame, method_summary: pd.DataFrame, deep_dive: pd.DataFrame) -> str:
    latest_month = monthly["month"].max()
    lines = ["# 査定月別 成約・未成約分析", "", "## 月別サマリー"]
    for _, row in monthly.iterrows():
        lines.append(f"- {row['month']}: 成約{int(row['成約件数'])}件、未成約{int(row['未成約件数'])}件、全査定{int(row['全査定件数'])}件、成約率{pct(row['成約率'])}、成約査定金額合計{yen(row['成約査定金額 合計'])}")
    lines.append("")
    lines.append(f"詳細は dashboard_summary.md を確認。最新月: {latest_month}")
    return "\n".join(lines) + "\n"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def delta_class(current: float, previous: float | None, higher_is_better: bool = True) -> str:
    if previous is None or current == previous:
        return "neutral"
    improved = current > previous if higher_is_better else current < previous
    return "good" if improved else "bad"


def delta_span(text: str, current: float, previous: float | None, higher_is_better: bool = True) -> str:
    return f'<span class="delta {delta_class(current, previous, higher_is_better)}">{esc(text)}</span>'


def html_table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{cell if isinstance(cell, HtmlCell) else esc(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


class HtmlCell(str):
    pass


def chart_data_uri(path: Path) -> str | None:
    if not path.exists():
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def chart_figure(charts_dir: Path, filename: str, title: str) -> str:
    uri = chart_data_uri(charts_dir / filename)
    if not uri:
        return ""
    return f'<figure><img src="{uri}" alt="{esc(title)}"><figcaption>{esc(title)}</figcaption></figure>'


def make_dashboard_summary_html(
    df: pd.DataFrame,
    monthly: pd.DataFrame,
    amount_summary: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    category_summary: pd.DataFrame,
    method_summary: pd.DataFrame,
    charts_dir: Path,
) -> str:
    latest_month = monthly["month"].max()
    months = monthly["month"].tolist()
    prev_month = months[-2] if len(months) >= 2 else None
    current_df = df[df["month"] == latest_month]
    current_unconverted = current_df[current_df["status"] == "未成約"]
    prev_unconverted = df[(df["month"] == prev_month) & (df["status"] == "未成約")] if prev_month else pd.DataFrame(columns=df.columns)

    cur_m = row_for(monthly, latest_month)
    prev_m = row_for(monthly, prev_month) if prev_month else None
    cur_first = row_for(repeat_summary, latest_month, "repeat_group", "初回ユーザー")
    prev_first = row_for(repeat_summary, prev_month, "repeat_group", "初回ユーザー") if prev_month else None
    cur_repeat2 = row_for(repeat_summary, latest_month, "repeat_group", "2回目以上ユーザー")
    prev_repeat2 = row_for(repeat_summary, prev_month, "repeat_group", "2回目以上ユーザー") if prev_month else None
    cur_repeat5 = row_for(repeat_summary, latest_month, "repeat_group", "5回以上ユーザー")
    prev_repeat5 = row_for(repeat_summary, prev_month, "repeat_group", "5回以上ユーザー") if prev_month else None

    first_7000 = current_unconverted[(current_unconverted["repeat_count"] <= 1) & (current_unconverted["amount"] >= 7000)]
    first_around_10000 = current_unconverted[(current_unconverted["repeat_count"] <= 1) & (current_unconverted["amount"].between(9000, 11000))]
    perfume_unconverted = current_unconverted[current_unconverted["category"] == "香水"]
    under_5000 = current_unconverted[current_unconverted["amount"] < 5000]
    around_10000 = current_unconverted[current_unconverted["amount"].between(9000, 11000)]
    band_7000_12000 = current_unconverted[current_unconverted["amount"].between(7000, 12000)]
    prev_band_7000_12000 = prev_unconverted[prev_unconverted["amount"].between(7000, 12000)] if prev_month else prev_unconverted

    point_items: list[tuple[float, str]] = [
        (abs(val(cur_m, "成約率") - val(prev_m, "成約率", val(cur_m, "成約率"))), f"全体成約率 {pct(val(prev_m, '成約率')) if prev_m is not None else '-'} → {pct(val(cur_m, '成約率'))}"),
        (abs(val(cur_first, "成約率") - val(prev_first, "成約率", val(cur_first, "成約率"))), f"初回成約率 {pct(val(prev_first, '成約率')) if prev_first is not None else '-'} → {pct(val(cur_first, '成約率'))}"),
        (abs(val(cur_repeat2, "成約率") - val(prev_repeat2, "成約率", val(cur_repeat2, "成約率"))), f"2回目以上成約率 {pct(val(prev_repeat2, '成約率')) if prev_repeat2 is not None else '-'} → {pct(val(cur_repeat2, '成約率'))}"),
        (abs(len(band_7000_12000) - len(prev_band_7000_12000)), f"7,000〜12,000円未成約 {len(prev_band_7000_12000)}件 → {len(band_7000_12000)}件"),
        (abs(val(cur_m, "成約査定金額 合計") - val(prev_m, "成約査定金額 合計", val(cur_m, "成約査定金額 合計"))) / 1000000, f"成約査定金額 {yen(val(prev_m, '成約査定金額 合計')) if prev_m is not None else '-'} → {yen(val(cur_m, '成約査定金額 合計'))}"),
    ]
    point_html = "".join(f"<li>{esc(text)}</li>" for _, text in sorted(point_items, reverse=True)[:5])

    cards = [
        ("成約率", pct(val(cur_m, "成約率")), diff_pt(val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None), val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None, True),
        ("成約件数", f"{int(val(cur_m, '成約件数'))}件", diff_num(val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, "件"), val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, True),
        ("未成約件数", f"{int(val(cur_m, '未成約件数'))}件", diff_num(val(cur_m, "未成約件数"), val(prev_m, "未成約件数") if prev_m is not None else None, "件"), val(cur_m, "未成約件数"), val(prev_m, "未成約件数") if prev_m is not None else None, False),
        ("成約金額率", pct(val(cur_m, "成約金額率")), diff_pt(val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None), val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None, True),
        ("初回成約率", pct(val(cur_first, "成約率")), diff_pt(val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None), val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None, True),
        ("5回以上成約率", pct(val(cur_repeat5, "成約率")), diff_pt(val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None), val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None, True),
    ]
    card_html = "".join(
        f'<div class="card"><div class="card-label">{esc(label)}</div><div class="card-value">{esc(value_text)}</div>{delta_span(delta_text, current, previous, high_good)}</div>'
        for label, value_text, delta_text, current, previous, high_good in cards
    )

    def dspan(text: str, current: float, previous: float | None, high_good: bool = True) -> HtmlCell:
        return HtmlCell(delta_span(text, current, previous, high_good))

    sections: list[str] = []
    sections.append('<section><h2>1. 全体</h2>' + html_table(
        ["項目", latest_month, f"前月比({prev_month})" if prev_month else "前月比"],
        [
            ["成約件数", f"{int(val(cur_m, '成約件数'))}件", dspan(diff_num(val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, "件"), val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, True)],
            ["未成約件数", f"{int(val(cur_m, '未成約件数'))}件", dspan(diff_num(val(cur_m, "未成約件数"), val(prev_m, "未成約件数") if prev_m is not None else None, "件"), val(cur_m, "未成約件数"), val(prev_m, "未成約件数") if prev_m is not None else None, False)],
            ["全査定件数", f"{int(val(cur_m, '全査定件数'))}件", diff_num(val(cur_m, "全査定件数"), val(prev_m, "全査定件数") if prev_m is not None else None, "件")],
            ["成約率", pct(val(cur_m, "成約率")), dspan(diff_pt(val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None), val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None, True)],
        ],
    ) + "</section>")

    sections.append('<section><h2>2. 成約金額</h2>' + html_table(
        ["項目", latest_month, f"前月比({prev_month})" if prev_month else "前月比"],
        [
            ["成約査定金額合計", yen(val(cur_m, "成約査定金額 合計")), dspan(diff_num(val(cur_m, "成約査定金額 合計"), val(prev_m, "成約査定金額 合計") if prev_m is not None else None, "円"), val(cur_m, "成約査定金額 合計"), val(prev_m, "成約査定金額 合計") if prev_m is not None else None, True)],
            ["未成約査定金額合計", yen(val(cur_m, "未成約査定金額 合計")), dspan(diff_num(val(cur_m, "未成約査定金額 合計"), val(prev_m, "未成約査定金額 合計") if prev_m is not None else None, "円"), val(cur_m, "未成約査定金額 合計"), val(prev_m, "未成約査定金額 合計") if prev_m is not None else None, False)],
            ["全査定金額合計", yen(val(cur_m, "全査定金額 合計")), diff_num(val(cur_m, "全査定金額 合計"), val(prev_m, "全査定金額 合計") if prev_m is not None else None, "円")],
            ["成約金額率", pct(val(cur_m, "成約金額率")), dspan(diff_pt(val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None), val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None, True)],
        ],
    ) + "</section>")

    sections.append('<section><h2>3. 初回ユーザー</h2>' + html_table(
        ["項目", latest_month, f"前月比({prev_month})" if prev_month else "前月比"],
        [
            ["初回成約件数", f"{int(val(cur_first, '成約件数'))}件", dspan(diff_num(val(cur_first, "成約件数"), val(prev_first, "成約件数") if prev_first is not None else None, "件"), val(cur_first, "成約件数"), val(prev_first, "成約件数") if prev_first is not None else None, True)],
            ["初回未成約件数", f"{int(val(cur_first, '未成約件数'))}件", dspan(diff_num(val(cur_first, "未成約件数"), val(prev_first, "未成約件数") if prev_first is not None else None, "件"), val(cur_first, "未成約件数"), val(prev_first, "未成約件数") if prev_first is not None else None, False)],
            ["初回成約率", pct(val(cur_first, "成約率")), dspan(diff_pt(val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None), val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None, True)],
            ["初回かつ7,000円以上未成約", f"{len(first_7000)}件", ""],
            ["初回かつ10,000円前後未成約", f"{len(first_around_10000)}件", ""],
        ],
    ) + "</section>")

    sections.append('<section><h2>4. リピーター</h2>' + html_table(
        ["項目", latest_month, f"前月比({prev_month})" if prev_month else "前月比"],
        [
            ["2回目以上成約率", pct(val(cur_repeat2, "成約率")), dspan(diff_pt(val(cur_repeat2, "成約率"), val(prev_repeat2, "成約率") if prev_repeat2 is not None else None), val(cur_repeat2, "成約率"), val(prev_repeat2, "成約率") if prev_repeat2 is not None else None, True)],
            ["5回以上成約率", pct(val(cur_repeat5, "成約率")), dspan(diff_pt(val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None), val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None, True)],
        ],
    ) + "</section>")

    amount_rows = []
    for band, _, _ in AMOUNT_BANDS:
        cur = row_for(amount_summary, latest_month, "amount_band", band)
        prev = row_for(amount_summary, prev_month, "amount_band", band) if prev_month else None
        amount_rows.append([band, f"{int(val(cur, '成約件数'))}件", f"{int(val(cur, '未成約件数'))}件", pct(val(cur, "成約率")), dspan(diff_pt(val(cur, "成約率"), val(prev, "成約率") if prev is not None else None), val(cur, "成約率"), val(prev, "成約率") if prev is not None else None, True), diff_num(val(cur, "全査定件数"), val(prev, "全査定件数") if prev is not None else None, "件")])
    sections.append('<section><h2>5. 金額帯分析</h2>' + html_table(["金額帯", "成約", "未成約", "成約率", "前月比", "件数変化"], amount_rows) + "</section>")

    category_rows = []
    for cat in CATEGORIES:
        cur = row_for(category_summary, latest_month, "category", cat)
        prev = row_for(category_summary, prev_month, "category", cat) if prev_month else None
        category_rows.append([cat, f"{int(val(cur, '成約件数'))}件", f"{int(val(cur, '未成約件数'))}件", pct(val(cur, "成約率")), dspan(diff_pt(val(cur, "成約率"), val(prev, "成約率") if prev is not None else None), val(cur, "成約率"), val(prev, "成約率") if prev is not None else None, True)])
    sections.append('<section><h2>6. カテゴリ分析</h2>' + html_table(["カテゴリ", "成約", "未成約", "成約率", "前月比較"], category_rows) + "</section>")

    method_rows = []
    for method in METHODS:
        cur = row_for(method_summary, latest_month, "method", method)
        prev = row_for(method_summary, prev_month, "method", method) if prev_month else None
        method_rows.append([method, pct(val(cur, "成約率")), yen(val(cur, "成約金額合計")), dspan(diff_pt(val(cur, "成約率"), val(prev, "成約率") if prev is not None else None), val(cur, "成約率"), val(prev, "成約率") if prev is not None else None, True)])
    sections.append('<section><h2>7. 査定方法分析</h2>' + html_table(["査定方法", "成約率", "成約金額", "前月比較"], method_rows) + "</section>")

    total_unconverted = len(current_unconverted)
    first_ratio = (current_unconverted["repeat_count"] <= 1).mean() if total_unconverted else 0
    single_ratio = current_unconverted["is_single_item"].mean() if total_unconverted else 0
    perfume_ratio = current_unconverted["category"].eq("香水").mean() if total_unconverted else 0
    features = [
        f"未成約{total_unconverted}件のうち、初回{int((current_unconverted['repeat_count'] <= 1).sum())}件、初回比率{pct(first_ratio)}",
        f"未成約{total_unconverted}件のうち、単品{int(current_unconverted['is_single_item'].sum())}件、単品比率{pct(single_ratio)}",
        f"未成約{total_unconverted}件のうち、香水{len(perfume_unconverted)}件、香水比率{pct(perfume_ratio)}",
        f"10,000円前後未成約{len(around_10000)}件、初回{int((around_10000['repeat_count'] <= 1).sum()) if len(around_10000) else 0}件、単品{int(around_10000['is_single_item'].sum()) if len(around_10000) else 0}件、香水{int(around_10000['category'].eq('香水').sum()) if len(around_10000) else 0}件",
        f"7,000〜12,000円未成約{len(band_7000_12000)}件、初回{int((band_7000_12000['repeat_count'] <= 1).sum()) if len(band_7000_12000) else 0}件、単品{int(band_7000_12000['is_single_item'].sum()) if len(band_7000_12000) else 0}件、香水{int(band_7000_12000['category'].eq('香水').sum()) if len(band_7000_12000) else 0}件",
    ]
    sections.append('<section><h2>未成約の特徴</h2><ul class="plain-list">' + "".join(f"<li>{esc(x)}</li>" for x in features) + "</ul></section>")

    hypotheses = [
        f"初回7,000円以上の未成約 {len(first_7000)}件",
        f"5,000円未満の成約率 {pct(val(row_for(amount_summary, latest_month, 'amount_band', '0〜2,999円'), '成約率'))} / {pct(val(row_for(amount_summary, latest_month, 'amount_band', '3,000〜4,999円'), '成約率'))}",
        f"香水未成約 {len(perfume_unconverted)}件、香水成約率 {pct(val(row_for(category_summary, latest_month, 'category', '香水'), '成約率'))}",
        f"5回以上ユーザー成約率 {pct(val(cur_repeat5, '成約率'))}",
    ]
    sections.append('<section><h2>改善仮説</h2><ul class="plain-list">' + "".join(f"<li>{esc(x)}</li>" for x in hypotheses) + "</ul></section>")

    sections.append('<section><h2>深掘りリスト</h2>' + html_table(
        ["条件", "件数"],
        [
            ["初回かつ7,000円以上未成約", f"{len(first_7000)}件"],
            ["初回かつ10,000円前後未成約", f"{len(first_around_10000)}件"],
            ["香水未成約", f"{len(perfume_unconverted)}件"],
            ["5,000円未満未成約", f"{len(under_5000)}件"],
        ],
    ) + "</section>")

    top20 = top_unconverted(current_df)
    if top20.empty:
        top_html = '<p class="empty">対象なし</p>'
    else:
        top_rows = [[row["優先理由"], row["data_no"], yen(row["amount"]), row["category"], row["method"], f"{int(row['points'])}点", row["repeat_group"]] for _, row in top20.iterrows()]
        top_html = html_table(["優先理由", "データNo", "査定額", "カテゴリ", "方法", "点数", "利用回数"], top_rows)
    sections.append('<section><h2>今月確認優先の未成約案件 TOP20</h2>' + top_html + "</section>")

    charts_html = "".join(
        chart_figure(charts_dir, filename, title)
        for filename, title in [
            ("recent_conversion_rate.png", "過去半年 成約率推移"),
            ("recent_converted_amount.png", "過去半年 成約査定金額合計推移"),
            ("recent_first_conversion_rate.png", "過去半年 初回成約率推移"),
            ("recent_repeat5_conversion_rate.png", "過去半年 5回以上ユーザー成約率推移"),
            ("recent_amount_band_conversion_rate.png", "過去半年 金額帯別成約率推移"),
            ("recent_category_conversion_rate.png", "過去半年 カテゴリ別成約率推移"),
            ("monthly_conversion_rate.png", "月別成約率推移"),
            ("first_user_conversion_rate.png", "初回成約率推移"),
            ("amount_band_conversion_rate.png", "金額帯別成約率"),
            ("category_conversion_rate.png", "カテゴリ別成約率"),
        ]
    )

    analysis_html = (
        '<section><h2>分析コメント</h2><ul class="plain-list">'
        + "".join(f"<li>{esc(x)}</li>" for x in make_analysis_comments(df, monthly, repeat_summary, category_summary))
        + "</ul><h3>原因候補</h3><ul class=\"plain-list\">"
        + "".join(f"<li>{esc(x)}</li>" for x in make_cause_candidates(df, monthly, repeat_summary))
        + "</ul></section>"
    )
    trend_html = '<section><h2>過去半年推移</h2>' + html_table(
        [
            "月",
            "成約",
            "未成約",
            "全査定",
            "全査定金額",
            "成約率",
            "成約査定金額",
            "未成約査定金額",
            "成約金額率",
            "初回成約率",
            "5回以上成約率",
            "初回7,000〜9,999円未成約",
            "8,000〜12,000円未成約",
            "12,000〜20,000円未成約",
            "20,000円以上未成約",
            "香水成約率",
            "サプリ成約率",
        ],
        make_recent_trend_rows(df, monthly, repeat_summary, category_summary),
    ) + "</section>"
    segment_rows = []
    for label, key, comment in [
        ("初回かつ7,000〜9,999円未成約", "初回7000_9999", "初回7,000〜9,999円の未成約確認"),
        ("8,000〜12,000円未成約", "8000_12000", "中高額帯の未成約確認"),
        ("12,000〜20,000円未成約", "12000_20000", "高額帯の未成約確認"),
        ("20,000円以上未成約", "20000以上", "高額未成約の個別確認"),
        ("香水カテゴリ未成約", "香水", "香水カテゴリの査定理由確認"),
        ("5,000円未満未成約", "5000未満", "低単価案件の対応方針確認"),
        ("10,000円以上未成約", "10000以上", "高額未成約の個別確認"),
    ]:
        current_count = segment_count(df, latest_month, key)
        previous_count = segment_count(df, prev_month, key) if prev_month else None
        current_amount = unconverted_amount(df, latest_month, key)
        previous_amount = unconverted_amount(df, prev_month, key) if prev_month else None
        segment_rows.append(
            [
                label,
                f"{current_count}件",
                yen(current_amount),
                dspan(diff_num(current_count, previous_count, "件") if previous_count is not None else "-", current_count, previous_count, False),
                dspan(diff_num(current_amount, previous_amount, "円") if previous_amount is not None else "-", current_amount, previous_amount, False),
                comment,
            ]
        )
    segment_html = '<section><h2>改善対象セグメント</h2>' + html_table(
        ["セグメント", "件数", "査定金額合計", "件数前月比", "金額前月比", "コメント"],
        segment_rows,
    ) + "</section>"
    ordered_sections = "".join([sections[4], sections[5], sections[6], sections[7], segment_html, sections[-1]])

    css = """
body{margin:0;background:#fff;color:#1f2937;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Yu Gothic",Meiryo,sans-serif;line-height:1.55}
.page{max-width:1180px;margin:0 auto;padding:32px 28px 56px}
header{border-bottom:3px solid #1f2937;padding-bottom:18px;margin-bottom:24px}
h1{font-size:30px;margin:0 0 6px}
.subtitle{color:#64748b;margin:0}
h2{font-size:20px;margin:0 0 14px;border-left:6px solid #2563eb;padding-left:10px}
h3{font-size:16px;margin:18px 0 8px;color:#334155}
section{margin:28px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:18px 0 24px}
.card{border:1px solid #dbe3ef;border-radius:8px;padding:14px 16px;background:#f8fafc}
.card-label{font-size:13px;color:#64748b}.card-value{font-size:26px;font-weight:700;margin:4px 0}
.focus{background:#eef6ff;border:1px solid #bfdbfe;border-radius:8px;padding:18px 20px}
.focus h2{border-left-color:#0ea5e9}.focus ul{margin:0;padding-left:20px;font-size:17px;font-weight:650}
.table-wrap{overflow-x:auto;border:1px solid #dbe3ef;border-radius:8px}
table{width:100%;border-collapse:collapse;background:#fff}
th{background:#f1f5f9;text-align:left;color:#334155;font-weight:700}
th,td{padding:10px 12px;border-bottom:1px solid #e5e7eb;white-space:nowrap}
tbody tr:nth-child(even){background:#fafafa}
.delta{display:inline-block;font-weight:700;padding:2px 8px;border-radius:999px}
.delta.good{color:#047857;background:#d1fae5}.delta.bad{color:#b91c1c;background:#fee2e2}.delta.neutral{color:#475569;background:#e2e8f0}
.plain-list{margin:0;padding-left:20px}.plain-list li{margin:6px 0}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:18px}
figure{margin:0;border:1px solid #dbe3ef;border-radius:8px;padding:12px;background:#fff}
img{width:100%;height:auto;display:block}figcaption{font-size:13px;color:#64748b;margin-top:8px}
.empty{color:#64748b}
@media print{.page{max-width:none;padding:16px}.cards{grid-template-columns:repeat(3,1fr)}section{break-inside:avoid}.charts{grid-template-columns:repeat(2,1fr)}}
"""

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>分析ダッシュボード（{esc(latest_month)}）</title>
<style>{css}</style>
</head>
<body>
<main class="page">
<header>
<h1>分析ダッシュボード（{esc(latest_month)}）</h1>
<p class="subtitle">査定月基準 / 前月比較: {esc(prev_month or "-")}</p>
</header>
<section>
<h2>今月の重要指標</h2>
<div class="cards">{card_html}</div>
</section>
{analysis_html}
<section class="focus">
<h2>注目ポイント</h2>
<ul>{point_html}</ul>
</section>
{trend_html}
<section>
<h2>グラフ</h2>
<div class="charts">{charts_html}</div>
</section>
{ordered_sections}
</main>
</body>
</html>
"""


def make_dashboard_summary_html(
    df: pd.DataFrame,
    monthly: pd.DataFrame,
    amount_summary: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    category_summary: pd.DataFrame,
    method_summary: pd.DataFrame,
    charts_dir: Path,
) -> str:
    months = monthly["month"].tolist()
    latest_month = months[-1]

    def metric(month: str, table: pd.DataFrame, col: str | None = None, value: str | None = None) -> pd.Series | None:
        return row_for(table, month, col, value)

    def table_rows_for(month: str, summary: pd.DataFrame, group_col: str, groups: list[str]) -> list[dict[str, object]]:
        rows = []
        for group in groups:
            row = metric(month, summary, group_col, group)
            rows.append(
                {
                    "label": group,
                    "converted": int(val(row, "成約件数")),
                    "unconverted": int(val(row, "未成約件数")),
                    "total": int(val(row, "全査定件数")),
                    "rate": val(row, "成約率"),
                    "rateText": pct(val(row, "成約率")),
                    "convertedAmount": int(val(row, "成約金額合計")),
                    "convertedAmountText": yen(val(row, "成約金額合計")),
                }
            )
        return rows

    def month_payload(month: str) -> dict[str, object]:
        idx = months.index(month)
        prev = months[idx - 1] if idx > 0 else None
        cur_m = metric(month, monthly)
        prev_m = metric(prev, monthly) if prev else None
        cur_first = metric(month, repeat_summary, "repeat_group", "初回ユーザー")
        prev_first = metric(prev, repeat_summary, "repeat_group", "初回ユーザー") if prev else None
        cur_repeat2 = metric(month, repeat_summary, "repeat_group", "2回目以上ユーザー")
        prev_repeat2 = metric(prev, repeat_summary, "repeat_group", "2回目以上ユーザー") if prev else None
        cur_repeat5 = metric(month, repeat_summary, "repeat_group", "5回以上ユーザー")
        prev_repeat5 = metric(prev, repeat_summary, "repeat_group", "5回以上ユーザー") if prev else None
        cur_perfume = metric(month, category_summary, "category", "香水")
        prev_perfume = metric(prev, category_summary, "category", "香水") if prev else None

        current_df = df[df["month"] == month]
        current_unconverted = current_df[current_df["status"] == "未成約"]
        first_7000 = segment_count(df, month, "初回7000以上")
        first_7000_9999 = segment_count(df, month, "初回7000_9999")
        first_around = segment_count(df, month, "初回10000前後")
        perfume_unconverted = segment_count(df, month, "香水")
        under_5000 = segment_count(df, month, "5000未満")
        over_10000 = segment_count(df, month, "10000以上")
        around_10000 = unconverted_count(df, month, "10000前後")
        band_8000_12000 = unconverted_count(df, month, "8000_12000")
        band_12000_20000 = unconverted_count(df, month, "12000_20000")
        band_20000_over = unconverted_count(df, month, "20000以上")
        band_7000_12000 = int(((current_unconverted["amount"].between(7000, 12000))).sum())

        def delta(current: float, previous: float | None, suffix: str = "", yen_value: bool = False) -> dict[str, object]:
            if previous is None:
                return {"text": "-", "value": 0}
            diff = current - previous
            if yen_value:
                text = f"{int(diff):+,}円"
            elif suffix == "pt":
                text = f"{diff * 100:+.1f}pt"
            else:
                text = f"{int(diff):+,d}{suffix}"
            return {"text": text, "value": diff}

        cards = [
            {"label": "成約率", "value": pct(val(cur_m, "成約率")), "delta": delta(val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None, "pt"), "goodUp": True, "target": "comparison"},
            {"label": "全査定件数", "value": f"{int(val(cur_m, '全査定件数'))}件", "delta": delta(val(cur_m, "全査定件数"), val(prev_m, "全査定件数") if prev_m is not None else None, "件"), "goodUp": True, "target": "comparison"},
            {"label": "全査定金額", "value": yen(val(cur_m, "全査定金額 合計")), "delta": delta(val(cur_m, "全査定金額 合計"), val(prev_m, "全査定金額 合計") if prev_m is not None else None, "円", True), "goodUp": True, "target": "comparison"},
            {"label": "成約件数", "value": f"{int(val(cur_m, '成約件数'))}件", "delta": delta(val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, "件"), "goodUp": True, "target": "comparison"},
            {"label": "成約金額", "value": yen(val(cur_m, "成約査定金額 合計")), "delta": delta(val(cur_m, "成約査定金額 合計"), val(prev_m, "成約査定金額 合計") if prev_m is not None else None, "円", True), "goodUp": True, "target": "comparison"},
            {"label": "成約金額率", "value": pct(val(cur_m, "成約金額率")), "delta": delta(val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None, "pt"), "goodUp": True, "target": "comparison"},
            {"label": "初回成約率", "value": pct(val(cur_first, "成約率")), "delta": delta(val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None, "pt"), "goodUp": True, "target": "repeat-segment"},
            {"label": "5回以上成約率", "value": pct(val(cur_repeat5, "成約率")), "delta": delta(val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None, "pt"), "goodUp": True, "target": "repeat"},
            {"label": "初回7,000〜9,999円未成約", "value": f"{first_7000_9999}件", "delta": delta(first_7000_9999, segment_count(df, prev, "初回7000_9999") if prev else None, "件"), "goodUp": False, "target": "deep-dive"},
            {"label": "8,000〜12,000円未成約", "value": f"{band_8000_12000}件", "delta": delta(band_8000_12000, unconverted_count(df, prev, "8000_12000") if prev else None, "件"), "goodUp": False, "target": "deep-dive"},
            {"label": "12,000〜20,000円未成約", "value": f"{band_12000_20000}件", "delta": delta(band_12000_20000, unconverted_count(df, prev, "12000_20000") if prev else None, "件"), "goodUp": False, "target": "deep-dive"},
            {"label": "20,000円以上未成約", "value": f"{band_20000_over}件", "delta": delta(band_20000_over, unconverted_count(df, prev, "20000以上") if prev else None, "件"), "goodUp": False, "target": "deep-dive"},
        ]

        alerts = []
        def add_alert(label: str, previous: float, current: float, threshold: float, percent: bool = True) -> None:
            diff = current - previous
            if diff <= threshold:
                alerts.append(f"{label}：{pct(previous) if percent else int(previous)} → {pct(current) if percent else int(current)}（{diff * 100:+.1f}pt）")
        if prev:
            add_alert("成約率", val(prev_m, "成約率"), val(cur_m, "成約率"), -0.03)
            add_alert("成約金額率", val(prev_m, "成約金額率"), val(cur_m, "成約金額率"), -0.05)
            add_alert("初回成約率", val(prev_first, "成約率"), val(cur_first, "成約率"), -0.03)
            ten_delta = over_10000 - segment_count(df, prev, "10000以上")
            if ten_delta >= 10:
                alerts.append(f"10,000円以上未成約：{segment_count(df, prev, '10000以上')}件 → {over_10000}件（+{ten_delta}件）")
            add_alert("香水成約率", val(prev_perfume, "成約率"), val(cur_perfume, "成約率"), -0.05)

        points = [
            f"全体成約率 {pct(val(prev_m, '成約率')) if prev_m is not None else '-'} → {pct(val(cur_m, '成約率'))}",
            f"初回成約率 {pct(val(prev_first, '成約率')) if prev_first is not None else '-'} → {pct(val(cur_first, '成約率'))}",
            f"2回目以上成約率 {pct(val(prev_repeat2, '成約率')) if prev_repeat2 is not None else '-'} → {pct(val(cur_repeat2, '成約率'))}",
            f"7,000〜12,000円未成約 {int(((df[(df['month'] == prev) & (df['status'] == '未成約')]['amount'].between(7000, 12000))).sum()) if prev else '-'}件 → {band_7000_12000}件",
            f"成約査定金額 {yen(val(prev_m, '成約査定金額 合計')) if prev_m is not None else '-'} → {yen(val(cur_m, '成約査定金額 合計'))}",
        ]

        top_rows = []
        for _, row in top_unconverted(current_df).iterrows():
            top_rows.append(
                {
                    "優先理由": row["優先理由"],
                    "データNo": row["data_no"],
                    "査定額": yen(row["amount"]),
                    "査定額Raw": float(row["amount"]),
                    "カテゴリ": row["category"],
                    "方法": row["method"],
                    "点数": f"{int(row['points'])}点",
                    "点数Raw": float(row["points"]),
                    "利用回数": row["repeat_group"],
                }
            )

        def high_value_priority(row: pd.Series) -> tuple[str, int, str]:
            is_first = row["repeat_count"] <= 1
            amount = float(row["amount"])
            if is_first and amount >= 20000:
                return "S", 1, "初回かつ20,000円以上"
            if is_first and amount >= 10000:
                return "A", 2, "初回かつ10,000円以上"
            if not is_first and amount >= 20000:
                return "B", 3, "リピーター20,000円以上"
            return "C", 4, "その他"

        high_value_unconverted_rows = []
        high_value_unconverted = current_unconverted[current_unconverted["amount"] >= 10000].sort_values(
            ["amount", "data_no"], ascending=[False, True]
        )
        for _, row in high_value_unconverted.iterrows():
            priority, priority_raw, comment = high_value_priority(row)
            high_value_unconverted_rows.append(
                {
                    "優先度": priority,
                    "優先度Raw": priority_raw,
                    "データNo": row["data_no"],
                    "査定額": yen(row["amount"]),
                    "査定額Raw": float(row["amount"]),
                    "カテゴリ": row["category"],
                    "点数": f"{int(row['points'])}点",
                    "点数Raw": float(row["points"]),
                    "利用回数": f"{int(row['repeat_count'])}回",
                    "利用回数Raw": int(row["repeat_count"]),
                    "初回/リピート": "初回" if row["repeat_count"] <= 1 else "リピート",
                    "査定方法": row["method"],
                    "コメント": comment,
                }
            )

        trend_start = max(0, idx - 5)
        trend_months = months[trend_start : idx + 1]
        trend_rows = []
        for trend_month in trend_months:
            m = metric(trend_month, monthly)
            first = metric(trend_month, repeat_summary, "repeat_group", "初回ユーザー")
            repeat5 = metric(trend_month, repeat_summary, "repeat_group", "5回以上ユーザー")
            perfume = metric(trend_month, category_summary, "category", "香水")
            supplement = metric(trend_month, category_summary, "category", "サプリ")
            trend_rows.append(
                {
                    "月": trend_month,
                    "成約": f"{int(val(m, '成約件数'))}件",
                    "未成約": f"{int(val(m, '未成約件数'))}件",
                    "全査定": f"{int(val(m, '全査定件数'))}件",
                    "全査定金額": yen(val(m, "全査定金額 合計")),
                    "成約率": pct(val(m, "成約率")),
                    "成約査定金額": yen(val(m, "成約査定金額 合計")),
                    "未成約査定金額": yen(val(m, "未成約査定金額 合計")),
                    "成約金額率": pct(val(m, "成約金額率")),
                    "初回成約率": pct(val(first, "成約率")),
                    "5回以上成約率": pct(val(repeat5, "成約率")),
                    "初回7,000〜9,999円未成約": f"{unconverted_count(df, trend_month, '初回7000_9999')}件",
                    "8,000〜12,000円未成約": f"{unconverted_count(df, trend_month, '8000_12000')}件",
                    "12,000〜20,000円未成約": f"{unconverted_count(df, trend_month, '12000_20000')}件",
                    "20,000円以上未成約": f"{unconverted_count(df, trend_month, '20000以上')}件",
                    "香水成約率": pct(val(perfume, "成約率")),
                    "サプリ成約率": pct(val(supplement, "成約率")),
                }
            )

        segment_rows = []
        for label, key, comment in [
            ("初回かつ7,000〜9,999円未成約", "初回7000_9999", "初回7,000〜9,999円の未成約確認"),
            ("8,000〜12,000円未成約", "8000_12000", "中高額帯の未成約確認"),
            ("12,000〜20,000円未成約", "12000_20000", "高額帯の未成約確認"),
            ("20,000円以上未成約", "20000以上", "高額未成約の個別確認"),
            ("香水カテゴリ未成約", "香水", "香水カテゴリの査定理由確認"),
            ("5,000円未満未成約", "5000未満", "低単価案件の対応方針確認"),
            ("10,000円以上未成約", "10000以上", "高額未成約の個別確認"),
        ]:
            cur_count = segment_count(df, month, key)
            prev_count = segment_count(df, prev, key) if prev else None
            cur_amount = unconverted_amount(df, month, key)
            prev_amount = unconverted_amount(df, prev, key) if prev else None
            segment_rows.append(
                {
                    "セグメント": label,
                    "件数": f"{cur_count}件",
                    "件数Raw": cur_count,
                    "査定金額合計": yen(cur_amount),
                    "査定金額合計Raw": cur_amount,
                    "件数前月比": diff_num(cur_count, prev_count, "件") if prev_count is not None else "-",
                    "件数前月比Raw": (cur_count - prev_count) if prev_count is not None else 0,
                    "金額前月比": diff_num(cur_amount, prev_amount, "円") if prev_amount is not None else "-",
                    "金額前月比Raw": (cur_amount - prev_amount) if prev_amount is not None else 0,
                    "コメント": comment,
                }
            )

        converted_avg = val(cur_m, "成約査定額 平均")
        prev_converted_avg = val(prev_m, "成約査定額 平均") if prev_m is not None else None
        current_over_10000_stats = unconverted_segment_stats(df, month, "10000以上")
        previous_over_10000_stats = unconverted_segment_stats(df, prev, "10000以上") if prev else {"count": 0, "amount": 0, "avg": 0}
        high_band_cur = row_for(amount_summary, month, "amount_band", "20,000円以上")
        high_band_prev = row_for(amount_summary, prev, "amount_band", "20,000円以上") if prev else None

        executive_summary = [
            f"{month}は成約率{pct(val(cur_m, '成約率'))}で、前月比{diff_pt(val(cur_m, '成約率'), val(prev_m, '成約率') if prev_m is not None else None)}。",
            f"全査定件数は{int(val(cur_m, '全査定件数'))}件で、前月比{diff_num(val(cur_m, '全査定件数'), val(prev_m, '全査定件数') if prev_m is not None else None, '件')}。",
            f"全査定金額は{yen(val(cur_m, '全査定金額 合計'))}で、前月比{diff_num(val(cur_m, '全査定金額 合計'), val(prev_m, '全査定金額 合計') if prev_m is not None else None, '円')}。",
            f"成約金額は{yen(val(cur_m, '成約査定金額 合計'))}で、前月比{diff_num(val(cur_m, '成約査定金額 合計'), val(prev_m, '成約査定金額 合計') if prev_m is not None else None, '円')}。",
            f"初回成約率は{pct(val(cur_first, '成約率'))}。5回以上ユーザーの{pct(val(cur_repeat5, '成約率'))}と比べて{(val(cur_first, '成約率') - val(cur_repeat5, '成約率')) * 100:+.1f}pt。",
            f"未成約金額は{yen(val(cur_m, '未成約査定金額 合計'))}で、前月比{diff_num(val(cur_m, '未成約査定金額 合計'), val(prev_m, '未成約査定金額 合計') if prev_m is not None else None, '円')}。",
        ]
        if prev_m is not None and (val(cur_m, "成約金額率") - val(prev_m, "成約金額率")) <= -0.05:
            executive_summary.append(
                f"成約金額率は{pct(val(prev_m, '成約金額率'))}→{pct(val(cur_m, '成約金額率'))}（{diff_pt(val(cur_m, '成約金額率'), val(prev_m, '成約金額率'))}）。金額面の未成約確認を優先します。"
            )
        executive_summary.append("今月は件数よりも、金額の高い未成約が増えた月です。")

        comparison_specs = [
            ("全査定件数", val(cur_m, "全査定件数"), val(prev_m, "全査定件数") if prev_m is not None else None, "件", False, None),
            ("全査定金額", val(cur_m, "全査定金額 合計"), val(prev_m, "全査定金額 合計") if prev_m is not None else None, "円", False, None),
            ("成約件数", val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, "件", False, True),
            ("未成約件数", val(cur_m, "未成約件数"), val(prev_m, "未成約件数") if prev_m is not None else None, "件", False, False),
            ("成約率", val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None, "pt", True, True),
            ("成約金額", val(cur_m, "成約査定金額 合計"), val(prev_m, "成約査定金額 合計") if prev_m is not None else None, "円", False, True),
            ("未成約金額", val(cur_m, "未成約査定金額 合計"), val(prev_m, "未成約査定金額 合計") if prev_m is not None else None, "円", False, False),
            ("成約金額率", val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None, "pt", True, True),
            ("初回成約率", val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None, "pt", True, True),
            ("5回以上成約率", val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None, "pt", True, True),
        ]
        comparison_rows = []
        for label, current_value, previous_value, unit, is_rate, higher_good in comparison_specs:
            current_text = pct(current_value) if is_rate else (yen(current_value) if unit == "円" else f"{int(current_value)}{unit}")
            previous_text = "-" if previous_value is None else (pct(previous_value) if is_rate else (yen(previous_value) if unit == "円" else f"{int(previous_value)}{unit}"))
            difference_text = diff_pt(current_value, previous_value) if is_rate else diff_num(current_value, previous_value, unit)
            comparison_rows.append(
                {
                    "項目": label,
                    "今月": current_text,
                    "前月": previous_text,
                    "差分": difference_text,
                    "差分Raw": 0 if previous_value is None else current_value - previous_value,
                    "評価": "横ばい" if higher_good is None else evaluate_delta(current_value, previous_value, higher_good, 0.0005 if is_rate else 0.5),
                }
            )

        factor_comments = []
        if prev_m is not None and val(cur_m, "成約率") < val(prev_m, "成約率"):
            factor_comments.append(f"成約率は{pct(val(prev_m, '成約率'))}→{pct(val(cur_m, '成約率'))}。初回成約率は{pct(val(prev_first, '成約率'))}→{pct(val(cur_first, '成約率'))}。")
            factor_comments.append(f"5回以上ユーザー成約率は{pct(val(prev_repeat5, '成約率'))}→{pct(val(cur_repeat5, '成約率'))}。")
            factor_comments.append(f"5,000円未満構成比は{pct(low_amount_share(df, prev))}→{pct(low_amount_share(df, month))}。")
            factor_comments.append(f"香水カテゴリ成約率は{pct(val(prev_perfume, '成約率'))}→{pct(val(cur_perfume, '成約率'))}。")
            factor_comments.append(f"10,000円以上未成約は{previous_over_10000_stats['count']}件→{current_over_10000_stats['count']}件。")
        else:
            factor_comments.append(f"成約率は{pct(val(prev_m, '成約率')) if prev_m is not None else '-'}→{pct(val(cur_m, '成約率'))}。")
        if prev_m is not None:
            factor_comments.append(f"全査定件数は{int(val(prev_m, '全査定件数'))}件→{int(val(cur_m, '全査定件数'))}件。")
            factor_comments.append(f"全査定金額は{yen(val(prev_m, '全査定金額 合計'))}→{yen(val(cur_m, '全査定金額 合計'))}。")
        if prev_m is not None and val(cur_m, "成約査定金額 合計") < val(prev_m, "成約査定金額 合計"):
            factor_comments.append(f"成約金額は前月比{diff_num(val(cur_m, '成約査定金額 合計'), val(prev_m, '成約査定金額 合計'), '円')}。成約件数は{int(val(prev_m, '成約件数'))}件→{int(val(cur_m, '成約件数'))}件。")
            factor_comments.append(f"成約平均単価は{yen(prev_converted_avg or 0)}→{yen(converted_avg)}。")
            factor_comments.append(f"20,000円以上の成約件数は{int(val(high_band_prev, '成約件数')) if high_band_prev is not None else 0}件→{int(val(high_band_cur, '成約件数'))}件。")
            factor_comments.append(f"10,000円以上未成約金額は{yen(previous_over_10000_stats['amount'])}→{yen(current_over_10000_stats['amount'])}。")
        if prev_m is not None and (val(cur_m, "成約金額率") - val(prev_m, "成約金額率")) <= -0.05:
            factor_comments.append(
                f"成約金額率は{pct(val(prev_m, '成約金額率'))}→{pct(val(cur_m, '成約金額率'))}（{diff_pt(val(cur_m, '成約金額率'), val(prev_m, '成約金額率'))}）。"
            )
            factor_comments.append(
                f"金額面では10,000円以上未成約金額が{yen(previous_over_10000_stats['amount'])}→{yen(current_over_10000_stats['amount'])}です。"
            )

        def segment_rows_from(summary: pd.DataFrame, group_col: str, groups: list[str]) -> list[dict[str, object]]:
            rows = []
            for group in groups:
                cur = row_for(summary, month, group_col, group)
                prv = row_for(summary, prev, group_col, group) if prev else None
                rows.append(
                    {
                        "区分": group,
                        "成約件数": f"{int(val(cur, '成約件数'))}件",
                        "成約件数Raw": int(val(cur, "成約件数")),
                        "未成約件数": f"{int(val(cur, '未成約件数'))}件",
                        "未成約件数Raw": int(val(cur, "未成約件数")),
                        "成約率": pct(val(cur, "成約率")),
                        "成約率Raw": val(cur, "成約率"),
                        "成約金額": yen(val(cur, "成約金額合計")),
                        "成約金額Raw": val(cur, "成約金額合計"),
                        "前月比": diff_pt(val(cur, "成約率"), val(prv, "成約率") if prv is not None else None),
                        "前月比Raw": 0 if prv is None else val(cur, "成約率") - val(prv, "成約率"),
                    }
                )
            return rows

        repeat_segment_rows = segment_rows_from(repeat_summary, "repeat_group", REPEAT_GROUPS)
        amount_segment_rows = segment_rows_from(amount_summary, "amount_band", [x[0] for x in AMOUNT_BANDS])
        category_segment_rows = segment_rows_from(category_summary, "category", CATEGORIES)

        deep_dive_defs = [
            ("優先確認A", "初回かつ10,000円以上未成約", "初回10000以上"),
            ("優先確認A", "10,000円以上未成約", "10000以上"),
            ("優先確認B", "初回かつ7,000〜9,999円未成約", "初回7000_9999"),
            ("優先確認C", "8,000〜12,000円未成約", "8000_12000"),
            ("優先確認D", "12,000〜20,000円未成約", "12000_20000"),
            ("優先確認E", "20,000円以上未成約", "20000以上"),
            ("優先確認F", "香水カテゴリ未成約", "香水"),
            ("優先度低", "5,000円未満未成約", "5000未満"),
        ]
        deep_dive_rows = []
        for rank, label, key in deep_dive_defs:
            cur_stats = unconverted_segment_stats(df, month, key)
            prev_stats = unconverted_segment_stats(df, prev, key) if prev else {"count": 0, "amount": 0, "avg": 0}
            deep_dive_rows.append(
                {
                    "優先区分": rank,
                    "対象": label,
                    "件数": f"{cur_stats['count']}件",
                    "件数Raw": cur_stats["count"],
                    "査定金額合計": yen(cur_stats["amount"]),
                    "査定金額合計Raw": cur_stats["amount"],
                    "平均査定額": yen(cur_stats["avg"]),
                    "平均査定額Raw": cur_stats["avg"],
                    "前月比": diff_num(cur_stats["count"], prev_stats["count"], "件") if prev else "-",
                    "前月比Raw": cur_stats["count"] - prev_stats["count"] if prev else 0,
                }
            )

        priority_rows = []
        for row in deep_dive_rows:
            target = row["対象"]
            amount_score = row["査定金額合計Raw"] / 10000
            price_band_score = 0
            if "初回かつ10,000円以上" in target:
                price_band_score = 160
            elif target == "10,000円以上未成約":
                price_band_score = 140
            elif "初回かつ7,000〜9,999円" in target:
                price_band_score = 120
            elif "香水" in target:
                price_band_score = 90
            elif "20,000円以上" in target:
                price_band_score = 110
            elif "12,000〜20,000円" in target:
                price_band_score = 100
            elif "8,000〜12,000円" in target:
                price_band_score = 70
            elif "5,000円未満" in target:
                price_band_score = -1000
            worsening_score = max(0, row["前月比Raw"]) * 8
            count_score = row["件数Raw"] * 0.2
            score = amount_score + price_band_score + worsening_score + count_score
            if "5,000円未満" in target:
                score = -100000 + amount_score * 0.01
            if "初回" in target and "10,000円以上" in target:
                reason_focus = "初回高額未成約。初回かつ10,000円以上の案件を優先確認"
            elif target == "10,000円以上未成約":
                reason_focus = "全体高額未成約。初回とリピーターを含む10,000円以上の案件"
            elif "初回かつ7,000〜9,999円" in target:
                reason_focus = "初回かつ7,000〜9,999円の未成約確認"
            elif "20,000円以上" in target:
                reason_focus = "20,000円以上の高額未成約確認"
            elif "12,000〜20,000円" in target:
                reason_focus = "12,000〜20,000円の高額帯未成約確認"
            elif "8,000〜12,000円" in target:
                reason_focus = "8,000〜12,000円の中高額帯未成約確認"
            elif "香水" in target:
                reason_focus = "香水カテゴリの未成約確認"
            elif "5,000円未満" in target:
                reason_focus = "金額インパクトが低いため優先度低"
            else:
                reason_focus = "前月比と金額を確認"
            priority_rows.append(
                {
                    "優先順位": 0,
                    "改善対象": row["対象"],
                    "理由": f"{reason_focus}。件数{row['件数']}、査定金額合計{row['査定金額合計']}、前月比{row['前月比']}。",
                    "件数": row["件数"],
                    "件数Raw": row["件数Raw"],
                    "金額合計": row["査定金額合計"],
                    "金額合計Raw": row["査定金額合計Raw"],
                    "score": score,
                }
            )
        priority_order = {
            "初回かつ10,000円以上未成約": 1,
            "10,000円以上未成約": 2,
            "20,000円以上未成約": 3,
            "12,000〜20,000円未成約": 4,
            "香水カテゴリ未成約": 5,
            "8,000〜12,000円未成約": 6,
            "初回かつ7,000〜9,999円未成約": 7,
            "5,000円未満未成約": 8,
        }
        priority_rows.sort(key=lambda x: priority_order.get(x["改善対象"], 99))
        for i, row in enumerate(priority_rows, start=1):
            row["優先順位"] = i

        next_checks = [
            "初回10,000円以上未成約の金額上位10件を確認",
            "10,000円以上未成約のうち、リピーター案件を確認",
            "初回7,000〜9,999円未成約の提示金額と返信内容を確認",
            "香水未成約の査定額上位10件を確認",
            "20,000円以上未成約の件数と金額を確認",
            "12,000〜20,000円未成約の金額上位10件を確認",
            "8,000〜12,000円未成約の単品率と利用回数を確認",
            "高額未成約の競合価格との差額確認",
            "前年同カテゴリの平均提示額との差確認",
            "査定方法別の平均提示率確認",
            "高額帯の提示率推移確認",
        ]

        return {
            "month": month,
            "prevMonth": prev,
            "executiveSummary": executive_summary,
            "cards": cards,
            "alerts": alerts,
            "comparisonRows": comparison_rows,
            "factorComments": factor_comments,
            "repeatSegmentRows": repeat_segment_rows,
            "amountSegmentRows": amount_segment_rows,
            "categorySegmentRows": category_segment_rows,
            "deepDiveRows": deep_dive_rows,
            "priorityRows": priority_rows,
            "nextChecks": next_checks,
            "comments": make_analysis_comments(df, monthly[monthly["month"].le(month)], repeat_summary[repeat_summary["month"].le(month)], category_summary[category_summary["month"].le(month)]),
            "causes": make_cause_candidates(df[df["month"].le(month)], monthly[monthly["month"].le(month)], repeat_summary[repeat_summary["month"].le(month)]),
            "points": points,
            "overallRows": [
                {"項目": "成約件数", "値": f"{int(val(cur_m, '成約件数'))}件", "前月比": diff_num(val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, "件"), "raw": int(val(cur_m, "成約件数"))},
                {"項目": "未成約件数", "値": f"{int(val(cur_m, '未成約件数'))}件", "前月比": diff_num(val(cur_m, "未成約件数"), val(prev_m, "未成約件数") if prev_m is not None else None, "件"), "raw": int(val(cur_m, "未成約件数"))},
                {"項目": "全査定件数", "値": f"{int(val(cur_m, '全査定件数'))}件", "前月比": diff_num(val(cur_m, "全査定件数"), val(prev_m, "全査定件数") if prev_m is not None else None, "件"), "raw": int(val(cur_m, "全査定件数"))},
                {"項目": "成約率", "値": pct(val(cur_m, "成約率")), "前月比": diff_pt(val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None), "raw": val(cur_m, "成約率")},
            ],
            "amountRows": [
                {"項目": "成約査定金額合計", "値": yen(val(cur_m, "成約査定金額 合計")), "前月比": diff_num(val(cur_m, "成約査定金額 合計"), val(prev_m, "成約査定金額 合計") if prev_m is not None else None, "円"), "raw": val(cur_m, "成約査定金額 合計")},
                {"項目": "未成約査定金額合計", "値": yen(val(cur_m, "未成約査定金額 合計")), "前月比": diff_num(val(cur_m, "未成約査定金額 合計"), val(prev_m, "未成約査定金額 合計") if prev_m is not None else None, "円"), "raw": val(cur_m, "未成約査定金額 合計")},
                {"項目": "全査定金額合計", "値": yen(val(cur_m, "全査定金額 合計")), "前月比": diff_num(val(cur_m, "全査定金額 合計"), val(prev_m, "全査定金額 合計") if prev_m is not None else None, "円"), "raw": val(cur_m, "全査定金額 合計")},
                {"項目": "成約金額率", "値": pct(val(cur_m, "成約金額率")), "前月比": diff_pt(val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None), "raw": val(cur_m, "成約金額率")},
            ],
            "firstRows": [
                {"項目": "初回成約件数", "値": f"{int(val(cur_first, '成約件数'))}件", "前月比": diff_num(val(cur_first, "成約件数"), val(prev_first, "成約件数") if prev_first is not None else None, "件")},
                {"項目": "初回未成約件数", "値": f"{int(val(cur_first, '未成約件数'))}件", "前月比": diff_num(val(cur_first, "未成約件数"), val(prev_first, "未成約件数") if prev_first is not None else None, "件")},
                {"項目": "初回成約率", "値": pct(val(cur_first, "成約率")), "前月比": diff_pt(val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None)},
                {"項目": "初回かつ7,000〜9,999円未成約", "値": f"{first_7000_9999}件", "前月比": ""},
            ],
            "repeatRows": [
                {"項目": "2回目以上成約率", "値": pct(val(cur_repeat2, "成約率")), "前月比": diff_pt(val(cur_repeat2, "成約率"), val(prev_repeat2, "成約率") if prev_repeat2 is not None else None)},
                {"項目": "5回以上成約率", "値": pct(val(cur_repeat5, "成約率")), "前月比": diff_pt(val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None)},
            ],
            "amountBandRows": table_rows_for(month, amount_summary, "amount_band", [x[0] for x in AMOUNT_BANDS]),
            "categoryRows": table_rows_for(month, category_summary, "category", CATEGORIES),
            "methodRows": table_rows_for(month, method_summary, "method", METHODS),
            "featureRows": [
                f"未成約{len(current_unconverted)}件のうち、初回{int((current_unconverted['repeat_count'] <= 1).sum())}件、初回比率{pct((current_unconverted['repeat_count'] <= 1).mean() if len(current_unconverted) else 0)}",
                f"未成約{len(current_unconverted)}件のうち、単品{int(current_unconverted['is_single_item'].sum())}件、単品比率{pct(current_unconverted['is_single_item'].mean() if len(current_unconverted) else 0)}",
                f"未成約{len(current_unconverted)}件のうち、香水{perfume_unconverted}件、香水比率{pct((current_unconverted['category'].eq('香水')).mean() if len(current_unconverted) else 0)}",
                f"8,000〜12,000円未成約{band_8000_12000}件",
                f"12,000〜20,000円未成約{band_12000_20000}件",
                f"20,000円以上未成約{band_20000_over}件",
            ],
            "segmentRows": segment_rows,
            "topRows": top_rows,
            "highValueUnconvertedRows": high_value_unconverted_rows,
            "trendRows": trend_rows,
        }

    payload = {
        "months": months,
        "latestMonth": latest_month,
        "byMonth": {month: month_payload(month) for month in months},
        "charts": {
            name: chart_data_uri(charts_dir / name)
            for name in [
                "recent_conversion_rate.png",
                "recent_total_assessments.png",
                "recent_total_amount.png",
                "recent_converted_amount.png",
                "recent_first_conversion_rate.png",
                "recent_repeat5_conversion_rate.png",
                "recent_amount_band_conversion_rate.png",
                "recent_category_conversion_rate.png",
                "monthly_conversion_rate.png",
                "first_user_conversion_rate.png",
                "amount_band_conversion_rate.png",
                "category_conversion_rate.png",
            ]
        },
    }
    def json_default(value: object) -> object:
        if isinstance(value, numbers.Integral):
            return int(value)
        if isinstance(value, numbers.Real):
            return float(value)
        return str(value)

    payload_json = json.dumps(payload, ensure_ascii=False, default=json_default)
    safe_payload_json = payload_json.replace("</", "<\\/")
    initial = payload["byMonth"][latest_month]

    def static_list(items: list[str]) -> str:
        return "".join(f"<li>{esc(item)}</li>" for item in items)

    def static_card_html(cards: list[dict[str, object]]) -> str:
        chunks = []
        for card in cards:
            delta_obj = card["delta"]
            delta_class_name = "neutral"
            if delta_obj["text"] != "-" and delta_obj["value"] != 0:
                good_up = bool(card["goodUp"])
                delta_class_name = "good" if ((delta_obj["value"] > 0) == good_up) else "bad"
            chunks.append(
                f'<div class="card" data-target="{esc(card["target"])}">'
                f'<div><div class="card-label">{esc(card["label"])}</div><div class="card-value">{esc(card["value"])}</div></div>'
                f'<div><span class="card-delta-label">前月比</span><span class="delta {delta_class_name}">{esc(delta_obj["text"])}</span></div>'
                f"</div>"
            )
        return "".join(chunks)

    def static_table_from_dicts(headers: list[str], rows: list[dict[str, object]]) -> str:
        def column_class(header: str) -> str:
            text_headers = {"セグメント", "改善対象", "コメント", "理由", "区分", "対象", "項目", "優先区分", "優先理由", "優先度", "カテゴリ", "方法", "査定方法", "利用回数", "初回/リピート", "データNo", "評価", "月"}
            numeric_words = ("件数", "金額", "成約率", "前月比", "差分", "平均査定額", "査定金額合計", "査定額", "点数", "順位", "値", "今月", "前月", "成約", "未成約", "全査定")
            if header in text_headers:
                return "text"
            if any(word in header for word in numeric_words):
                return "num"
            return "text"

        head = "".join(f'<th class="{column_class(header)}">{esc(header)}</th>' for header in headers)
        body = []
        for row in rows:
            cells = "".join(f'<td class="{column_class(header)}">{esc(row.get(header, ""))}</td>' for header in headers)
            body.append(f"<tr>{cells}</tr>")
        return f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'

    static_alerts = (
        "".join(f'<div class="alert">{esc(item)}</div>' for item in initial["alerts"])
        if initial["alerts"]
        else '<div class="alert-ok">重要アラートなし</div>'
    )
    static_charts = "".join(
        f'<figure><img src="{uri}" alt="{esc(name)}"><figcaption>{esc(name.replace(".png", ""))}</figcaption></figure>'
        for name, uri in payload["charts"].items()
        if uri
    )

    css = """
:root{--ink:#111827;--muted:#667085;--line:#e6eaf0;--line-strong:#d5dbe5;--soft:#f8fafc;--soft-2:#f3f6fa;--panel:#fff;--table-head:#f5f7fb;--row-alt:#fbfcfe;--row-hover:#f3f8ff;--input-bg:#fff;--good:#067647;--good-bg:#e6f6ec;--bad:#b42318;--bad-bg:#fff1f0;--flat:#475467;--flat-bg:#eef2f6;--blue:#175cd3;--blue-bg:#f4f8ff;--high-bg:#fff1f0;--high-hover:#ffe7e3;--shadow:0 1px 2px rgba(16,24,40,.04),0 10px 24px rgba(16,24,40,.05);--radius:12px}html.dark{--ink:#e5e7eb;--muted:#9ca3af;--line:#293241;--line-strong:#3b4658;--soft:#141a24;--soft-2:#1a2230;--panel:#111827;--table-head:#1f2937;--row-alt:#151d29;--row-hover:#213047;--input-bg:#0f172a;--good:#8be0b3;--good-bg:#123624;--bad:#ffb4ab;--bad-bg:#421815;--flat:#cbd5e1;--flat-bg:#263242;--blue:#93c5fd;--blue-bg:#13243b;--high-bg:#3a1717;--high-hover:#4a1f1f;--shadow:none}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--soft);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Yu Gothic",Meiryo,sans-serif;line-height:1.62}
.page{max-width:1240px;margin:0 auto;padding:42px 34px 72px}.topbar{display:flex;justify-content:space-between;gap:28px;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:26px;margin-bottom:28px}
h1{font-size:34px;line-height:1.15;letter-spacing:0;margin:0 0 8px;font-weight:760}.subtitle{margin:0;color:var(--muted);font-size:14px}.selector{display:flex;gap:10px;align-items:center;background:var(--soft);border:1px solid var(--line);border-radius:var(--radius);padding:11px 13px;color:var(--ink);font-weight:650;white-space:nowrap}.header-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.updated-at{color:var(--muted);font-size:13px}.theme-toggle{white-space:nowrap}
select,input{font:inherit;border:1px solid var(--line-strong);border-radius:10px;background:var(--input-bg);padding:9px 11px;color:var(--ink);outline:none}select:focus,input:focus{border-color:#84adff;box-shadow:0 0 0 3px #2b5aa833}
section{margin:30px 0}.panel{border:1px solid var(--line);border-radius:var(--radius);background:var(--panel);padding:24px;box-shadow:var(--shadow)}.panel.primary{border-color:#d7e4ff;background:var(--panel)}.panel.reading{padding:26px 28px}.section-kicker{font-size:12px;letter-spacing:.08em;color:var(--muted);font-weight:760;text-transform:uppercase;margin-bottom:6px}
h2{font-size:21px;line-height:1.25;margin:0 0 16px;font-weight:760}h3{font-size:15px;margin:20px 0 9px;color:var(--ink)}.grid{display:grid;gap:16px}.cards{grid-template-columns:repeat(auto-fit,minmax(176px,1fr));align-items:stretch}.card{min-height:142px;border:1px solid var(--line);border-radius:var(--radius);padding:20px;background:var(--panel);cursor:pointer;transition:box-shadow .16s ease,transform .16s ease,border-color .16s ease;display:flex;flex-direction:column;justify-content:space-between}.card:hover{box-shadow:0 16px 34px rgba(16,24,40,.10);transform:translateY(-2px);border-color:#bfd3ff}.card:active{transform:translateY(0)}
.card-label{font-size:13px;color:var(--muted);font-weight:700}.card-value{font-size:36px;line-height:1.05;font-weight:780;margin:10px 0 12px;letter-spacing:-.01em}.card-delta-label{font-size:12px;color:var(--muted);display:block;margin-bottom:4px}.delta{display:inline-block;font-weight:760;padding:3px 10px;border-radius:999px;font-size:13px}.good{color:var(--good);background:var(--good-bg)}.bad{color:var(--bad);background:var(--bad-bg)}.neutral{color:var(--flat);background:var(--flat-bg)}
.alerts{display:grid;gap:12px;margin:24px 0}.alert{border:1px solid #ffd0cc;border-left:6px solid var(--bad);background:var(--bad-bg);border-radius:var(--radius);padding:14px 16px;font-weight:760}.alert-ok{border:1px solid var(--line);background:var(--soft);border-radius:var(--radius);padding:12px 14px;color:var(--muted);font-weight:700}
.focus{background:var(--blue-bg);border-color:#cfe0ff}.focus h2{color:#123b7a}.focus ul,.comment-list{margin:0;padding-left:20px}.focus li,.comment-list li{margin:7px 0}.comment-list li{font-size:15.5px}.flow-note{font-size:13px;color:var(--muted);margin:-5px 0 16px}
.table-tools{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:4px 0 14px}.search{min-width:300px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:var(--radius);max-height:560px}
button{font:inherit;border:1px solid var(--line-strong);border-radius:10px;background:var(--input-bg);padding:9px 13px;color:var(--ink);font-weight:700;cursor:pointer}button:hover{background:var(--row-hover)}.filter-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:4px 0 14px}.filter-tools label{display:flex;gap:7px;align-items:center;color:var(--ink);font-weight:650}.filter-tools input[type="checkbox"]{width:16px;height:16px}.filter-tools .search{min-width:260px}.high-rank td{background:var(--high-bg)}.high-rank:hover td{background:var(--high-hover)}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel)}th,td{padding:15px 16px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:left;vertical-align:middle}th{position:sticky;top:0;z-index:2;background:var(--table-head);font-size:13px;font-weight:780;color:var(--ink);cursor:pointer;border-bottom:1px solid var(--line-strong)}td.text,th.text{text-align:left;white-space:normal;min-width:180px}td.num,th.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}#priority-table th:nth-child(2),#priority-table td:nth-child(2),#priority-table th:nth-child(3),#priority-table td:nth-child(3),#deep-dive-table th:nth-child(1),#deep-dive-table td:nth-child(1),#deep-dive-table th:nth-child(2),#deep-dive-table td:nth-child(2),#segments-table th:first-child,#segments-table td:first-child,#segments-table th:last-child,#segments-table td:last-child{text-align:left;white-space:normal;min-width:220px}#priority-table th:nth-child(1),#priority-table td:nth-child(1),#priority-table th:nth-child(4),#priority-table td:nth-child(4),#priority-table th:nth-child(5),#priority-table td:nth-child(5),#deep-dive-table th:nth-child(n+3),#deep-dive-table td:nth-child(n+3),#segments-table th:nth-child(n+2):nth-child(-n+5),#segments-table td:nth-child(n+2):nth-child(-n+5){text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}td:first-child,th:first-child{text-align:left}tbody tr:nth-child(even){background:var(--row-alt)}tbody tr:hover{background:var(--row-hover)}tbody tr:last-child td{border-bottom:0}.sort-mark{font-size:11px;color:#98a2b3;margin-left:6px}
details.panel{padding:0;overflow:hidden}details.panel>summary{list-style:none;cursor:pointer;padding:20px 24px;font-size:20px;font-weight:780;display:flex;align-items:center;justify-content:space-between;gap:18px;border-radius:var(--radius);transition:background-color .16s ease}details.panel>summary:hover{background:var(--row-hover)}details.panel>summary::-webkit-details-marker{display:none}details.panel>summary::after{content:"▶";font-size:15px;color:#667085;transition:transform .18s ease}details.panel[open]>summary{border-bottom:1px solid var(--line);border-bottom-left-radius:0;border-bottom-right-radius:0}details.panel[open]>summary::after{content:"▼"}.details-body{padding:18px 24px 24px;animation:openSection .18s ease-out}@keyframes openSection{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:18px}figure{margin:0;border:1px solid var(--line);border-radius:var(--radius);padding:14px;background:var(--panel)}img{width:100%;height:auto;display:block}figcaption{font-size:13px;color:var(--muted);margin-top:9px}.two-col{grid-template-columns:1fr 1fr}
@media(max-width:900px){.topbar{display:block}.header-tools{justify-content:flex-start;margin-top:18px}.selector{margin-top:0}.two-col{grid-template-columns:1fr}.page{padding:24px 18px}.search{min-width:0;width:100%}.card-value{font-size:31px}.table-wrap{max-height:none}}
@media(max-width:640px){.page{padding:18px 12px 48px}h1{font-size:28px}.panel{padding:18px 14px}.cards{grid-template-columns:1fr}.filter-tools,.table-tools,.header-tools{align-items:stretch}.filter-tools>*{width:100%}.selector{justify-content:space-between}.charts{grid-template-columns:1fr}th,td{padding:12px 10px}.updated-at{font-size:12px}}
@media print{.page{max-width:none;padding:18px}.selector,.table-tools{display:none}.panel,details.panel{break-inside:avoid;box-shadow:none}.charts{grid-template-columns:repeat(2,1fr)}details.panel:not([open]) .details-body{display:block}}
"""

    js = """
const DATA = JSON.parse(document.getElementById('dashboard-data').textContent);
let state = { month: DATA.latestMonth, sort: {} };
let highValueState = { search: '', firstOnly: false, category: 'all' };
function applyTheme(mode){
  document.documentElement.classList.toggle('dark', mode === 'dark');
  const button = document.getElementById('theme-toggle');
  if(button) button.textContent = mode === 'dark' ? 'ライトモード' : 'ダークモード';
}
function initTheme(){
  const saved = localStorage.getItem('dashboard-theme');
  const dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(dark ? 'dark' : 'light');
}
function toggleTheme(){
  const next = document.documentElement.classList.contains('dark') ? 'light' : 'dark';
  localStorage.setItem('dashboard-theme', next);
  applyTheme(next);
}
const yen = v => String(v ?? '');
function cls(delta, goodUp=true){ if(!delta || delta.text==='-' || delta.value===0) return 'neutral'; return (goodUp ? delta.value>0 : delta.value<0) ? 'good' : 'bad'; }
function deltaHtml(delta, goodUp=true){ return `<span class="delta ${cls(delta, goodUp)}">${delta?.text ?? '-'}</span>`; }
function parseNum(v){ return Number(String(v ?? '').replace(/[^\\d.-]/g,'')) || 0; }
function isNumericCell(value){ return /[-+]?\\d/.test(String(value ?? '')) && /(%|円|件|pt|点|^[\\d,.-]+$)/.test(String(value ?? '')); }
function columnClass(header){
  const textHeaders = new Set(['セグメント','改善対象','コメント','理由','区分','対象','項目','優先区分','優先理由','優先度','カテゴリ','方法','査定方法','利用回数','初回/リピート','データNo','評価','月']);
  const numericWords = ['件数','金額','成約率','前月比','差分','平均査定額','査定金額合計','査定額','点数','順位','値','今月','前月','成約','未成約','全査定'];
  if(textHeaders.has(header)) return 'text';
  return numericWords.some(word => String(header).includes(word)) ? 'num' : 'text';
}
function table(id, headers, rows, opts={}){
  const mount = document.getElementById(id);
  if(!mount) return;
  const sortKey = state.sort[id]?.key, dir = state.sort[id]?.dir ?? 1;
  let q = (document.querySelector(`[data-search="${id}"]`)?.value || '').toLowerCase();
  let filtered = rows.filter(r => !q || Object.values(r).join(' ').toLowerCase().includes(q));
  if(sortKey){
    filtered.sort((a,b)=>{
      const av = a[sortKey+'Raw'] ?? a[sortKey] ?? '';
      const bv = b[sortKey+'Raw'] ?? b[sortKey] ?? '';
      const hasRaw = Object.prototype.hasOwnProperty.call(a, sortKey+'Raw') || Object.prototype.hasOwnProperty.call(b, sortKey+'Raw');
      if(hasRaw || isNumericCell(av) || isNumericCell(bv)) return dir * (parseNum(av) - parseNum(bv));
      return dir * String(av).localeCompare(String(bv), 'ja');
    });
  }
  const head = headers.map((h,i)=>{
    const mark = sortKey===h ? (dir>0 ? '▲' : '▼') : '↕';
    const klass = ` class="${columnClass(h)}"`;
    return `<th${klass} data-table="${id}" data-key="${h}">${h}<span class="sort-mark">${mark}</span></th>`;
  }).join('');
  const body = filtered.map(r=>`<tr>${headers.map(h=>`<td class="${columnClass(h)}">${r[h] ?? ''}</td>`).join('')}</tr>`).join('');
  mount.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}
const highValueHeaders = ['優先度','データNo','査定額','カテゴリ','点数','利用回数','初回/リピート','査定方法','コメント'];
function csvValue(value){
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
function downloadCsv(filename, headers, rows){
  const csv = '\\ufeff' + [headers.join(','), ...rows.map(row=>headers.map(header=>csvValue(row[header])).join(','))].join('\\n');
  const blob = new Blob([csv], {type:'text/csv;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
function highValueRows(d){
  let rows = [...(d.highValueUnconvertedRows || [])];
  const q = highValueState.search.toLowerCase();
  if(q) rows = rows.filter(row => Object.values(row).join(' ').toLowerCase().includes(q));
  if(highValueState.firstOnly) rows = rows.filter(row => row['初回/リピート'] === '初回');
  if(highValueState.category !== 'all') rows = rows.filter(row => row['カテゴリ'] === highValueState.category);
  return rows;
}
function renderHighValueTable(d){
  const rows = highValueRows(d);
  table('high-value-unconverted-table', highValueHeaders, rows);
  document.querySelectorAll('#high-value-unconverted-table tbody tr').forEach((tr, index) => {
    if(index < 20) tr.classList.add('high-rank');
  });
}
function renderHighValueControls(d){
  const categorySelect = document.getElementById('high-value-category-filter');
  if(categorySelect){
    const categories = [...new Set((d.highValueUnconvertedRows || []).map(row => row['カテゴリ']).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b), 'ja'));
    const current = highValueState.category;
    categorySelect.innerHTML = '<option value="all">すべて</option>' + categories.map(category => `<option value="${category}">${category}</option>`).join('');
    categorySelect.value = categories.includes(current) ? current : 'all';
    highValueState.category = categorySelect.value;
  }
}
function simpleRows(rows){ return rows.map(r=>({項目:r.項目, 値:r.値, 前月比:r.前月比})); }
function render(){
  const d = DATA.byMonth[state.month];
  renderHighValueControls(d);
  document.getElementById('subtitle').textContent = `査定月基準 / 前月比較: ${d.prevMonth || '-'}`;
  document.getElementById('alerts').innerHTML = d.alerts.length ? d.alerts.map(x=>`<div class="alert">${x}</div>`).join('') : '<div class="alert-ok">重要アラートなし</div>';
  document.getElementById('executive-summary').innerHTML = d.executiveSummary.map(x=>`<li>${x}</li>`).join('');
  document.getElementById('cards').innerHTML = d.cards.map(c=>`<div class="card" data-target="${c.target}"><div><div class="card-label">${c.label}</div><div class="card-value">${c.value}</div></div><div><span class="card-delta-label">前月比</span>${deltaHtml(c.delta,c.goodUp)}</div></div>`).join('');
  table('comparison-table', ['項目','今月','前月','差分','評価'], d.comparisonRows);
  document.getElementById('factor-comments').innerHTML = d.factorComments.map(x=>`<li>${x}</li>`).join('');
  table('trend-table', Object.keys(d.trendRows[0] || {}), d.trendRows);
  table('overall-table', ['項目','値','前月比'], simpleRows(d.overallRows));
  table('amount-table', ['項目','値','前月比'], simpleRows(d.amountRows));
  table('first-table', ['項目','値','前月比'], simpleRows(d.firstRows));
  table('repeat-table', ['項目','値','前月比'], simpleRows(d.repeatRows));
  table('amount-band-table', ['金額帯','成約','未成約','成約率','成約金額'], d.amountBandRows.map(r=>({'金額帯':r.label,'成約':r.converted+'件','成約Raw':r.converted,'未成約':r.unconverted+'件','未成約Raw':r.unconverted,'成約率':r.rateText,'成約率Raw':r.rate,'成約金額':r.convertedAmountText,'成約金額Raw':r.convertedAmount})));
  table('category-table', ['カテゴリ','成約','未成約','成約率','成約金額'], d.categoryRows.map(r=>({'カテゴリ':r.label,'成約':r.converted+'件','成約Raw':r.converted,'未成約':r.unconverted+'件','未成約Raw':r.unconverted,'成約率':r.rateText,'成約率Raw':r.rate,'成約金額':r.convertedAmountText,'成約金額Raw':r.convertedAmount})));
  table('method-table', ['査定方法','成約率','成約金額'], d.methodRows.map(r=>({'査定方法':r.label,'成約率':r.rateText,'成約率Raw':r.rate,'成約金額':r.convertedAmountText,'成約金額Raw':r.convertedAmount})));
  table('repeat-segment-table', ['区分','成約件数','未成約件数','成約率','成約金額','前月比'], d.repeatSegmentRows);
  table('amount-segment-table', ['区分','成約件数','未成約件数','成約率','成約金額','前月比'], d.amountSegmentRows);
  table('category-segment-table', ['区分','成約件数','未成約件数','成約率','成約金額','前月比'], d.categorySegmentRows);
  table('deep-dive-table', ['優先区分','対象','件数','査定金額合計','平均査定額','前月比'], d.deepDiveRows);
  table('priority-table', ['優先順位','改善対象','理由','件数','金額合計'], d.priorityRows);
  document.getElementById('next-checks').innerHTML = d.nextChecks.map(x=>`<li>${x}</li>`).join('');
  document.getElementById('features').innerHTML = d.featureRows.map(x=>`<li>${x}</li>`).join('');
  table('segments-table', ['セグメント','件数','査定金額合計','件数前月比','金額前月比','コメント'], d.segmentRows);
  renderHighValueTable(d);
  table('top-table', ['優先理由','データNo','査定額','カテゴリ','方法','点数','利用回数'], d.topRows);
}
document.addEventListener('input', e=>{ if(e.target.dataset.search) render(); });
document.addEventListener('click', e=>{
  const th = e.target.closest('th[data-table]');
  if(th){ const id=th.dataset.table,key=th.dataset.key; state.sort[id] = {key, dir: state.sort[id]?.key===key ? -state.sort[id].dir : 1}; render(); return; }
  const card = e.target.closest('.card[data-target]');
  if(card){ document.getElementById(card.dataset.target)?.scrollIntoView({behavior:'smooth',block:'start'}); }
  if(e.target.id === 'high-value-download'){
    const d = DATA.byMonth[state.month];
    downloadCsv(`高額未成約一覧_${state.month}.csv`, highValueHeaders, highValueRows(d));
  }
});
document.addEventListener('input', e=>{
  if(e.target.id === 'high-value-search'){ highValueState.search = e.target.value; render(); }
  if(e.target.id === 'high-value-first-only'){ highValueState.firstOnly = e.target.checked; render(); }
});
document.addEventListener('change', e=>{
  if(e.target.id === 'high-value-category-filter'){ highValueState.category = e.target.value; render(); }
});
document.getElementById('month-select').addEventListener('change', e=>{ state.month=e.target.value; render(); });
document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
document.getElementById('month-select').innerHTML = DATA.months.map(m=>`<option value="${m}">${m}</option>`).join('');
document.getElementById('month-select').value = DATA.latestMonth;
document.getElementById('charts').innerHTML = Object.entries(DATA.charts).filter(([,v])=>v).map(([k,v])=>`<figure><img src="${v}" alt="${k}"><figcaption>${k.replace('.png','')}</figcaption></figure>`).join('');
initTheme();
render();
"""

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>分析ダッシュボード</title>
<style>{css}</style>
</head>
<body>
<main class="page">
  <header class="topbar">
    <div><h1>分析ダッシュボード</h1><p id="subtitle" class="subtitle"></p><p class="updated-at">更新日時: {updated_at}</p></div>
    <div class="header-tools"><button id="theme-toggle" class="theme-toggle" type="button">ダークモード</button><label class="selector">表示月 <select id="month-select"></select></label></div>
  </header>
  <section id="alerts" class="alerts">{static_alerts}</section>
  <section class="panel focus"><div class="section-kicker">1. 結論</div><h2>エグゼクティブサマリー</h2><ul id="executive-summary" class="comment-list">{static_list(initial["executiveSummary"])}</ul></section>
  <section class="panel primary"><div class="section-kicker">2. 重要KPI</div><h2>KPIサマリー</h2><div id="cards" class="grid cards">{static_card_html(initial["cards"])}</div></section>
  <section id="comparison" class="panel reading"><div class="section-kicker">3. 前月比較</div><h2>前月比較サマリー</h2><div id="comparison-table" class="table-wrap">{static_table_from_dicts(["項目","今月","前月","差分","評価"], initial["comparisonRows"])}</div></section>
  <section id="factors" class="panel reading"><div class="section-kicker">4. 変化要因</div><h2>変化要因分析</h2><ul id="factor-comments" class="comment-list">{static_list(initial["factorComments"])}</ul></section>
  <section class="panel reading"><div class="section-kicker">過去推移</div><h2>過去半年推移</h2><div id="trend-table" class="table-wrap">{static_table_from_dicts(list(initial["trendRows"][0].keys()) if initial["trendRows"] else [], initial["trendRows"])}</div></section>
  <section id="repeat-segment" class="panel"><div class="section-kicker">5. セグメント別分析</div><h2>利用回数別</h2><div id="repeat-segment-table" class="table-wrap">{static_table_from_dicts(["区分","成約件数","未成約件数","成約率","成約金額","前月比"], initial["repeatSegmentRows"])}</div></section>
  <section class="panel"><h2>金額帯別</h2><div class="table-tools"><input class="search" data-search="amount-segment-table" placeholder="金額帯で検索"></div><div id="amount-segment-table" class="table-wrap">{static_table_from_dicts(["区分","成約件数","未成約件数","成約率","成約金額","前月比"], initial["amountSegmentRows"])}</div></section>
  <section class="panel"><h2>カテゴリ別</h2><div class="table-tools"><input class="search" data-search="category-segment-table" placeholder="カテゴリで検索"></div><div id="category-segment-table" class="table-wrap">{static_table_from_dicts(["区分","成約件数","未成約件数","成約率","成約金額","前月比"], initial["categorySegmentRows"])}</div></section>
  <section id="deep-dive" class="panel"><div class="section-kicker">6. 未成約の深掘り</div><h2>未成約深掘り</h2><div id="deep-dive-table" class="table-wrap">{static_table_from_dicts(["優先区分","対象","件数","査定金額合計","平均査定額","前月比"], initial["deepDiveRows"])}</div></section>
  <section class="panel"><div class="section-kicker">7. 改善優先度</div><h2>改善優先度</h2><div id="priority-table" class="table-wrap">{static_table_from_dicts(["優先順位","改善対象","理由","件数","金額合計"], initial["priorityRows"])}</div></section>
  <section class="panel"><div class="section-kicker">8. 次に確認すべきこと</div><h2>次に確認すべきこと</h2><ul id="next-checks" class="comment-list">{static_list(initial["nextChecks"])}</ul></section>
  <section class="panel"><h2>未成約の特徴</h2><ul id="features" class="comment-list">{static_list(initial["featureRows"])}</ul></section>
  <section class="panel"><h2>改善対象セグメント</h2><div class="table-tools"><input class="search" data-search="segments-table" placeholder="セグメント・コメントで検索"></div><div id="segments-table" class="table-wrap">{static_table_from_dicts(["セグメント","件数","査定金額合計","件数前月比","金額前月比","コメント"], initial["segmentRows"])}</div></section>
  <section class="panel"><h2>高額未成約一覧</h2><div class="filter-tools"><input id="high-value-search" class="search" placeholder="優先度・データNo・カテゴリ・査定方法・コメントで検索"><label><input id="high-value-first-only" type="checkbox">初回のみ</label><label>カテゴリ <select id="high-value-category-filter"><option value="all">すべて</option></select></label><button id="high-value-download" type="button">CSVダウンロード</button></div><div id="high-value-unconverted-table" class="table-wrap">{static_table_from_dicts(["優先度","データNo","査定額","カテゴリ","点数","利用回数","初回/リピート","査定方法","コメント"], initial["highValueUnconvertedRows"])}</div></section>
  <details class="panel"><summary>グラフ</summary><div class="details-body"><div id="charts" class="charts">{static_charts}</div></div></details>
  <details class="panel"><summary>今月確認優先の未成約案件 TOP20</summary><div class="details-body"><div class="table-tools"><input class="search" data-search="top-table" placeholder="カテゴリ・方法・利用回数・金額で検索"></div><div id="top-table" class="table-wrap">{static_table_from_dicts(["優先理由","データNo","査定額","カテゴリ","方法","点数","利用回数"], initial["topRows"])}</div></div></details>
</main>
<script id="dashboard-data" type="application/json">{safe_payload_json}</script>
<script>{js}</script>
</body>
</html>
"""


def make_dashboard_summary(
    df: pd.DataFrame,
    monthly: pd.DataFrame,
    amount_summary: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    category_summary: pd.DataFrame,
    method_summary: pd.DataFrame,
) -> str:
    months = monthly["month"].tolist()
    latest_month = months[-1]
    prev_month = months[-2] if len(months) >= 2 else None
    cur_m = row_for(monthly, latest_month)
    prev_m = row_for(monthly, prev_month) if prev_month else None
    cur_first = row_for(repeat_summary, latest_month, "repeat_group", "初回ユーザー")
    prev_first = row_for(repeat_summary, prev_month, "repeat_group", "初回ユーザー") if prev_month else None
    cur_repeat5 = row_for(repeat_summary, latest_month, "repeat_group", "5回以上ユーザー")
    prev_repeat5 = row_for(repeat_summary, prev_month, "repeat_group", "5回以上ユーザー") if prev_month else None

    def simple_segment_rows(summary: pd.DataFrame, group_col: str, groups: list[str]) -> list[list[object]]:
        rows = []
        for group in groups:
            cur = row_for(summary, latest_month, group_col, group)
            prev = row_for(summary, prev_month, group_col, group) if prev_month else None
            rows.append(
                [
                    group,
                    f"{int(val(cur, '成約件数'))}件",
                    f"{int(val(cur, '未成約件数'))}件",
                    pct(val(cur, "成約率")),
                    yen(val(cur, "成約金額合計")),
                    diff_pt(val(cur, "成約率"), val(prev, "成約率") if prev is not None else None),
                ]
            )
        return rows

    comparison_rows = []
    comparison_specs = [
        ("全査定件数", val(cur_m, "全査定件数"), val(prev_m, "全査定件数") if prev_m is not None else None, "件", False, None),
        ("全査定金額", val(cur_m, "全査定金額 合計"), val(prev_m, "全査定金額 合計") if prev_m is not None else None, "円", False, None),
        ("成約件数", val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, "件", False, True),
        ("未成約件数", val(cur_m, "未成約件数"), val(prev_m, "未成約件数") if prev_m is not None else None, "件", False, False),
        ("成約率", val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None, "pt", True, True),
        ("成約金額", val(cur_m, "成約査定金額 合計"), val(prev_m, "成約査定金額 合計") if prev_m is not None else None, "円", False, True),
        ("未成約金額", val(cur_m, "未成約査定金額 合計"), val(prev_m, "未成約査定金額 合計") if prev_m is not None else None, "円", False, False),
        ("成約金額率", val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None, "pt", True, True),
        ("初回成約率", val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None, "pt", True, True),
        ("5回以上成約率", val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None, "pt", True, True),
    ]
    for label, current, previous, unit, is_rate, higher_good in comparison_specs:
        current_text = pct(current) if is_rate else (yen(current) if unit == "円" else f"{int(current)}{unit}")
        previous_text = "-" if previous is None else (pct(previous) if is_rate else (yen(previous) if unit == "円" else f"{int(previous)}{unit}"))
        difference_text = diff_pt(current, previous) if is_rate else diff_num(current, previous, unit)
        comparison_rows.append([label, current_text, previous_text, difference_text, "横ばい" if higher_good is None else evaluate_delta(current, previous, higher_good)])

    factor_comments = make_cause_candidates(df, monthly, repeat_summary)
    high_unconverted_current = unconverted_segment_stats(df, latest_month, "10000以上")
    high_unconverted_previous = unconverted_segment_stats(df, prev_month, "10000以上") if prev_month else {"amount": 0, "count": 0, "avg": 0}
    factor_comments.append(
        f"成約平均単価は{yen(val(prev_m, '成約査定額 平均')) if prev_m is not None else '-'}→{yen(val(cur_m, '成約査定額 平均'))}。"
    )
    factor_comments.append(
        f"10,000円以上未成約金額は{yen(high_unconverted_previous['amount'])}→{yen(high_unconverted_current['amount'])}。"
    )
    if prev_m is not None:
        factor_comments.append(f"全査定件数は{int(val(prev_m, '全査定件数'))}件→{int(val(cur_m, '全査定件数'))}件。")
        factor_comments.append(f"全査定金額は{yen(val(prev_m, '全査定金額 合計'))}→{yen(val(cur_m, '全査定金額 合計'))}。")
    if prev_m is not None and (val(cur_m, "成約金額率") - val(prev_m, "成約金額率")) <= -0.05:
        factor_comments.append(
            f"成約金額率は{pct(val(prev_m, '成約金額率'))}→{pct(val(cur_m, '成約金額率'))}（{diff_pt(val(cur_m, '成約金額率'), val(prev_m, '成約金額率'))}）。金額面の未成約確認を優先。"
        )

    deep_dive_defs = [
        ("優先確認A", "初回かつ10,000円以上未成約", "初回10000以上"),
        ("優先確認A", "10,000円以上未成約", "10000以上"),
        ("優先確認B", "初回かつ7,000〜9,999円未成約", "初回7000_9999"),
        ("優先確認C", "8,000〜12,000円未成約", "8000_12000"),
        ("優先確認D", "12,000〜20,000円未成約", "12000_20000"),
        ("優先確認E", "20,000円以上未成約", "20000以上"),
        ("優先確認F", "香水カテゴリ未成約", "香水"),
        ("優先度低", "5,000円未満未成約", "5000未満"),
    ]
    deep_rows = []
    priority_rows = []
    for rank, label, key in deep_dive_defs:
        cur = unconverted_segment_stats(df, latest_month, key)
        prev = unconverted_segment_stats(df, prev_month, key) if prev_month else {"count": 0, "amount": 0, "avg": 0}
        deep_rows.append([rank, label, f"{cur['count']}件", yen(cur["amount"]), yen(cur["avg"]), diff_num(cur["count"], prev["count"], "件") if prev_month else "-"])
        amount_score = cur["amount"] / 10000
        price_band_score = 0
        if label == "初回かつ10,000円以上未成約":
            price_band_score = 160
        elif label == "10,000円以上未成約":
            price_band_score = 140
        elif label == "初回かつ7,000〜9,999円未成約":
            price_band_score = 120
        elif label == "香水カテゴリ未成約":
            price_band_score = 90
        elif label == "20,000円以上未成約":
            price_band_score = 110
        elif label == "12,000〜20,000円未成約":
            price_band_score = 100
        elif label == "8,000〜12,000円未成約":
            price_band_score = 70
        elif label == "5,000円未満未成約":
            price_band_score = -1000
        worsening_score = max(0, cur["count"] - prev["count"]) * 8
        count_score = cur["count"] * 0.2
        score = amount_score + price_band_score + worsening_score + count_score
        if label == "5,000円未満未成約":
            score = -100000 + amount_score * 0.01
        reason_focus = "査定金額合計を優先"
        if label == "初回かつ10,000円以上未成約":
            reason_focus = "初回高額未成約。初回かつ10,000円以上の案件を優先確認"
        elif label == "10,000円以上未成約":
            reason_focus = "全体高額未成約。初回とリピーターを含む10,000円以上の案件"
        elif label == "初回かつ7,000〜9,999円未成約":
            reason_focus = "初回かつ7,000〜9,999円の未成約確認"
        elif label == "20,000円以上未成約":
            reason_focus = "20,000円以上の高額未成約確認"
        elif label == "12,000〜20,000円未成約":
            reason_focus = "12,000〜20,000円の高額帯未成約確認"
        elif label == "8,000〜12,000円未成約":
            reason_focus = "8,000〜12,000円の中高額帯未成約確認"
        elif label == "香水カテゴリ未成約":
            reason_focus = "香水カテゴリの未成約確認"
        elif label == "5,000円未満未成約":
            reason_focus = "金額インパクトが低いため優先度低"
        priority_rows.append([score, label, f"{reason_focus}。件数{cur['count']}件、査定金額合計{yen(cur['amount'])}、前月比{diff_num(cur['count'], prev['count'], '件') if prev_month else '-'}。", f"{cur['count']}件", yen(cur["amount"])])
    priority_order = {
        "初回かつ10,000円以上未成約": 1,
        "10,000円以上未成約": 2,
        "20,000円以上未成約": 3,
        "12,000〜20,000円未成約": 4,
        "香水カテゴリ未成約": 5,
        "8,000〜12,000円未成約": 6,
        "初回かつ7,000〜9,999円未成約": 7,
        "5,000円未満未成約": 8,
    }
    priority_rows.sort(key=lambda x: priority_order.get(x[1], 99))

    lines = [f"# 月次分析レポート（{latest_month}）", ""]
    lines.append("## 1. エグゼクティブサマリー")
    lines.append(f"- {latest_month}は成約率{pct(val(cur_m, '成約率'))}で、前月比{diff_pt(val(cur_m, '成約率'), val(prev_m, '成約率') if prev_m is not None else None)}。")
    lines.append(f"- 全査定件数は{int(val(cur_m, '全査定件数'))}件で、前月比{diff_num(val(cur_m, '全査定件数'), val(prev_m, '全査定件数') if prev_m is not None else None, '件')}。")
    lines.append(f"- 全査定金額は{yen(val(cur_m, '全査定金額 合計'))}で、前月比{diff_num(val(cur_m, '全査定金額 合計'), val(prev_m, '全査定金額 合計') if prev_m is not None else None, '円')}。")
    lines.append(f"- 成約金額は{yen(val(cur_m, '成約査定金額 合計'))}で、前月比{diff_num(val(cur_m, '成約査定金額 合計'), val(prev_m, '成約査定金額 合計') if prev_m is not None else None, '円')}。")
    lines.append(f"- 初回成約率は{pct(val(cur_first, '成約率'))}。5回以上ユーザーの{pct(val(cur_repeat5, '成約率'))}と比べて{(val(cur_first, '成約率') - val(cur_repeat5, '成約率')) * 100:+.1f}pt。")
    lines.append(f"- 未成約金額は{yen(val(cur_m, '未成約査定金額 合計'))}で、前月比{diff_num(val(cur_m, '未成約査定金額 合計'), val(prev_m, '未成約査定金額 合計') if prev_m is not None else None, '円')}。")
    if prev_m is not None and (val(cur_m, "成約金額率") - val(prev_m, "成約金額率")) <= -0.05:
        lines.append(f"- 成約金額率は{pct(val(prev_m, '成約金額率'))}→{pct(val(cur_m, '成約金額率'))}（{diff_pt(val(cur_m, '成約金額率'), val(prev_m, '成約金額率'))}）。金額面の未成約確認を優先。")
    lines.append("- 今月は件数よりも、金額の高い未成約が増えた月です。")
    lines.append("")

    lines.append("## 2. KPIサマリー")
    lines += md_table(["KPI", latest_month, "前月比"], [
        ["成約率", pct(val(cur_m, "成約率")), diff_pt(val(cur_m, "成約率"), val(prev_m, "成約率") if prev_m is not None else None)],
        ["全査定件数", f"{int(val(cur_m, '全査定件数'))}件", diff_num(val(cur_m, "全査定件数"), val(prev_m, "全査定件数") if prev_m is not None else None, "件")],
        ["全査定金額", yen(val(cur_m, "全査定金額 合計")), diff_num(val(cur_m, "全査定金額 合計"), val(prev_m, "全査定金額 合計") if prev_m is not None else None, "円")],
        ["成約件数", f"{int(val(cur_m, '成約件数'))}件", diff_num(val(cur_m, "成約件数"), val(prev_m, "成約件数") if prev_m is not None else None, "件")],
        ["成約金額", yen(val(cur_m, "成約査定金額 合計")), diff_num(val(cur_m, "成約査定金額 合計"), val(prev_m, "成約査定金額 合計") if prev_m is not None else None, "円")],
        ["成約金額率", pct(val(cur_m, "成約金額率")), diff_pt(val(cur_m, "成約金額率"), val(prev_m, "成約金額率") if prev_m is not None else None)],
        ["初回成約率", pct(val(cur_first, "成約率")), diff_pt(val(cur_first, "成約率"), val(prev_first, "成約率") if prev_first is not None else None)],
        ["5回以上成約率", pct(val(cur_repeat5, "成約率")), diff_pt(val(cur_repeat5, "成約率"), val(prev_repeat5, "成約率") if prev_repeat5 is not None else None)],
        ["7,000〜9,999円初回未成約件数", f"{segment_count(df, latest_month, '初回7000_9999')}件", diff_num(segment_count(df, latest_month, "初回7000_9999"), segment_count(df, prev_month, "初回7000_9999") if prev_month else None, "件")],
        ["8,000〜12,000円未成約件数", f"{unconverted_count(df, latest_month, '8000_12000')}件", diff_num(unconverted_count(df, latest_month, "8000_12000"), unconverted_count(df, prev_month, "8000_12000") if prev_month else None, "件")],
        ["12,000〜20,000円未成約件数", f"{unconverted_count(df, latest_month, '12000_20000')}件", diff_num(unconverted_count(df, latest_month, "12000_20000"), unconverted_count(df, prev_month, "12000_20000") if prev_month else None, "件")],
        ["20,000円以上未成約件数", f"{unconverted_count(df, latest_month, '20000以上')}件", diff_num(unconverted_count(df, latest_month, "20000以上"), unconverted_count(df, prev_month, "20000以上") if prev_month else None, "件")],
    ])
    lines.append("")

    lines.append("## 3. 前月比較サマリー")
    lines += md_table(["項目", "今月", "前月", "差分", "評価"], comparison_rows)
    lines.append("")
    lines.append("## 4. 過去半年推移")
    lines += md_table(
        [
            "月",
            "成約",
            "未成約",
            "全査定",
            "全査定金額",
            "成約率",
            "成約査定金額",
            "未成約査定金額",
            "成約金額率",
            "初回成約率",
            "5回以上成約率",
            "初回7,000〜9,999円未成約",
            "8,000〜12,000円未成約",
            "12,000〜20,000円未成約",
            "20,000円以上未成約",
            "香水成約率",
            "サプリ成約率",
        ],
        make_recent_trend_rows(df, monthly, repeat_summary, category_summary),
    )
    lines.append("")
    lines.append("## 5. 変化要因分析")
    for comment in factor_comments:
        lines.append(f"- {comment}")
    lines.append("")

    lines.append("## 6. セグメント別分析")
    lines.append("### 利用回数別")
    lines += md_table(["区分", "成約件数", "未成約件数", "成約率", "成約金額", "前月比"], simple_segment_rows(repeat_summary, "repeat_group", REPEAT_GROUPS))
    lines.append("")
    lines.append("### 金額帯別")
    lines += md_table(["区分", "成約件数", "未成約件数", "成約率", "成約金額", "前月比"], simple_segment_rows(amount_summary, "amount_band", [x[0] for x in AMOUNT_BANDS]))
    lines.append("")
    lines.append("### カテゴリ別")
    lines += md_table(["区分", "成約件数", "未成約件数", "成約率", "成約金額", "前月比"], simple_segment_rows(category_summary, "category", CATEGORIES))
    lines.append("")

    lines.append("## 7. 未成約深掘り")
    lines += md_table(["優先区分", "対象", "件数", "査定金額合計", "平均査定額", "前月比"], deep_rows)
    lines.append("")
    lines.append("## 8. 改善優先度")
    lines += md_table(["順位", "改善対象", "理由", "件数", "金額合計"], [[i, row[1], row[2], row[3], row[4]] for i, row in enumerate(priority_rows, start=1)])
    lines.append("")
    lines.append("## 9. 次に確認すべきこと")
    for item in [
        "初回10,000円以上未成約の金額上位10件を確認",
        "10,000円以上未成約のうち、リピーター案件を確認",
        "初回7,000〜9,999円未成約の提示金額と返信内容を確認",
        "香水未成約の査定額上位10件を確認",
        "20,000円以上未成約の件数と金額を確認",
        "12,000〜20,000円未成約の金額上位10件を確認",
        "8,000〜12,000円未成約の単品率と利用回数を確認",
        "高額未成約の競合価格との差額確認",
        "前年同カテゴリの平均提示額との差確認",
        "査定方法別の平均提示率確認",
        "高額帯の提示率推移確認",
    ]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def get_font(size: int):
    if ImageFont is None:
        return None
    for path in [r"C:\Windows\Fonts\meiryo.ttc", r"C:\Windows\Fonts\YuGothM.ttc", r"C:\Windows\Fonts\msgothic.ttc"]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def save_charts_with_pillow(monthly: pd.DataFrame, repeat_summary: pd.DataFrame, amount_summary: pd.DataFrame, category_summary: pd.DataFrame, charts_dir: Path) -> None:
    if Image is None:
        log("[WARN] matplotlib/Pillow が無いためグラフPNGを出力できませんでした。")
        return

    def canvas(title: str):
        image = Image.new("RGB", (1000, 620), "white")
        draw = ImageDraw.Draw(image)
        draw.text((40, 28), title, fill="#222222", font=get_font(26))
        draw.line((80, 510, 940, 510), fill="#444444", width=2)
        draw.line((80, 110, 80, 510), fill="#444444", width=2)
        for i in range(5):
            y = 510 - i * 80
            draw.line((80, y, 940, y), fill="#dddddd")
            draw.text((25, y - 10), f"{i * 25}%", fill="#555555", font=get_font(15))
        return image, draw

    def y_pos(rate: float) -> int:
        return int(510 - max(0.0, min(1.0, float(rate))) * 320)

    def line_chart(data: pd.DataFrame, x_col: str, y_col: str, title: str, filename: str) -> None:
        image, draw = canvas(title)
        data = data.sort_values(x_col)
        step = 0 if len(data) <= 1 else 760 / (len(data) - 1)
        pts = []
        for i, (_, row) in enumerate(data.iterrows()):
            x, y = int(120 + i * step), y_pos(row[y_col])
            pts.append((x, y))
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#1f77b4")
            draw.text((x - 34, 528), str(row[x_col]), fill="#333333", font=get_font(15))
            draw.text((x - 24, y - 28), pct(row[y_col]), fill="#1f77b4", font=get_font(15))
        if len(pts) >= 2:
            draw.line(pts, fill="#1f77b4", width=3)
        image.save(charts_dir / filename)

    def bar_chart(data: pd.DataFrame, label_col: str, y_col: str, title: str, filename: str) -> None:
        image, draw = canvas(title)
        x = 120
        width = max(45, int(700 / max(1, len(data)) * 0.55))
        gap = max(25, int(700 / max(1, len(data)) * 0.35))
        for _, row in data.iterrows():
            y = y_pos(row[y_col])
            draw.rectangle((x, y, x + width, 510), fill="#2ca02c")
            draw.text((x - 8, y - 26), pct(row[y_col]), fill="#2ca02c", font=get_font(15))
            label = str(row[label_col]).replace("〜", "\n〜") if len(str(row[label_col])) > 8 else str(row[label_col])
            draw.multiline_text((x - 14, 528), label, fill="#333333", font=get_font(14), spacing=2)
            x += width + gap
        image.save(charts_dir / filename)

    line_chart(monthly, "month", "成約率", "月別成約率推移", "monthly_conversion_rate.png")
    line_chart(repeat_summary[repeat_summary["repeat_group"] == "初回ユーザー"], "month", "成約率", "初回成約率推移", "first_user_conversion_rate.png")
    latest = monthly["month"].max()
    bar_chart(amount_summary[amount_summary["month"] == latest], "amount_band", "成約率", f"金額帯別成約率 ({latest})", "amount_band_conversion_rate.png")
    bar_chart(category_summary[category_summary["month"] == latest], "category", "成約率", f"カテゴリ別成約率 ({latest})", "category_conversion_rate.png")


def save_charts(monthly: pd.DataFrame, repeat_summary: pd.DataFrame, amount_summary: pd.DataFrame, category_summary: pd.DataFrame, charts_dir: Path) -> None:
    charts_dir.mkdir(parents=True, exist_ok=True)
    if plt is None:
        save_charts_with_pillow(monthly, repeat_summary, amount_summary, category_summary, charts_dir)
        return
    plt.rcParams["font.family"] = ["Meiryo", "Yu Gothic", "MS Gothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(monthly["month"], monthly["成約率"] * 100, marker="o")
    ax.set_title("月別成約率推移")
    ax.set_ylabel("成約率(%)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(charts_dir / "monthly_conversion_rate.png", dpi=160)
    plt.close(fig)
    save_charts_with_pillow(monthly, repeat_summary, amount_summary, category_summary, charts_dir)


def save_recent_trend_charts(
    monthly: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    amount_summary: pd.DataFrame,
    category_summary: pd.DataFrame,
    charts_dir: Path,
) -> None:
    if Image is None:
        log("[WARN] Pillow が無いため過去半年グラフPNGを出力できませんでした。")
        return
    charts_dir.mkdir(parents=True, exist_ok=True)
    months = recent_months(monthly)
    colors = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2"]

    def canvas(title: str):
        image = Image.new("RGB", (1120, 660), "white")
        draw = ImageDraw.Draw(image)
        draw.text((42, 28), title, fill="#111827", font=get_font(28))
        draw.line((90, 540, 1040, 540), fill="#374151", width=2)
        draw.line((90, 120, 90, 540), fill="#374151", width=2)
        for i in range(5):
            y = 540 - i * 95
            draw.line((90, y, 1040, y), fill="#e5e7eb")
        return image, draw

    def save_line(series: list[tuple[str, list[float]]], title: str, filename: str, percent: bool = False, yen_axis: bool = False) -> None:
        image, draw = canvas(title)
        all_values = [v for _, values in series for v in values]
        if not all_values:
            image.save(charts_dir / filename)
            return
        if percent:
            ymin, ymax = 0.0, 1.0
        else:
            ymin, ymax = min(all_values), max(all_values)
            if ymin == ymax:
                ymin = 0
                ymax = ymax or 1
            pad = (ymax - ymin) * 0.1
            ymin = max(0, ymin - pad)
            ymax = ymax + pad

        def x_pos(i: int) -> int:
            return 120 if len(months) <= 1 else int(120 + i * (850 / (len(months) - 1)))

        def y_pos(value: float) -> int:
            return int(540 - ((value - ymin) / (ymax - ymin)) * 380)

        for i, month in enumerate(months):
            draw.text((x_pos(i) - 35, 558), month, fill="#374151", font=get_font(14))

        for idx, (label, values) in enumerate(series):
            color = colors[idx % len(colors)]
            points = []
            for i, value in enumerate(values):
                x, y = x_pos(i), y_pos(value)
                points.append((x, y))
                draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)
                text = pct(value) if percent else (f"{int(value / 10000):,}万" if yen_axis else f"{value:.0f}")
                if len(series) == 1:
                    draw.text((x - 24, y - 28), text, fill=color, font=get_font(14))
            if len(points) >= 2:
                draw.line(points, fill=color, width=3)
            lx = 120 + (idx % 3) * 300
            ly = 92 + (idx // 3) * 24
            draw.rectangle((lx, ly + 5, lx + 18, ly + 17), fill=color)
            draw.text((lx + 26, ly), label, fill="#111827", font=get_font(15))
        image.save(charts_dir / filename)

    save_line(
        [("成約率", [val(row_for(monthly, m), "成約率") for m in months])],
        "過去半年 成約率推移",
        "recent_conversion_rate.png",
        percent=True,
    )
    save_line(
        [("全査定件数", [val(row_for(monthly, m), "全査定件数") for m in months])],
        "過去半年 全査定件数推移",
        "recent_total_assessments.png",
    )
    save_line(
        [("全査定金額", [val(row_for(monthly, m), "全査定金額 合計") for m in months])],
        "過去半年 全査定金額推移",
        "recent_total_amount.png",
        yen_axis=True,
    )
    save_line(
        [("成約査定金額合計", [val(row_for(monthly, m), "成約査定金額 合計") for m in months])],
        "過去半年 成約査定金額合計推移",
        "recent_converted_amount.png",
        yen_axis=True,
    )
    save_line(
        [("初回成約率", [val(row_for(repeat_summary, m, "repeat_group", "初回ユーザー"), "成約率") for m in months])],
        "過去半年 初回成約率推移",
        "recent_first_conversion_rate.png",
        percent=True,
    )
    save_line(
        [("5回以上ユーザー成約率", [val(row_for(repeat_summary, m, "repeat_group", "5回以上ユーザー"), "成約率") for m in months])],
        "過去半年 5回以上ユーザー成約率推移",
        "recent_repeat5_conversion_rate.png",
        percent=True,
    )
    save_line(
        [(band, [val(row_for(amount_summary, m, "amount_band", band), "成約率") for m in months]) for band, _, _ in AMOUNT_BANDS],
        "過去半年 金額帯別成約率推移",
        "recent_amount_band_conversion_rate.png",
        percent=True,
    )
    save_line(
        [(cat, [val(row_for(category_summary, m, "category", cat), "成約率") for m in months]) for cat in CATEGORIES],
        "過去半年 カテゴリ別成約率推移",
        "recent_category_conversion_rate.png",
        percent=True,
    )


def open_dashboard_html(path: Path) -> None:
    try:
        html_path = path.resolve()
        if sys.platform.startswith("win"):
            os.startfile(str(html_path))  # type: ignore[attr-defined]
        else:
            webbrowser.open(html_path.as_uri())
        log(f"[INFO] opened html dashboard: {html_path}")
    except Exception as exc:
        log(f"[WARN] html dashboard を自動で開けませんでした: {path} ({exc})")


def analyze(root: Path, output_dir: Path, open_html: bool = True) -> None:
    df = build_dataset(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    monthly = make_monthly_summary(df)
    months = monthly["month"].tolist()
    repeat_summary = ensure_all_groups(make_repeat_summary(df), "repeat_group", REPEAT_GROUPS, months)
    amount_summary = ensure_all_groups(summarize_group(df, ["month", "amount_band"]), "amount_band", [x[0] for x in AMOUNT_BANDS], months)
    category_summary = ensure_all_groups(summarize_group(df, ["month", "category"]), "category", CATEGORIES, months)
    method_summary = ensure_all_groups(summarize_group(df, ["month", "method"]), "method", METHODS, months)
    deep_dive = make_deep_dive(df)

    write_csv(monthly, output_dir / "monthly_summary.csv")
    write_csv(amount_summary, output_dir / "amount_band_summary.csv")
    write_csv(repeat_summary, output_dir / "repeat_summary.csv")
    write_csv(category_summary, output_dir / "category_summary.csv")
    write_csv(method_summary, output_dir / "method_summary.csv")
    write_csv(deep_dive, output_dir / "deep_dive_unconverted.csv")

    charts_dir = output_dir / "charts"
    save_charts(monthly, repeat_summary, amount_summary, category_summary, charts_dir)
    save_recent_trend_charts(monthly, repeat_summary, amount_summary, category_summary, charts_dir)
    (output_dir / "report.md").write_text(make_report(monthly, amount_summary, repeat_summary, category_summary, method_summary, deep_dive), encoding="utf-8")
    (output_dir / "dashboard_summary.md").write_text(make_dashboard_summary(df, monthly, amount_summary, repeat_summary, category_summary, method_summary), encoding="utf-8")
    html_path = output_dir / "dashboard_summary.html"
    html_content = make_dashboard_summary_html(df, monthly, amount_summary, repeat_summary, category_summary, method_summary, output_dir / "charts")
    html_path.write_text(html_content, encoding="utf-8")
    index_path = output_dir / "index.html"
    index_path.write_text(html_content, encoding="utf-8")
    if output_dir.name == "outputs":
        pages_index_path = output_dir.parent / "index.html"
        pages_index_path.write_text(html_content, encoding="utf-8")
    log(f"[INFO] outputs written: {output_dir}")
    log(f"[INFO] dashboard written: {output_dir / 'dashboard_summary.md'}")
    log(f"[INFO] html dashboard written: {html_path}")
    log(f"[INFO] GitHub Pages index written: {index_path}")
    if output_dir.name == "outputs":
        log(f"[INFO] GitHub Pages root index written: {pages_index_path}")
    if open_html:
        open_dashboard_html(html_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="査定CSVを査定月基準で成約・未成約分析します。")
    parser.add_argument("--root", default=".", help="月フォルダまたは data/ を含むルートディレクトリ")
    parser.add_argument("--output", default="outputs", help="出力先ディレクトリ")
    parser.add_argument("--no-open", action="store_true", help="生成後に dashboard_summary.html を自動で開かない")
    args = parser.parse_args()
    try:
        analyze(Path(args.root), Path(args.output), open_html=not args.no_open)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
