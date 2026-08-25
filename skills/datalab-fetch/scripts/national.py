"""전국 요약 지표(메인 화면)를 사람이 읽는 모양으로 푼다.

데이터랩 첫 화면은 전국 상황을 스무 남짓 되는 숫자로 요약한다. 그런데
응답에는 **이름이 없다.** DIV_NM이라는 코드만 오고, 무엇이 무엇인지는
화면이 그 코드로 어느 칸을 채우는지에만 적혀 있다.

그래서 CARDS는 추측이 아니라 옮겨 적은 것이다. 근거는 두 곳이다:

  이름  main.html 의 `statusItemVal<코드>` 바로 앞 라벨
  단위  main_*.js 가 그 코드의 값을 그릴 때 붙이는 문자열
        (예: 12번은 `item.VALUE.toLocaleString()+'명'`)

값(VALUE)의 단위와 증감(RATE)의 단위가 다른 카드가 있다. 관심도·긍정반응은
값이 %이고 증감이 %p다. 이것도 사이트 코드에서 확인한 것이다 — 둘을
섞으면 "관심도가 59% 늘었다"처럼 틀린 문장이 나온다.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import client  # noqa: E402
import period  # noqa: E402

SUMMARY_QID = "MN_01_01_026"
ROLLUP_QID = "MN_01_01_023"
TOP_COUNTRY_QID = "MN_01_01_020"
HOT_DOMESTIC_QID = "MM_HO_HOT_001_001"
HOT_FOREIGN_QID = "MM_HO_HOT_001_002"
HOT_SEARCH_QID = "MM_HO_HOT_001_004"
AGE_POPULAR_QID = "MM_HO_HOT_001_003"
SIDO_STAY_QID = "TSA_03_01_0012"
CONTINENT_QID = "NAT_08_01_011"
BALANCE_QID = "TS_01_03_004"
DOM_SURVEY_QIDS = (("TS_03_01_003", "국내여행 경험률", "%"),
                   ("TS_03_01_010", "1인 평균 여행 횟수", "회"),
                   ("TS_03_01_011", "1인 평균 여행 일수", "일"),
                   ("TS_03_01_012", "1인 평균 지출액", "천원"))
COMPLAINT_QID = "TS_01_12_006"
GATEWAY_QID = "NAT_07_01_006"

# 월별 추이. 값 이름이 전부 TOU_NUM이지만 뜻이 다르다 — 의료·한류는
# 인원이 아니라 소비액이다. 컬럼 이름을 믿으면 안 되는 자리다.
TRENDS = {
    "방한외래객": {"qid": "MN_01_01_027", "label": "방한 외래객수", "unit": "명"},
    "국내방문객": {"qid": "MN_01_01_031", "label": "국내 방문객수", "unit": "명"},
    "의료관광소비": {"qid": "MN_01_01_028", "label": "의료관광 소비액", "unit": "원"},
    "한류관광소비": {"qid": "MN_01_01_030", "label": "한류관광 소비액", "unit": "원"},
    "크루즈입국자": {"qid": "MN_01_01_029", "label": "크루즈 입국자수", "unit": "명"},
}

# DIV_NM → 무엇인가. value_unit은 VALUE의 단위, rate_unit은 RATE의 단위다.
# kind가 "목록"이면 VALUE는 늘 0이고 ARR_VAL에 상위 항목이 들어 있다.
CARDS = {
    "11": {"group": "방한여행", "label": "방한여행 전 관심도",
           "value_unit": "%", "rate_unit": "%p", "kind": "값", "basis": "전월 대비"},
    "12": {"group": "방한여행", "label": "방한 외래객수",
           "value_unit": "명", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "13": {"group": "방한여행", "label": "외국인 관광소비",
           "value_unit": "원", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "14": {"group": "방한여행", "label": "방한여행 후 긍정반응",
           "value_unit": "%", "rate_unit": "%p", "kind": "값", "basis": "전월 대비"},
    "21": {"group": "의료관광", "label": "의료관광 관심도",
           "value_unit": "%", "rate_unit": "%p", "kind": "값", "basis": "전월 대비"},
    "22": {"group": "의료관광", "label": "의료관광 소비",
           "value_unit": "원", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "23": {"group": "의료관광", "label": "의료관광 국가별 소비 상위",
           "value_unit": "원", "rate_unit": "%", "kind": "목록", "basis": "연간 누적"},
    "24": {"group": "의료관광", "label": "의료관광 진료과목별 소비 상위",
           "value_unit": "원", "rate_unit": "%", "kind": "목록", "basis": "연간 누적"},
    "31": {"group": "한류관광", "label": "한류관광 관심도",
           "value_unit": "%", "rate_unit": "%p", "kind": "값", "basis": "전월 대비"},
    "32": {"group": "한류관광", "label": "한류관광 소비",
           "value_unit": "원", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "33": {"group": "한류관광", "label": "한류관광 분야별 소비 상위",
           "value_unit": "원", "rate_unit": "%", "kind": "목록", "basis": "연간 누적"},
    "34": {"group": "한류관광", "label": "한류관광 언급량",
           "value_unit": "건", "rate_unit": "%", "kind": "값", "basis": "전년 동기 대비"},
    "41": {"group": "크루즈", "label": "크루즈 입항계획",
           "value_unit": "명", "rate_unit": "%", "kind": "값",
           "basis": "전년 동기 입항실적 대비"},
    "42": {"group": "크루즈", "label": "크루즈 입국자수",
           "value_unit": "명", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "43": {"group": "크루즈", "label": "크루즈 국적별 입국자수 상위",
           "value_unit": "명", "rate_unit": "%", "kind": "목록", "basis": "연간 누적"},
    "44": {"group": "크루즈", "label": "크루즈 항구별 입국자수 상위",
           "value_unit": "명", "rate_unit": "%", "kind": "목록", "basis": "연간 누적"},
    "51": {"group": "국내여행", "label": "국내여행 전 관심도",
           "value_unit": "%", "rate_unit": "%p", "kind": "값", "basis": "전월 대비"},
    "52": {"group": "국내여행", "label": "내국인 여행객수",
           "value_unit": "명", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "53": {"group": "국내여행", "label": "내국인 관광소비",
           "value_unit": "원", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "54": {"group": "국내여행", "label": "숙박 여행객수",
           "value_unit": "명", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "61": {"group": "지역", "label": "지역 공항·항만 입국자수",
           "value_unit": "명", "rate_unit": "%", "kind": "목록", "basis": "연간 누적"},
    "62": {"group": "지역", "label": "외국인 지역방문",
           "value_unit": "명", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "63": {"group": "지역", "label": "외국인 지역소비",
           "value_unit": "원", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "64": {"group": "지역", "label": "내국인 지역방문",
           "value_unit": "명", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
    "65": {"group": "지역", "label": "내국인 지역소비",
           "value_unit": "원", "rate_unit": "%", "kind": "값", "basis": "연간 누적"},
}

GROUP_ORDER = ["방한여행", "의료관광", "한류관광", "크루즈", "국내여행", "지역"]

# MN_01_01_023의 DIV_NM. 사이트가 카드 밑에 적어 두는 출처 문구까지
# 옮겼다 — 다섯 숫자가 서로 다른 출처에서 오기 때문이다. 출처를 빼고
# 나란히 놓으면 같은 잣대로 잰 것처럼 보인다.
ROLLUP = {
    "1": {"label": "외지인 방문자수", "unit": "명", "source": "통신 빅데이터"},
    "2": {"label": "내국인 관광소비", "unit": "원", "source": "신용카드 빅데이터"},
    "3": {"label": "방한 외래객수", "unit": "명", "source": "한국관광통계"},
    "4": {"label": "외국인 관광소비", "unit": "원", "source": "신용카드 빅데이터"},
    "5": {"label": "관광사업체 수", "unit": "개", "source": "지역행정 인허가 정보"},
}


class NationalError(RuntimeError):
    """전국 요약을 만들 수 없을 때."""


def _num(value):
    """숫자로 바꾼다. 못 바꾸면 None — 0으로 떨어뜨리지 않는다."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch(qid, params, cache_dir=None):
    return client.fetch(qid, params, cache_dir=cache_dir)


