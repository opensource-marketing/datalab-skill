"""스코어 결과를 Artifact용 HTML 리포트로 렌더링한다.

문서 래퍼(<html>, <head>, <body>)는 넣지 않는다. Artifact가 감싸기 때문이다.
테마 대응을 위해 색상은 :root 토큰으로 정의하고 다크 모드에서 재정의한다.
"""
import datetime
import html as html_mod
import pathlib
import sys

import pandas as pd

from purpose import QID as PURPOSE_QID
from purpose import purpose_columns

# report.py는 여러 리포트 스킬의 render.py가 가져다 쓰는데, 그 호출부가
# 전부 datalab-fetch/scripts를 sys.path에 올려 두지는 않는다. 그래서
# LOGIN_HINT를 만들려면 이 파일 스스로 경로를 잡아야 한다.
# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FETCH = _SKILLS_ROOT / "datalab-fetch" / "scripts"
if str(_FETCH) not in sys.path:
    sys.path.insert(0, str(_FETCH))

import workspace  # noqa: E402

SOURCE = "출처: 한국관광공사 한국관광 데이터랩(datalab.visitkorea.or.kr)"


def table_head(columns):
    """표 머리칸을 만든다. scope="col"을 빠뜨리지 않기 위한 자리다.

    스크린리더는 <th>가 어느 열의 머리인지 scope 로 안다. 없으면 표
    구조를 추론에 맡기게 되고, 열이 많은 표에서 값과 머리칸의 짝이
    어긋나 읽힌다. 이 저장소의 표는 머리칸이 전부 <thead> 안에 있으므로
    언제나 col 이다. 새 표를 만들 때는 이 함수를 쓴다.
    """
    return "".join(f'<th scope="col">{html_mod.escape(str(c))}</th>'
                   for c in columns)


def footer_text(when=None):
    """리포트 바닥에 넣을 출처 + 작성 일시.

    리포트 파일은 저장돼 나중에 다시 열린다. 그때 "이것이 언제 만들어진
    문서인가"를 알 수 없으면 옛 파일과 새 파일을 가릴 수 없다.
    **기준기간은 데이터의 범위이지 문서의 나이가 아니다.**

    **"인출"이 아니라 "작성"이다.** 작업 공간의 캐시(`workspace.cache_dir()`,
    기본 `.datalab/data/raw/`)는 만료되지 않으므로 3주 전에 받아 둔 응답으로 오늘
    리포트를 그릴 수 있다. 그 경우 이 날짜는 숫자를 받은 날이 아니다.
    인출 시점까지 말하려면 캐시 파일의 mtime을 meta에 실어 올려야
    하는데, 그것은 인출 계층부터 손대야 하는 일이라 여기서는 사실만
    적는다 — 지어내지 않는다.

    when 을 받는 이유는 테스트가 오늘 날짜에 기대지 않게 하기 위해서다.
    """
    day = when or datetime.date.today().isoformat()
    return f"{SOURCE} · {day} 작성"
AXIS_COLUMNS = ["규모_점수", "성장_점수", "지출력_점수", "접근성_점수", "전환여지_점수"]
AXIS_KEY_BY_LABEL = {
    "규모": "volume", "성장": "momentum", "지출력": "value",
    "접근성": "access", "전환여지": "headroom",
}
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")

