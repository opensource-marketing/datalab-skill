"""지역 지표를 섹션별로 인출한다.

지표 하나가 실패해도 나머지 수집을 계속한다. 이 스킬은 지역 간 순위를
매기지 않으므로, 인바운드 브리핑과 달리 편향된 부분집합이 결과를
왜곡할 위험이 없다. 대신 빠진 지표를 사유와 함께 meta에 남긴다.
"""
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH_SCRIPTS = _SKILLS_ROOT / "datalab-fetch" / "scripts"
if str(_FETCH_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FETCH_SCRIPTS))

import client
import codes
import normalize
import period

SEXAGE_CATALOG_PATH = (_SKILLS_ROOT / "datalab-fetch" / "catalog"
                       / "sexage_qid_catalog.yaml")
LOC_CATALOG_PATH = (_SKILLS_ROOT / "datalab-fetch" / "catalog"
                    / "loc_qid_catalog.yaml")

SECTIONS = {
    "규모·추세": ["LN_04_01_022", "LN_02_01_014"],
    "누구": ["LN_02_01_004", "LN_03_01_067"],
    "어디서": ["LN_04_01_008", "LN_03_010_003"],
    # 외국인(_013_02)을 함께 싣는 이유가 있다. 강남구는 외지인 숙박
    # 비중이 3.4%인데 외국인은 15.6%다 — 같은 지역이 내국인에게는
    # 스쳐 가는 곳이고 외국인에게는 묵는 곳이다.
    # **'전체'(LN_02_01_013)는 넣지 않는다.** 평균 숙박일이 외국인
    # 값과 같아서, 셋을 나란히 실으면 "전체와 외국인이 똑같다"는
    # 잘못된 문장이 표에서 저절로 만들어진다.
    "체류 깊이": ["LN_02_01_011_002", "LN_02_01_013_01", "LN_02_01_013_02",
                 "LN_02_01_012"],
    "소비": ["LN_03_03_059", "LN_04_01_006_001"],
    # 같은 값을 주면서 '전국 기초지자체별 평균'을 한 행 더 얹어 주는
    # 지표들이다. 위 '체류 깊이'는 이 지역 값의 월별 추이이고, 여기는
    # 전국과 견준 자리다 — 절대값만으로는 34시간이 긴지 짧은지 모른다.
    "전국과 견주면": ["LN_03_01_007", "LN_03_01_006", "LN_03_01_007_02",
                     "LN_03_01_006_02"],
    # 시군구 아래를 보는 유일한 자리다. "강릉에 누가 오나"까지는 위
    # 섹션들이 답하지만 "강릉 **어디에** 누가 모이나"는 여기서만
    # 답한다. 성·연령 코드 체계가 이 계열만 다르므로(1/2 · 2029)
    # 카탈로그의 fixed_params 를 그대로 쓴다.
    "동네까지 보면": ["SE_AG_01_01_001", "SE_AG_01_03_001",
                     "SE_AG_01_04_001"],
}
SUPPORT_QIDS = ["LN_03_01_030"]

_catalog_cache = None


def load_loc_catalog():
    """이 리포트가 쓰는 카탈로그를 읽어 캐시한다.

    이름은 loc 이지만 **읍면동 지표(성·연령별 조회)가 다른 파일에
    있어** 둘을 합쳐 돌려준다. 렌더 계층이 이 함수로 지표 이름과
    caution 을 얻으므로, 합치지 않으면 새 섹션의 표에 이름도 주의도
    붙지 않는다.
    """
    global _catalog_cache
    if _catalog_cache is None:
        merged = dict(normalize.load_catalog(LOC_CATALOG_PATH))
        merged.update(normalize.load_catalog(SEXAGE_CATALOG_PATH))
        _catalog_cache = merged
    return _catalog_cache


def _fetch_one(qid, params, catalog, cache_dir, session_file, notes=None):
    """지표 하나를 인출한다. (DataFrame, 사유) 중 한쪽만 채워 돌려준다.

    사유는 데이터없음 / 세션만료 / 인출실패 / 미발표 중 하나다. 스펙 §4.3대로
    빈 배열과 0바이트 본문은 다른 실패이며, 후자는 client가 FetchError로
    올려주므로 여기서 자동으로 구분된다.

    부르기 전에 기간을 그 지표의 수록 시점까지로 줄인다. 아직 발표되지
    않은 달은 오류가 아니라 빈 배열로 오기 때문이다.
    """
    used1, used2, note = period.clamp(qid, params.get("BASE_YM1"),
                                      params.get("BASE_YM2"))
    if note and notes is not None:
        notes[qid] = note
    if used2 is None:
        return None, "미발표"
    params = dict(params, BASE_YM1=used1, BASE_YM2=used2)
    try:
        rows = normalize.fetch_qid(qid, params, catalog=catalog,
                                   cache_dir=cache_dir, session_file=session_file)
    except client.SessionExpired:
        return None, "세션만료"
    except client.FetchError:
        return None, "인출실패"
    if not rows:
        return None, "데이터없음"
    return normalize.to_frame(qid, rows, catalog=catalog), None


def collect(sgg_cd, ym1, ym2, *, catalog=None, cache_dir=None, session_file=None):
    """한 지역의 모든 섹션 지표를 인출한다.

    반환값은 ({섹션명: {qid: DataFrame}}, meta) 두 개다. 실패한 지표는
    첫 번째 dict에 키 자체가 없고, meta["미수록지표"][qid]에 사유가 있다.
    """
    catalog = catalog or load_loc_catalog()
    params = {"SGG_CD": str(sgg_cd), "BASE_YM1": str(ym1), "BASE_YM2": str(ym2)}

    sections = {}
    support = {}
    missing = {}
    missing_sections = []
    notes = {}

    for name, qids in SECTIONS.items():
        frames = {}
        for qid in qids:
            frame, reason = _fetch_one(qid, params, catalog, cache_dir,
                                       session_file, notes)
            if reason is None:
                frames[qid] = frame
            else:
                missing[qid] = reason
        if frames:
            sections[name] = frames
        else:
            missing_sections.append(name)

    for qid in SUPPORT_QIDS:
        frame, reason = _fetch_one(qid, params, catalog, cache_dir,
                                   session_file, notes)
        if reason is None:
            support[qid] = frame
        else:
            missing[qid] = reason

    attempted = sum(len(q) for q in SECTIONS.values())
    included = attempted - sum(1 for q in missing if q not in SUPPORT_QIDS)

    meta = {
        "지역코드": str(sgg_cd),
        "기준기간": f"{ym1}~{ym2}",
        "수록지표": included,
        "시도지표": attempted,
        "수록률": included / attempted if attempted else 0.0,
        "미수록지표": missing,
        "미수록섹션": missing_sections,
        "기간조정": notes,
        "통합시안내": codes.merged_city_note(sgg_cd) if missing else None,
        "보조지표": support,
        "세션상태": "만료" if "세션만료" in missing.values() else "정상",
    }
    return sections, meta
