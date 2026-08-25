"""조회 결과를 사람이 읽을 표로 만든다.

리포트 Skill들은 HTML을 만들지만 조회는 터미널에서 끝나는 일이 많다.
그래서 여기서는 폭이 좁고 붙여 넣기 쉬운 형태를 우선한다.
"""
import csv
import io
import json

SOURCE = "출처: 한국관광공사 한국관광 데이터랩(datalab.visitkorea.or.kr)"


def _cell(value):
    """숫자는 천단위 구분을 넣고, 정수는 소수점을 떼고, 결측은 비운다.

    pandas는 결측을 None이 아니라 float('nan')으로 준다. None만 걸러내면
    표에 "nan"이 숫자처럼 찍히는데, 읽는 사람은 그것을 값으로 오해한다.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:   # NaN
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _raw(value):
    """csv·json에 넣을 원값. 정수로 떨어지는 실수는 소수점을 뗀다.

    데이터랩 값은 사람 수·건수가 대부분인데, pandas 가 결측 때문에
    컬럼을 float64 로 담아 "2733037.0" 이 된다. 스프레드시트는 견디지만
    JSON 을 그대로 옮겨 적으면 "2,733,037.0명" 이 된다 — 사람 수에
    소수점은 뜻이 없다. 결측은 비운다(None).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value != value:      # NaN
            return None
        if value.is_integer():
            return int(value)
    return value


def _width(text):
    """한글은 터미널에서 두 칸을 차지한다. 그 폭으로 센다."""
    return sum(2 if ord(ch) > 0x1100 else 1 for ch in str(text))


def _pad(text, width):
    return str(text) + " " * max(0, width - _width(text))


def as_table(frame, limit=None):
    """DataFrame을 고정폭 표 문자열로 만든다."""
    if frame.empty:
        return "(행 없음)"
    view = frame if limit is None else frame.head(limit)
    columns = list(view.columns)
    cells = [[_cell(v) for v in row] for row in view.itertuples(index=False)]
    widths = [max(_width(col), *(_width(r[i]) for r in cells)) if cells
              else _width(col) for i, col in enumerate(columns)]

    lines = ["  ".join(_pad(c, w) for c, w in zip(columns, widths)),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(_pad(c, w) for c, w in zip(row, widths)) for row in cells]
    if limit is not None and len(frame) > limit:
        lines.append(f"... 전체 {len(frame)}행 중 {limit}행만 보였습니다 "
                     f"(--limit 으로 조절)")
    return "\n".join(lines)


def as_markdown(frame, limit=None):
    """마크다운 표. 문서나 메신저에 그대로 붙여 넣을 때 쓴다."""
    if frame.empty:
        return "(행 없음)"
    view = frame if limit is None else frame.head(limit)
    columns = list(view.columns)
    lines = ["| " + " | ".join(str(c) for c in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for row in view.itertuples(index=False):
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return "\n".join(lines)


def as_csv(frame):
    """CSV. 엑셀로 넘길 때 쓴다. 여기서는 숫자를 가공하지 않는다 —
    표시용 천단위 쉼표가 들어가면 스프레드시트가 문자열로 읽는다."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(frame.columns))
    for row in frame.itertuples(index=False):
        writer.writerow(["" if _raw(v) is None else _raw(v) for v in row])
    return buffer.getvalue().rstrip("\n")


def as_json(frame):
    records = [{k: _raw(v) for k, v in row.items()}
               for row in frame.to_dict(orient="records")]
    return json.dumps(records, ensure_ascii=False, indent=1, default=str)


RENDERERS = {"table": as_table, "md": as_markdown,
             "csv": as_csv, "json": as_json}


def render(frame, fmt="table", limit=None):
    """형식 이름으로 렌더링한다. limit은 표 형식에서만 의미가 있다 —
    csv와 json은 기계가 읽으므로 잘라 내면 조용한 데이터 손실이 된다."""
    if fmt in ("table", "md"):
        return RENDERERS[fmt](frame, limit)
    return RENDERERS[fmt](frame)
