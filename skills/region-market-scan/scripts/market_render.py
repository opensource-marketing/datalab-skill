"""지역 시장 스캔을 Artifact용 HTML로 렌더링한다.

문서 래퍼(<html>, <head>, <body>)는 넣지 않는다 — Artifact가 감싼다.
스타일과 출처 표기는 inbound-country-brief의 report.py에서 가져다 쓴다.
같은 프로젝트의 리포트가 서로 다르게 보이면 안 되고, 테마 토큰 3중 정의를
여러 곳에서 관리하면 반드시 어긋난다.

요약을 먼저 놓고 표를 뒤에 놓는다. 이 리포트는 읽는 문서가 아니라
판단하는 화면이므로, 답이 먼저 보여야 한다.
"""
# 모듈 이름에 market_ 접두사를 붙인 이유: region-visitor-profile도 collect.py와
# render.py를 가지고 있다. 두 스킬을 한 파이썬 프로세스에서 쓰면(테스트
# 스위트가 그렇다) 먼저 import된 쪽이 sys.modules를 차지해 다른 쪽 함수를
# 조용히 대신 실행한다.
import html as html_mod
import numbers
import pathlib
import sys

import pandas as pd

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "region-market-scan" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from report import STYLE, footer_text

import market_collect as collect
import market_metrics
import normalize
import period
import workspace

LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")
MAX_ROWS = 20

# 추정 경고와 실측 안내를 나눠 둔다. 비교 리포트에는 유료관광지점 입장객이
# 실리지 않으므로, 거기까지 "실측이 있다"고 적으면 없는 표를 가리키게 된다.
ESTIMATE_NOTE = (
    "방문자·숙박 방문자 수치는 이동통신 데이터 기반 <b>추정치</b>입니다."
)
MEASURED_NOTE = (
    "이 리포트에서 <b>유료관광지점 입장객 수만 실측</b>(매표 집계)이며, "
    "표에 <b>[실측]</b>으로 표시했습니다."
)
SEARCH_NOTE = (
    "검색건수는 <b>내비게이션 목적지 검색 건수</b>이지 방문자 수가 아닙니다. "
    "검색 없이 찾아가는 곳(주민 단골집 등)은 잡히지 않습니다."
)
STOCK_NOTE = (
    "관광사업체·객실 수는 <b>특정 시점의 재고</b>이고 방문자 수는 "
    "<b>기간 합계</b>입니다. 성격이 다른 값이므로 나눌 때는 기준 시점을 "
    "함께 읽어야 합니다."
)
NO_COMPARE_NOTE = (
    "이 리포트는 <b>유사지역 비교 없이</b> 생성되었습니다"
    "(<code>--no-compare</code>). 객실당 수요가 높은지 낮은지 판단할 기준이 "
    "붙어 있지 않으니, 비교가 필요하면 옵션 없이 다시 생성하세요."
)

SECTION_NOTES = {"매력": SEARCH_NOTE, "공급": STOCK_NOTE}

# 화면에 싣지 않는 컬럼. 내부 식별자와 차트 렌더링 부산물이다.
HIDDEN_COLUMNS = {
    "지역코드", "포털_지역코드", "시도코드", "시도명", "시군구명",
    "POI_ID", "관광지_ID", "중심_POI_ID", "업종코드",
}
HIDDEN_SUFFIX = "_제곱근"

SORT_BY = {
    "LN_03_010_001": "개업_수",
    "LN_03_010_002": "폐업_수",
    "LN_03_01_038": "검색건수",
    "LN_03_01_041": "검색건수",
    "LN_03_012_001_001": "기간_입장객수",
    "LN_03_012_001_003": "기간_외국인_입장객수",
    "LN_03_01_004": "세부_검색건수",
    "BZM_02_01_003": "사업체_수",
    "BZM_03_02_002": "숙박시설_수",
}

# 관광지점당 12개월치가 오지만 기간 합계 컬럼이 모든 행에 되풀이된다.
# 월별 원본을 20행 보여 주면 지점 두 개밖에 못 본다. 지점 단위로 접는다.
COLLAPSE = {
    "LN_03_012_001_001": ("관광지점명", ["기간_입장객수"]),
    "LN_03_012_001_003": ("관광지점명", ["기간_외국인_입장객수"]),
}
MEASURED_QIDS = {"LN_03_012_001_001", "LN_03_012_001_003"}