STYLE = """
<style>
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #666666;
  --line: #e2e2e2; --accent: #1d4ed8; --warn-bg: #fff4e5; --warn-fg: #7a4100;
  --heat-0: #f5f7ff; --heat-1: #dbe4ff; --heat-2: #adc0ff; --heat-3: #7d9bff;
  --track-empty: #e7e9ee;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14161a; --fg: #eceef2; --muted: #9aa0ab;
    --line: #2b2f37; --accent: #7d9bff; --warn-bg: #3a2a12; --warn-fg: #ffd9a8;
    --heat-0: #1a1f2b; --heat-1: #223054; --heat-2: #2f4680; --heat-3: #3f5fae;
    --track-empty: #23262d;
  }
}
:root[data-theme="dark"] {
  --bg: #14161a; --fg: #eceef2; --muted: #9aa0ab;
  --line: #2b2f37; --accent: #7d9bff; --warn-bg: #3a2a12; --warn-fg: #ffd9a8;
  --heat-0: #1a1f2b; --heat-1: #223054; --heat-2: #2f4680; --heat-3: #3f5fae;
  --track-empty: #23262d;
}
body { background: var(--bg); color: var(--fg);
       font-family: -apple-system, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
       line-height: 1.65; margin: 0; padding: 2rem 1.25rem; }
.wrap { max-width: 64rem; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; }
h2 { font-size: 1.15rem; margin: 2.5rem 0 .75rem;
     border-bottom: 1px solid var(--line); padding-bottom: .4rem; }
h3 { font-size: 1rem; margin: 1.6rem 0 .4rem; }
.sub { color: var(--muted); margin: 0 0 2rem; }
.note { color: var(--muted); font-size: .85rem; margin: .5rem 0 0; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { border-bottom: 1px solid var(--line); padding: .5rem .6rem;
         text-align: right; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 600; }
.card { border: 1px solid var(--line); border-radius: .5rem;
        padding: .9rem 1.1rem; margin: .6rem 0; }
.card b { color: var(--accent); }
.warn { background: var(--warn-bg); color: var(--warn-fg);
        border-radius: .5rem; padding: .8rem 1rem; margin: 1rem 0; }
code { background: var(--heat-0); padding: .1rem .35rem; border-radius: .25rem; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--line);
         color: var(--muted); font-size: .85rem; }
</style>
"""


def _heat(value):
    if pd.isna(value):
        return "var(--bg)"
    for threshold, token in ((75, "--heat-3"), (50, "--heat-2"), (25, "--heat-1")):
        if value >= threshold:
            return f"var({token})"
    return "var(--heat-0)"


def _fmt(value, digits=1):
    return "—" if pd.isna(value) else f"{value:.{digits}f}"


def _fmt_people(value):
    """사람 수를 사람이 읽는 꼴로. 점수용 `_fmt` 와 다르다.

    `_fmt` 는 0~100 점수를 위한 것이라 소수 한 자리를 붙인다 —
    방문자 수에 쓰면 "2280434.0" 이 되어 천 단위도 안 끊긴다.
    """
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.0f}"


def _fmt_survey_years(years):
    """조사연도 목록을 사람이 읽는 문자열로 만든다.

    단일 연도는 "2025"처럼, 여러 연도에 걸쳐 있으면 "2019~2025"처럼
    최소~최대로 표시한다. 조사 데이터가 전혀 쓰이지 않았으면 그 사실을
    한국어로 명시한다.
    """
    if not years:
        return "조사 데이터가 포함되지 않았습니다"
    if len(years) == 1:
        return years[0]
    return f"{min(years)}~{max(years)}"


def _fmt_delta(value):
    if pd.isna(value):
        return "—"
    number = int(round(value))
    if number == 0:
        return "0"
    return f"+{number}" if number > 0 else str(number)


AXIS_KEY_BY_COLUMN = {c: AXIS_KEY_BY_LABEL[c.replace("_점수", "")] for c in AXIS_COLUMNS}
# 축마다 고정 색상 슬롯을 부여한다. AXIS_COLUMNS 상의 위치로 정해지므로,
# 어떤 국가가 어떤 축을 갖고 있는지와 무관하게 규모는 항상 같은 색,
# 성장은 항상 다른 같은 색이 된다. (국가 간 색상을 범례처럼 쓰기 위함)
BAR_TOKENS = ["--heat-3", "--heat-2", "--heat-1", "--accent", "--heat-0"]
AXIS_TOKEN_BY_COLUMN = dict(zip(AXIS_COLUMNS, BAR_TOKENS))

