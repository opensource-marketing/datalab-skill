"""지역 활력 브리프에 필요한 지표를 모은다.

**지표 하나가 실패해도 멈추지 않는다.** 재정자립도가 아직 발표되지
않았다고 관광 대체 효과까지 못 보게 되면 리포트의 뜻이 없다. 실패는
삼키되 meta에 사유를 남긴다 — 삼키고 남기지 않으면 빈 칸이 "값이 0"으로
읽힌다. 이 스킬은 그 오해가 특히 위험하다. 다루는 지표의 상당수가
실제로 0을 결측으로 보내오기 때문이다.

# 모듈 이름에 vitality_ 접두사를 붙인 이유: 다른 스킬에도 collect.py가
# 있다. 한 프로세스에서 둘 다 쓰면 먼저 import된 쪽이 sys.modules를 차지한다.
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
import vitality  # noqa: E402

# 체력 지표는 한 해만 봐서는 뜻이 없다. 고령화가 34%인 것보다 5년 만에
# 28%에서 34%가 된 것이 더 많은 것을 말한다.
DEFAULT_SPAN = 5

# 이 지표들의 마지막 발표 연도. 데이터랩이 더 최근을 내놓기 전까지
# 여기를 넘겨 물으면 빈 배열이 온다.
LATEST_YEAR = "2024"


def _try(meta, key, fn):
    """지표 하나를 모은다. 실패하면 사유만 남기고 None."""
    try:
        return fn()
    except vitality.VitalityError as exc:
        meta["미수록"][key] = f"지표없음: {exc}"
    except client.SessionExpired:
        meta["미수록"][key] = "세션만료"
        meta["세션상태"] = "만료"
    except client.FetchError as exc:
        meta["미수록"][key] = f"인출실패: {exc}"
    return None


def default_period(latest=LATEST_YEAR, span=DEFAULT_SPAN):
    """기본 기간: 마지막 발표 연도에서 다섯 해를 되짚는다."""
    end = int(latest)
    return str(end - span + 1), str(end)


def collect(sgg_cd, region_name, y1, y2, *, cache_dir=None):
    """지역 활력 브리프의 재료를 한 번에 모은다."""
    meta = {"지역코드": sgg_cd, "지역명": region_name,
            "기준기간": f"{y1}~{y2}", "미수록": {}, "세션상태": "정상",
            "빠진해": {}, "검산경고": []}

    data = {}
    data["요약"] = _try(meta, "요약",
                      lambda: vitality.summary(sgg_cd, y2, cache_dir=cache_dir))
    if data["요약"]:
        check = data["요약"]["검산"]
        if check["통과"] is False:
            # 카탈로그에 적어 둔 10,000 배율이 더는 맞지 않는다는 뜻이다.
            # 값을 그대로 실으면 만 배 틀린 금액이 리포트에 남는다.
            meta["검산경고"].append(
                "주민 1인당 역내소비액의 배율 보정이 이 지역에서 맞지 "
                "않습니다. 금액을 인용하지 마세요.")
        elif check["통과"] is None:
            # 검산에 쓸 값(1회 평균 지출액)이 없어 확인 자체를 못 했다.
            # 통과와 같은 자리에 두면 검증된 금액처럼 읽힌다.
            meta["검산경고"].append(
                "주민 1인당 역내소비액의 배율 보정을 이 지역에서는 "
                "확인하지 못했습니다(1회 평균 지출액이 오지 않았습니다). "
                "금액을 인용하기 전에 다른 지역과 견주어 보세요.")

    data["체력"] = {}
    for name in vitality.SERIES:
        got = _try(meta, f"체력:{name}",
                   lambda n=name: vitality.series(n, sgg_cd, y1, y2,
                                                  cache_dir=cache_dir))
        if got is None:
            continue
        data["체력"][name] = got
        if got["빠진해"]:
            meta["빠진해"][got["라벨"]] = got["빠진해"]

    data["대체추이"] = _try(
        meta, "대체추이",
        lambda: vitality.substitution_trend(sgg_cd, y1, y2, cache_dir=cache_dir))
    data["인구대비방문"] = _try(
        meta, "인구대비방문",
        lambda: vitality.visitor_ratio(sgg_cd, y1, y2, cache_dir=cache_dir))
    data["연령분포"] = _try(
        meta, "연령분포",
        lambda: vitality.age_profile(sgg_cd, y2, cache_dir=cache_dir))
    data["관광고용"] = _try(
        meta, "관광고용",
        lambda: vitality.tourism_jobs(sgg_cd, cache_dir=cache_dir))

    if data["연령분포"] and not data["연령분포"]["합계일치"]:
        meta["검산경고"].append(
            "연령 여덟 칸의 합이 총인구와 맞지 않습니다. 어느 칸이 "
            "결측으로 0이 된 것이므로 비중을 인용하지 마세요.")
    if data["관광고용"] and not data["관광고용"]["관광행찾음"]:
        meta["검산경고"].append(
            "산업 목록에서 관광산업 행을 찾지 못했습니다. 데이터랩이 "
            "분류를 바꿨을 수 있으니 관광 고용 수치를 인용하지 마세요.")
    if data["관광고용"] and not data["관광고용"]["합계일치"]:
        meta["검산경고"].append(
            "산업별 종사자 합이 전체와 맞지 않습니다. 데이터랩이 산업 "
            "분류를 바꿨을 수 있으니 비중을 인용하지 마세요.")

    meta["전체지표"] = 5 + len(vitality.SERIES)
    meta["수록지표"] = meta["전체지표"] - len(meta["미수록"])
    return data, meta
