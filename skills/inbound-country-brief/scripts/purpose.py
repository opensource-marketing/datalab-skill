"""국가별 입국목적 구성을 가져온다.

5축 스코어링은 "어느 국가를 노릴까"에 답하지만 "그 사람들이 왜 오는가"는
말하지 않는다. 관광 99%인 시장과 유학·기타가 절반인 시장은 같은 방한객
수라도 마케팅이 다르다.

이 지표는 점수에 넣지 않는다. 순위를 바꾸지 않고 읽는 사람에게 맥락만
준다. 축을 늘리면 이미 정의된 다섯 축의 뜻과 가중치 프로필이 흔들린다.
"""
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH = _SKILLS_ROOT / "datalab-fetch" / "scripts"
if str(_FETCH) not in sys.path:
    sys.path.insert(0, str(_FETCH))

import client
import codes
import normalize

QID = "NAT_07_01_005"
# 목적 이름에 자리맞춤용 공백이 박혀 있다("관      광"). 표에 그대로
# 실으면 읽기 어렵다.
PURPOSE_ORDER = ["관광", "상용", "공용", "유학연수", "기타"]


def _tidy(name):
    return "".join(str(name).split())


def for_country(name, ym1, ym2, *, cache_dir=None, session_file=None):
    """국가 이름 하나의 목적 구성을 돌려준다. (구성dict, 사유) 중 한쪽만 채운다."""
    hits = codes.resolve_country(name)
    if not hits:
        return None, "국가코드 없음"
    if len(hits) > 1:
        return None, "국가명이 여러 곳에 일치"
    code = hits[0][0]
    try:
        rows = normalize.fetch_qid(
            QID, {"natCd": code, "BASE_YM1": str(ym1), "BASE_YM2": str(ym2)},
            cache_dir=cache_dir, session_file=session_file)
    except client.SessionExpired:
        return None, "세션만료"
    except client.FetchError:
        return None, "인출실패"
    if not rows:
        return None, "데이터없음"

    mix = {}
    for row in rows:
        label = _tidy(row.get("목적") or row.get("CD_NM") or "")
        value = row.get("구성비", row.get("TOU_NUM_RATE"))
        if label and value is not None:
            mix[label] = float(value)
    return (mix, None) if mix else (None, "구성비 없음")


def for_countries(names, ym1, ym2, *, cache_dir=None, session_file=None):
    """여러 국가의 목적 구성을 모은다. (구성, 미수록사유)."""
    mixes = {}
    missing = {}
    for name in names:
        mix, reason = for_country(name, ym1, ym2, cache_dir=cache_dir,
                                  session_file=session_file)
        if reason is None:
            mixes[name] = mix
        else:
            missing[name] = reason
            if reason == "세션만료":
                break
    return mixes, missing


def purpose_columns(mixes):
    """표에 쓸 목적 이름을 순서대로 정한다.

    미리 정한 순서를 먼저 쓰고, 응답에 그 밖의 목적이 있으면 뒤에 붙인다.
    새 목적이 생겼을 때 조용히 사라지지 않게 하기 위해서다.
    """
    seen = {p for mix in mixes.values() for p in mix}
    ordered = [p for p in PURPOSE_ORDER if p in seen]
    return ordered + sorted(seen - set(ordered))
