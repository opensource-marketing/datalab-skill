"""지역 프로파일을 Artifact용 HTML로 렌더링한다.

문서 래퍼(<html>, <head>, <body>)는 넣지 않는다 — Artifact가 감싼다.
스타일과 출처 표기는 inbound-country-brief의 report.py에서 가져다 쓴다.
같은 프로젝트의 리포트가 서로 다르게 보이면 안 되고, 테마 토큰 3중 정의를
두 곳에서 관리하면 반드시 어긋난다.
"""
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
           _SKILLS_ROOT / "region-visitor-profile" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from report import STYLE, footer_text

import normalize
import period
from collect import SECTIONS, load_loc_catalog
import workspace

LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")
ESTIMATE_NOTE = (
    "이 수치는 이동통신·신용카드·내비게이션 데이터를 바탕으로 한 <b>추정치</b>이며, "
    "실측 방문자 수가 아닙니다."
)
CONSUMPTION_NOTE = (
    "소비 수치는 <b>외국인 카드 사용액</b>이며 단위는 <b>백만 원</b>입니다"
    "(전국·업종별 소비를 세 지표로 교차검산해 확정했습니다). "
    "데이터랩이 <b>시군구 단위</b> 내국인 카드소비 지표를 내렸으므로 "
    "<b>이 리포트에는 내국인 소비가 없습니다</b>. "
    "<b>시도 단위</b> 내국인 관광소비는 야간관광 지표"
    "(<code>BY_TH_NIGHT_TOUR_002_002</code>)에 현지인·외지인으로 나뉘어 "
    "남아 있으니, 필요하면 <code>datalab-query</code>로 따로 조회하세요."
)
NO_COMPARE_NOTE = (
    "이 리포트는 <b>전년·유사지역 비교 없이</b> 생성되었습니다"
    "(<code>--no-compare</code>). 각 수치가 높은지 낮은지 판단할 기준이 "
    "붙어 있지 않으니, 비교가 필요하면 옵션 없이 다시 생성하세요."
)
MAX_ROWS = 20
HIDDEN_SUFFIX = "_제곱근"   # 차트 버블 크기용 렌더링 부산물. 표에 싣지 않는다.

# 20행을 넘는 표는 잘라야 하는데 데이터랩 응답 순서는 크기순이 아니다.
# 무엇을 기준으로 상위를 뽑을지 qid마다 정해 둔다. 정하지 않은 지표는
# 자르더라도 "상위"라고 말하지 않는다.
SORT_BY = {
    "LN_04_01_008": "시군구_방문자수",
    "LN_03_01_067": "방문자수",
    "LN_04_01_006_001": "업종_소비액",
}


def _esc(value):
    return html_mod.escape(str(value))


def _fmt(value, digits=1):
    """표에 넣을 값을 사람이 읽는 문자열로 만든다.

    결측은 문자열 "nan"이나 "<NA>"가 아니라 대시로 보여야 한다. numpy·pandas가
    쓰는 결측 표현이 여러 가지이므로 pd.isna로 한 번에 거른다.
    """
    if value is None:
        return "—"
    if not isinstance(value, str) and pd.isna(value):
        return "—"
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        # 방문자 수 같은 정수값에 ".0"을 달면 기계 출력처럼 읽힌다.
        # 소수부가 실제로 있는 값(비율·평균일수)만 자릿수를 붙인다.
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.{digits}f}"
    return _esc(value)


def _table(frame, qid):
    """DataFrame을 가로 스크롤 가능한 표로 만든다.

    행이 많으면 잘라야 하는데, 데이터랩 응답 순서는 크기순이 아니다.
    정렬 없이 앞에서 20행을 떼어 "상위"라고 부르면 사실이 아닌 순위를
    주장하게 된다. 그래서 SORT_BY가 정한 컬럼으로 먼저 내림차순 정렬하고,
    정할 컬럼이 없으면 문구를 "처음"으로 낮춘다.
    """
    frame = frame[[c for c in frame.columns if not c.endswith(HIDDEN_SUFFIX)]]

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
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>{more}")


