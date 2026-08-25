"""지역 시장 스캔에 필요한 지표를 섹션별로 인출한다.

지표 하나가 실패해도 나머지를 계속 모은다. 이 스킬은 지역에 점수를 매겨
순위를 세우지 않으므로 빠진 지표가 결과를 왜곡하지 않는다. 대신 무엇이
왜 빠졌는지를 meta에 남기고 리포트에 그대로 싣는다.

카탈로그를 넷 쓴다. 수요·매력·개폐업은 지역 카탈로그(LN_*), 사업체·
객실 재고는 관광사업체 카탈로그(BZM_*), 시도 안 순위는 빅데이터
카탈로그(BDT_*), 캠핑은 캠핑 카탈로그에 있다. 파라미터 모양이 서로
달라 나뉘어 있으므로, qid마다 어느 카탈로그를 쓸지 여기서 정한다.

**캠핑이 따로 있는 이유**는 관광진흥법상 야영장업이 숙박업과 다른
업종이기 때문이다. BZM_03_* 숙박 지표에 캠핑장은 들어 있지 않다 —
그것만 보면 캠핑 수요가 큰 지역의 공급을 통째로 못 본다.
"""
# 모듈 이름에 market_ 접두사를 붙인 이유: region-visitor-profile도 collect.py와
# render.py를 가지고 있다. 두 스킬을 한 파이썬 프로세스에서 쓰면(테스트
# 스위트가 그렇다) 먼저 import된 쪽이 sys.modules를 차지해 다른 쪽 함수를
# 조용히 대신 실행한다.
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

CATALOG_DIR = _SKILLS_ROOT / "datalab-fetch" / "catalog"
LOC_CATALOG_PATH = CATALOG_DIR / "loc_qid_catalog.yaml"
BZM_CATALOG_PATH = CATALOG_DIR / "bzm_qid_catalog.yaml"
BDA_CATALOG_PATH = CATALOG_DIR / "bda_qid_catalog.yaml"
CAMP_CATALOG_PATH = CATALOG_DIR / "camp_qid_catalog.yaml"
MAIN_CATALOG_PATH = CATALOG_DIR / "main_qid_catalog.yaml"
SEXAGE_CATALOG_PATH = CATALOG_DIR / "sexage_qid_catalog.yaml"

# 리포트에 나오는 순서 그대로다.
SECTIONS = {
    "수요": ["LN_04_01_022", "LN_02_01_014", "LN_02_01_011_002"],
    # LN_03_01_045 는 현지인과 외지인이 각각 무엇을 찾는지를 한 표에
    # 담는다. 출점 자리를 고를 때 둘의 차이가 곧 기회다 — 강릉은
    # 자연관광을 현지인 13.3% · 외지인 17.6% 로 찾는다.
    "매력": ["LN_03_01_038", "LN_03_01_041", "LN_03_012_001_001",
             "LN_03_012_001_003", "LN_03_01_004", "LN_03_01_045",
             # 세대별로 표가 완전히 달라진다(20대 여의도한강공원,
             # 60대 코엑스·통도사). 어느 세대를 겨냥할지가 곧 어느
             # 관광지 옆에 낼지다.
             "MM_HO_HOT_001_003_DETAIL"],
    "공급": ["BZM_02_01_001_01", "BZM_02_01_003", "BZM_03_01_001_01",
             "BZM_03_02_001_01", "BZM_03_02_002",
             "LN_03_010_001", "LN_03_010_002",
             # 캠핑은 관광진흥법상 숙박업이 아니라 야영장업이라
             # BZM_03_* 숙박 지표에 들어 있지 않다. 빼면 캠핑 수요가
             # 큰 지역의 공급을 통째로 못 본다.
             "LN_01_03_003_01_002", "LN_01_03_003_03_002",
             "LN_01_03_003_03_004"],
    # 시군구 안에서 어느 동네에 사람과 돈이 있는지. 출점 자리를 고르는
    # 리포트인데 시군구까지만 보고 있었다 — 강릉시가 통째로 좋아
    # 보여도 읍면동별로는 열 배 넘게 갈린다.
    "동네": ["SE_AG_01_01_001", "SE_AG_02_20_001"],
}
SUPPORT_QIDS = ["LN_03_01_030"]

