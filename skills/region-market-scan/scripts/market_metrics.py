"""수집한 지표에서 파생 수치를 계산한다.

데이터랩에 없는 값을 만드는 곳이므로, 계산식과 그 한계를 함께 돌려준다.
리포트가 근거를 감추면 숫자를 믿을 수 없다.

계산할 수 없으면 None을 돌려준다. 예외를 던지지 않는다 — 지표 하나가
빠졌다고 리포트 전체가 사라지면 안 된다.
"""
# 모듈 이름에 market_ 접두사를 붙인 이유: region-visitor-profile도 collect.py와
# render.py를 가지고 있다. 두 스킬을 한 파이썬 프로세스에서 쓰면(테스트
# 스위트가 그렇다) 먼저 import된 쪽이 sys.modules를 차지해 다른 쪽 함수를
# 조용히 대신 실행한다.
import pandas as pd

import activate
import client
import codes
import market_collect as collect

MAX_PEERS = 3
TOTAL_ROW = "전체"

# 이 문구들은 계산 결과와 함께 리포트에 실린다. 수치만 남고 단서가 사라지면
# 읽는 사람이 가동률로 오해한다.
ROOM_DEMAND_FORMULA = "월평균 숙박 방문자 수 ÷ 객실 수"
ROOM_DEMAND_CAVEAT = (
    "숙박 방문자 수는 이동통신 기반 <b>추정치</b>이고 객실 수는 등록 기준 "
    "<b>시점 재고</b>입니다. 둘의 비는 <b>객실 가동률이 아닙니다</b>. "
    "같은 방식으로 계산한 다른 지역과 견줄 때만 뜻이 있습니다."
)
NET_OPENING_FORMULA = "기간 내 개업 수 − 폐업 수 (업종 '전체' 행 기준)"
PEAK_FORMULA = "최대월 방문자 수 ÷ 최소월 방문자 수"


def _numeric(frame, column):
    if frame is None or frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return values if not values.empty else None


def peak_ratio(visitors):
    """성수기 배수와 최대·최소 달을 돌려준다."""
    values = _numeric(visitors, "방문자수")
    if values is None or "기준월" not in visitors.columns:
        return None
    frame = visitors.loc[values.index, ["기준월"]].assign(값=values)
    low = frame.loc[frame["값"].idxmin()]
    high = frame.loc[frame["값"].idxmax()]
    if not low["값"]:
        return None
    return {
        "배수": float(high["값"] / low["값"]),
        "최대월": str(high["기준월"]), "최대값": float(high["값"]),
        "최소월": str(low["기준월"]), "최소값": float(low["값"]),
        "계산식": PEAK_FORMULA,
    }


def lodging_rate(stay):
    """숙박 비율을 순방문자 수로 가중평균한다.

    달마다 방문자 수가 크게 다르므로 단순평균하면 비수기의 비율이 성수기와
    같은 무게를 갖는다. 사이트가 이미 계산해 둔 비율을 쓰되, 기간 대표값은
    규모로 가중해 만든다.
    """
    rates = _numeric(stay, "숙박비율")
    weights = _numeric(stay, "순방문자수")
    if rates is None or weights is None:
        return None
    pair = pd.DataFrame({"r": rates, "w": weights}).dropna()
    total = pair["w"].sum()
    if not total:
        return None
    return float((pair["r"] * pair["w"]).sum() / total)


def rooms(stock):
    """시점 객실 수와 그 기준월을 돌려준다."""
    values = _numeric(stock, "객실_수")
    if values is None:
        return None
    month = ""
    if "기준월" in stock.columns and not stock["기준월"].empty:
        month = str(stock["기준월"].iloc[0])
    return {"객실수": float(values.iloc[0]), "기준월": month}


def room_demand(lodging_visitors, room_stock):
    """객실당 월 숙박 방문자 수. 가동률이 아니다."""
    monthly = _numeric(lodging_visitors, "숙박방문자수")
    stock = rooms(room_stock)
    if monthly is None or stock is None or not stock["객실수"]:
        return None
    return {
        "값": float(monthly.mean() / stock["객실수"]),
        "월평균_숙박방문자": float(monthly.mean()),
        "객실수": stock["객실수"],
        "재고기준월": stock["기준월"],
        "계산식": ROOM_DEMAND_FORMULA,
        "주의": ROOM_DEMAND_CAVEAT,
    }


