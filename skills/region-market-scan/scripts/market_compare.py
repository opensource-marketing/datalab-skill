"""여러 지역을 같은 잣대로 나란히 놓는다.

출점·투자 판단은 대개 후보지 몇 곳 중 하나를 고르는 일이다. 한 지역을
깊게 보는 것(scan.py)과 여러 곳을 나란히 보는 것은 다른 산출물이라
따로 둔다.

# 모듈 이름에 market_ 접두사를 붙인 이유: region-visitor-profile도 collect.py와
# render.py를 가지고 있다. 두 스킬을 한 파이썬 프로세스에서 쓰면 먼저
# import된 쪽이 sys.modules를 차지해 다른 쪽 함수를 조용히 대신 실행한다.

**어느 지표도 "높을수록 좋다"고 말하지 않는다.** 객실당 수요가 높으면
공급이 빠듯하다는 뜻인데, 그것이 기회인지 위험인지는 사업 모델이 정한다.
표는 값과 그 값이 뜻하는 바만 적고, 판단은 읽는 사람에게 남긴다.
"""
import pandas as pd

import codes
import market_collect as collect
import market_metrics as metrics

# 표에 실을 열과, 그 값이 크다는 것이 무엇을 뜻하는지.
# 좋다/나쁘다가 아니라 사실만 적는다.
COLUMN_MEANING = {
    "월평균 방문자": "그 지역을 오간 사람이 많다(이동통신 추정).",
    "성수기 배수": "계절 쏠림이 크다. 연중 고르게 벌기 어렵다.",
    "숙박 비율": "잠자고 가는 비중이 높다. 체류형에 가깝다.",
    "객실 수": "등록된 숙박 객실 재고가 많다.",
    "객실당 월 숙박 방문자": "객실 하나가 감당하는 숙박 수요가 크다. "
                             "공급이 상대적으로 빠듯하다는 신호다.",
    "관광사업체 수": "관광 관련 등록 사업체가 많다.",
    "사업체 순증": "기간 중 개업이 폐업보다 많았다.",
}
SORTABLE = list(COLUMN_MEANING)
DEFAULT_SORT = "객실당 월 숙박 방문자"


def _mean(frame, column):
    if frame is None or frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _first(frame, column):
    if frame is None or frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.iloc[0]) if not values.empty else None


def row_for(name, frames):
    """한 지역의 비교 행을 만든다. 못 구한 값은 None으로 남긴다."""
    visitors = frames.get(collect.QID_VISITORS)
    lodging = frames.get(collect.QID_LODGING_VISITORS)
    room_stock = frames.get(collect.QID_ROOMS)

    peak = metrics.peak_ratio(visitors)
    demand = metrics.room_demand(lodging, room_stock)
    net = metrics.net_openings(frames.get(collect.QID_OPENINGS),
                               frames.get(collect.QID_CLOSINGS))
    return {
        "지역": name,
        "월평균 방문자": _mean(visitors, "방문자수"),
        "성수기 배수": peak["배수"] if peak else None,
        "숙박 비율": metrics.lodging_rate(frames.get("LN_02_01_011_002")),
        "객실 수": _first(room_stock, "객실_수"),
        "객실당 월 숙박 방문자": demand["값"] if demand else None,
        "관광사업체 수": _first(frames.get("BZM_02_01_001_01"), "사업체_수"),
        "사업체 순증": net["순증"] if net else None,
    }


def build(targets, ym1, ym2, *, cache_dir=None, session_file=None):
    """(비교표 DataFrame, meta)를 만든다.

    targets는 (코드, 표시이름) 목록이다. 지역 하나가 통째로 실패해도
    나머지는 그대로 싣고, 무엇이 왜 빠졌는지 meta에 남긴다.
    """
    rows = []
    missing = {}
    notes = {}
    merged = []
    stock_months = set()
    for code, name in targets:
        note = codes.merged_city_note(code)
        if note:
            merged.append(note)
        frames, reasons = collect.collect_compact(
            code, ym1, ym2, cache_dir=cache_dir, session_file=session_file,
            notes=notes)
        if reasons:
            missing[name] = reasons
        if not frames:
            continue
        rows.append(row_for(name, frames))
        stock = frames.get(collect.QID_ROOMS)
        if stock is not None and "기준월" in stock.columns and not stock.empty:
            stock_months.add(str(stock["기준월"].iloc[0]))

    meta = {
        "기준기간": f"{ym1}~{ym2}",
        "재고기준월": ", ".join(sorted(stock_months)) or "-",
        "비교지역수": len(rows),
        "요청지역수": len(targets),
        "미수록": missing,
        "기간조정": notes,
        "통합시안내": merged,
        "세션상태": "만료" if any("세션만료" in r.values()
                                   for r in missing.values()) else "정상",
    }
    return pd.DataFrame(rows), meta


def sort_table(frame, column, descending=True):
    """정렬한다. 없는 컬럼이면 그대로 두고 사유를 함께 돌려준다."""
    if frame.empty:
        return frame, None
    if column not in frame.columns:
        return frame, f"'{column}' 컬럼이 없어 정렬하지 않았습니다."
    return (frame.sort_values(column, ascending=not descending,
                              na_position="last", kind="mergesort")
                 .reset_index(drop=True)), None