def summary(cache_dir=None):
    """전국 요약 카드를 코드가 아니라 이름으로 돌려준다.

    카드마다 기준 시점(MAX_BASE_YM)이 다르다. 하나로 뭉뚱그리지 않고
    카드마다 그대로 실어 보낸다 — 방한 외래객은 6월까지인데 국내
    여행객은 7월까지인 식이라, 한 시점으로 적으면 거짓이 된다.
    """
    rows = _fetch(SUMMARY_QID, {}, cache_dir)
    if not rows:
        raise NationalError(
            "전국 요약이 비어 있습니다. 데이터랩 첫 화면이 개편됐을 수 있습니다.")

    cards, unknown = [], []
    for row in rows:
        code = str(row.get("DIV_NM", ""))
        meta = CARDS.get(code)
        if meta is None:
            # 사이트가 카드를 늘리면 여기로 온다. 조용히 버리면 새로
            # 생긴 지표를 영영 모른다.
            unknown.append(code)
            continue
        card = {"코드": code, "구분": meta["group"], "이름": meta["label"],
                "기준": row.get("MAX_BASE_YM") or "", "기준설명": meta["basis"],
                "값단위": meta["value_unit"], "증감단위": meta["rate_unit"],
                "종류": meta["kind"],
                "값": _num(row.get("VALUE")), "증감": _num(row.get("RATE"))}
        if meta["kind"] == "목록":
            card["값"] = None
            card["항목"] = _parse_items(row.get("ARR_VAL"), meta["value_unit"])
        cards.append(card)

    cards.sort(key=lambda c: (GROUP_ORDER.index(c["구분"]), c["코드"]))
    return {"카드": cards, "모르는코드": unknown}


