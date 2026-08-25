"""수집 결과를 HTML 조각으로 만든다. 네트워크도 파일도 모른다.

**카탈로그의 caution 을 표 옆에 싣는다**(스펙 05). SKILL.md 에만
적어 두면 안 된다 — SKILL.md 는 에이전트가 읽고 리포트는 사람이
읽는다. "상담과 위해는 다른 통계"를 못 보면 두 숫자를 더한다.
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
           _SKILLS_ROOT / "tourism-service-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import normalize  # noqa: E402
from report import STYLE, footer_text, table_head  # noqa: E402
import service_collect as collect  # noqa: E402
import service_config as config  # noqa: E402
import workspace  # noqa: E402

# 표 하나에 보일 행 수. 넘으면 잘랐다고 적는다 — 조용히 자르면
# 73행짜리 유형 표가 스무 줄로 보이는데 아무도 모른다.
MAX_ROWS = 20
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")

EXTRA_STYLE = """
<style>
h3 { font-size: 1rem; margin: 1.5rem 0 .4rem; }
td.num, th.num { text-align: right; }
.src { color: var(--muted); font-size: .85rem; margin: .2rem 0 .6rem; }
</style>
"""


def _esc(value):
    return html_mod.escape("" if value is None else str(value))


def _fmt(value, digits=2):
    if value is None:
        return "—"
    if not isinstance(value, str) and pd.isna(value):
        return "—"
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
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
            parts.append(f'<p class="src">주의: {normalize.caution_html(caution)}</p>')
        parts.append(_table(frame))
    return "".join(parts)


def _meta_block(meta):
    조정 = ""
    if meta["기간조정"]:
        줄 = ", ".join(f"{_esc(q)}: {_esc(v)}" for q, v in
                       meta["기간조정"].items())
        조정 = (f'<p class="note">수록 시점까지 기간을 줄인 지표가 '
                f"있습니다 — {줄}</p>")
    빈섹션 = ""
    if meta["미수록섹션"]:
        이름 = ", ".join(_esc(s) for s in meta["미수록섹션"])
        빈섹션 = (f'<div class="warn">전체가 비어 표시하지 못한 섹션: '
                  f"<b>{이름}</b></div>")
    return (f'<p class="sub">기준기간 {_esc(meta["기준기간"])} · '
            f'수록 {meta["수록지표"]}/{meta["시도지표"]}</p>'
            f"{조정}{빈섹션}")


def render_report(sections, meta):
    catalog = collect.load_catalog()
    # 표 제목은 지표 이름이고 감성 표만 "이름 — 긍정" 꼴이다.
    cautions = {}
    for qid, entry in catalog.items():
        if not entry.get("caution"):
            continue
        cautions[entry["name"]] = entry["caution"]
        for 라벨, _ in config.SENTIMENT_KINDS:
            cautions[f"{entry['name']} — {라벨}"] = entry["caution"]

    warn = ""
    if meta["세션상태"] == "만료":
        warn = ('<div class="warn">로그인 세션이 만료되어 일부 지표를 '
                f"가져오지 못했습니다. <code>{_esc(LOGIN_HINT)}</code>를 "
                "실행한 뒤 다시 생성하세요. (datalab-auth 스킬)</div>")

    body = "".join(_section(name, sections[name], cautions)
                   for name in config.SECTIONS if name in sections)
    return (
        f"{STYLE}{EXTRA_STYLE}"
        f'<div class="wrap">'
        f"<h1>관광 서비스 브리프</h1>"
        f"{_meta_block(meta)}"
        f"{warn}"
        f'<div class="warn">{config.HEADLINE_CAVEAT}</div>'
        f"{body}"
        f"<footer>{_esc(footer_text())}</footer>"
        f"</div>")
