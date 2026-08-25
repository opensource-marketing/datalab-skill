"""수집 결과를 HTML 조각으로 만든다. 네트워크도 파일도 모른다.

**카탈로그의 caution 을 표 옆에 싣는다**(스펙 05). 이 리포트에서는
특히 중요하다 — 증감률 표와 건수 표의 컬럼 이름이 같아서, 옆에
적어 두지 않으면 8.83 을 "여덟 건"으로 읽는다.
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
           _SKILLS_ROOT / "global-social-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import normalize  # noqa: E402
from report import STYLE, footer_text, table_head  # noqa: E402
import social_collect as collect  # noqa: E402
import social_config as config  # noqa: E402
import workspace  # noqa: E402

# 해시태그 표가 국가 × 달 × 10위라 120행이다. 넘으면 잘랐다고 적는다 —
# 조용히 자르면 열두 달을 물었는데 두 달만 보이는 이유를 아무도 모른다.
MAX_ROWS = 20
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")

EXTRA_STYLE = """
<style>
h3 { font-size: 1rem; margin: 1.5rem 0 .4rem; }
td.num, th.num { text-align: right; }
.src { color: var(--muted); font-size: .85rem; margin: .2rem 0 .6rem; }
dl.gloss { margin: .6rem 0 1.2rem; }
dl.gloss dt { font-weight: 600; margin-top: .4rem; }
dl.gloss dd { margin: 0 0 0 1rem; color: var(--muted); }
</style>
"""


def _esc(value):
    return html_mod.escape("" if value is None else str(value))


def _fmt(value, digits=2):
    """값을 사람이 읽는 문자열로.

    **`None` 을 먼저 막는다.** 데이터랩이 컬럼 하나를 바꾸면
    `f"{v:,.1f}"` 가 TypeError 로 리포트를 통째로 죽인다.
    """
    if value is None:
        return "—"
    if not isinstance(value, str) and pd.isna(value):
        return "—"
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        # 페이스북 점유율이 4.27e-06 으로 온다. 0 으로 반올림하면
        # "페이스북이 없다"가 되므로 아주 작은 값은 그대로 적는다.
        if value and abs(value) < 0.01:
            return f"{value:.2e}"
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.{digits}f}"
    return _esc(value)


def _table(frame):
    shown = frame.head(MAX_ROWS)
    head = table_head(list(shown.columns))
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(v)}</td>" for v in row) + "</tr>"
        for row in shown.itertuples(index=False))
    more = ""
    if len(frame) > MAX_ROWS:
        more = (f'<p class="note">{len(frame):,}행 중 처음 {MAX_ROWS}행만 '
                f"보여 줍니다.</p>")
    return (f'<div class="scroll"><table>{head}<tbody>{body}</tbody>'
            f"</table></div>{more}")


def _section(name, frames, cautions):
    note = config.SECTION_NOTES.get(name, "")
    parts = [f"<h2>{_esc(name)}</h2>"]
    if note:
        parts.append(f'<div class="warn">{note}</div>')
    for 제목, frame in frames.items():
        parts.append(f"<h3>{_esc(제목)}</h3>")
        caution = cautions.get(제목)
        if caution:
            parts.append('<p class="src">주의: '
                         f"{normalize.caution_html(caution)}</p>")
        parts.append(_table(frame))
    return "".join(parts)


def _glossary():
    """세 낱말의 뜻. 표 이름만으로는 무엇을 센 것인지 알 수 없다."""
    items = "".join(f"<dt>{_esc(낱말)}</dt><dd>{_esc(뜻)}</dd>"
                    for 낱말, 뜻 in config.GLOSSARY)
    return f'<dl class="gloss">{items}</dl>'


def _meta_block(meta):
    조정 = ""
    if meta["기간조정"]:
        줄 = ", ".join(f"{_esc(q)}: {_esc(v)}" for q, v in
                       meta["기간조정"].items())
        조정 = ('<p class="note">수록 시점까지 기간을 줄인 지표가 '
                f"있습니다 — {줄}</p>")
    빈섹션 = ""
    if meta["미수록섹션"]:
        이름 = ", ".join(_esc(s) for s in meta["미수록섹션"])
        빈섹션 = ('<div class="warn">전체가 비어 표시하지 못한 섹션: '
                  f"<b>{이름}</b></div>")
    나라 = ""
    if meta.get("국가"):
        나라 = f' · 국가별 표는 <b>{_esc(meta["국가"])}</b>'
    else:
        # 나라를 못 고르면 슬쩍 기본값으로 부르지 않는다. 그러면
        # 사용자가 자기가 물은 나라의 표로 읽는다.
        #
        # **코드표를 아예 못 받은 경우까지 말해야 한다.** 고를 수 있는
        # 나라 목록이 비었다는 이유로 이 경고를 건너뛰면, 국가별 표가
        # 통째로 사라졌는데 화면에는 아무 말도 남지 않는다.
        if meta.get("고를수있는국가"):
            목록 = ", ".join(_esc(n) for n in meta["고를수있는국가"][:12])
            빈섹션 += ('<div class="warn">국가를 알아보지 못해 국가별 표를 '
                       f"뺐습니다. 고를 수 있는 나라: {목록} …</div>")
        else:
            사유 = _esc(meta.get("코드표사유") or "알 수 없음")
            빈섹션 += ('<div class="warn">국가 코드표를 가져오지 못해 '
                       f"국가별 표를 뺐습니다(사유: {사유}). 기간을 넓혀 "
                       "다시 만들어 보세요.</div>")
    return (f'<p class="sub">기준기간 {_esc(meta["기준기간"])}{나라} · '
            f'수록 {meta["수록지표"]}/{meta["시도지표"]}</p>'
            f"{조정}{빈섹션}")


def render_report(sections, meta):
    catalog = collect.load_catalog()
    cautions = {entry["name"]: entry["caution"]
                for entry in catalog.values() if entry.get("caution")}

    warn = ""
    if meta["세션상태"] == "만료":
        warn = ('<div class="warn">로그인 세션이 만료되어 일부 지표를 '
                f"가져오지 못했습니다. <code>{_esc(LOGIN_HINT)}</code>를 "
                "실행한 뒤 다시 생성하세요. (datalab-auth 스킬)</div>")

    순서 = list(config.GLOBAL_SECTIONS) + list(config.COUNTRY_SECTIONS)
    body = "".join(_section(name, sections[name], cautions)
                   for name in 순서 if name in sections)
    return (
        f"{STYLE}{EXTRA_STYLE}"
        f'<div class="wrap">'
        f"<h1>해외 소셜미디어 브리프</h1>"
        f"{_meta_block(meta)}"
        f"{warn}"
        f'<div class="warn">{config.HEADLINE_CAVEAT}</div>'
        f"{_glossary()}"
        f"{body}"
        f"<footer>{_esc(footer_text())}</footer>"
        f"</div>")
