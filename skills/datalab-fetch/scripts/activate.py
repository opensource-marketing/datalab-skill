"""관광수요 경쟁력 지수를 사람이 읽는 모양으로 푼다.

다른 모듈이 "몇 명이 왔는가"를 센다면 여기는 **그 지역이 관광지로서
얼마나 힘이 있는가**를 하나의 지수로 말한다. 전국 252개 시군구(또는
17개 시도)를 같은 잣대로 줄 세운 자리가 함께 온다.

함정이 셋인데 셋 다 "숫자를 거꾸로 읽게 만드는" 종류다.

**하나. 큰 쪽이 순위가 아니다.**
TURSM_DNS_DIV_VAL이 173, TURSM_DNS_DIV_VAL2가 80으로 온다. 순위는
작은 쪽(80)이고 큰 쪽은 RK_CNT - 순위 + 1로 뒤집은 값이다. 큰 쪽을
순위로 읽으면 80등을 173등으로 본다.

**둘. 모집단이 축에 따라 바뀐다.**
시군구로 부르면 252곳, 시도로 부르면 17곳이다. "3위"만 떼어 말하면
17곳 중 3위인지 252곳 중 3위인지 알 수 없다.

**셋. 세부지표의 RNK는 지역 순위가 아니다.**
그 중분류 안에서 이 지역의 점수가 높은 순서다. 다른 지역과의 순위로
읽으면 "레포츠 SNS언급량 전국 1위"처럼 없는 사실을 만든다.

옛 지수(LN_09_*)를 여기서 다루지 않는 이유는 **2024년 5월에 멈췄기**
때문이다. 값 체계도 달라 섞을 수 없다.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import client  # noqa: E402
import codes  # noqa: E402

TREND_QID = "TA_01_01_001"
SUMMARY_QID = "TA_01_01_001_001"
RADAR_QID = "TA_01_03_001"
GROUP_QID = "TA_01_03_003"
DETAIL_QID = "TA_01_03_002"

# 화면 요약문(tour_activate.js)에서 옮긴 이름. 지어내지 않았다.
GROUPS = {
    "11": "관광서비스수요", "12": "문화자연자원 수요",
    "21": "관광체류강도", "22": "관광소비강도",
    "31": "관광객 다양성", "32": "관광소비 다양성", "33": "국제적 다양성",
    "41": "여행거리",
}


class ActivateError(Exception):
    """지표를 받았지만 쓸 수 있는 모양이 아니다."""


def _rank_ok(rank, inverted, total, value, top_value):
    """순위 컬럼이 우리가 아는 그 컬럼인지 값으로 확인한다.

    **이 검산은 두 컬럼이 통째로 맞바뀌는 경우를 잡지 못한다.**
    rank + inverted == total + 1 은 두 값의 교환에 대해 대칭이라
    (80, 173)이든 (173, 80)이든 통과한다. 그것을 알면서도 남겨 두는
    것은, 한쪽만 망가지는 흔한 손상은 이 식이 잡기 때문이다.

    비대칭 근거를 하나 더 붙였다 — **이 지역 값이 전국 최고값과
    같으면 순위는 1이어야 한다.** 전국 1위 지역에서는 스왑이 잡힌다
    (강남구가 실제로 그런 지역이다). 그 밖의 지역에서는 한 지역의
    응답만으로 스왑을 구분할 방법이 없다.
    """
    if rank is None or inverted is None or total is None:
        return False
    if abs(inverted - (total - rank + 1)) >= 0.5:
        return False
    # 전국 최고값을 가진 축이면 1위여야 한다. 소수점 반올림을 감안해
    # 아주 작은 차이는 같은 값으로 본다.
    if (value is not None and top_value is not None
            and abs(value - top_value) < 0.005 and rank != 1):
        return False
    return True


def _rows(qid, sgg_cd, ym1, ym2, cache_dir=None):
    return client.fetch(qid, {"SGG_CD": sgg_cd, "BASE_YM1": str(ym1),
                              "BASE_YM2": str(ym2)}, cache_dir=cache_dir)


def _num(row, key):
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summary(sgg_cd, ym1, ym2, *, cache_dir=None):
    """이 지역 지수와 같은 기간 전국 지수. 한 행만 온다."""
    rows = _rows(SUMMARY_QID, sgg_cd, ym1, ym2, cache_dir)
    if not rows:
        raise ActivateError("관광수요 지수 요약이 비어 있다")
    row = rows[0]
    here, national = _num(row, "CURR_INDX"), _num(row, "ALL_INDX")
    prev = _num(row, "PREV_INDX")
    return {
        "지역명": row.get("CURR_INDX_NM"),
        "이지역": here,
        "전국": national,
        "직전": prev,
        # 전국을 100으로 볼 때 이 지역이 몇인가. 지수 자체의 단위를
        # 모르므로, 비로 바꿔야 "전국의 95% 수준"이라 말할 수 있다.
        "전국대비": (here / national * 100) if here and national else None,
        "증감": (here - prev) if here is not None and prev is not None else None,
        "기간": f'{row.get("MIN_BASE_YM", "")}~{row.get("MAX_BASE_YM", "")}',
    }


def competitiveness(sgg_cd, ym1, ym2, *, cache_dir=None):
    """4대분류별 값·전국 순위·전국 평균. 이 모듈의 중심이다."""
    rows = _rows(RADAR_QID, sgg_cd, ym1, ym2, cache_dir)
    if not rows:
        raise ActivateError("관광수요 경쟁력이 비어 있다")

    axes = []
    for row in rows:
        rank, total = _num(row, "TURSM_DNS_DIV_VAL2"), _num(row, "RK_CNT")
        value, avg = _num(row, "DMAND_DTLS_IDCT_VAL_AVG"), _num(row, "AVG_ALL")
        inverted = _num(row, "TURSM_DNS_DIV_VAL")
        axes.append({
            "순번": row.get("SEQ"),
            "대분류": row.get("TURSM_DNS_DIV_NM"),
            "값": value,
            "전국평균": avg,
            "전국최고": _num(row, "MAX_AVG"),
            "순위": rank,
            "모집단": total,
            # 상위 몇 %인가. 순위만으로는 252곳 중 80위가 좋은지
            # 나쁜지 바로 오지 않는다.
            "상위백분율": (rank / total * 100) if rank and total else None,
            "전국평균대비": (value / avg * 100) if value and avg else None,
            "순위검산": _rank_ok(rank, inverted, total, value,
                              _num(row, "MAX_AVG")),
        })
    axes.sort(key=lambda a: a["순위"] if a["순위"] is not None else 1e9)
    return {
        "지역명": rows[0].get("SGG_NM"),
        "모집단": _num(rows[0], "RK_CNT"),
        "축": axes,
        "검산통과": all(a["순위검산"] for a in axes),
        "가장강한": axes[0]["대분류"] if axes else None,
        "가장약한": axes[-1]["대분류"] if axes else None,
    }


def groups(sgg_cd, ym1, ym2, *, cache_dir=None):
    """8중분류 점수. 순위는 여기 없다 — competitiveness에 있다."""
    rows = _rows(GROUP_QID, sgg_cd, ym1, ym2, cache_dir)
    if not rows:
        raise ActivateError("중분류 점수가 비어 있다")
    out = []
    for row in rows:
        code = str(row.get("IDCT_SCLS_CD", ""))
        out.append({
            "대분류": row.get("IDCT_MCLS_NM"),
            "중분류": row.get("IDCT_SCLS_NM") or GROUPS.get(code, code),
            "코드": code,
            "점수": _num(row, "AVG_DMAND_DTLS_IDCT"),
        })
    out.sort(key=lambda g: g["점수"] if g["점수"] is not None else -1,
             reverse=True)
    return {"중분류": out}


def details(sgg_cd, ym1, ym2, *, cache_dir=None, top=None):
    """세부지표별 점수. RNK는 지역 순위가 아니라 지역 안의 순번이다."""
    rows = _rows(DETAIL_QID, sgg_cd, ym1, ym2, cache_dir)
    if not rows:
        raise ActivateError("세부지표가 비어 있다")
    out = [{
        "대분류": r.get("IDCT_MCLS_NM"),
        "중분류": r.get("IDCT_SCLS_NM"),
        "세부지표": r.get("DTLS_IDCT_NM"),
        "점수": _num(r, "AVG_DMAND_DTLS_IDCT"),
        # 이름을 '순위'로 짓지 않는 것이 중요하다. 이 값은 다른
        # 지역과 견준 자리가 아니다.
        "지역내순번": _num(r, "RNK"),
    } for r in rows]
    out.sort(key=lambda d: d["점수"] if d["점수"] is not None else -1,
             reverse=True)
    result = {"전체수": len(out), "세부지표": out[:top] if top else out}
    if top:
        # top이 전체의 절반을 넘으면 같은 지표가 강점과 약점 양쪽에
        # 실린다. 겹치는 만큼 약한 쪽을 줄인다.
        room = max(0, len(out) - top)
        result["약한지표"] = out[-min(top, room):][::-1] if room else []
    return result


def _sorted_by_year(points):
    """연도 오름차순으로 세운다.

    데이터랩이 대체로 오름차순으로 주지만 그것은 관례일 뿐이다.
    순서가 바뀌면 '처음'과 '끝'이 뒤집혀 증감의 부호가 반대가 된다.
    """
    return sorted(points, key=lambda p: str(p.get("연도") or p.get("연월") or ""))


def trend(sgg_cd, ym1, ym2, *, cache_dir=None):
    """월별 지수 추이."""
    rows = _rows(TREND_QID, sgg_cd, ym1, ym2, cache_dir)
    if not rows:
        raise ActivateError("관광수요 지수 추이가 비어 있다")
    points = [{"연월": r.get("BASE_YM"), "지수": _num(r, "DMAND_AVG_IDCT_VAL")}
              for r in rows]
    values = [p["지수"] for p in points if p["지수"] is not None]
    return {
        "지역명": rows[0].get("SIDO_NM"),
        "값": points,
        "최대": max(values) if values else None,
        "최소": min(values) if values else None,
    }


def _main(argv=None):
    parser = argparse.ArgumentParser(
        description="관광수요 경쟁력 지수를 조회한다")
    parser.add_argument(
        "command",
        choices=["summary", "axes", "groups", "details", "trend"])
    parser.add_argument("sgg_cd",
                        help="시군구 5자리·시도 2자리·지역 이름(강릉시)")
    parser.add_argument("--from", dest="ym1", default="202401")
    parser.add_argument("--to", dest="ym2", default="202412")
    parser.add_argument("--top", type=int, default=None)
    args = parser.parse_args(argv)

    # 데이터랩은 없는 코드에 오류를 주지 않는다. 지역명이 null인 채로
    # 전국 값만 채워 돌려준다 — 그대로 두면 "이 지역 지수는 없지만
    # 전국은 73.3"이라는 문장이 나가고, null을 0으로 읽는 일도 생긴다.
    try:
        args.sgg_cd = codes.resolve_axis_code(args.sgg_cd)
    except codes.CodeError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "summary":
            out = summary(args.sgg_cd, args.ym1, args.ym2)
        elif args.command == "axes":
            out = competitiveness(args.sgg_cd, args.ym1, args.ym2)
        elif args.command == "groups":
            out = groups(args.sgg_cd, args.ym1, args.ym2)
        elif args.command == "details":
            out = details(args.sgg_cd, args.ym1, args.ym2, top=args.top)
        else:
            out = trend(args.sgg_cd, args.ym1, args.ym2)
    except ActivateError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except client.SessionExpired as exc:
        # FetchError의 하위가 아니라 형제다. 함께 잡지 않으면 세션
        # 만료가 이 자리를 뚫고 올라가 사용자에게 traceback이 간다.
        # 스스로 다시 로그인하지 않는다 — 안내만 하고 멈춘다.
        print(str(exc), file=sys.stderr)
        return 1
    except client.FetchError as exc:
        print(f"인출 실패: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
