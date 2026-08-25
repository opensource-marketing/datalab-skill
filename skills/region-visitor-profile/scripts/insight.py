"""지역 지표에 비교 기준을 붙인다.

수치 하나만 놓으면 높은 건지 낮은 건지 알 수 없다. 전년 동기와
유사지역이라는 두 기준을 붙여 해석 가능한 값으로 만든다. 기준을
만들지 못하면 예외가 아니라 None을 돌려주고, 호출부가 "비교기준 없음"을
렌더한다 — 없는 기준을 지어내는 것보다 없다고 말하는 편이 낫다.
"""
import pathlib
import re
import sys

import pandas as pd

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH_SCRIPTS = _SKILLS_ROOT / "datalab-fetch" / "scripts"
if str(_FETCH_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FETCH_SCRIPTS))

import client
import normalize

from collect import load_loc_catalog

YM = re.compile(r"^\d{6}$")
MAX_PEERS = 3

# 월별 추이형 지표만 기간 대표값을 비교할 수 있다.
# {qid: (방식, 값_컬럼, 가중_컬럼)}
#   mean  — 월별 값의 단순평균. 카운트형이거나 가중치를 구할 수 없는 경우
#   wmean — Σ(값×가중)/Σ(가중). 같은 프레임에 규모 컬럼이 있는 비율형
#   ratio — Σ(분자)/Σ(분모)×100. 분자·분모 원자료가 둘 다 있는 비율형.
#           사이트가 이미 반올림해 버린 비율 컬럼을 쓰지 않으므로 손실이 없다
AGGREGATION = {
    "LN_04_01_022": ("mean", "방문자수", None),
    "LN_02_01_014": ("mean", "숙박방문자수", None),
    "LN_02_01_011_002": ("wmean", "숙박비율", "순방문자수"),
    "LN_02_01_012": ("wmean", "평균_체류시간", "방문자수"),
    "LN_02_01_013_01": ("mean", "평균_숙박일", None),  # 절대 규모 컬럼이 없다
    "LN_03_03_059": ("ratio", "지역_카드사용액", "전국_카드사용액"),
}


def shift_year(ym):
    """YYYYMM을 1년 앞으로 민다."""
    text = str(ym)
    if not YM.match(text):
        raise ValueError(f"YYYYMM 형식이어야 합니다: {ym}")
    return f"{int(text[:4]) - 1}{text[4:]}"


def _numeric(frame, column):
    """프레임에서 숫자 시리즈를 꺼낸다. 없으면 None."""
    if frame is None or frame.empty or column not in frame.columns:
        return None
    return pd.to_numeric(frame[column], errors="coerce")


def _aggregate(frame, qid):
    """qid에 정해진 방식으로 기간 대표값을 낸다. 낼 수 없으면 None.

    비율형 지표를 단순평균하면 규모가 작은 달이 큰 달과 같은 무게로 들어가
    기간 전체 비율과 어긋난다. 그래서 가중 컬럼이 있으면 가중평균을,
    분자·분모가 둘 다 있으면 합계 비율을 쓴다.
    """
    kind, value_col, weight_col = AGGREGATION[qid]
    values = _numeric(frame, value_col)
    if values is None:
        return None

    if kind == "ratio":
        # 분자·분모 원자료로 기간 전체 비율을 직접 낸다. 사이트가 반올림한
        # 비율 컬럼을 평균내면 작은 지역에서 0이 되어 버린다.
        # 분자와 분모를 따로 합하면 안 된다 — 한쪽만 결측인 달이 있으면
        # 서로 다른 행 집합을 나누게 되어 비율이 조용히 어긋난다.
        denominators = _numeric(frame, weight_col)
        if denominators is None:
            return None
        pair = pd.DataFrame({"n": values, "d": denominators}).dropna()
        total = pair["d"].sum()
        if not total:
            return None
        return float(pair["n"].sum() / total * 100.0)

    if kind == "wmean":
        weights = _numeric(frame, weight_col)
        if weights is not None:
            pair = pd.DataFrame({"v": values, "w": weights}).dropna()
            if len(pair) and pair["w"].sum():
                return float((pair["v"] * pair["w"]).sum() / pair["w"].sum())
        # 가중치를 못 구하면 단순평균으로 물러난다. 없는 것보다는 낫다.

    series = values.dropna()
    return float(series.mean()) if len(series) else None


def _fetch_aggregate(qid, sgg_cd, ym1, ym2, catalog, cache_dir, session_file):
    """다른 지역/기간의 같은 지표를 인출해 기간 대표값을 낸다. 실패하면 None."""
    params = {"SGG_CD": str(sgg_cd), "BASE_YM1": str(ym1), "BASE_YM2": str(ym2)}
    try:
        rows = normalize.fetch_qid(qid, params, catalog=catalog,
                                   cache_dir=cache_dir, session_file=session_file)
    except (client.SessionExpired, client.FetchError):
        return None
    if not rows:
        return None
    return _aggregate(normalize.to_frame(qid, rows, catalog=catalog), qid)


def yoy(qid, current, sgg_cd, ym1, ym2, *,
        catalog=None, cache_dir=None, session_file=None):
    """전년 동기 대비를 계산한다. 계산할 수 없으면 None."""
    if qid not in AGGREGATION:
        return None
    now = _aggregate(current, qid)
    if now is None:
        return None

    before = _fetch_aggregate(qid, sgg_cd, shift_year(ym1), shift_year(ym2),
                              catalog or load_loc_catalog(), cache_dir, session_file)
    if before is None:
        return None

    rate = None if before == 0 else (now - before) / before * 100.0
    return {"현재": now, "전년": before, "증감률": rate}


def similar_regions(meta):
    """collect가 담아온 유사지역 표를 (코드, 이름, 유사도) 목록으로 만든다."""
    frame = meta.get("보조지표", {}).get("LN_03_01_030")
    if frame is None or frame.empty:
        return []
    needed = {"유사_지역코드", "유사_지역명", "유사도"}
    if not needed <= set(frame.columns):
        return []
    ordered = frame.sort_values("유사도", ascending=False).head(MAX_PEERS)
    return [(str(r["유사_지역코드"]), str(r["유사_지역명"]), float(r["유사도"]))
            for _, r in ordered.iterrows()]


def vs_similar(qid, current, peers, ym1, ym2, *,
               catalog=None, cache_dir=None, session_file=None):
    """유사지역 평균 대비를 계산한다. 계산할 수 없으면 None."""
    if qid not in AGGREGATION or not peers:
        return None
    mine = _aggregate(current, qid)
    if mine is None:
        return None

    catalog = catalog or load_loc_catalog()
    values, names = [], []
    # 호출량 상한은 similar_regions가 이미 적용하지만, 다른 호출자가
    # 잘라내지 않은 목록을 넘겨도 예산을 넘지 않도록 여기서도 막는다.
    for code, name, _score in peers[:MAX_PEERS]:
        value = _fetch_aggregate(qid, code, ym1, ym2, catalog, cache_dir, session_file)
        if value is not None:
            values.append(value)
            names.append(name)
    if not values:
        return None

    average = sum(values) / len(values)
    gap = None if average == 0 else (mine - average) / average * 100.0
    return {"본지역": mine, "유사지역평균": average, "격차율": gap, "비교지역": names}