def _parse_items(raw, unit):
    """ARR_VAL의 JSON 문자열을 항목 목록으로 푼다.

    사이트가 문자열 안에 JSON을 넣어 보낸다. 형식이 깨져 있으면 빈
    목록을 돌려주되, 깨졌다는 사실을 감추지 않도록 예외는 이름으로
    잡는다.
    """
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    out = []
    for item in items:
        out.append({"이름": item.get("sclsNm", ""),
                    "값": _num(item.get("irdsN2Rat")),
                    "증감": _num(item.get("irdsN1Rat")),
                    "단위": unit})
    return out


def rollup(cache_dir=None):
    """전국 5대 지표(연간 누적)를 출처와 함께 돌려준다."""
    rows = _fetch(ROLLUP_QID, {}, cache_dir)
    out = []
    for row in rows:
        meta = ROLLUP.get(str(row.get("DIV_NM", "")))
        if meta is None:
            continue
        out.append({"이름": meta["label"], "단위": meta["unit"],
                    "출처": meta["source"], "기준": row.get("MAX_BASE_YM") or "",
                    "값": _num(row.get("VALUE")),
                    "전년": _num(row.get("PRE_VALUE")),
                    "증감률": _num(row.get("RATE"))})
    return out


def trend(metric, ym1, ym2, cache_dir=None):
    """월별 추이 하나를 돌려준다.

    기간을 bgngYm·endYm으로 보낸다. 다른 카탈로그의 습관대로
    BASE_YM1을 보내면 오류가 아니라 빈 배열이 온다 — 그러면 "값이
    없다"로 잘못 읽히므로, 그 이름을 이 함수 안에 가둬 둔다.
    """
    if metric not in TRENDS:
        raise NationalError(
            f"모르는 지표입니다: {metric}. 쓸 수 있는 것: {', '.join(TRENDS)}")
    spec = TRENDS[metric]
    rows = _fetch(spec["qid"], {"bgngYm": ym1, "endYm": ym2}, cache_dir)
    out = []
    for row in rows:
        out.append({"기준월": row.get("BASE_YM") or "",
                    "값": _num(row.get("TOU_NUM")),
                    "전년동월": _num(row.get("PREV_TOU_NUM")),
                    "증감률": _num(row.get("TOU_NUM_PER"))})
    out.sort(key=lambda r: r["기준월"])
    return {"이름": spec["label"], "단위": spec["unit"], "행": out,
            "요청": {"시작": ym1, "종료": ym2},
            "빠진달": _missing_months(ym1, ym2, [r["기준월"] for r in out])}


