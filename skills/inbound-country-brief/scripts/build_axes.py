"""qid 인출 결과를 5축 원시값으로 조립한다."""
import pathlib

import yaml

import client
from normalize import fetch_qid
from score import winsorized_minmax

PROFILES_PATH = pathlib.Path(__file__).resolve().parents[1] / "profiles.yaml"

QID_VOLUME_MOMENTUM = "NAT_08_01_021"
QID_ACCESS = "NAT_10_01_001"
QID_VALUE_HEADROOM = "NAT_07_01_018"

NON_COUNTRY_ROWS = {"총계", "전체", "합계"}


def load_profile(name, path=None):
    """업종 프로필 이름으로 축 가중치를 반환한다."""
    data = yaml.safe_load(pathlib.Path(path or PROFILES_PATH).read_text())
    if name not in data:
        raise KeyError(f"알 수 없는 프로필: {name}. 사용 가능: {sorted(data)}")
    return dict(data[name]["weights"])


def build_axis_values(ym1, ym2, *, countries=None, cache_dir=None,
                      session_file=None):
    """기준 기간의 5축 원시값과 메타데이터를 조립한다."""
    kw = {"cache_dir": cache_dir, "session_file": session_file}
    meta = {"기준기간": f"{ym1}~{ym2}", "사용_qid": [],
            "세션필요_실패": False, "결측국가": [], "항공_미매칭": []}
    survey_years = set()  # 실제로 사용된 외래관광객조사 기준연도 모음
    axis_values = {a: {} for a in
                   ["volume", "momentum", "value", "access", "headroom"]}
    # 지출력 축은 1인 평균지출(총액, 체류일 긴 시장에 유리)과 1일 평균지출
    # (지출 강도, 단기·고밀도 소비 시장에 유리) 두 지표의 합성이다. 두
    # 지표는 단위(1회 총액 vs 1일 단가)와 스케일이 달라 원값을 그대로
    # 평균하면 절대 크기가 큰 1인 지출이 항상 지배한다. 그래서 국가별로
    # winsorized_minmax(0~100 스케일)로 각각 변환한 뒤 그 값끼리 평균한다.
    # rank_percentile을 쓰지 않는 이유: 순위 기반 백분위는 이미 "몇 등인가"만
    # 남기고 원값의 크기 차이를 지운다. 지출력 축은 총점_값기반(순위가
    # 아니라 크기 격차를 보여주는 값 기반 점수) 계산의 입력이 되므로,
    # 여기서 순위로 미리 뭉개버리면 값 기반 점수도 결국 순위를 재현할
    # 뿐이다. winsorized_minmax는 단위·스케일 문제는 그대로 해결하면서
    # (두 지표 모두 0~100으로 스케일되므로) 국가 간 크기 격차는 보존한다.
    person_expenses = {}
    day_expenses = {}

    # 규모·성장 — 국가별 방한객수와 전년 대비 증감률을 한 번에 얻는다
    rows = fetch_qid(QID_VOLUME_MOMENTUM,
                     {"natCd": "999", "BASE_YM1": ym1, "BASE_YM2": ym2}, **kw)
    meta["사용_qid"].append(QID_VOLUME_MOMENTUM)
    code_by_name = {}
    for r in rows:
        name = r.get("NAT_NM")
        if not name or name in NON_COUNTRY_ROWS:
            continue
        if countries and name not in countries:
            continue
        tou_num = _to_float(r.get("TOU_NUM"))
        if tou_num is not None:
            axis_values["volume"][name] = tou_num
        if r.get("PER") is not None:
            axis_values["momentum"][name] = float(r["PER"])
        if r.get("PTL_NAT_CD"):
            code_by_name[name] = r["PTL_NAT_CD"]

    # 접근성 — 국가별 공급 좌석수
    air = fetch_qid(QID_ACCESS, {"BASE_YM1": ym1, "BASE_YM2": ym2}, **kw)
    meta["사용_qid"].append(QID_ACCESS)
    for r in air:
        name = r.get("NAT_NM")
        if not name or name in NON_COUNTRY_ROWS:
            continue
        if name in axis_values["volume"]:
            seat_num = _to_float(r.get("SEAT_NUM"))
            if seat_num is not None:
                axis_values["access"][name] = seat_num
        else:
            # 항공 응답의 국가명이 방한객수(volume) 국가 집합과 정확히
            # 일치하지 않아 접근성 축에 반영되지 못한 국가를 기록한다
            meta["항공_미매칭"].append(name)

    # 지출력·전환여지 — 국가별 조사 데이터. 로그인 세션이 필요하다.
    for name, code in code_by_name.items():
        try:
            survey = fetch_qid(QID_VALUE_HEADROOM,
                               {"natCd": code, "natNm": name,
                                "BASE_YM1": ym1, "BASE_YM2": ym2}, **kw)
        except client.SessionExpired:
            # 루프 중간에 세션이 만료되면 이미 채운 값들은 처리 순서에
            # 따라 편향된 일부 국가만 반영된 상태다. 이런 절반짜리 축은
            # 점수 산정 시 왜곡을 낳으므로, 축 전체를 통째로 비워서
            # "데이터 없음"으로 처리되게 한다 (부분 데이터는 무데이터보다 나쁘다)
            axis_values["value"].clear()
            axis_values["headroom"].clear()
            person_expenses.clear()
            day_expenses.clear()
            survey_years.clear()
            meta["세션필요_실패"] = True
            break
        if not survey:
            continue
        latest = max(survey, key=lambda r: r.get("BASE_YEAR", ""))
        year = latest.get("BASE_YEAR")
        if year:
            survey_years.add(str(year))
        expenses = _to_float(latest.get("PERSON_EXPENSES_AVG"))
        if expenses is not None:
            person_expenses[name] = expenses
        day_expenses_avg = _to_float(latest.get("DAY_EXPENSES_AVG"))
        if day_expenses_avg is not None:
            day_expenses[name] = day_expenses_avg
        parts = [_to_float(latest.get(k)) for k in
                 ("REVISIT_RATE", "REVISIT_INTENT", "RECOM_INTENT")]
        parts = [p for p in parts if p is not None]
        if parts:
            axis_values["headroom"][name] = sum(parts) / len(parts)

    # 지출력 축 합성 — 1인 지출과 1일 지출 각각을 국가 간 winsorized_minmax로
    # 0~100 스케일링한 뒤 두 값을 평균해 최종 지출력 값(0~100)으로 삼는다.
    # 한쪽 지표만 있는 국가는 그 지표의 스케일값 하나만 쓴다(불이익 없는
    # 단일값 사용).
    person_pct = winsorized_minmax(person_expenses)
    day_pct = winsorized_minmax(day_expenses)
    for name in set(person_expenses) | set(day_expenses):
        scores = []
        if name in person_pct.index:
            scores.append(float(person_pct[name]))
        if name in day_pct.index:
            scores.append(float(day_pct[name]))
        if scores:
            axis_values["value"][name] = sum(scores) / len(scores)

    # code_by_name이 비어 있으면 조사 qid는 한 번도 호출되지 않은 것이므로
    # 재현 정보에 기록하지 않는다 — 기록하면 실제로 호출하지 않은 qid를
    # 호출한 것처럼 보여 재현 정보가 거짓이 된다.
    if (code_by_name and not meta["세션필요_실패"]
            and QID_VALUE_HEADROOM not in meta["사용_qid"]):
        meta["사용_qid"].append(QID_VALUE_HEADROOM)

    # 축_커버리지 — volume 축(도구가 다루는 국가 전체 집합)을 기준으로
    # 각 축이 실제로 값을 보유한 국가 수와, 값이 없는 국가 목록을
    # 최종 axis_values로부터 그대로 계산한다. 어떤 경로(세션만료,
    # 국가명 불일치, 조사데이터 없음)로 누락됐든 결과에서 드러난다
    universe = sorted(axis_values["volume"])
    coverage = {}
    missing_any = set()
    for axis in ["volume", "momentum", "value", "access", "headroom"]:
        missing = sorted(c for c in universe if c not in axis_values[axis])
        coverage[axis] = {"국가수": len(axis_values[axis]), "미보유국가": missing}
        missing_any.update(missing)
    meta["축_커버리지"] = coverage
    # 결측국가 — 5축 중 하나 이상에서 값이 빠진 국가 (정직하게 재정의)
    meta["결측국가"] = sorted(missing_any)
    meta["항공_미매칭"] = sorted(set(meta["항공_미매칭"]))
    meta["조사연도"] = sorted(survey_years)
    return axis_values, meta


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