# 월별 × 업종 행이 함께 와서 37행이 된다. 20행에서 자르면 업종별 그림이
# 잘려 나가므로, 업종 단위로 기간 합계를 내어 보여 준다.
GROUP_SUM = {
    "LN_03_010_001": ("업종", "개업_수"),
    "LN_03_010_002": ("업종", "폐업_수"),
}
GROUP_SUM_NOTE = "기간 전체를 업종별로 합산했습니다."


def _esc(value):
    return html_mod.escape(str(value))


def _비었나(value):
    """값이 없는 것과 같은가. 생략 안내에 "= —"를 적지 않기 위해 쓴다."""
    if value is None:
        return True
    if not isinstance(value, str) and pd.isna(value):
        return True
    return isinstance(value, str) and not value.strip()


def _fmt(value, digits=1):
    """표에 넣을 값을 사람이 읽는 문자열로 만든다."""
    if value is None:
        return "—"
    if not isinstance(value, str) and pd.isna(value):
        return "—"
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.{digits}f}"
    return _esc(value)


def _drop_constant(frame):
    """모든 행에서 값이 같은 컬럼을 뺀다.

    "지역명"이 12행 내내 같은 값이면 그 컬럼은 정보를 담지 않고 가로 폭만
    먹는다. 다만 조용히 지우면 표를 따로 떼어 봤을 때 무엇에 관한
    수치인지 알 수 없어지므로, 뺀 컬럼과 그 값을 표 아래에 적는다.

    **숫자 컬럼은 값이 같아도 빼지 않는다.** 두 업종의 개업 수가 우연히
    같을 수 있는데, 그때 그 컬럼을 지우면 표의 알맹이가 사라진다.
    되풀이되는 것은 라벨이고, 재는 것은 숫자다.
    """
    if len(frame) < 2:
        return frame, []
    dropped = []
    keep = []
    for column in frame.columns:
        values = frame[column]
        if (not pd.api.types.is_numeric_dtype(values)
                and values.nunique(dropna=False) == 1):
            dropped.append((column, values.iloc[0]))
        else:
            keep.append(column)
    if not keep:      # 전부 상수면 표가 사라진다. 그냥 둔다.
        return frame, []
    return frame[keep], dropped


def _drop_duplicate(frame):
    """앞선 컬럼과 값이 완전히 같은 컬럼을 뺀다.

    관광사업체 계열은 NUM과 SUM_NUM을 함께 준다. 시군구 하나만 조회할
    때는 두 값이 언제나 같아서 같은 숫자를 두 번 보여 주게 된다. 값이
    실제로 같을 때만 빼므로 시도 단위 합계가 다른 경우에는 그대로 남는다.
    """
    dropped = []
    keep = []
    for column in frame.columns:
        twin = next((k for k in keep if frame[k].equals(frame[column])), None)
        if twin is None:
            keep.append(column)
        else:
            dropped.append((column, twin))
    return frame[keep], dropped


def _reshape(frame, qid):
    """표로 보여 주기 전에 모양을 다듬는다. (프레임, 주석들)을 돌려준다."""
    frame = frame[[c for c in frame.columns
                   if c not in HIDDEN_COLUMNS
                   and not c.endswith(HIDDEN_SUFFIX)]]
    notes = []

    collapse = COLLAPSE.get(qid)
    if collapse:
        key, keep = collapse
        columns = [key] + [c for c in keep if c in frame.columns]
        if key in frame.columns:
            frame = frame[columns].drop_duplicates(subset=[key])

    group = GROUP_SUM.get(qid)
    if group:
        key, value = group
        if key in frame.columns and value in frame.columns:
            frame = (frame.groupby(key, as_index=False)[value].sum())
            notes.append(GROUP_SUM_NOTE)

    frame, duplicated = _drop_duplicate(frame)
    if duplicated:
        pairs = ", ".join(f"{_esc(c)}({_esc(t)}와 동일)" for c, t in duplicated)
        notes.append(f"값이 같아 생략한 컬럼: {pairs}")

    frame, constant = _drop_constant(frame)
    if constant:
        # 통합시 모시 코드(포항시 47110 등)에는 데이터랩이 지역명을
        # 주지 않는다 — 산하 구에는 준다. 그것까지 값으로 적으면
        # "지역명 = —"라는 아무 말도 아닌 안내가 표 밑에 남는다.
        있음 = [(c, v) for c, v in constant if not _비었나(v)]
        없음 = [c for c, v in constant if _비었나(v)]
        if 있음:
            pairs = ", ".join(f"{_esc(c)} = {_fmt(v)}" for c, v in 있음)
            notes.append(f"모든 행에서 값이 같아 생략한 컬럼: {pairs}")
        if 없음:
            빈것 = ", ".join(_esc(c) for c in 없음)
            notes.append(f"모든 행에서 비어 있어 생략한 컬럼: {빈것}")

    return frame, notes