def _missing_months(ym1, ym2, got):
    """요청한 창에서 오지 않은 달. 아직 발표되지 않은 달을 드러낸다."""
    want, cur = [], ym1
    for _ in range(period.span(ym1, ym2)):
        want.append(cur)
        cur = period.shift(cur, 1)
    return [m for m in want if m not in set(got)]


def top_countries(cache_dir=None):
    """방한객 상위 10개국. 합계는 전체 방한객수가 아니다."""
    rows = _fetch(TOP_COUNTRY_QID, {}, cache_dir)
    return [{"국가": r.get("NAT_NM") or "", "코드": r.get("PTL_NAT_CD") or "",
             "방한객수": _num(r.get("TOU_NUM"))} for r in rows]


def hotspots(cache_dir=None):
    """방문자가 급등한 행정동(내국인·외국인)."""
    out = {}
    for key, qid in (("내국인", HOT_DOMESTIC_QID), ("외국인", HOT_FOREIGN_QID)):
        rows = _fetch(qid, {}, cache_dir)
        out[key] = [{"순위": r.get("RNK"), "시도": r.get("SIDO_NM") or "",
                     "시군구": r.get("SGG_NM") or "", "행정동": r.get("ADONG_NM") or "",
                     "구간": r.get("BASE_YM_STR") or "",
                     "방문자수": _num(r.get("TOU_NUM")),
                     "전년동기": _num(r.get("SPPY_TOU_NUM")),
                     "증가율": _num(r.get("RAT"))} for r in rows]
    return out


def rising_places(cache_dir=None):
    """검색이 급등한 관광지. 검색은 방문이 아니다."""
    rows = _fetch(HOT_SEARCH_QID, {}, cache_dir)
    return [{"순위": r.get("RNK"), "기준월": r.get("BASE_YM") or "",
             "시도": r.get("SIDO_NM") or "", "시군구": r.get("SGG_NM") or "",
             "관광지": r.get("ITS_BRO_NM") or "",
             "분류": r.get("TMAP_CATE_MCLS_NM") or "",
             "검색건수": _num(r.get("SRCH_CNT")),
             "전년동월": _num(r.get("PREYR_SRCH_CNT")),
             "증가율": _num(r.get("GROW_RATE"))} for r in rows]


def popular_by_age(ym_from, ym_to, age=None, cache_dir=None):
    """연령대별 인기 관광지. age를 비우면 전 연령이 섞인다."""
    params = {"BASE_YM_TMAP_FR": ym_from, "BASE_YM_TMAP_TO": ym_to}
    if age:
        params["AGEG_DIV_CD"] = str(age)
    rows = _fetch(AGE_POPULAR_QID, params, cache_dir)
    return [{"순위": r.get("RNK"), "시도": r.get("SIDO_NM") or "",
             "시군구": r.get("SGG_NM") or "", "관광지": r.get("ITS_BRO_NM") or "",
             "분류": r.get("TMAP_CATE_MCLS_NM") or "",
             "연령대": r.get("AGEG_DIV_CD") or "",
             "검색건수": _num(r.get("SRCH_CNT_SUM")),
             "상위5내_비중": _num(r.get("SRCH_CNT_RATE"))} for r in rows]