def _comparison_block(entry):
    """한 지표의 전년·유사지역 비교를 카드로 만든다.

    entry가 없다는 것은 "비교에 실패했다"가 아니라 "이 지표는 애초에 기간
    비교 대상이 아니다"라는 뜻이다(성·연령 분포처럼 구성 스냅샷인 지표).
    거기에 "비교기준 없음"을 붙이면 시도했다가 실패한 것처럼 읽히므로
    아무것도 붙이지 않는다. 시도했으나 못 만든 경우는 전년·유사 두 키가
    모두 None으로 들어오며, 그때 "비교기준 없음"을 적는다.
    """
    if not entry:
        return ""
    parts = []
    yoy = entry.get("전년")
    if yoy:
        rate = ("—" if yoy["증감률"] is None
                else f'{yoy["증감률"]:+,.1f}%')
        parts.append(f'<b>전년 대비</b> {rate} '
                     f'({_fmt(yoy["전년"])} → {_fmt(yoy["현재"])})')
    peer = entry.get("유사")
    if peer:
        gap = "—" if peer["격차율"] is None else f'{peer["격차율"]:+,.1f}%'
        names = ", ".join(_esc(n) for n in peer["비교지역"])
        parts.append(f'<b>유사지역 대비</b> {gap} '
                     f'(유사지역 평균 {_fmt(peer["유사지역평균"])} · {names})')
    if not parts:
        return '<p class="note">비교기준 없음 — 전년 동기와 유사지역 데이터를 ' \
               '가져오지 못했습니다.</p>'
    return '<div class="card">' + "<br>".join(parts) + "</div>"


# 전국 평균과 이 지역 값이 한 달에 두 행으로 온다. 그대로 그리면
# 두 줄이 번갈아 나와 배수가 눈에 들어오지 않고, 열두 달이면 24행이라
# 표가 잘린다. 한 줄에 나란히 놓는다.
BENCHMARK_QIDS = ("LN_03_01_006", "LN_03_01_006_01", "LN_03_01_006_02",
                  "LN_03_01_007", "LN_03_01_007_01", "LN_03_01_007_02")
BENCHMARK_LABEL = "전국 기초지자체별 평균"


def _benchmark_table(frame, region_name):
    """전국 평균 행과 지역 행을 한 줄로 합친다. 못 합치면 None."""
    if "구분" not in frame.columns or "기준월" not in frame.columns:
        return None
    value_cols = [c for c in frame.columns if c not in ("기준월", "구분")]
    if len(value_cols) != 1:
        return None
    value = value_cols[0]

    rows, skipped = [], []
    for month, group in frame.groupby("기준월", sort=True):
        national = group[group["구분"] == BENCHMARK_LABEL][value]
        local = group[group["구분"] != BENCHMARK_LABEL][value]
        if national.empty or local.empty:
            # 한쪽만 온 달은 배수를 낼 수 없다. 조용히 0으로 채우면
            # 그 달만 뚝 떨어진 것처럼 보인다. 대신 뺀 사실을 적는다 —
            # 열두 달을 물었는데 열 행이 오는 이유를 알 수 있어야 한다.
            skipped.append(str(month))
            continue
        n, l = float(national.iloc[0]), float(local.iloc[0])
        ratio = f"{l / n:,.2f}배" if n else "—"
        rows.append((month, n, l, ratio))
    if not rows:
        return None

    head = (f"<th scope='col'>기준월</th><th scope='col'>전국 평균</th>"
            f"<th scope='col'>{_esc(region_name)}</th><th scope='col'>배수</th>")
    body = "".join(
        f"<tr><td>{_esc(m)}</td><td>{_fmt(n)}</td><td>{_fmt(l)}</td>"
        f"<td>{_esc(r)}</td></tr>" for m, n, l, r in rows)
    missing = ""
    if skipped:
        missing = (f'<p class="note">{_esc(", ".join(skipped))}은(는) '
                   f'한쪽 값만 와서 뺐습니다 — 배수를 낼 수 없습니다.</p>')
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>"
            f'{missing}'
            f'<p class="note">배수가 1보다 크면 전국 기초지자체 평균보다 '
            f'높다는 뜻입니다. 전국 평균은 시군구들의 평균이지 전국 '
            f'합계가 아닙니다.</p>')


def _catalog_cautions():
    """카탈로그가 적어 둔 함정. 표 옆에 그대로 싣는다(스펙 05).

    SKILL.md에만 적어 두면 안 된다 — SKILL.md는 에이전트가 읽고
    리포트는 사람이 읽는다. "이 값의 단위는 분이다"를 못 보면
    2,039를 시간으로 읽는다.
    """
    return {qid: entry["caution"]
            for qid, entry in load_loc_catalog().items()
            if entry.get("caution")}


