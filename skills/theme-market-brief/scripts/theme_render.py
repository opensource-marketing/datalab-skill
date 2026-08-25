"""테마 브리프를 Artifact용 HTML로 렌더링한다.

문서 래퍼(<html>, <head>, <body>)는 넣지 않는다 — Artifact가 감싼다.
스타일과 출처 표기는 inbound-country-brief의 report.py에서 가져다 쓴다.

# 모듈 이름에 theme_ 접두사를 붙인 이유: 다른 스킬도 render.py를 가지고
# 있다. 한 프로세스에서 둘 다 쓰면 먼저 import된 쪽이 sys.modules를 차지한다.

**컬럼 헤더에 단위를 붙인다.** 테마 지표는 같은 화면 안에서도 원·천원·
백만원이 섞여 있다. 헤더에 단위가 없으면 숫자만 보고 크기를 짐작하게 된다.
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
           _SKILLS_ROOT / "theme-market-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from report import STYLE, footer_text

import theme_collect as collect
import normalize
import period
import theme_config as config
import workspace

LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")
MAX_ROWS = 24
HIDDEN_SUFFIX = ("_코드", "코드")
NO_CROSS_THEME = (
    "테마끼리 숫자를 견주지 마세요. 의료 소비액(천원)과 MICE 매출(원)과 "
    "야간 소비(원)는 단위도 모집단도 다릅니다."
)


def _esc(value):
    return html_mod.escape(str(value))


def _fmt(value, digits=1):
    if value is None:
        return "—"
    if not isinstance(value, str) and pd.isna(value):
        return "—"
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.{digits}f}"
    return _esc(value)


def _units(qid):
    """카탈로그가 적어 둔 컬럼별 단위를 라벨 → 단위로 돌려준다."""
    entry = collect.load_catalog()[qid]
    return {meta["label"]: (meta.get("unit") or "")
            for meta in entry["columns"].values()}


def _drop_code_columns(frame):
    """내부 코드 컬럼은 싣지 않는다. 사람이 읽을 값이 아니다.

    단, 코드만 남고 이름 컬럼이 없는 표는 통째로 비므로 그때는 남긴다.
    """
    keep = [c for c in frame.columns if not str(c).endswith(HIDDEN_SUFFIX)]
    return frame[keep] if keep else frame


def _table(frame, qid):
    frame = _drop_code_columns(frame)
    units = _units(qid)
    shown = frame.head(MAX_ROWS)
    head = "".join(
        f"<th scope='col'>{_esc(c)}"
        + (f' <span class="note">({_esc(units[c])})</span>'
           if units.get(c) else "")
        + "</th>" for c in shown.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(v)}</td>" for v in row) + "</tr>"
        for row in shown.itertuples(index=False, name=None))
    more = ""
    if len(frame) > MAX_ROWS:
        more = (f'<p class="note">{len(frame):,}행 중 처음 {MAX_ROWS}행만 '
                "표시합니다. 크기순으로 정렬된 것이 아닙니다.</p>")
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>{more}")


def _section_html(name, frames):
    catalog = collect.load_catalog()
    blocks = [f"<h2>{_esc(name)}</h2>"]
    for qid, frame in frames.items():
        entry = catalog[qid]
        blocks.append(f"<h3>{_esc(entry['name'])} "
                      f"<span class='note'>{_esc(qid)}</span></h3>")
        caution = entry.get("caution")
        if caution:
            blocks.append(f'<p class="note">주의: {normalize.caution_html(caution)}</p>')
        blocks.append(_table(frame, qid))
    return "".join(blocks)


def _coverage_html(meta):
    trimmed = ""
    lines = period.summarize_notes(meta.get("기간조정") or {})
    if lines:
        items = "".join(f"<li>{_esc(line)}</li>" for line in lines)
        trimmed = ('<div class="warn">지표마다 데이터가 나오는 시점이 '
                   f"다릅니다.<ul>{items}</ul></div>")
    head = (f"<h2>데이터 수록 현황</h2>"
            f'<p>수록 지표 <b>{meta["수록지표"]}/{meta["시도지표"]}</b></p>'
            f"{trimmed}")
    if not meta["미수록지표"]:
        return head
    # qid 만 적으면 무엇이 빠졌는지 알 수 없다. 카탈로그가 이름을
    # 알고 있으므로 함께 적는다.
    catalog = collect.load_catalog()
    rows = "".join(
        f"<tr><td>{_esc((catalog.get(qid) or {}).get('name', qid))}"
        f" <span class='note'>{_esc(qid)}</span></td>"
        f"<td>{_esc(normalize.reason_text(reason))}</td></tr>"
        for qid, reason in sorted(meta["미수록지표"].items()))
    return (head
            + '<p class="note">빈칸은 0이 아니라 데이터가 없다는 뜻입니다.</p>'
            + '<div class="scroll"><table><thead><tr><th scope="col">지표</th>'
            + f"<th scope='col'>사유</th></tr></thead><tbody>{rows}</tbody></table></div>")


def render_report(sections, meta):
    warn = ""
    if meta["세션상태"] == "만료":
        warn = ('<div class="warn">로그인 세션이 만료되어 일부 지표를 '
                f"가져오지 못했습니다. <code>{_esc(LOGIN_HINT)}</code>를 "
                "실행한 뒤 다시 생성하세요. (datalab-auth 스킬)</div>")
    note = config.THEME_NOTES.get(meta["테마"], "")
    body = "".join(
        _section_html(name, sections[name])
        for name in config.THEMES[meta["테마"]]["sections"] if name in sections)
    return (
        f"{STYLE}"
        f'<div class="wrap">'
        f"<h1>{_esc(meta['테마명'])} 브리프</h1>"
        f'<p class="sub">{_esc(meta["조회대상"])} · '
        f'기준기간 {_esc(meta["기준기간"])}</p>'
        f"{warn}"
        + (f'<div class="warn">{note}</div>' if note else "")
        + f'<div class="warn">{NO_CROSS_THEME}</div>'
        f"{body}"
        f"{_coverage_html(meta)}"
        f"<footer>{_esc(footer_text())}</footer>"
        f"</div>"
    )
