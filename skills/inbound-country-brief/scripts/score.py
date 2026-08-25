"""국가별 5축 스코어링.

결측 축을 0점으로 처리하지 않는다. 조사 데이터가 없는 신흥 시장이
자동으로 최하위가 되면, 바로 그 시장을 찾으려는 목적이 무너지기 때문이다.
대신 결측 축의 가중치를 남은 축에 비례 재분배한다.

정규화 방식은 두 가지를 함께 제공한다. 순위(rank) 기반 점수는 "누가 1등인가"를,
값(value) 기반 점수는 "1등이 얼마나 압도적인가"를 답한다. 두 점수가 크게 엇갈리는
국가야말로 리포트에서 가장 흥미로운 신호다.

가중치 재분배는 총점을 0~100 범위로 유지해 주지만, 통계적 편향을 하나
남긴다: 축 2개만 있는 국가는 두 가지만 잘하면 되고, 축 5개인 국가는
다섯 가지를 다 잘해야 한다. 그 결과 데이터가 얕은 국가가 상위권을
독식하는 현상이 실제 리포트에서 관측됐다. 이를 보정하기 위해 보유비율
(실제 확보한 원래 가중치의 비중)만큼만 총점을 신뢰하고, 나머지는 중립값
50점 쪽으로 당기는 "커버리지 축소(coverage shrinkage)"를 적용한 총점_보정을
함께 제공한다.
"""
import numpy as np
import pandas as pd

AXES = ["volume", "momentum", "value", "access", "headroom"]
AXIS_LABELS = {
    "volume": "규모",
    "momentum": "성장",
    "value": "지출력",
    "access": "접근성",
    "headroom": "전환여지",
}


def rank_percentile(series):
    """0~100 백분위(순위 기반)로 변환한다.

    의도적으로 winsorize(극단값 클리핑)를 하지 않는다. 순위는 단조 변환에
    불변(invariant)이므로, 클리핑 후 순위를 매기는 것은 두 극단값이
    클리핑으로 인해 우연히 동률이 되는 극히 드문 경우를 제외하면 결과를
    바꾸지 않는다. 게다가 백분위 자체가 이미 "몇 등인가"만 남기고 원값의
    크기 차이를 지우기 때문에, 극단값의 영향력은 구조적으로 이미 제한되어
    있다. 극단값의 "정도"를 반영하고 싶다면 winsorized_minmax를 쓴다.
    """
    s = pd.Series(series).astype(float).dropna()
    if s.empty:
        return pd.Series(dtype=float)
    if s.max() == s.min():
        return pd.Series(50.0, index=s.index)
    return s.rank(pct=True) * 100


def winsorized_minmax(series, limit=0.05):
    """상하위 limit 비율을 클리핑한 뒤 0~100으로 min-max 스케일링한다.

    값(value) 기반 점수용 정규화다. 여기서는 클리핑이 실제로 결과를
    바꾼다 — 극단값의 영향력을 억제해 "얼마나 압도적인가"를 과장 없이
    보여주는 것이 목적이다.
    """
    s = pd.Series(series).astype(float).dropna()
    if s.empty:
        return pd.Series(dtype=float)
    if len(s) >= 3:
        lo, hi = s.quantile(limit), s.quantile(1 - limit)
        s = s.clip(lo, hi)
    if s.max() == s.min():
        return pd.Series(50.0, index=s.index)
    return (s - s.min()) / (s.max() - s.min()) * 100


def renormalize_weights(weights, available):
    """결측 축의 가중치를 사용 가능한 축에 비례 재분배한다."""
    kept = {k: float(v) for k, v in weights.items() if k in available}
    total = sum(kept.values())
    if total <= 0:
        return {}
    return {k: v / total * 100.0 for k, v in kept.items()}


_NORMALIZERS = {
    "rank": rank_percentile,
    "value": winsorized_minmax,
}