def net_openings(openings, closings):
    """개업 − 폐업.

    응답에는 업종 '전체' 행과 업종별 행이 함께 온다. 다 더하면 정확히
    두 배가 된다(강릉 2024년: 전체 40, 모든 행 80). '전체' 행만 센다.
    """
    def _total(frame, column):
        if frame is None or frame.empty or "업종" not in frame.columns:
            return None
        rows = frame[frame["업종"] == TOTAL_ROW]
        values = _numeric(rows, column)
        return float(values.sum()) if values is not None else None

    opened = _total(openings, "개업_수")
    closed = _total(closings, "폐업_수")
    if opened is None or closed is None:
        return None
    return {"개업": opened, "폐업": closed, "순증": opened - closed,
            "계산식": NET_OPENING_FORMULA}


def peer_codes(support, self_code):
    """유사지역 코드와 이름을 돌려준다. 자기 자신은 뺀다."""
    frame = support.get(collect.QID_PEERS)
    if frame is None or frame.empty:
        return []
    needed = {"유사_지역코드", "유사_지역명"}
    if not needed <= set(frame.columns):
        return []
    out = []
    for code, name in zip(frame["유사_지역코드"], frame["유사_지역명"]):
        code = _되찾은_코드(str(code).strip(), str(name).strip())
        if not code or code == str(self_code) or any(c == code for c, _ in out):
            continue
        out.append((code, str(name).strip()))
    return out[:MAX_PEERS]


def _되찾은_코드(code, name):
    """시군구 표에 없는 코드는 이름으로 되찾는다. 못 찾으면 None.

    유사지역 응답에 표에 없는 코드가 섞여 온다 — 2026-08-23 강릉시를
    물으면 "전남광주통합특별시 여수시"(12130)가 후보로 온다. 그 코드로
    부르면 **빈 배열**이라 그 지역만 조용히 빠진다. 사용자는 유사지역
    셋 중 둘만 나온 이유를 알 수 없다.

    이름의 마지막 낱말로 되찾는다(여수시 → 46130). 여러 곳에 걸리면
    고르지 않고 뺀다 — 임의로 고르면 남의 지역 값을 유사지역이라고
    싣게 된다.
    """
    if not code:
        return None
    if code in codes.load_codes():
        return code
    끝말 = name.split()[-1] if name else ""
    hits = codes.resolve_region(끝말) if 끝말 else []
    return hits[0][0] if len(hits) == 1 else None


def peer_room_demand(peers, ym1, ym2, *, cache_dir=None, session_file=None):
    """유사지역의 객실당 월 숙박 방문자 수를 같은 방식으로 계산한다.

    한 지역이라도 값을 못 만들면 그 지역만 빼고 나머지로 평균을 낸다.
    전부 실패하면 None이다.
    """
    rows = []
    for code, name in peers:
        data = collect.collect_supply_demand(code, ym1, ym2,
                                             cache_dir=cache_dir,
                                             session_file=session_file)
        value = room_demand(data["숙박방문자"], data["객실"])
        if value is not None:
            rows.append({"지역명": name, "지역코드": code, "값": value["값"]})
    if not rows:
        return None
    average = sum(r["값"] for r in rows) / len(rows)
    return {"평균": average, "지역별": rows}


def compare_room_demand(own, peer):
    """자기 값과 유사지역 평균의 격차율(%)."""
    if own is None or peer is None or not peer["평균"]:
        return None
    return (own["값"] - peer["평균"]) / peer["평균"] * 100.0