def _table(frame, qid):
    """DataFrame을 가로 스크롤 가능한 표로 만든다.

    데이터랩 응답 순서는 크기순이 아니다. 정렬 없이 앞에서 20행을 떼어
    "상위"라고 부르면 사실이 아닌 순위를 주장하게 되므로, 정렬 컬럼이
    있을 때만 "상위"라고 쓴다.
    """
    frame, notes = _reshape(frame, qid)
    sort_col = SORT_BY.get(qid)
    ranked = sort_col is not None and sort_col in frame.columns
    if ranked:
        frame = frame.sort_values(sort_col, ascending=False)

    shown = frame.head(MAX_ROWS)
    head = "".join(f"<th scope='col'>{_esc(c)}</th>" for c in shown.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(v)}</td>" for v in row) + "</tr>"
        for row in shown.itertuples(index=False, name=None))
    more = ""
    if len(frame) > MAX_ROWS:
        if ranked:
            more = (f'<p class="note">{len(frame):,}행 중 {_esc(sort_col)} '
                    f"기준 상위 {MAX_ROWS}행만 표시합니다.</p>")
        else:
            more = (f'<p class="note">{len(frame):,}행 중 처음 {MAX_ROWS}행만 '
                    "표시합니다. 크기순으로 정렬된 것이 아닙니다.</p>")
    for note in notes:
        more += f'<p class="note">{note}</p>'
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>{more}")


def _card(title, value, detail=""):
    detail_html = f'<br><span class="note">{detail}</span>' if detail else ""
    return (f'<div class="card"><b>{_esc(title)}</b><br>{value}'
            f"{detail_html}</div>")


