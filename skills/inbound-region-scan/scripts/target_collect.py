"""한 국가를 겨냥한 지역 후보 데이터를 모은다.

데이터랩에는 "국가별 지역 분포" 지표가 없다. 지역별 국적 구성을 전국으로
훑어 뒤집어야 나온다. 그래서 여기는 지역을 하나씩 도는 수집기다.

# 모듈 이름에 target_ 접두사를 붙인 이유: 다른 스킬도 collect.py와
# render.py를 가지고 있다. 한 파이썬 프로세스에서 둘 다 쓰면 먼저
# import된 쪽이 sys.modules를 차지해 다른 쪽 함수를 조용히 대신 실행한다.
"""
import pathlib
import sys

import pandas as pd

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH = _SKILLS_ROOT / "datalab-fetch" / "scripts"
if str(_FETCH) not in sys.path:
    sys.path.insert(0, str(_FETCH))

import client
import codes
import normalize

LOC_CATALOG_PATH = (_SKILLS_ROOT / "datalab-fetch" / "catalog"
                    / "loc_qid_catalog.yaml")

QID_NATIONALITY = "LN_03_01_067"     # 국적별 방문자 수·비중
QID_COUNTRY_SPEND = "LN_10_02_004"   # 국가별 외국인 카드소비(원)

# 국적 → 대한민국구석구석 언어권 지표. 그 나라 사람이 어느 관광지
# **페이지를 읽었는지**를 준다 — 방문자 수가 아니다.
# 중국 본토는 간체, 대만·홍콩은 번체다. 합치면 같은 관광지를 두 번 센다.
LANG_QID = {
    "중국": "LN_03_01_062",
    "대만": "LN_03_01_063",
    "홍콩": "LN_03_01_063",
    "일본": "LN_03_01_061",
    "미국": "LN_03_01_060",
    "영국": "LN_03_01_060",
    "캐나다": "LN_03_01_060",
    "호주": "LN_03_01_060",
}

_catalog_cache = None


class CollectError(Exception):
    """수집을 시작할 수 없을 때. 사용자 입력이 원인이다."""


def load_catalog():
    global _catalog_cache
    if _catalog_cache is None:
        _catalog_cache = normalize.load_catalog(LOC_CATALOG_PATH)
    return _catalog_cache


def regions_for(sido=None):
    """훑을 시군구 목록을 정한다. (코드, 표시이름)."""
    table = codes.load_codes()
    if sido is None:
        return sorted((code, codes.display_name(code, table)) for code in table)
    hits = codes.resolve_sido(sido)
    if not hits:
        raise CollectError(f"일치하는 시도가 없습니다: {sido}")
    if len(hits) > 1:
        lines = "\n".join(f"  {c}  {n}" for c, n in hits)
        raise CollectError(f"'{sido}'에 여러 시도가 일치합니다:\n{lines}")
    prefix = hits[0][0]
    picked = sorted((code, codes.display_name(code, table))
                    for code in table if code.startswith(prefix))
    if not picked:
        raise CollectError(f"{hits[0][1]}에는 시군구가 없습니다.")
    return picked


def _frame(qid, sgg_cd, ym1, ym2, cache_dir, session_file):
    """지표 하나를 인출한다. (DataFrame, 사유) 중 한쪽만 채운다."""
    params = {"SGG_CD": str(sgg_cd), "BASE_YM1": str(ym1),
              "BASE_YM2": str(ym2)}
    catalog = load_catalog()
    try:
        rows = normalize.fetch_qid(qid, params, catalog=catalog,
                                   cache_dir=cache_dir,
                                   session_file=session_file)
    except client.SessionExpired:
        return None, "세션만료"
    except client.FetchError:
        return None, "인출실패"
    if not rows:
        return None, "데이터없음"
    return normalize.to_frame(qid, rows, catalog=catalog), None