def score_countries(axis_values, weights, *, min_axes=2, method="rank"):
    """축별 원시값과 가중치로 국가 순위를 산출한다.

    axis_values: {축이름: {국가명: 원시값}}
    method: "rank"(순위 기반, 기본값) 또는 "value"(값 기반)
    반환 컬럼: 국가, {축}_점수 …, 사용축수, 총점, 보유비율, 총점_보정, 제외사유

    보유비율 = 사용된 축들의 "원래" 가중치 합 / 전체 가중치 합 (재분배 후
    가중치가 아니라 원래 프로필 가중치 기준이어야 한다 — 재분배 후 가중치는
    항상 합이 100이 되어 버려 이 비율이 항상 1이 되고 만다).
    총점_보정 = 50 + (총점 - 50) × 보유비율. 모든 축을 보유한 국가는 보정
    전후가 동일하고(비율 1.0), 축을 절반만 보유한 국가는 평균(50점)으로부터의
    편차가 그만큼 줄어든다. min_axes 미달로 제외된 국가는 총점과 마찬가지로
    보유비율·총점_보정도 NaN으로 남긴다.
    """
    if method not in _NORMALIZERS:
        raise ValueError(
            f"알 수 없는 정규화 방식입니다: {method!r} "
            f"(허용값: {sorted(_NORMALIZERS)})")
    normalize = _NORMALIZERS[method]

    pct = {axis: normalize(pd.Series(vals))
           for axis, vals in axis_values.items() if vals}

    countries = sorted({c for vals in axis_values.values() for c in vals})
    total_weight = sum(float(v) for v in weights.values())
    rows = []
    for country in countries:
        available = {a for a, s in pct.items()
                     if country in s.index and not pd.isna(s[country])}
        row = {"국가": country}
        for axis in axis_values:
            row[f"{AXIS_LABELS.get(axis, axis)}_점수"] = (
                float(pct[axis][country]) if axis in available else np.nan)
        row["사용축수"] = len(available)

        if len(available) < min_axes:
            row["총점"] = np.nan
            row["보유비율"] = np.nan
            row["총점_보정"] = np.nan
            row["제외사유"] = (f"사용 가능한 축 {len(available)}개 "
                             f"(최소 {min_axes}개 필요)")
        else:
            w = renormalize_weights(weights, available)
            total = sum(pct[a][country] * w[a] for a in w) / 100.0
            kept_weight = sum(float(weights[a]) for a in available
                              if a in weights)
            보유비율 = kept_weight / total_weight if total_weight > 0 else 0.0
            row["총점"] = total
            row["보유비율"] = 보유비율
            row["총점_보정"] = 50.0 + (total - 50.0) * 보유비율
            row["제외사유"] = ""
        rows.append(row)

    columns = (["국가"]
               + [f"{AXIS_LABELS.get(a, a)}_점수" for a in axis_values]
               + ["사용축수", "총점", "보유비율", "총점_보정", "제외사유"])
    df = pd.DataFrame(rows, columns=columns)
    if df.empty:
        # 국가가 하나도 없으면(공개 qid가 빈 리스트를 반환하는 경우 등)
        # sort_values("총점")이 존재하지 않는 컬럼에 접근해 KeyError를
        # 내므로, 여기서 곧바로 정의된 컬럼만 가진 빈 DataFrame을 반환한다.
        return df
    return df.sort_values("총점", ascending=False,
                          na_position="last").reset_index(drop=True)


def score_both(axis_values, weights, *, min_axes=2):
    """순위 기반과 값 기반 점수를 함께 산출하고 둘의 순위 변동을 계산한다.

    반환 컬럼: 국가, {축}_점수 …(순위 기반), 총점(순위 기반), 총점_값기반,
    보유비율, 총점_보정, 순위변동, 사용축수, 제외사유

    순위변동 = 값 기반 순위 - 순위 기반 순위 (1등이 1위, 동률은 등장 순서로
    구분). 이 순위는 어디까지나 원래의 총점(순위 기반 vs 값 기반) 기준이며,
    커버리지 축소와는 무관하다 — 총점_보정을 도입했다고 해서 순위변동의
    정의를 바꾸지 않는다. 양수면 값 기반 방식에서 더 순위가 밀린다는
    뜻이다. 총점이 NaN인(제외된) 국가는 순위변동도 NaN으로 남긴다.

    최종 반환 순서는 총점_보정 내림차순이다(NaN은 맨 뒤) — 보유 축이 적어
    총점만 높은 국가가 상위권을 차지하는 편향을 리포트 단계에서 바로잡기
    위함이다.
    """
    rank_df = score_countries(axis_values, weights, min_axes=min_axes,
                               method="rank")
    value_df = score_countries(axis_values, weights, min_axes=min_axes,
                                method="value")

    rank_order = {c: i + 1 for i, c in enumerate(rank_df["국가"])}
    value_order = {c: i + 1 for i, c in enumerate(value_df["국가"])}
    value_total = dict(zip(value_df["국가"], value_df["총점"]))
    rank_total = dict(zip(rank_df["국가"], rank_df["총점"]))

    df = rank_df.copy()
    df["총점_값기반"] = df["국가"].map(value_total)

    def 순위변동(country):
        if pd.isna(rank_total[country]):
            return np.nan
        return value_order[country] - rank_order[country]

    df["순위변동"] = df["국가"].apply(순위변동)

    axis_cols = [f"{AXIS_LABELS.get(a, a)}_점수" for a in axis_values]
    column_order = (["국가"] + axis_cols
                     + ["총점", "총점_값기반", "보유비율", "총점_보정",
                        "순위변동", "사용축수", "제외사유"])
    df = df[column_order]
    return df.sort_values("총점_보정", ascending=False,
                          na_position="last").reset_index(drop=True)