def contribution_svg(row, weights, width=420):
    """축별 기여도(축 점수 × 재분배 가중치)를 가로 누적 막대 SVG로 그린다.

    막대 트랙은 항상 전체 너비다. 그중 "채워진" 구간은 사용축수/전체축수
    비율만큼만 차지하고, 나머지는 회색의 빈 트랙으로 남긴다. 이렇게 해야
    축 1개짜리 국가와 축 5개짜리 국가가 화면에서 똑같이 꽉 찬 막대로
    보이는 착시를 막을 수 있다. 채워진 구간 안에서는 각 축의 기여도
    (축 점수 × 재분배 가중치) 비율대로 분할해, 구성비를 그대로 읽을 수 있게 한다.

    결측 축은 색이 있는 세그먼트로는 절대 그리지 않는다. 결측 축은 점수가
    0인 것이 아니라 애초에 측정되지 않은 것이며, 그 사실은 빈 트랙(회색,
    다른 시각 요소)으로만 나타낸다.
    """
    total_axes = len(AXIS_COLUMNS)
    available = {AXIS_KEY_BY_COLUMN[c] for c in AXIS_COLUMNS
                 if not pd.isna(row.get(c))}
    kept = {k: float(v) for k, v in weights.items() if k in available}
    total_w = sum(kept.values())
    if total_w <= 0:
        return ""

    height, pad = 26, 1
    contributions = []
    for column in AXIS_COLUMNS:
        key = AXIS_KEY_BY_COLUMN[column]
        if key not in kept:
            continue
        share = kept[key] / total_w
        contributions.append((column, row[column] * share))
    grand = sum(value for _, value in contributions) or 1.0

    used_axes = len(contributions)
    filled_width = width * used_axes / total_axes
    inner_pad_total = pad * max(used_axes - 1, 0)
    usable = max(filled_width - inner_pad_total, 0.0)

    segments = []
    offset = 0.0
    for i, (column, value) in enumerate(contributions):
        seg_w = max(value / grand * usable, 0.0)
        token = AXIS_TOKEN_BY_COLUMN[column]
        label = html_mod.escape(column.replace("_점수", ""))
        segments.append(
            f'<rect x="{offset:.1f}" y="0" width="{seg_w:.1f}" '
            f'height="{height}" fill="var({token})">'
            f'<title>{label} 기여 {value:.1f}점</title></rect>')
        offset += seg_w
        if i < used_axes - 1:
            offset += pad

    if used_axes < total_axes:
        missing = total_axes - used_axes
        empty_x = filled_width + pad if used_axes else 0.0
        empty_w = max(width - empty_x, 0.0)
        segments.append(
            f'<rect x="{empty_x:.1f}" y="0" width="{empty_w:.1f}" '
            f'height="{height}" fill="var(--track-empty)">'
            f'<title>{missing}개 축 미측정 (점수 0이 아니라 데이터 없음)</title>'
            f'</rect>')

    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'height="{height}" role="img" '
            f'aria-label="축별 기여도 분해">{"".join(segments)}</svg>')

def action_lines(row):
    """축 점수 패턴을 읽어 권고 문장을 만든다. 결측 축은 언급하지 않는다."""
    scored = [(c.replace("_점수", ""), float(row[c])) for c in AXIS_COLUMNS
              if not pd.isna(row.get(c))]
    if not scored:
        return []
    scored.sort(key=lambda pair: pair[1], reverse=True)
    lines = []

    top_name, top_value = scored[0]
    lines.append(f"{top_name} 축이 {top_value:.0f}점으로 가장 강합니다. "
                 f"이 축을 소구점으로 삼으십시오.")

    if len(scored) >= 2:
        low_name, low_value = scored[-1]
        if low_value < 40:
            lines.append(f"{low_name} 축이 {low_value:.0f}점으로 약합니다. "
                         f"이 국가에 투자한다면 여기가 병목입니다.")

    if len(scored) < len(AXIS_COLUMNS):
        missing = len(AXIS_COLUMNS) - len(scored)
        lines.append(f"{missing}개 축은 데이터가 없어 평가에서 제외했습니다. "
                     f"점수가 낮은 것이 아니라 측정되지 않은 것입니다.")
    return lines