def _summary_html(derived, compare):
    """판단에 쓰는 네 숫자를 맨 앞에 놓는다."""
    cards = []

    peak = derived.get("성수기")
    if peak:
        cards.append(_card(
            "성수기 배수", f'{peak["배수"]:,.2f}배',
            f'{_esc(peak["최대월"])} {_fmt(peak["최대값"])}명 ↔ '
            f'{_esc(peak["최소월"])} {_fmt(peak["최소값"])}명 · '
            f'{_esc(peak["계산식"])}'))

    rate = derived.get("숙박비율")
    if rate is not None:
        cards.append(_card("숙박 비율", f"{rate:,.1f}%",
                           "데이터랩이 계산한 월별 숙박 비율을 "
                           "순방문자 수로 가중평균했습니다."))

    demand = derived.get("객실당수요")
    if demand:
        gap = derived.get("객실당수요_격차율")
        peers = derived.get("유사지역")
        detail = (f'{_esc(demand["계산식"])} · 월평균 숙박 방문자 '
                  f'{_fmt(demand["월평균_숙박방문자"])}명 ÷ 객실 '
                  f'{_fmt(demand["객실수"])}실'
                  f'(재고 기준 {_esc(demand["재고기준월"])})')
        if gap is not None and peers:
            names = ", ".join(_esc(r["지역명"]) for r in peers["지역별"])
            detail += (f'<br>유사지역 평균 {peers["평균"]:,.1f} 대비 '
                       f"<b>{gap:+,.1f}%</b> ({names})")
        cards.append(_card("객실당 월 숙박 방문자",
                           f'{demand["값"]:,.1f}명', detail))

    position = derived.get("시도내위치")
    if position:
        for label, unit in (("방문자수", "명"), ("지출액", "천원")):
            rank = position.get(label)
            if not rank:
                continue
            share = ("" if rank["비중"] is None
                     else f' · 시도 안 비중 {rank["비중"]:,.1f}%')
            cards.append(_card(
                f"시도 안 {label} 순위",
                f'{rank["순위"]}위 / {rank["시군구수"]}곳',
                f'{_fmt(rank["값"])}{unit}{share}<br>'
                f'{_esc(market_metrics.SIDO_RANK_CAVEAT)}'))
        if position.get("없음이유"):
            cards.append(_card("시도 안 순위", "낼 수 없음",
                               _esc(position["없음이유"])))

    comp = derived.get("관광경쟁력")
    # 지수 자체가 없으면 카드를 내지 않는다. 값이 None인 채로 "—"를
    # 크게 띄우면 0으로 읽힌다. 빠진 사실은 수록 현황이 말한다.
    if comp and comp.get("요약") and comp["요약"]["이지역"] is not None:
        s = comp["요약"]
        ratio = ("" if s["전국대비"] is None
                 else f' · 전국의 <b>{s["전국대비"]:,.1f}%</b> 수준')
        delta = ("" if s["증감"] is None
                 else f' · 직전 기간 대비 {s["증감"]:+,.1f}')
        national = ("" if s["전국"] is None
                    else f'같은 기간 전국 {s["전국"]:,.1f}')
        cards.append(_card(
            "관광수요 지수",
            f'{s["이지역"]:,.1f}',
            f'{national}{ratio}{delta}<br>'
            f'{_esc(market_metrics.COMPETITIVENESS_CAVEAT)}'))

    net = derived.get("순증")
    if net:
        cards.append(_card(
            "관광사업체 순증", f'{net["순증"]:+,.0f}개',
            f'개업 {_fmt(net["개업"])} − 폐업 {_fmt(net["폐업"])} · '
            f'{_esc(net["계산식"])}'))

    if not cards:
        return ('<h2>요약</h2><div class="warn">파생 지표를 계산할 수 있는 '
                "지표가 하나도 수집되지 않았습니다.</div>")

    caveat = ""
    if derived.get("객실당수요"):
        caveat = f'<div class="warn">{derived["객실당수요"]["주의"]}</div>'
    skipped = "" if compare else f'<div class="warn">{NO_COMPARE_NOTE}</div>'
    return f"<h2>요약</h2>{''.join(cards)}{caveat}{skipped}"


