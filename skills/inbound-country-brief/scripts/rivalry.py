"""그 나라 사람들이 어디로 가는지, 그중 한국은 몇 번째인지.

5축 스코어링은 "우리에게 얼마나 좋은 시장인가"에 답한다. 이 표는
**그 시장 쪽에서 우리가 어떻게 보이는가**를 말한다 — 일본인의 여행
목적지에서 한국이 미국보다 위인지 아래인지는 순위 점수에 없다.

점수에 넣지 않는다. 축을 늘리면 이미 정의된 다섯 축의 뜻과 가중치
프로필이 흔들린다(`purpose.py` 와 같은 이유다).
"""
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH = _SKILLS_ROOT / "datalab-fetch" / "scripts"
if str(_FETCH) not in sys.path:
    sys.path.insert(0, str(_FETCH))

import client  # noqa: E402
import codes  # noqa: E402
import normalize  # noqa: E402

QID = "NAT_02_01_006"
CATALOG = _SKILLS_ROOT / "datalab-fetch" / "catalog" / "yearrep_qid_catalog.yaml"
# 한국 행에 붙는 표시. **순위가 아니다.**
KOREA_MARK = 0


def _catalog():
    return normalize.load_catalog(CATALOG)


def for_country(name, *, cache_dir=None, session_file=None):
    """(최신 연도 표, 사유) 중 한쪽만 채운다.

    표는 [{'목적지': …, '방문자수': …, '순위': …}] 이고 한국이 맨
    앞이다. **`RK` 를 그대로 순위로 쓰지 않는다** — 한국 행이 0 이라
    어느 나라를 물어도 한국이 1위가 된다.
    """
    hits = codes.resolve_country(name)
    if not hits:
        return None, "국가코드 없음"
    if len(hits) > 1:
        return None, "국가명이 여러 곳에 일치"
    code, 이름 = hits[0]
    try:
        rows = normalize.fetch_qid(
            QID, {"natCd": code, "natNm": 이름},
            catalog=_catalog(), cache_dir=cache_dir,
            session_file=session_file)
    except client.SessionExpired:
        return None, "세션만료"
    except client.FetchError:
        return None, "인출실패"
    if not rows:
        return None, "데이터없음"

    # 기간 파라미터를 무시하는 지표라 응답이 자기 창을 준다.
    # 최신 연도만 쓴다 — 여덟 해를 다 실으면 표가 팔십 행이 된다.
    연도 = max(str(r.get("BASE_YEAR") or "") for r in rows)
    최신 = [r for r in rows if str(r.get("BASE_YEAR") or "") == 연도]
    표 = []
    for r in 최신:
        수 = r.get("DSTN_CNT")
        표.append({
            "목적지": str(r.get("TOUR_NAT_NM") or ""),
            "방문자수": None if 수 is None else float(수),
            "표시": r.get("RK"),
        })
    한국 = [x for x in 표 if x["표시"] == KOREA_MARK]
    나머지 = sorted((x for x in 표 if x["표시"] != KOREA_MARK),
                   key=lambda x: -(x["방문자수"] or 0))
    return {"연도": 연도, "한국": 한국[0] if 한국 else None,
            "다른곳": 나머지}, None


def korea_rank(표):
    """(순위, 사유). 순위를 셀 수 있으면 (n, None), 아니면 (None, 사유).

    `RK` 를 믿지 않고 방문자수로 직접 센다.

    **"셀 수 없다"에는 뜻이 둘이다.** 한국이 응답에 온 라이벌 전부보다
    작으면 "이 목록 밖"이고, 한국 행 자체가 없거나 값이 비었으면
    "확인 불가"다. 하나로 뭉개면 리포트가 값이 없는 것을 순위 주장으로
    바꾼다 — 방문자수 칸이 "—"인데 순위 칸은 "10위 밖"이라고 단언한다.

    **몇 위 밖인지도 못 박지 않는다.** 상위 아홉이 오는 것이 지금
    모습이지만 개수는 해마다 달라질 수 있다(CLAUDE.md 의 그 규칙이다).
    실제로 온 라이벌 수로 "N위 밖"이라고 말한다.
    """
    표 = 표 or {}
    한국 = 표.get("한국")
    if not 한국 or 한국.get("방문자수") is None:
        return None, "확인 불가"
    라이벌 = [x for x in 표.get("다른곳") or []
              if x.get("방문자수") is not None]
    위 = [x for x in 라이벌 if x["방문자수"] > 한국["방문자수"]]
    if 라이벌 and len(위) == len(라이벌):
        # 온 라이벌이 전부 한국보다 크다. 아래에 몇이 더 있는지는
        # 이 응답으로 알 수 없다.
        return None, f"{len(라이벌) + 1}위 밖"
    return len(위) + 1, None


def for_countries(names, *, cache_dir=None, session_file=None):
    """여러 나라. ({이름: 표}, {이름: 사유})."""
    표들, missing = {}, {}
    for name in names:
        표, reason = for_country(name, cache_dir=cache_dir,
                                 session_file=session_file)
        if reason is None:
            표들[name] = 표
        else:
            missing[name] = reason
            if reason == "세션만료":
                break
    return 표들, missing
