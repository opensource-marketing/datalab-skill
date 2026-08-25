"""인구감소지역의 '체력'과 관광의 대체 효과를 사람이 읽는 모양으로 푼다.

다른 모듈이 "관광객이 얼마나 오는가"를 다룬다면 여기는 **그 지역이
버티고 있는가**를 다룬다. 인구·고령화·재정자립도 같은 지역 체력과,
주민이 빠져나간 자리를 관광이 얼마나 메우는지를 함께 본다.

이 화면들이 왜 따로 다뤄져야 하는가 — 함정이 셋이다.

**하나. 0이 값이 아니라 결측이다.**
재정자립도 2024는 정선·신안·의성 세 곳 모두 0.0으로 온다. 조출생률은
정선군 2023만 0.0이고 앞뒤 해는 2.6·2.5다. 그대로 그리면 그 해에
지자체 재정이 무너지고 아이가 한 명도 안 태어난 것처럼 보인다.
데이터랩은 "아직 발표되지 않았다"를 0으로 말한다.

**둘. 컬럼 이름이 방문자 수라고 말하지만 아니다.**
LN_06_01_002의 LODG_PSON_NUM은 42, THDY_PSON_NUM은 106이다(정선군
2024). 방문자 수가 아니라 **주민 1명이 빠져나갈 때 그 사람의 지역 내
소비를 메우려면 관광객이 몇 명 와야 하는지**다. 이 스킬의 척추가 되는
숫자이면서, 동시에 가장 오해하기 쉬운 숫자다.

**셋. 같은 이름의 컬럼이 지표마다 배율이 다르다.**
ONP_BY_REGN_IN_CNSM_AMT는 LN_06_01_003에서는 원 단위로 그대로 오는데
(정선군 2024: 8,848,682원) LN_06_01_002에서는 10,000배로 온다
(89,098,028,835). 사이트 화면은 후자를 나누지 않은 채 '천원'을 붙여
보여 준다 — 화면이 틀렸다.

배율 10,000은 짐작이 아니다. 다섯 지역에서 산술로 확인했다:

    (raw ÷ 10,000) ÷ 숙박여행_1회평균지출액 ≈ 대체필요_숙박관광객수
    정선 41.83→42 · 강원고성 19.20→19 · 경남고성 30.13→30
    신안 9.51→10 · 의성 14.69→15

그리고 LN_06_01_003이 같은 값을 나누지 않은 채로 준다(8,848,682원 대
8,909,803원, 0.7% 차이는 카드 재소급으로 보인다). 서로 다른 두 지표가
같은 결론을 가리킨다.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import client  # noqa: E402
import codes  # noqa: E402

SUMMARY_QID = "LN_06_01_002"
SUBSTITUTE_QID = "LN_06_01_003"
VISITOR_RATIO_QID = "LN_06_01_004"
AGE_QID = "LN_06_01_005"
TOUR_JOBS_QID = "PD_01_01_003"
ALL_JOBS_QID = "PD_01_01_007"

# 고용 지표는 다른 지표보다 늦게 나온다. 2020~2024로 부르면 오류가
# 아니라 빈 배열이라, 기간을 그대로 넘기면 "이 지역엔 관광 일자리가
# 없다"로 잘못 읽힌다.
JOBS_YEARS = ("2018", "2023")

# 전 산업 목록 안에서 관광산업만 이 코드를 쓴다(표준산업분류가 아니다).
# 데이터랩이 이 placeholder를 바꾸면 관광 행을 못 찾는데, 그때 값이
# 조용히 전부 None이 되므로 이름으로도 한 번 더 찾는다.
TOUR_INDUSTRY_CODE = "?"
TOUR_INDUSTRY_NAME = "관광산업"

# LN_06_01_002의 1인당 역내소비액이 부풀려 오는 배율. 위 docstring의
# 다섯 지역 검산이 근거다.
SUMMARY_AMT_SCALE = 10_000

# 연도별 한 줄짜리 지표들. COL1(과 있으면 COL2)만 값이다.
# 이름은 사이트 차트가 그 계열에 붙이는 문자열에서 옮겨 적었다.
# 0을결측으로: 그 지표에서 0이 관측된 적이 없고, 값으로서 0이
# 나올 수 없는 것만 True다. 일괄로 켜면 **값인 0을 지운다** —
# 청년 순 이동률은 전입과 전출이 같으면 실제로 0.0이다.
SERIES = {
    "고령화비율": {"qid": "LN_06_01_006", "col": "COL1", "unit": "%",
                "label": "고령화 비율", "좋은방향": "낮을수록",
                "0은결측": True},
    "유소년비율": {"qid": "LN_06_01_006", "col": "COL2", "unit": "%",
                "label": "유소년 비율", "좋은방향": "높을수록",
                "0은결측": True},
    # 두 단위는 사이트가 적지 않아 산술로 확인했다. 근거는 카탈로그
    # popl_qid_catalog.yaml 의 해당 항목 caution에 있다.
    # 인구감소지역만 2023이 0으로 온다(같은 해 강남구는 4.3). 출생아가
    # 없는 시군구는 없다.
    "조출생률": {"qid": "LN_06_01_007", "col": "COL1", "unit": "명/천명",
              "label": "조출생률", "좋은방향": "높을수록", "0은결측": True},
    "인구밀도": {"qid": "LN_06_01_009", "col": "COL1", "unit": "명/㎢",
              "label": "인구밀도", "좋은방향": None, "0은결측": True},
    # **0이 실제 값이다.** 전입과 전출이 같으면 0.0이 나온다.
    # 결측으로 지우면 그 해가 통째로 사라지고 변화의 기준점도 바뀐다.
    "청년순이동률": {"qid": "LN_06_01_010", "col": "COL1", "unit": "%",
                 "label": "청년 순 이동률", "좋은방향": "높을수록",
                 "0은결측": False},
    # 인구감소지역만 2024가 0으로 온다(같은 해 강남 56.1·춘천 18.9).
    "재정자립도": {"qid": "LN_06_01_011", "col": "COL1", "unit": "%",
                "label": "재정자립도", "좋은방향": "높을수록",
                "0은결측": True},
}

# 연령 여덟 칸. 차트가 붙이는 이름 그대로다.
AGE_BANDS = [("COL1", "10대 이하"), ("COL2", "10대"), ("COL3", "20대"),
             ("COL4", "30대"), ("COL5", "40대"), ("COL6", "50대"),
             ("COL7", "60대"), ("COL8", "70대 이상")]


class VitalityError(Exception):
    """지표를 받았지만 쓸 수 있는 모양이 아니다."""


def _rows(qid, sgg_cd, y1, y2, cache_dir=None, extra=None):
    params = {"SGG_CD": sgg_cd, "BASE_YM1": str(y1), "BASE_YM2": str(y2)}
    if extra:
        params.update(extra)
    return client.fetch(qid, params, cache_dir=cache_dir)


def _num(row, key):
    """숫자를 꺼낸다. 없거나 숫자가 아니면 None."""
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summary(sgg_cd, year, *, cache_dir=None):
    """관광 대체 효과 요약 — 이 스킬이 답하는 한 문장.

    기간을 넓게 줘도 한 해만 오므로 연도를 하나만 받는다. 넓은 기간을
    받아 마지막 해만 돌려주면 호출한 쪽이 추이를 얻었다고 착각한다.
    """
    rows = _rows(SUMMARY_QID, sgg_cd, year, year, cache_dir)
    if not rows:
        raise VitalityError(f"{year}년 요약이 비어 있다")
    row = rows[0]

    per_person_raw = _num(row, "ONP_BY_REGN_IN_CNSM_AMT")
    per_person = (per_person_raw / SUMMARY_AMT_SCALE
                  if per_person_raw is not None else None)

    result = {
        "기준연도": row.get("BASE_YEAR"),
        "시도명": row.get("SIDO_NM"),
        "시군구명": row.get("SGG_NM"),
        "인구감소지역": row.get("POPL_DCRS_REGN_YN") == "Y",
        "관심지역": row.get("POPL_DCRS_ITS_REGN_YN") == "Y",
        "주민등록인구": _num(row, "ADT_POPL_NUM"),
        "주민1인당_역내소비액": per_person,
        "숙박여행_1회지출": _num(row, "LODG_VISITR_CNSM_AMT"),
        "당일여행_1회지출": _num(row, "THDY_VISITR_CNSM_AMT"),
        "대체필요_숙박": _num(row, "LODG_PSON_NUM"),
        "대체필요_당일": _num(row, "THDY_PSON_NUM"),
        "대체필요_숙박_구성비반영": _num(row, "TURSM_RPM_SCLE_LODG_PSON_NUM"),
        "대체필요_당일_구성비반영": _num(row, "TURSM_RPM_SCLE_THDY_PSON_NUM"),
        "숙박구성비": _num(row, "LODG_TOUR_NUM_RAT"),
        "당일구성비": _num(row, "THDY_TOUR_NUM_RAT"),
        "역내소비비율": _num(row, "REGN_IN_CNSM_RAT"),
        "역외소비비율": _num(row, "REGN_EXCEP_CNSM_RAT"),
    }
    result["검산"] = _crosscheck(result)
    return result


def _crosscheck(summ):
    """÷10,000 보정이 이 지역에서도 맞는지 값으로 확인한다.

    카탈로그에 적어 둔 것으로 충분하지 않다. 데이터랩이 어느 날 배율을
    고치면 카탈로그는 그대로인데 값만 10,000배 틀리기 때문이다. 리포트가
    스스로 검산해서 어긋나면 말하게 한다.
    """
    per = summ["주민1인당_역내소비액"]
    checks = []
    for spend_key, need_key, name in (
            ("숙박여행_1회지출", "대체필요_숙박", "숙박"),
            ("당일여행_1회지출", "대체필요_당일", "당일")):
        spend, need = summ[spend_key], summ[need_key]
        if not per or not spend or need is None:
            continue
        checks.append({"구분": name, "계산값": per / spend, "사이트값": need})
    if not checks:
        return {"통과": None, "항목": []}
    # 사이트가 반올림한 정수를 주므로 1 이내면 같은 값으로 본다.
    ok = all(abs(c["계산값"] - c["사이트값"]) <= 1.0 for c in checks)
    return {"통과": ok, "항목": checks}


def series(name, sgg_cd, y1, y2, *, cache_dir=None):
    """연도별 한 줄 지표. 0은 결측으로 걸러 낸다.

    걸러 낸 해를 '빠진해'로 함께 돌려주는 것이 중요하다. 조용히 빼면
    리포트에 다섯 해를 물었는데 네 해만 그려지는 이유를 아무도 모른다.
    """
    if name not in SERIES:
        raise VitalityError(f"모르는 지표: {name}")
    spec = SERIES[name]
    rows = _rows(spec["qid"], sgg_cd, y1, y2, cache_dir)
    if not rows:
        raise VitalityError(f"{spec['label']}이(가) 비어 있다")

    zero_is_missing = spec["0은결측"]
    points, missing = [], []
    for row in rows:
        year = str(row.get("BASE_YEAR", ""))
        value = _num(row, spec["col"])
        # 데이터랩은 미발표를 0으로 말한다. 다만 지표마다 다르다 —
        # 0이 실제 값인 지표에서 지우면 그 해가 통째로 사라진다.
        if value is None or (zero_is_missing and value == 0):
            missing.append(year)
            continue
        points.append({"연도": year, "값": value})
    if not points:
        raise VitalityError(f"{spec['label']}: 모든 해가 결측(0)이다")

    # 데이터랩이 대체로 연도 오름차순으로 주지만 그것은 관례일 뿐이다.
    # 순서가 바뀌면 '처음'과 '끝'이 뒤집혀 증감의 부호가 반대가 된다.
    points.sort(key=lambda p: p["연도"])
    first, last = points[0]["값"], points[-1]["값"]
    return {
        "이름": name, "라벨": spec["label"], "단위": spec["unit"],
        "좋은방향": spec["좋은방향"], "값": points, "빠진해": missing,
        # 어느 두 해 사이의 변화인지 함께 준다. 0을 걸러 낸 뒤라
        # 물어본 기간의 양 끝이 아닐 수 있는데, 그것을 모르면
        # "5년간 -9.2%p"라고 쓰게 된다.
        "시작연도": points[0]["연도"], "끝연도": points[-1]["연도"],
        "변화": last - first,
        "변화율": (last - first) / first * 100 if first else None,
    }


def substitution_trend(sgg_cd, y1, y2, *, cache_dir=None):
    """대체 필요 관광객 수의 연도별 추이.

    요약(LN_06_01_002)이 한 해만 주기 때문에 추이는 여기서 얻는다.
    두 지표의 값은 구성비를 반영한 쪽끼리 일치한다.
    """
    rows = _rows(SUBSTITUTE_QID, sgg_cd, y1, y2, cache_dir,
                 extra={"SIDO_CD": str(sgg_cd)[:2]})
    if not rows:
        raise VitalityError("대체 필요 관광객 추이가 비어 있다")
    points = []
    for row in rows:
        points.append({
            "연도": str(row.get("BASE_YEAR", "")),
            "주민1인당_역내소비액": _num(row, "ONP_BY_REGN_IN_CNSM_AMT"),
            "숙박": _num(row, "COL1"),
            "당일": _num(row, "COL2"),
        })
    return {"값": points}


def visitor_ratio(sgg_cd, y1, y2, *, cache_dir=None):
    """주민등록 인구 대비 방문자. 단위를 사이트가 밝히지 않는다.

    절대 인원으로 읽으면 안 되므로 값과 함께 그 사실을 늘 들고 다닌다.
    """
    rows = _rows(VISITOR_RATIO_QID, sgg_cd, y1, y2, cache_dir,
                 extra={"SIDO_CD": str(sgg_cd)[:2]})
    if not rows:
        raise VitalityError("인구 대비 방문자가 비어 있다")
    points = [{"연도": str(r.get("BASE_YEAR", "")),
               "외지인": _num(r, "COL1"), "현지인": _num(r, "COL2")}
              for r in rows]
    return {"값": points,
            "주의": "사이트가 단위를 밝히지 않는다. 절대 인원이 아니라 "
                  "주민등록 인구를 1로 볼 때의 배수다."}


def age_profile(sgg_cd, year, *, cache_dir=None):
    """연령별 인구 분포. 여덟 칸의 합은 PO와 맞는 것을 확인했다."""
    rows = _rows(AGE_QID, sgg_cd, year, year, cache_dir)
    if not rows:
        raise VitalityError(f"{year}년 연령 분포가 비어 있다")
    row = rows[0]
    total = _num(row, "PO")
    bands = []
    for col, label in AGE_BANDS:
        value = _num(row, col)
        bands.append({"구간": label, "인구": value,
                      "비중": (value / total * 100)
                              if value is not None and total else None})
    band_sum = sum(b["인구"] for b in bands if b["인구"] is not None)
    return {
        "기준연도": row.get("BASE_YEAR"), "총인구": total, "구간": bands,
        # 합이 어긋나면 어느 칸이 결측으로 0이 된 것이다. 조용히 넘기면
        # 비중이 전부 조금씩 틀린다.
        "합계일치": total is not None and abs(band_sum - total) < 1,
    }


def tourism_jobs(sgg_cd, *, cache_dir=None):
    """이 지역 일자리 가운데 관광이 차지하는 몫과 그 안의 업종 구성.

    연도를 받지 않는다. 무엇을 넣든 데이터랩이 마지막 해 한 번만 주기
    때문이다 — 인자를 받아 두면 호출한 쪽이 연도를 고를 수 있다고
    착각한다. 실제 기준연도는 결과의 '기준연도'에 담아 돌려준다.
    """
    y1, y2 = JOBS_YEARS
    params = {"SIDO_CD": str(sgg_cd)[:2]}
    all_rows = _rows(ALL_JOBS_QID, sgg_cd, y1, y2, cache_dir, extra=params)
    if not all_rows:
        raise VitalityError("산업별 고용이 비어 있다")

    tour = next((r for r in all_rows
                 if r.get("GRP_CD") == TOUR_INDUSTRY_CODE), None)
    if tour is None:
        # 이름은 정확히 일치할 때만 쓴다 — '관광 숙박업' 같은 업종이
        # 이 목록에는 없지만, 부분 일치를 허용하면 언젠가 걸린다.
        tour = next((r for r in all_rows
                     if r.get("GRP_NM") == TOUR_INDUSTRY_NAME), None)
    total = _num(all_rows[0], "TOT_TOU_NUM")

    industries = sorted(
        ({"산업": r.get("GRP_NM"), "종사자": _num(r, "EMPLY_NUM"),
          "사업체": _num(r, "BZPLC_NUM"), "비중": _num(r, "RATE_VAL"),
          "관광": r is tour}
         for r in all_rows),
        key=lambda x: x["종사자"] or 0, reverse=True)

    sectors = []
    tour_rows = _rows(TOUR_JOBS_QID, sgg_cd, y1, y2, cache_dir, extra=params)
    for row in tour_rows:
        sectors.append({"업종": row.get("GRP_NM"),
                        "종사자": _num(row, "TOT_TOU_NUM"),
                        "비중": _num(row, "RATE_VAL")})
    sectors.sort(key=lambda x: x["종사자"] or 0, reverse=True)

    # 합이 어긋나면 데이터랩이 분류를 바꾼 것이다. 조용히 넘기면 비중이
    # 전부 조금씩 틀린 채로 리포트에 실린다.
    row_sum = sum(i["종사자"] for i in industries if i["종사자"] is not None)
    return {
        "기준연도": all_rows[0].get("BASE_YEAR"),
        "전체종사자": total,
        "관광종사자": _num(tour, "EMPLY_NUM") if tour else None,
        "관광사업체": _num(tour, "BZPLC_NUM") if tour else None,
        "관광비중": _num(tour, "RATE_VAL") if tour else None,
        "산업": industries,
        "관광업종": sectors,
        "합계일치": total is not None and abs(row_sum - total) < 1,
        # 관광 행을 못 찾으면 관광 관련 값이 전부 None이 되는데
        # 합계일치는 그대로 True다. 아무도 못 알아채므로 따로 말한다.
        "관광행찾음": tour is not None,
    }


def _main(argv=None):
    parser = argparse.ArgumentParser(
        description="인구감소지역 체력·관광 대체 효과를 조회한다")
    parser.add_argument("command",
                        choices=["summary", "series", "trend", "age",
                                 "jobs"])
    parser.add_argument("sgg_cd",
                        help="시군구 5자리 또는 시군구 이름(정선군)")
    parser.add_argument("--year", default="2024")
    parser.add_argument("--from", dest="y1", default="2020")
    parser.add_argument("--to", dest="y2", default="2024")
    parser.add_argument("--name", default="재정자립도",
                        help=f"series가 볼 지표: {', '.join(SERIES)}")
    args = parser.parse_args(argv)

    # 데이터랩은 유효하지 않은 SGG_CD를 오류로 알리지 않는다. 조용히
    # 첫 시군구(서울 종로구)로 대체해 값을 준다 — "정선군"이라고 적어
    # 보내면 종로구 숫자가 돌아온다. 빈 표보다 나쁜 실패다.
    try:
        # 이 지표군은 시군구 축이다. 시도를 넣으면 데이터랩이 그 시도의
        # 첫 시군구로 대체한다 — "강원"이 춘천시가 됐다.
        args.sgg_cd = codes.resolve_axis_code(args.sgg_cd, allow_sido=False)
    except codes.CodeError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "summary":
            out = summary(args.sgg_cd, args.year)
        elif args.command == "series":
            out = series(args.name, args.sgg_cd, args.y1, args.y2)
        elif args.command == "trend":
            out = substitution_trend(args.sgg_cd, args.y1, args.y2)
        elif args.command == "jobs":
            out = tourism_jobs(args.sgg_cd)
        else:
            out = age_profile(args.sgg_cd, args.year)
    except VitalityError as exc:
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