# 파생 지표가 이 qid들을 이름으로 찾는다. 카탈로그에서 qid가 빠지면
# 조용히 계산이 사라지므로, 여기 상수로 두고 테스트로 존재를 지킨다.
QID_VISITORS = "LN_04_01_022"
QID_LODGING_VISITORS = "LN_02_01_014"
QID_ROOMS = "BZM_03_01_001_01"
QID_LODGING_PLACES = "BZM_03_02_001_01"
QID_OPENINGS = "LN_03_010_001"
QID_CLOSINGS = "LN_03_010_002"
QID_PEERS = "LN_03_01_030"
QID_CAMPS = "LN_01_03_003_01_002"
QID_CAMP_SITES = "LN_01_03_003_03_002"

# 시도 안에서 이 지역이 어디쯤인지 보는 지표. 시군구가 아니라 **시도**를
# 넣어야 하고, 응답은 그 시도의 시군구 전부다. 우리 지역 행을 골라
# 순위와 비중을 뽑는다 — 다른 지표에는 없는 "상대 위치"다.
QID_SIDO_VISITORS = "BDT_01_01_002"
QID_SIDO_SPENDING = "BDT_02_01_002_33"
SIDO_RANK_QIDS = [QID_SIDO_VISITORS, QID_SIDO_SPENDING]

# 방문자 구분. **이 파라미터는 지표군마다 코드 체계가 다르다.**
#
#   이동통신 방문자(BDT_01_*)  1 전체 · 2 외지인 · 3 외국인 · 4 외지인+외국인
#   신용카드 소비(BDT_02_*)    0 현지인(a) · 1 외지인(b) · 2 내국인(a+b)
#
# 소비 쪽은 화면의 select 옵션에서 읽었고 산술로 확인했다 —
# 강원 2024년 0(2,300억) + 1(4조 9,397억) = 2(5조 1,697억), 오차 1.
#
# **소비 지표에 4를 보내면 오류가 아니라 기본값(2)으로 처리된다.**
# 한동안 그렇게 보내고 있었고, SKILL.md는 "현지인을 뺐다"고 적었는데
# 실제로는 현지인이 포함된 값이 리포트에 실렸다. 강원 지출액 1위가
# 강릉시가 아니라 원주시로 나오는 등 순위가 바뀐다.
#
# 관광시장을 보는 리포트이므로 양쪽 다 현지인을 뺀다.
SIDO_RANK_TOU_DIV = {
    QID_SIDO_VISITORS: "4",   # 외지인 + 외국인
    QID_SIDO_SPENDING: "1",   # 외지인 (소비 지표에는 외국인 구분이 없다)
}

_loc_cache = None
_bzm_cache = None
_bda_cache = None
_camp_cache = None
_sexage_cache = None
_main_cache = None


def load_loc_catalog():
    global _loc_cache
    if _loc_cache is None:
        _loc_cache = normalize.load_catalog(LOC_CATALOG_PATH)
    return _loc_cache


def load_bzm_catalog():
    global _bzm_cache
    if _bzm_cache is None:
        _bzm_cache = normalize.load_catalog(BZM_CATALOG_PATH)
    return _bzm_cache


def load_bda_catalog():
    global _bda_cache
    if _bda_cache is None:
        _bda_cache = normalize.load_catalog(BDA_CATALOG_PATH)
    return _bda_cache


def load_camp_catalog():
    global _camp_cache
    if _camp_cache is None:
        _camp_cache = normalize.load_catalog(CAMP_CATALOG_PATH)
    return _camp_cache


def load_sexage_catalog():
    global _sexage_cache
    if _sexage_cache is None:
        _sexage_cache = normalize.load_catalog(SEXAGE_CATALOG_PATH)
    return _sexage_cache