def sido_position(sgg_cd, region_name, ym1, ym2, *, cache_dir=None,
                  session_file=None):
    """시도 안에서 이 지역의 방문자·지출 순위를 낸다. 실패하면 None."""
    got = collect.collect_sido_rank(sgg_cd, ym1, ym2, cache_dir=cache_dir,
                                    session_file=session_file)
    out = {}
    for qid, label in ((collect.QID_SIDO_VISITORS, "방문자수"),
                       (collect.QID_SIDO_SPENDING, "지출액")):
        frame = (got.get(qid) or {}).get("표")
        out[label] = sido_rank(frame, region_name, label) if frame is not None else None
    if any(out.values()):
        return out
    # 카드가 조용히 사라지면 사용자는 모시 리포트에는 있던 순위가 왜
    # 없는지 알 수 없다. 짚을 수 있는 이유는 짚는다.
    이유 = rank_missing_reason(sgg_cd)
    return {"없음이유": 이유} if 이유 else None


def rank_missing_reason(sgg_cd):
    """시도 안 순위가 나오지 않는 이유. 짚을 수 없으면 None.

    통합시 산하 구는 시도 표에 모시 이름으로 합쳐져 있어 자기 행이
    없다 — 포항시 남구를 찾아도 표에는 "포항시"뿐이다.
    """
    entry = codes.load_codes().get(str(sgg_cd)) or {}
    이름 = entry.get("시군구", "")
    if " " not in 이름:
        return None
    모시 = 이름.split(" ")[0]
    return (f"시도 안 순위는 시군구 단위로만 나옵니다. {이름}는 시도 "
            f"표에 {모시}로 합쳐져 있어 자기 행이 없습니다 — "
            f"--region '{모시}' 로 다시 실행하면 순위가 나옵니다.")


# 시도 안 순위가 "옆 동네보다 나은가"에 답한다면, 이쪽은 "전국에서
# 어디쯤인가"에 답한다. 두 자리가 크게 어긋나는 지역이 실제로 있다 —
# 시도 안에서 1등인데 전국 252곳에서는 중간인 경우다.
COMPETITIVENESS_CAVEAT = (
    "관광수요 경쟁력은 데이터랩이 방문·소비·검색·SNS 등을 묶어 만든 "
    "종합 지수입니다. 값 자체의 단위는 공개돼 있지 않으므로 절대값이 "
    "아니라 전국 평균 대비와 순위로 읽으세요."
)


# SessionExpired는 FetchError의 부모가 아니라 형제다(client.py). 함께
# 적지 않으면 build()를 뚫고 scan.py까지 올라가 리포트가 통째로
# 사라지고, 사용자는 필요도 없는 로그인 안내를 받는다 — 이 지표는
# 전부 공개라 로그인해도 달라지는 것이 없다.
_ACTIVATE_ERRORS = (activate.ActivateError, client.SessionExpired,
                    client.FetchError)


def tourism_competitiveness(sgg_cd, ym1, ym2, *, cache_dir=None):
    """전국에서 이 지역의 관광수요 경쟁력. 실패하면 None.

    지수 요약과 4대분류 순위를 함께 가져온다. 둘 중 하나만 와도
    쓸 수 있으므로 따로 감싼다.
    """
    out = {"요약": None, "축": None, "검산통과": None, "세션만료": False}
    try:
        out["요약"] = activate.summary(sgg_cd, ym1, ym2, cache_dir=cache_dir)
    except client.SessionExpired:
        out["세션만료"] = True
    except (activate.ActivateError, client.FetchError):
        pass
    try:
        axes = activate.competitiveness(sgg_cd, ym1, ym2, cache_dir=cache_dir)
    except client.SessionExpired:
        # 세션 만료는 그냥 없는 것과 다르다. None을 돌려주면 그 사실이
        # 사라져 리포트가 "값이 없다"로만 말한다.
        out["세션만료"] = True
        return out
    except (activate.ActivateError, client.FetchError):
        return out if out["요약"] else None
    out["축"] = axes["축"]
    out["모집단"] = axes["모집단"]
    # 정렬 규칙이 두 곳에 생기지 않도록 activate가 낸 결론을 그대로
    # 옮긴다. 렌더가 축[0]/축[-1]로 다시 구하면 정렬이 바뀔 때 두
    # 곳을 고쳐야 한다.
    out["가장강한"] = axes["가장강한"]
    out["가장약한"] = axes["가장약한"]
    # 순위와 역순위의 관계가 깨지면 우리가 순위로 쓰는 컬럼이 바뀐
    # 것이다. 그대로 실으면 1등을 꼴등으로 적는다.
    out["검산통과"] = axes["검산통과"]
    return out