PURPOSE_NOTE = (
    "입국목적은 <b>점수에 넣지 않았습니다</b>. 이미 정의된 다섯 축의 뜻과 "
    "업종 프로필의 가중치가 흔들리기 때문입니다. 순위를 바꾸지 않고 "
    "맥락만 더합니다."
)


def purpose_section(mixes, missing, esc):
    """국가별 입국목적 구성을 표로 만든다.

    같은 방한객 수라도 관광 99%인 시장과 유학·기타가 절반인 시장은
    마케팅이 다르다. 순위가 말하지 않는 것을 여기서 말한다.
    """
    if not mixes:
        return []
    columns = purpose_columns(mixes)
    head = table_head(columns)
    body = []
    for name, mix in mixes.items():
        cells = "".join(f"<td>{_fmt(mix.get(c))}</td>" for c in columns)
        body.append(f"<tr><td>{esc(name)}</td>{cells}</tr>")
    parts = ['<section id="purpose">', "<h2>입국목적 구성</h2>",
             f'<div class="warn">{PURPOSE_NOTE}</div>',
             '<div class="scroll"><table><thead><tr><th scope="col">국가</th>'
             f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>",
             '<p class="note">단위는 %입니다. 외래관광객 입국 통계 기준이며 '
             "조사가 아니라 전수입니다.</p>"]
    if missing:
        rows = ", ".join(f"{esc(k)}({esc(v)})" for k, v in sorted(missing.items()))
        parts.append(f'<p class="note">목적 구성을 가져오지 못한 국가: {rows}</p>')
    parts.append("</section>")
    return parts


RIVALRY_QID = "NAT_02_01_006"
RIVALRY_NOTE = (
    "그 나라 사람들이 실제로 어디를 가는지, 그중 한국이 몇 번째인지입니다. "
    "<b>데이터랩이 주는 순위 컬럼은 한국 행을 0으로 표시할 뿐 1위라는 뜻이 "
    "아니어서</b>, 여기서는 방문자 수로 직접 셉니다. 상위 몇 나라만 오므로 "
    "한국이 그 아래면 순위를 말하지 않고 \"N위 밖\"이라고만 적습니다. "
    "<b>이 지표는 기간 지정을 무시하고 자기 창을 줍니다</b> — 기준연도 칸을 "
    "보세요. 다른 섹션과 연도가 다를 수 있고, 2021년이면 코로나 시기 값입니다.")


def _rivalry_missing_html(missing, esc):
    """가져오지 못한 국가를 적는다. **표가 하나도 없어도 적는다.**

    셋 다 세션 만료로 실패하면 섹션이 통째로 사라져, 사용자는 이런
    표가 원래 없는 줄 안다 — "뺀 행이 있으면 뺐다는 사실을 적는다".
    """
    if not missing:
        return ""
    rows = ", ".join(f"{esc(k)}({esc(v)})" for k, v in sorted(missing.items()))
    return f'<p class="note">가져오지 못한 국가: {rows}</p>'