def load_main_catalog():
    global _main_cache
    if _main_cache is None:
        _main_cache = normalize.load_catalog(MAIN_CATALOG_PATH)
    return _main_cache


def catalog_for(qid):
    """qid가 속한 카탈로그를 돌려준다. 어디에도 없으면 KeyError."""
    loc = load_loc_catalog()
    if qid in loc:
        return loc
    bzm = load_bzm_catalog()
    if qid in bzm:
        return bzm
    bda = load_bda_catalog()
    if qid in bda:
        return bda
    sexage = load_sexage_catalog()
    if qid in sexage:
        return sexage
    main = load_main_catalog()
    if qid in main:
        return main
    camp = load_camp_catalog()
    if qid in camp:
        return camp
    raise KeyError(f"어느 카탈로그에도 없는 qid: {qid}")


def params_for(qid, sgg_cd, ym1, ym2, extra=None):
    """qid가 받는 파라미터만 골라 넘긴다.

    관광사업체 계열은 시점 재고라 BASE_YM2 하나로 시점을 정한다. 여기에
    기간 시작(BASE_YM1)을 얹으면 지표에 따라 응답 모양이 달라지므로,
    카탈로그가 선언한 params에 있는 것만 넣는다.
    """
    entry = catalog_for(qid)[qid]
    accepted = set(entry.get("params") or ())
    region = str(sgg_cd)
    if entry.get("query_axis") == "시도":
        # 이 계열은 SGG_CD라는 이름으로 **시도 두 자리**를 받는다.
        # 시군구를 그대로 넘기면 오류가 아니라 앞 두 자리만 보거나
        # 빈 배열이 온다 — 어느 쪽이든 조용히 틀린다.
        region = region[:2]
    candidate = {"SGG_CD": region, "BASE_YM1": str(ym1),
                 "BASE_YM2": str(ym2)}
    candidate.update(extra or {})
    return {k: v for k, v in candidate.items() if k in accepted}


def _fetch_one(qid, sgg_cd, ym1, ym2, cache_dir, session_file, notes=None,
               extra=None):
    """지표 하나를 인출한다. (DataFrame, 사유) 중 한쪽만 채워 돌려준다.

    사유는 데이터없음 / 세션만료 / 인출실패 / 미발표 중 하나다. 빈 배열과
    0바이트 본문은 원인이 다른 실패이며, 후자는 client가 FetchError로
    올려주므로 여기서 자동으로 갈린다.

    부르기 전에 기간을 그 지표의 수록 시점까지로 줄인다. 관광사업체처럼
    시점 재고인 지표는 아직 발표되지 않은 달을 넣으면 빈 배열이 오는데,
    그것을 "사업체가 없다"로 읽으면 정반대의 판단을 하게 된다. 줄였다는
    사실은 notes에 남겨 리포트에 싣는다.
    """
    catalog = catalog_for(qid)
    used1, used2, note = period.clamp(qid, str(ym1), str(ym2))
    if note and notes is not None:
        notes[qid] = note
    if used2 is None:
        return None, "미발표"
    try:
        rows = normalize.fetch_qid(qid,
                                   params_for(qid, sgg_cd, used1, used2, extra),
                                   catalog=catalog, cache_dir=cache_dir,
                                   session_file=session_file)
    except client.SessionExpired:
        return None, "세션만료"
    except client.FetchError:
        return None, "인출실패"
    if not rows:
        return None, "데이터없음"
    return normalize.to_frame(qid, rows, catalog=catalog), None