def _pick(frame, name_column, value_columns, country):
    """국가 행 하나를 골라 값들을 돌려준다. 없으면 None."""
    if frame is None or name_column not in frame.columns:
        return None
    picked = frame[frame[name_column].astype(str).str.strip() == country]
    if picked.empty:
        return None
    row = picked.iloc[0]
    out = {}
    for column in value_columns:
        if column not in frame.columns:
            return None
        value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
        out[column] = None if pd.isna(value) else float(value)
    return out


def per_visitor(spend, visitors):
    """방문자 1인당 카드소비.

    분자는 그 국가 외국인의 카드 사용액, 분모는 이동통신 기반 연인원
    추정치다. 같은 사람이 여러 번 잡히고 카드를 안 쓴 방문자도 분모에
    들어가므로 "1인당 얼마 쓴다"가 아니라 **지역끼리 견주는 값**이다.
    """
    if not spend or not visitors:
        return None
    return spend / visitors


def collect(country, *, sido=None, ym1, ym2, cache_dir=None,
            session_file=None, progress=None):
    """후보 지역 표와 meta를 만든다."""
    places = regions_for(sido)
    rows = []
    missing = {}
    expired = False

    for index, (code, name) in enumerate(places, start=1):
        if progress:
            progress(index, len(places), name)

        nationality, reason = _frame(QID_NATIONALITY, code, ym1, ym2,
                                     cache_dir, session_file)
        if reason == "세션만료":
            missing[name] = reason
            expired = True
            break
        if reason is not None:
            missing[name] = reason
            continue

        picked = _pick(nationality, "국적", ["방문자수", "국적_비중"], country)
        if picked is None:
            missing[name] = f"{country} 행 없음"
            continue

        spend_frame, spend_reason = _frame(QID_COUNTRY_SPEND, code, ym1, ym2,
                                           cache_dir, session_file)
        spend = None
        if spend_reason is None:
            spend_row = _pick(spend_frame, "국가", ["국가_소비액"], country)
            if spend_row is not None:
                spend = spend_row["국가_소비액"]

        rows.append({
            "지역": name,
            "방문자수": picked["방문자수"],
            "국적_비중": picked["국적_비중"],
            "카드소비": spend,
            "1인당_소비": per_visitor(spend, picked["방문자수"]),
        })

    meta = {
        "국가": country,
        "기준기간": f"{ym1}~{ym2}",
        "범위": sido or "전국",
        "훑은지역수": len(places),
        "값있는지역수": len(rows),
        "미수록": missing,
        "세션상태": "만료" if expired else "정상",
    }
    if not rows:
        return pd.DataFrame(), meta
    return pd.DataFrame(rows), meta


def language_interest(country, sgg_cd, ym1, ym2, *, cache_dir=None,
                      session_file=None, top=10):
    """그 나라 말 페이지에서 많이 읽힌 관광지. (행 목록, 사유) 중 하나.

    **방문자 수가 아니라 페이지 조회 수다.** 그래서 후보 지역 표와
    나란히 두지 않고 상위 지역의 곁다리로만 싣는다.
    국적을 언어권으로 옮길 수 없으면(예: 태국) 조용히 건너뛴다 —
    없는 언어권을 지어내면 남의 나라 관심사가 실린다.
    """
    qid = LANG_QID.get(country)
    if qid is None:
        return None, f"{country}에 맞는 언어권 지표가 없습니다"
    frame, reason = _frame(qid, sgg_cd, ym1, ym2, cache_dir, session_file)
    if reason is not None:
        return None, reason
    if "관광지명" not in frame.columns:
        return None, "관광지명 컬럼이 없습니다"
    view = frame.head(top)
    return [{"관광지": r["관광지명"], "분류": r.get("중분류"),
             "조회수": r.get("페이지_조회수")}
            for _, r in view.iterrows()], None


def known_countries(sgg_cd, ym1, ym2, *, cache_dir=None, session_file=None):
    """한 지역의 응답에 들어 있는 국적 이름들. --country 오타를 잡는 데 쓴다."""
    frame, reason = _frame(QID_NATIONALITY, sgg_cd, ym1, ym2, cache_dir,
                           session_file)
    if reason is not None or "국적" not in frame.columns:
        return []
    return sorted({str(v).strip() for v in frame["국적"]})