def _competitiveness_html(derived):
    """전국에서 이 지역의 관광 경쟁력. 네 축과 순위.

    시도 안 순위가 "옆 동네보다 나은가"라면 이 표는 "전국에서 어디쯤
    인가"다. 두 자리가 어긋나는 지역이 실제로 있어 둘 다 싣는다.
    """
    comp = derived.get("관광경쟁력")
    if not comp or not comp.get("축"):
        return ""

    if comp.get("검산통과") is False:
        # 순위와 역순위의 관계가 깨졌다. 순위를 그대로 실으면 1등을
        # 꼴등으로 적을 수 있으므로 표 대신 경고를 낸다.
        return ('<h2>전국에서의 관광 경쟁력</h2>'
                '<div class="warn">데이터랩이 주는 순위와 역순위의 관계가 '
                '맞지 않습니다. 순위를 잘못 읽을 수 있어 이 표를 '
                '생략했습니다.</div>')

    rows = []
    for axis in comp["축"]:
        # "상위 79%"는 읽는 사람이 좋은 자리로 오해한다. 절반을
        # 넘어가면 뒤에서 세는 편이 사실에 가깝다.
        pct = "—"
        if axis["상위백분율"] is not None:
            top = axis["상위백분율"]
            pct = (f'상위 {top:,.0f}%' if top <= 50
                   else f'하위 {100 - top:,.0f}%')
        vs = ("—" if axis["전국평균대비"] is None
              else f'{axis["전국평균대비"]:,.0f}%')
        # 데이터랩이 컬럼 하나를 바꾸면 activate._num()이 None을 준다.
        # 그대로 포맷하면 TypeError로 리포트가 통째로 사라진다 —
        # "지표 하나가 실패해도 리포트는 생성된다"는 규약이 깨진다.
        rank = ("—" if axis["순위"] is None or axis["모집단"] is None
                else f'{axis["순위"]:,.0f}위 / {axis["모집단"]:,.0f}곳')
        rows.append(
            f'<tr><td>{_esc(axis["대분류"])}</td>'
            f'<td>{_fmt(axis["값"])}</td>'
            f'<td>{_fmt(axis["전국평균"])}</td>'
            f'<td>{vs}</td>'
            f'<td>{rank}</td>'
            f'<td>{pct}</td></tr>')

    strong, weak = comp.get("가장강한"), comp.get("가장약한")
    lead = ""
    if strong and weak and strong != weak:
        lead = (f'<p>가장 강한 축은 <b>{_esc(strong)}</b>, 가장 약한 축은 '
                f'<b>{_esc(weak)}</b>입니다.</p>')

    return (
        '<h2>전국에서의 관광 경쟁력</h2>'
        f'{lead}'
        '<div class="scroll"><table><thead><tr><th scope="col">축</th><th scope="col">값</th>'
        '<th scope="col">전국평균</th><th scope="col">평균 대비</th><th scope="col">순위</th><th scope="col">백분위</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        '<p class="note">시도 안 순위가 "옆 동네보다 나은가"에 답한다면, '
        '이 표는 "전국에서 어디쯤인가"에 답합니다. 두 자리가 크게 '
        '어긋나는 지역이 있습니다 — 시도 안에서 앞자리인데 전국에서는 '
        '중간인 경우입니다.</p>'
        '<p class="note">순위는 작을수록 좋습니다. 데이터랩은 순위와 함께 '
        '그것을 뒤집은 값도 주는데, 뒤집은 쪽을 순위로 읽으면 1등이 '
        '꼴등이 됩니다. 이 리포트는 두 값의 관계를 확인한 뒤에만 표를 '
        '냅니다.</p>')


def _section_html(name, frames, catalog_names, cautions=None):
    blocks = [f"<h2>{_esc(name)}</h2>"]
    note = SECTION_NOTES.get(name)
    if note:
        blocks.append(f'<div class="warn">{note}</div>')
    for qid, frame in frames.items():
        title = catalog_names.get(qid, qid)
        badge = " <span class='note'>[실측]</span>" if qid in MEASURED_QIDS else ""
        blocks.append(f"<h3>{_esc(title)}{badge} "
                      f"<span class='note'>{_esc(qid)}</span></h3>")
        # **함정은 표 옆에 있어야 한다.** 여태 미수록 지표 설명에만
        # 실려서, 값이 온 표의 함정은 사람이 볼 길이 없었다 — 층이
        # 섞인 표를 그대로 더하는 사고가 바로 그 자리에서 난다.
        caution = (cautions or {}).get(qid)
        if caution:
            blocks.append(f'<p class="note">주의: {normalize.caution_html(caution)}</p>')
        blocks.append(_table(frame, qid))
    return "".join(blocks)


def _loaders():
    """이 리포트가 쓰는 카탈로그 로더 전부.

    **목록을 두 군데 적고 있었더니 한쪽만 늘었다.** 이름 표에는
    `main` 로더를 넣고 함정 표에는 빠뜨리면, 제목은 제대로 나오는데
    그 지표의 caution 만 조용히 사라진다 — 실제로 `main` 하나가
    두 곳 모두에서 빠져 세대별 인기관광지의 제목이 qid 로 나오고
    "상위 30곳 안에서의 비중" 경고가 실리지 않았다.

    **로더를 늘리는 자리는 여기 하나뿐이다.**
    """
    return (collect.load_loc_catalog, collect.load_bzm_catalog,
            collect.load_bda_catalog, collect.load_camp_catalog,
            collect.load_sexage_catalog, collect.load_main_catalog)


def _catalog_cautions():
    """카탈로그가 적어 둔 함정. 지표가 비었을 때 원인일 때가 많다."""
    out = {}
    for loader in _loaders():
        for qid, entry in loader().items():
            if entry.get("caution"):
                out[qid] = entry["caution"]
    return out