def collect(sgg_cd, ym1, ym2, *, cache_dir=None, session_file=None):
    """한 지역의 수요·매력·공급 지표를 모두 인출한다.

    반환값은 ({섹션명: {qid: DataFrame}}, meta)다. 실패한 지표는 첫
    dict에 키가 아예 없고 meta["미수록지표"][qid]에 사유가 있다.
    """
    sections = {}
    support = {}
    missing = {}
    missing_sections = []
    notes = {}

    for name, qids in SECTIONS.items():
        frames = {}
        for qid in qids:
            frame, reason = _fetch_one(qid, sgg_cd, ym1, ym2,
                                       cache_dir, session_file, notes)
            if reason is None:
                frames[qid] = frame
            else:
                missing[qid] = reason
        if frames:
            sections[name] = frames
        else:
            missing_sections.append(name)

    for qid in SUPPORT_QIDS:
        frame, reason = _fetch_one(qid, sgg_cd, ym1, ym2,
                                   cache_dir, session_file, notes)
        if reason is None:
            support[qid] = frame
        else:
            missing[qid] = reason

    attempted = sum(len(q) for q in SECTIONS.values())
    included = attempted - sum(1 for q in missing if q not in SUPPORT_QIDS)

    meta = {
        "지역코드": str(sgg_cd),
        "기준기간": f"{ym1}~{ym2}",
        "재고기준월": str(ym2),
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


def collect_supply_demand(sgg_cd, ym1, ym2, *, cache_dir=None,
                          session_file=None):
    """수급 지표 계산에 딱 필요한 두 가지만 인출한다.

    유사지역과 나란히 놓으려면 비교 지역마다 같은 값이 필요한데, 전체
    섹션을 다시 모으면 지표 13개를 헛되이 부른다. 여기서는 숙박 방문자
    수와 객실 수만 가져온다.
    """
    lodging, lodging_reason = _fetch_one(QID_LODGING_VISITORS, sgg_cd, ym1,
                                         ym2, cache_dir, session_file)
    rooms, rooms_reason = _fetch_one(QID_ROOMS, sgg_cd, ym1, ym2,
                                     cache_dir, session_file)
    return {"숙박방문자": lodging, "객실": rooms,
            "사유": {"숙박방문자": lodging_reason, "객실": rooms_reason}}


# 지역 여러 곳을 나란히 놓을 때 필요한 최소 지표. 전체 섹션(15개)을 지역마다
# 다시 부르면 비교 한 번에 60번 넘게 호출한다. 표에 실리는 것만 부른다.
COMPACT_QIDS = [
    QID_VISITORS, QID_LODGING_VISITORS, "LN_02_01_011_002",
    QID_ROOMS, "BZM_02_01_001_01", QID_OPENINGS, QID_CLOSINGS,
]


def collect_compact(sgg_cd, ym1, ym2, *, cache_dir=None, session_file=None,
                    notes=None):
    """비교표에 필요한 지표만 인출한다. ({qid: DataFrame}, {qid: 사유}).

    notes 를 주면 기간 조정 내역을 거기 담는다. 비교표는 지역끼리
    나란히 놓는 것이라, 창이 조용히 짧아진 채 비교되면 스캔 리포트보다
    더 위험하다 — 어느 지역이 왜 낮은지 알 수 없게 된다.
    """
    frames = {}
    missing = {}
    for qid in COMPACT_QIDS:
        frame, reason = _fetch_one(qid, sgg_cd, ym1, ym2, cache_dir,
                                   session_file, notes)
        if reason is None:
            frames[qid] = frame
        else:
            missing[qid] = reason
    return frames, missing


def collect_sido_rank(sgg_cd, ym1, ym2, *, cache_dir=None, session_file=None):
    """이 지역이 속한 시도 안에서 어디쯤인지 인출한다.

    다른 지표는 모두 "이 지역이 얼마나"를 말하지만, 출점을 정하는
    사람은 "**옆 동네보다 나은가**"를 묻는다. 시도 안 시군구 전부가
    한 응답에 오므로, 우리 지역 행을 골라 순위와 비중을 낼 수 있다.

    실패해도 예외를 올리지 않는다. 이 블록이 없어도 리포트의 나머지는
    성립하기 때문이다 — 사유만 남긴다.
    """
    out = {}
    for qid in SIDO_RANK_QIDS:
        frame, reason = _fetch_one(qid, sgg_cd, ym1, ym2, cache_dir,
                                   session_file,
                                   extra={"touDivCd": SIDO_RANK_TOU_DIV[qid]})
        out[qid] = {"표": frame, "사유": reason}
    return out
