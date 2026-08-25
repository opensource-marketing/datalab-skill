"""전국 브리프에 필요한 지표를 모은다.

**지표 하나가 실패해도 멈추지 않는다.** 전국 브리프는 서로 다른 출처
여섯 갈래를 한 장에 모으는 것이라, 크루즈 하나가 늦게 발표됐다고 방한
외래객까지 못 보게 되면 리포트의 뜻이 없다. 실패는 삼키되 meta에
사유를 남긴다 — 삼키고 남기지 않으면 빈 칸이 "값이 0"으로 읽힌다.

# 모듈 이름에 national_ 접두사를 붙인 이유: 다른 스킬에도 collect.py가
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
import national  # noqa: E402
import period  # noqa: E402

# 추이를 볼 기본 길이. 전년 동월과 견주려면 열두 달이 필요하다.
TREND_MONTHS = 12


def _try(meta, key, fn):
    """지표 하나를 모은다. 실패하면 사유만 남기고 None."""
    try:
        return fn()
    except national.NationalError as exc:
        meta["미수록"][key] = f"지표없음: {exc}"
    except client.SessionExpired:
        meta["미수록"][key] = "세션만료"
        meta["세션상태"] = "만료"
    except client.FetchError as exc:
        meta["미수록"][key] = f"인출실패: {exc}"
    return None


def collect(ym1, ym2, *, cache_dir=None, age=None):
    """전국 브리프의 재료를 한 번에 모은다."""
    meta = {"기준기간": f"{ym1}~{ym2}", "미수록": {}, "세션상태": "정상",
            "빠진달": {}, "모르는카드": []}

    data = {}
    data["요약"] = _try(meta, "요약", lambda: national.summary(cache_dir))
    if data["요약"]:
        meta["모르는카드"] = data["요약"]["모르는코드"]

    data["5대지표"] = _try(meta, "5대지표", lambda: national.rollup(cache_dir))
    data["상위국가"] = _try(meta, "상위국가",
                         lambda: national.top_countries(cache_dir))

    data["추이"] = {}
    for name in national.TRENDS:
        got = _try(meta, f"추이:{name}",
                   lambda n=name: national.trend(n, ym1, ym2, cache_dir))
        if got is None:
            continue
        data["추이"][name] = got
        if got["빠진달"]:
            meta["빠진달"][name] = got["빠진달"]

    data["급등동네"] = _try(meta, "급등동네", lambda: national.hotspots(cache_dir))
    data["급등관광지"] = _try(meta, "급등관광지",
                          lambda: national.rising_places(cache_dir))
    data["관광수지"] = _try(meta, "관광수지",
                        lambda: national.tourism_balance(ym1, ym2, cache_dir))
    data["국민여행"] = _try(meta, "국민여행",
                        lambda: national.domestic_survey(cache_dir))
    data["불편신고"] = _try(meta, "불편신고",
                        lambda: national.complaints(ym1, ym2, cache_dir))
    data["유입"] = _try(meta, "유입",
                      lambda: national.inbound_mix(ym1, ym2, cache_dir))
    data["시도체류"] = _try(meta, "시도체류",
                        lambda: national.sido_stay(ym1, ym2, cache_dir))

    # 인기 관광지는 내비게이션 창이 따로다(최근 석 달). 요청 기간을 그대로
    # 쓰면 빈 배열이 오므로 끝 달에서 석 달을 되짚는다.
    tmap_to = ym2
    tmap_from = period.shift(ym2, -2)
    data["연령인기"] = _try(
        meta, "연령인기",
        lambda: national.popular_by_age(tmap_from, tmap_to, age, cache_dir))
    meta["내비게이션창"] = f"{tmap_from}~{tmap_to}"
    meta["연령대"] = str(age) if age else "전 연령"

    meta["시도지표"] = 12
    meta["수록지표"] = 12 - len({k.split(":")[0] for k in meta["미수록"]})
    return data, meta


def default_period(today=None):
    """기본 기간: 지난달에서 열두 달을 되짚는다.

    이번 달을 끝으로 잡지 않는 것은, 어느 지표도 이번 달을 아직 내놓지
    않기 때문이다. 끝을 이번 달로 잡으면 늘 마지막 칸이 비어 보인다.
    """
    ym2 = period.resolve("최근1개월", today=today)[1]
    return period.shift(ym2, -(TREND_MONTHS - 1)), ym2