def _coverage_html(meta):
    names = _catalog_names()
    cautions = _catalog_cautions()
    adjusted = meta.get("기간조정") or {}
    rows = ""
    for qid, reason in sorted(meta["미수록지표"].items()):
        detail = period.note_text(adjusted.get(qid)) or ""
        # 값이 안 온 이유가 기간이 아니라 그 지표의 함정일 때가 있다.
        # 카탈로그가 이미 알고 있는 것을 사용자에게 숨기지 않는다.
        if reason == "데이터없음" and qid in cautions:
            detail = (detail + " " if detail else "") + cautions[qid]
        rows += "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            _esc(names.get(qid, qid)),
            _esc(normalize.reason_text(reason)),
            _esc(detail))
    table = ""
    if rows:
        table = ('<div class="scroll"><table><thead><tr><th scope="col">지표</th>'
                 "<th scope='col'>사유</th><th scope='col'>참고</th>"
                 f"</tr></thead><tbody>{rows}</tbody></table></div>")

    trimmed = ""
    lines = period.summarize_notes(adjusted)
    if lines:
        items = "".join(f"<li>{_esc(line)}</li>" for line in lines)
        trimmed = ('<div class="warn">지표마다 데이터가 나오는 시점이 다릅니다.'
                   f"<ul>{items}</ul></div>")

    merged = ""
    if meta.get("통합시안내"):
        merged = f'<div class="warn">{_esc(meta["통합시안내"])}</div>'

    dead = ""
    if meta["미수록섹션"]:
        section_names = ", ".join(_esc(s) for s in meta["미수록섹션"])
        dead = (f'<div class="warn">전체가 비어 표시하지 못한 섹션: '
                f"<b>{section_names}</b>. 값이 0이 아니라 데이터가 없다는 "
                "뜻입니다.</div>")
    return (f"<h2>데이터 수록 현황</h2>"
            f'<p>수록 지표 <b>{meta["수록지표"]}/{meta["시도지표"]}</b> '
            f'({meta["수록률"] * 100:.0f}%)</p>{merged}{trimmed}{dead}{table}')


def _catalog_names():
    # 로더를 빠뜨리면 제목이 qid 그대로 나온다. 사용자는 지표 이름이
    # 아니라 "LN_01_03_003_03_004"를 보게 된다.
    names = {}
    for loader in _loaders():
        names.update({qid: entry["name"] for qid, entry in loader().items()})
    return names


def render_report(sections, meta, derived, *, region_name, compare=True):
    """지역 시장 스캔 HTML을 만든다."""
    catalog_names = _catalog_names()
    # 섹션마다 부르면 카탈로그 넷을 그때마다 다시 읽는다.
    cautions = _catalog_cautions()

    warn = ""
    if meta.get("세션상태") == "만료":
        warn = ('<div class="warn">로그인 세션이 만료되어 일부 지표를 '
                f"가져오지 못했습니다. <code>{_esc(LOGIN_HINT)}</code>를 실행해 "
                "세션을 갱신한 뒤 다시 생성하세요. (datalab-auth 스킬)</div>")

    body = "".join(
        _section_html(name, sections[name], catalog_names, cautions)
        for name in collect.SECTIONS if name in sections)

    return (
        f"{STYLE}"
        f'<div class="wrap">'
        f"<h1>{_esc(region_name)} 관광시장 스캔</h1>"
        f'<p class="sub">기준기간 {_esc(meta["기준기간"])} · '
        f'지역코드 {_esc(meta["지역코드"])} · '
        f'재고 기준 {_esc(meta["재고기준월"])}</p>'
        f"{warn}"
        f'<div class="warn">{ESTIMATE_NOTE} {MEASURED_NOTE}</div>'
        f"{_summary_html(derived, compare)}"
        f"{_competitiveness_html(derived)}"
        f"{body}"
        f"{_coverage_html(meta)}"
        f'<p class="note">방문객이 누구인지 자세히 보려면 '
        f"<code>region-visitor-profile</code> 스킬을 쓰세요.</p>"
        f"<footer>{_esc(footer_text())}</footer>"
        f"</div>"
    )