def tourism_balance(ym1, ym2, cache_dir=None):
    """관광수지·수입·지출. 항목 이름에 단위가 적혀 있다.

    `BASE_DATE` 에 '총계' 행이 섞여 있어 그냥 쓰면 달 하나가 더
    보인다 — 여기서 걸러 낸다.
    """
    rows = _fetch(BALANCE_QID, {"BASE_YM1": ym1, "BASE_YM2": ym2,
                                "ALL_YN": "Y", "srchAreaDate": "1",
                                "tabDiv": "1"}, cache_dir)
    return [{"기준월": r.get("BASE_DATE") or "",
             "항목": r.get("ITEM_DIV_NM") or "",
             "값": _num(r.get("INTL_BALC_AMT")),
             "전년동월": _num(r.get("PREYR_GTOT"))}
            for r in rows if (r.get("BASE_DATE") or "") != "총계"]


def domestic_survey(cache_dir=None):
    """국민여행조사 네 갈래. 연 단위 설문이다.

    **기간을 네 자리 연도로 준다.** 연월 여섯 자리를 넣으면 시작
    연도가 빠지고 한 해만 물으면 빈 배열이 온다.
    `BAGE` 가 '전체'인 행만 쓴다 — 나머지는 연령대별이다.
    """
    out = []
    for qid, label, unit in DOM_SURVEY_QIDS:
        rows = _fetch(qid, {"BASE_YM1": "2018", "BASE_YM2": "2026"},
                      cache_dir)
        연도별 = [{"연도": r.get("BASE_YEAR") or "", "값": _num(r.get("T_VALUE"))}
                 for r in rows if (r.get("BAGE") or "") == "전체"]
        연도별.sort(key=lambda r: r["연도"])
        if 연도별:
            out.append({"이름": label, "단위": unit, "연도별": 연도별})
    return out


def complaints(ym1, ym2, cache_dir=None):
    """관광불편신고 시도 순위. 건수와 비중이 함께 온다."""
    rows = _fetch(COMPLAINT_QID, {"BASE_YM1": ym1, "BASE_YM2": ym2,
                                  "ALL_YN": "Y", "srchAreaDate": "1",
                                  "selectDiv": "1", "cplnDiv": ""}, cache_dir)
    return [{"순위": r.get("RK"), "시도": r.get("OCRN_SIDO_NM") or "",
             "건수": _num(r.get("DCLR_CNT")), "비중": _num(r.get("RATE"))}
            for r in rows]


def inbound_mix(ym1, ym2, cache_dir=None):
    """방한객이 어느 대륙에서 어느 관문으로 들어왔는가.

    두 표의 합이 같다는 것을 산술로 확인했다(2024년 16,369,629명).
    그래서 한 절에 나란히 놓아도 모집단이 어긋나지 않는다.

    **관문 표의 DIV_ORD 는 크기 순서가 아니다.** 1번이 기타항구,
    9번이 인천공항이다. 그대로 그리면 인천공항이 맨 아래로 간다.
    """
    params = {"BASE_YM1": ym1, "BASE_YM2": ym2, "ALL_YN": "Y",
              "NAT_CD": "000"}
    대륙 = [{"이름": r.get("CTNN_NM") or "",
            "방한객수": _num(r.get("TOU_NUM")),
            "비중": _num(r.get("TOU_NUM_RATE"))}
           for r in _fetch(CONTINENT_QID, params, cache_dir)]
    관문 = [{"이름": r.get("AIRPT_POT_NM") or "",
            "방한객수": _num(r.get("TOU_NUM")),
            "비중": _num(r.get("TOU_NUM_RATE"))}
           for r in _fetch(GATEWAY_QID, params, cache_dir)]
    for 표 in (대륙, 관문):
        표.sort(key=lambda r: (r["방한객수"] is None, -(r["방한객수"] or 0)))
    return {"대륙": 대륙, "관문": 관문}