def rivalry_section(tables, missing, esc):
    """그 나라의 여행 목적지에서 한국이 몇 번째인가.

    5축 점수는 "우리에게 좋은 시장인가"를 말한다. 이 표는 그 시장
    쪽에서 우리가 어떻게 보이는지를 말한다 — 둘은 다른 질문이다.
    """
    if not tables:
        빠짐 = _rivalry_missing_html(missing, esc)
        if not 빠짐:
            return []
        return ['<section id="rivalry">',
                "<h2>그 나라에서 한국은 몇 번째인가</h2>", 빠짐, "</section>"]
    import rivalry
    body = []
    for name, 표 in tables.items():
        # **"셀 수 없다"의 사유를 그대로 싣는다.** 하나로 뭉개면 값이
        # 없는 것("확인 불가")을 순위 주장("10위 밖")으로 바꾼다.
        순위, 사유 = rivalry.korea_rank(표)
        위 = 사유 if 순위 is None else f"{순위}위"
        한국수 = (표.get("한국") or {}).get("방문자수")
        선두 = 표["다른곳"][0] if 표["다른곳"] else None
        body.append(
            f"<tr><td>{esc(name)}</td><td>{esc(표['연도'])}</td>"
            f"<td>{esc(위)}</td><td>{_fmt_people(한국수)}</td>"
            f"<td>{esc(선두['목적지']) if 선두 else '—'}</td>"
            f"<td>{_fmt_people(선두['방문자수'] if 선두 else None)}</td></tr>")
    head = table_head(["기준연도", "한국 순위", "한국 방문자수",
                       "1위 목적지", "그 나라 방문자수"])
    parts = ['<section id="rivalry">', "<h2>그 나라에서 한국은 몇 번째인가</h2>",
             f'<div class="warn">{RIVALRY_NOTE}</div>',
             '<div class="scroll"><table><thead><tr><th scope="col">국가</th>'
             f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"]
    parts.append(_rivalry_missing_html(missing, esc))
    parts.append("</section>")
    return parts


def render_report(df, meta, *, profile_label, top_n=10, weights=None,
                  purpose_mix=None, purpose_missing=None,
                  rivalry_tables=None, rivalry_missing=None):
    """스코어 DataFrame과 메타데이터로 리포트 HTML을 만든다."""
    esc = html_mod.escape
    ranked = df[df["총점_보정"].notna()].head(top_n)
    excluded = df[df["총점_보정"].isna()]
    parts = [STYLE, '<div class="wrap">']

    parts.append("<h1>방한 인바운드 타겟 국가 브리핑</h1>")
    parts.append(f'<p class="sub">업종 프로필: <b>{esc(profile_label)}</b> · '
                 f'기준 기간: {esc(str(meta["기준기간"]))}</p>')

    if meta.get("세션필요_실패"):
        parts.append(
            '<div class="warn">로그인 세션이 만료되어 <b>지출력·전환여지</b> 축을 '
            '가져오지 못했습니다. 두 축을 부분적으로 채우면 순위가 왜곡되므로 '
            '해당 축을 통째로 제외하고, 나머지 축에 가중치를 재분배해 산출했습니다. '
            f'전체 축으로 다시 보려면 <code>{esc(LOGIN_HINT)}</code> 실행 후 '
            '리포트를 재생성하세요.</div>')

    parts.append('<section id="summary">')
    parts.append("<h2>요약</h2>")
    for _, row in ranked.head(3).iterrows():
        best = max(AXIS_COLUMNS, key=lambda c: -1 if pd.isna(row[c]) else row[c])
        parts.append(
            f'<div class="card"><b>{esc(str(row["국가"]))}</b> — 보정 총점 '
            f'{_fmt(row["총점_보정"])}점 (순위기반 총점 {_fmt(row["총점"])}점, '
            f'값기반 총점 {_fmt(row["총점_값기반"])}점). '
            f'가장 강한 축은 {esc(best.replace("_점수", ""))}'
            f'({_fmt(row[best])}점)이며, {int(row["사용축수"])}개 축 기준입니다.</div>')
    parts.append('</section>')

    parts.append("<h2>국가별 스코어</h2>")
    header = "".join(f"<th scope='col'>{esc(c.replace('_점수', ''))}</th>" for c in AXIS_COLUMNS)
    body = []
    for _, row in ranked.iterrows():
        cells = "".join(
            f'<td style="background:{_heat(row[c])}">{_fmt(row[c])}</td>'
            for c in AXIS_COLUMNS)
        body.append(
            f'<tr><td>{esc(str(row["국가"]))}</td>{cells}'
            f'<td><b>{_fmt(row["총점_보정"])}</b></td>'
            f'<td>{_fmt(row["총점"])}</td>'
            f'<td>{_fmt(row["총점_값기반"])}</td>'
            f'<td>{_fmt_delta(row["순위변동"])}</td>'
            f'<td>{int(row["사용축수"])}</td></tr>')
    parts.append(
        f'<div class="scroll"><table><thead><tr><th scope="col">국가</th>{header}'
        f'<th scope="col">총점(보정)</th><th scope="col">총점</th><th scope="col">총점(값기반)</th><th scope="col">순위변동</th>'
        f'<th scope="col">사용축수</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')
    parts.append(
        '<p class="note">총점(보정)이 순위를 결정하는 대표 지표입니다. '
        '축을 몇 개 보유했는지와 무관하게 "총점"만 비교하면, 축 2~3개만 보유한 국가가 '
        '몇 가지 축만 잘해도 상위권을 차지하는 반면 축 5개를 모두 보유한 국가는 '
        '다섯 가지 모두에서 잘해야 같은 총점에 도달하는 구조적 편향이 생깁니다. '
        '실제로 이 편향 때문에 데이터가 얕은 국가가 리포트 상위권을 독식하는 사례가 '
        '관측됐습니다. 이를 바로잡기 위해 보유비율(=실제 확보한 축의 원래 가중치 합 ÷ '
        '전체 가중치 합)만큼만 총점을 신뢰하고, 나머지 편차는 중립값인 50점 쪽으로 '
        '당겨서 총점(보정) = 50 + (총점 − 50) × 보유비율로 계산합니다. 축을 모두 보유한 '
        '국가는 보유비율이 1.0이라 보정 전후가 동일하고, 절반만 보유한 국가는 평균에서의 '
        '편차가 절반으로 줄어듭니다. 총점은 국가 간 순위(백분위) 기반입니다. '
        '총점(값기반)은 상하위 5%를 winsorize한 뒤 값의 크기를 반영한 점수로, '
        '"1위인가"가 아니라 "얼마나 압도적인가"를 나타냅니다. '
        '순위변동은 값기반 순위에서 순위기반 순위를 뺀 값이며(둘 다 보정 전 총점 기준), '
        '양수면 값 기준에서 더 밀립니다. '
        '<b>사용축수가 다른 국가끼리는 순위변동을 직접 비교하지 마십시오.</b> '
        '축이 적은 국가는 정규화 방식 변경에 더 민감해, 큰 순위변동이 실질적 신호가 아니라 '
        '좁은 축 집합의 변동성일 수 있습니다. '
        '<b>각 축 점수는 그 축을 보유한 국가들 사이의 백분위입니다.</b> 예를 들어 지출력 '
        '점수 50점은 지출력 데이터를 가진 국가(수가 적을 수 있음) 중 중앙값이라는 뜻이고, '
        '규모 점수 50점은 방한객수 데이터를 가진 국가(전체에 가까움) 중 중앙값이라는 '
        '뜻입니다. 두 축의 보유 국가수가 다르므로, 표의 같은 색 음영이라 해도 축을 '
        '가로질러(예: 지출력 대 규모) 점수를 직접 비교하지 마십시오.</p>')

    if weights:
        total_axes = len(AXIS_COLUMNS)
        parts.append("<h2>축별 기여도</h2>")
        parts.append('<p class="sub">막대에서 색이 채워진 길이는 사용축수 ÷ '
                     f'{total_axes}로, 다섯 축 중 얼마나 측정 가능했는지를 보여줍니다. '
                     '채워진 구간 안의 분할은 각 축의 기여도(축 점수 × 재분배 '
                     '가중치) 구성비입니다. 회색으로 남은 나머지는 측정되지 않은 '
                     '축이며, 점수가 0이라는 뜻이 아닙니다.</p>')
        for _, row in ranked.head(5).iterrows():
            used = int(row["사용축수"])
            parts.append(
                f'<div class="card"><b>{esc(str(row["국가"]))}</b> '
                f'<span style="color:var(--muted)">{used}/{total_axes} 축</span>'
                f'{contribution_svg(row, weights)}</div>')

    parts.append("<h2>액션</h2>")
    for _, row in ranked.head(5).iterrows():
        items = "".join(f"<li>{esc(line)}</li>" for line in action_lines(row))
        parts.append(f'<div class="card"><b>{esc(str(row["국가"]))}</b>'
                     f'<ul>{items}</ul></div>')

    if not excluded.empty:
        names = ", ".join(esc(str(n)) for n in excluded["국가"])
        parts.append("<h2>데이터 부족으로 순위에서 제외된 국가</h2>")
        parts.append(f'<p class="sub">{names}</p>')

    parts.append("<h2>데이터 신뢰 구간</h2>")
    coverage = meta.get("축_커버리지") or {}
    rows = []
    for label, key in AXIS_KEY_BY_LABEL.items():
        entry = coverage.get(key) or {}
        missing = entry.get("미보유국가") or []
        shown = ", ".join(esc(str(n)) for n in missing[:5])
        if len(missing) > 5:
            shown += f" 외 {len(missing) - 5}개국"
        rows.append(f'<tr><td>{esc(label)}</td>'
                    f'<td>{entry.get("국가수", 0)}</td>'
                    f'<td style="text-align:left">{shown or "—"}</td></tr>')
    parts.append(
        f'<div class="scroll"><table id="coverage-table"><thead><tr><th scope="col">축</th><th scope="col">보유 국가수</th>'
        f'<th scope="col">미보유 국가</th></tr></thead><tbody>{"".join(rows)}</tbody>'
        f'</table></div>')
    parts.append(
        '<ul>'
        f'<li>기준 기간: {esc(str(meta["기준기간"]))}</li>'
        f'<li>조사연도: {esc(_fmt_survey_years(meta.get("조사연도", [])))}</li>'
        '<li>데이터 지연: 신용카드 11일, 이동통신 4일, 내비게이션 6일</li>'
        '<li>지출력·전환여지 축은 외래관광객조사 기반이며 연 단위입니다. '
        '조사 미대상 국가는 해당 축이 결측 처리되고 가중치가 재분배됩니다.</li>'
        f'<li>축이 하나라도 없는 국가: {len(meta.get("결측국가", []))}개</li>'
        '</ul>')

    unmatched = meta.get("항공_미매칭") or []
    if unmatched:
        names = ", ".join(esc(str(n)) for n in unmatched[:10])
        if len(unmatched) > 10:
            names += f" 외 {len(unmatched) - 10}개국"
        parts.append(
            f'<p class="note">항공 데이터에는 있으나 방한객 데이터에서 같은 이름을 '
            f'찾지 못해 접근성 축에 반영되지 않은 국가: {names}</p>')

    parts.extend(purpose_section(purpose_mix or {}, purpose_missing or {}, esc))
    parts.extend(rivalry_section(rivalry_tables or {},
                                 rivalry_missing or {}, esc))

    parts.append('<section id="reproducibility">')
    parts.append("<h2>재현 정보</h2>")
    # 목적 구성은 축 계산 밖에서 부르므로 meta["사용_qid"]에 없다.
    # 리포트가 실제로 쓴 qid를 빠짐없이 적는다.
    used = list(meta.get("사용_qid", []))
    if purpose_mix and PURPOSE_QID not in used:
        used.append(PURPOSE_QID)
    if rivalry_tables and RIVALRY_QID not in used:
        used.append(RIVALRY_QID)
    qids = "".join(f"<li><code>{esc(str(q))}</code></li>" for q in used)
    parts.append(f"<ul>{qids}</ul>")
    parts.append('</section>')

    parts.append(f'<footer>{esc(footer_text())}</footer>')
    parts.append("</div>")
    return "\n".join(parts)