def _section_html(name, frames, catalog_names, comparisons,
                  region_name="이 지역", cautions=None):
    blocks = [f"<h2>{_esc(name)}</h2>"]
    if name == "소비":
        blocks.append(f'<div class="warn">{CONSUMPTION_NOTE}</div>')
    for qid, frame in frames.items():
        title = catalog_names.get(qid, qid)
        blocks.append(f"<h3>{_esc(title)} <span class='note'>{_esc(qid)}</span></h3>")
        caution = (cautions or {}).get(qid)
        if caution:
            blocks.append(f'<p class="note">주의: {normalize.caution_html(caution)}</p>')
        blocks.append(_comparison_block((comparisons or {}).get(qid)))
        merged = (_benchmark_table(frame, region_name)
                  if qid in BENCHMARK_QIDS else None)
        blocks.append(merged if merged else _table(frame, qid))
    return "".join(blocks)


def _coverage_html(meta, catalog_names=None):
    # qid 를 그대로 적으면 "LN_03_03_059 가 안 왔다"가 된다. 무엇이
    # 빠졌는지 알 수 없다 — 시장 스캔은 이름으로 적는다.
    names = catalog_names or {}
    rows = "".join(
        f"<tr><td>{_esc(names.get(qid, qid))}"
        f" <span class='note'>{_esc(qid)}</span></td>"
        f"<td>{_esc(normalize.reason_text(reason))}</td></tr>"
        for qid, reason in sorted(meta["미수록지표"].items()))
    table = ""
    if rows:
        table = ('<div class="scroll"><table><thead><tr><th scope="col">지표</th><th scope="col">사유</th>'
                 f"</tr></thead><tbody>{rows}</tbody></table></div>")
    trimmed = ""
    lines = period.summarize_notes(meta.get("기간조정") or {})
    if lines:
        items = "".join(f"<li>{_esc(line)}</li>" for line in lines)
        trimmed = ('<div class="warn">지표마다 데이터가 나오는 시점이 다릅니다.'
                   f"<ul>{items}</ul></div>")
    merged = ""
    if meta.get("통합시안내"):
        merged = f'<div class="warn">{_esc(meta["통합시안내"])}</div>'
    dead = ""
    if meta["미수록섹션"]:
        names = ", ".join(_esc(s) for s in meta["미수록섹션"])
        dead = (f'<div class="warn">전체가 비어 표시하지 못한 섹션: <b>{names}</b>. '
                "점수가 0이 아니라 데이터가 없다는 뜻입니다.</div>")
    return (f"<h2>데이터 수록 현황</h2>"
            f'<p>수록 지표 <b>{meta["수록지표"]}/{meta["시도지표"]}</b> '
            f'({meta["수록률"] * 100:.0f}%)</p>{trimmed}{merged}{dead}{table}')


def render_report(sections, meta, *, region_name, comparisons=None):
    """지역 프로파일 HTML을 만든다."""
    catalog = load_loc_catalog()
    catalog_names = {qid: entry["name"] for qid, entry in catalog.items()}
    cautions = _catalog_cautions()

    warn = ""
    if meta.get("세션상태") == "만료":
        warn = ('<div class="warn">로그인 세션이 만료되어 일부 지표를 '
                f"가져오지 못했습니다. <code>{_esc(LOGIN_HINT)}</code>를 실행해 "
                "세션을 갱신한 뒤 다시 생성하세요. (datalab-auth 스킬)</div>")

    skipped = ""
    if comparisons is None:
        skipped = f'<div class="warn">{NO_COMPARE_NOTE}</div>'

    body = "".join(
        _section_html(name, sections[name], catalog_names, comparisons,
                      region_name, cautions)
        for name in SECTIONS if name in sections)

    return (
        f"{STYLE}"
        f'<div class="wrap">'
        f"<h1>{_esc(region_name)} 방문객 프로파일</h1>"
        f'<p class="sub">기준기간 {_esc(meta["기준기간"])} · '
        f'지역코드 {_esc(meta["지역코드"])}</p>'
        f"{warn}"
        f'<div class="warn">{ESTIMATE_NOTE}</div>'
        f"{skipped}"
        f"{body}"
        f"{_coverage_html(meta, catalog_names)}"
        f"<footer>{_esc(footer_text())}</footer>"
        f"</div>"
    )