def sido_stay(ym1, ym2, cache_dir=None):
    """시도별 체류시간·숙박일. 단위를 사이트가 표기하지 않는다."""
    rows = _fetch(SIDO_STAY_QID, {"BASE_YM1": ym1, "BASE_YM2": ym2}, cache_dir)
    out = [{"시도": r.get("SIDO_NM") or "", "코드": r.get("SIDO_CD") or "",
            "체류시간": _num(r.get("STAY_TM")),
            "평균숙박일": _num(r.get("LODG_DAYS"))} for r in rows]
    out.sort(key=lambda r: (r["평균숙박일"] is None, -(r["평균숙박일"] or 0)))
    return out


def _render_summary(data):
    for code in data["모르는코드"]:
        print(f"[알림] 카탈로그에 없는 카드 코드 {code}. "
              f"사이트가 지표를 늘렸을 수 있습니다.", file=sys.stderr)
    group = None
    for card in data["카드"]:
        if card["구분"] != group:
            group = card["구분"]
            print(f"\n## {group}")
        if card["종류"] == "목록":
            print(f"  {card['이름']} ({card['기준']}, {card['기준설명']})")
            for item in card["항목"]:
                print(f"    - {item['이름']}: "
                      f"{_fmt(item['값'])}{item['단위']} ({_sign(item['증감'])}%)")
            continue
        print(f"  {card['이름']}: {_fmt(card['값'])}{card['값단위']}"
              f"  {_sign(card['증감'])}{card['증감단위']}"
              f"  [{card['기준']} · {card['기준설명']}]")


def _fmt(value):
    if value is None:
        return "-"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.4g}"


def _sign(value):
    if value is None:
        return "-"
    return f"{value:+.1f}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="전국 관광 요약 지표")
    sub = parser.add_subparsers(dest="mode", required=True)

    for name, help_text in [("summary", "전국 요약 카드 전부"),
                            ("rollup", "전국 5대 지표(연간 누적)"),
                            ("countries", "방한객 상위 10개국"),
                            ("hot", "방문자 급등 행정동"),
                            ("rising", "검색 급등 관광지")]:
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--json", action="store_true")
        cmd.add_argument("--cache-dir", default=None)

    trend_cmd = sub.add_parser("trend", help="월별 추이")
    trend_cmd.add_argument("metric", choices=sorted(TRENDS))
    trend_cmd.add_argument("--from", dest="ym1", required=True, metavar="YYYYMM")
    trend_cmd.add_argument("--to", dest="ym2", required=True, metavar="YYYYMM")
    trend_cmd.add_argument("--json", action="store_true")
    trend_cmd.add_argument("--cache-dir", default=None)

    stay_cmd = sub.add_parser("stay", help="시도별 체류시간·숙박일")
    stay_cmd.add_argument("--from", dest="ym1", required=True, metavar="YYYYMM")
    stay_cmd.add_argument("--to", dest="ym2", required=True, metavar="YYYYMM")
    stay_cmd.add_argument("--json", action="store_true")
    stay_cmd.add_argument("--cache-dir", default=None)

    args = parser.parse_args(argv)
    try:
        if args.mode == "summary":
            data = summary(args.cache_dir)
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                _render_summary(data)
            return 0
        if args.mode == "trend":
            data = trend(args.metric, args.ym1, args.ym2, args.cache_dir)
        elif args.mode == "rollup":
            data = rollup(args.cache_dir)
        elif args.mode == "countries":
            data = top_countries(args.cache_dir)
        elif args.mode == "hot":
            data = hotspots(args.cache_dir)
        elif args.mode == "rising":
            data = rising_places(args.cache_dir)
        else:
            data = sido_stay(args.ym1, args.ym2, args.cache_dir)
    except NationalError as exc:
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
        return 2
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