def build(sections, meta, ym1, ym2, *, cache_dir=None, session_file=None,
          compare=True, region_name=None):
    """리포트에 실을 파생 지표를 한꺼번에 만든다."""
    demand = sections.get("수요", {})
    supply = sections.get("공급", {})

    own_demand = room_demand(demand.get(collect.QID_LODGING_VISITORS),
                             supply.get(collect.QID_ROOMS))
    result = {
        "성수기": peak_ratio(demand.get(collect.QID_VISITORS)),
        "숙박비율": lodging_rate(demand.get("LN_02_01_011_002")),
        "객실당수요": own_demand,
        "순증": net_openings(supply.get(collect.QID_OPENINGS),
                             supply.get(collect.QID_CLOSINGS)),
        "유사지역": None,
        "객실당수요_격차율": None,
        "시도내위치": None,
        "관광경쟁력": None,
    }
    if region_name:
        # 실패해도 리포트의 나머지는 성립한다. 이 블록만 비운다.
        # region_name이 없으면 호출한 쪽이 위치 지표를 원하지 않는
        # 것이므로 네트워크를 쓰지 않는다.
        result["시도내위치"] = sido_position(
            meta["지역코드"], region_name, ym1, ym2,
            cache_dir=cache_dir, session_file=session_file)
        result["관광경쟁력"] = tourism_competitiveness(
            meta["지역코드"], ym1, ym2, cache_dir=cache_dir)
        if (result["관광경쟁력"] or {}).get("세션만료"):
            # 리포트 머리말이 로그인 안내를 띄우도록 meta에 옮긴다.
            meta["세션상태"] = "만료"
    if not compare:
        return result

    peers = peer_codes(meta.get("보조지표") or {}, meta["지역코드"])
    if not peers:
        return result
    peer_value = peer_room_demand(peers, ym1, ym2, cache_dir=cache_dir,
                                  session_file=session_file)
    result["유사지역"] = peer_value
    result["객실당수요_격차율"] = compare_room_demand(own_demand, peer_value)
    return result


SIDO_RANK_FORMULA = "시도 안 시군구를 값 순으로 세운 자리"
SIDO_RANK_CAVEAT = (
    "시도 안에서의 자리다. 다른 시도와 견줄 수 없다 — 시도마다 "
    "시군구 수가 다르다(서울 25곳, 강원 18곳)."
)


def sido_rank(frame, region_name, value_label):
    """시도 안 시군구 표에서 우리 지역의 순위와 비중을 뽑는다.

    지역명으로 찾는다. 이 지표는 시군구 코드를 응답에 담지 않고 이름만
    주기 때문이다. 이름이 없으면 None을 돌려준다 — 통합시처럼 시도
    목록에 다른 이름으로 들어 있는 경우가 있어, 못 찾은 것을 0위로
    적으면 거짓이 된다.
    """
    if frame is None or frame.empty:
        return None
    name_col = next((c for c in frame.columns if str(c).startswith("시군구명")),
                    None)
    if name_col is None or value_label not in frame.columns:
        return None

    values = _numeric(frame, value_label)
    if values is None or values.empty:
        return None
    work = frame.assign(_값=values).dropna(subset=["_값"])
    work = work.drop_duplicates(subset=[name_col])
    if work.empty:
        return None

    work = work.sort_values("_값", ascending=False).reset_index(drop=True)
    # 지역명이 두 가지 모양으로 돈다. 코드 조회는 "강원특별자치도 강릉시"를
    # 주는데 이 표에는 "강릉시"만 들어 있다. 그대로 견주면 못 찾고, 못
    # 찾은 것이 조용히 "순위 없음"이 되어 리포트에서 블록이 사라진다.
    short = str(region_name).split()[-1] if region_name else ""
    names = work[name_col].astype(str)
    hit = work.index[(names == str(region_name)) | (names == short)]
    if len(hit) == 0:
        return None
    position = int(hit[0]) + 1
    total = int(len(work))
    value = float(work.loc[hit[0], "_값"])
    whole = float(work["_값"].sum())
    return {"순위": position, "시군구수": total, "값": value,
            "비중": (value / whole * 100) if whole else None}
