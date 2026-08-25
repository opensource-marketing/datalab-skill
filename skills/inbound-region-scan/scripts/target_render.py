"""국가 타겟 지역 후보를 Artifact용 HTML로 렌더링한다.

문서 래퍼(<html>, <head>, <body>)는 넣지 않는다 — Artifact가 감싼다.
스타일과 출처 표기는 inbound-country-brief의 report.py에서 가져다 쓴다.

# 모듈 이름에 target_ 접두사를 붙인 이유: 다른 스킬도 render.py를 가지고
# 있다. 한 프로세스에서 둘 다 쓰면 먼저 import된 쪽이 sys.modules를 차지한다.

**순위를 하나로 합치지 않는다.** 규모·집중도·소비를 가중합해 "종합 1위"를
뽑으면 우리 가정이 사용자의 사업 모델을 대신하게 된다. 정렬 기준은
사용자가 고르고, 표는 네 숫자를 나란히 놓기만 한다.
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
           _SKILLS_ROOT / "inbound-region-scan" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from report import STYLE, footer_text, table_head
import workspace

LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")

COLUMN_MEANING = {
    "방문자수": "그 지역을 찾은 이 국가 방문자 수(이동통신 기반 추정, 연인원).",
    "국적_비중": "그 지역을 찾은 <b>외국인 전체</b> 중 이 국가가 차지하는 몫. "
                 "규모가 아니라 <b>집중도</b>다.",
    "카드소비": "그 지역에서 이 국가 외국인이 쓴 카드 금액(원).",
    "1인당_소비": "카드소비 ÷ 방문자 수.",
}
SCALE_VS_SHARE = (
    "<b>규모와 집중도는 다른 이야기입니다.</b> 방문자가 많아도 외국인 중 "
    "비중은 낮을 수 있고, 수가 적어도 외국인의 절반이 그 국가일 수 있습니다. "
    "매장 성격에 따라 무엇이 중요한지 달라지므로 <b>둘을 하나로 합치지 "
    "않았습니다</b>."
)
PER_VISITOR_CAVEAT = (
    "1인당 소비의 분자는 그 국가 외국인의 <b>카드 사용액</b>이고 분모는 "
    "이동통신 기반 <b>연인원 추정치</b>입니다. 같은 사람이 여러 번 잡히고 "
    "카드를 안 쓴 방문자도 분모에 들어갑니다. 그러므로 "
    "<b>\"1인당 얼마 쓴다\"가 아니라 지역끼리 견주는 값</b>입니다."
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


def _table(frame, limit=None):
    view = frame if limit is None else frame.head(limit)
    head = table_head(view.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_fmt(v)}</td>" for v in row) + "</tr>"
        for row in view.itertuples(index=False, name=None))
    more = ""
    if limit is not None and len(frame) > limit:
        more = (f'<p class="note">{len(frame):,}곳 중 {limit}곳만 '
                "표시합니다.</p>")
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>{more}")


def _glossary():
    rows = "".join(f"<tr><td>{_esc(k)}</td><td>{v}</td></tr>"
                   for k, v in COLUMN_MEANING.items())
    return (f"<h2>열이 무엇인가</h2>"
            f'<div class="scroll"><table><thead><tr><th scope="col">열</th><th scope="col">뜻</th>'
            f"</tr></thead><tbody>{rows}</tbody></table></div>")


def _missing(meta):
    if not meta["미수록"]:
        return ""
    rows = "".join(f"<tr><td>{_esc(name)}</td><td>{_esc(reason)}</td></tr>"
                   for name, reason in sorted(meta["미수록"].items()))
    return (f"<h2>값이 나오지 않은 지역</h2>"
            f'<p class="note">빈칸은 0이 아니라 데이터가 없다는 뜻입니다. '
            f'"{_esc(meta["국가"])} 행 없음"은 그 지역 응답에 해당 국적이 '
            f"들어 있지 않다는 뜻입니다.</p>"
            f'<div class="scroll"><table><thead><tr><th scope="col">지역</th>'
            f"<th scope='col'>사유</th></tr></thead><tbody>{rows}</tbody></table></div>")


def _language_section(blocks):
    """상위 지역에서 그 언어권이 무엇을 읽었나.

    **페이지 조회 수이지 방문자 수가 아니다.** 후보 지역 표와 나란히
    두면 같은 축으로 읽히므로 절을 나누고 그 사실을 표마다 적는다.
    """
    if not blocks:
        return ""
    out = ["<h2>그 나라 말 페이지에서 많이 읽힌 관광지</h2>",
           '<p class="note">대한민국구석구석의 해당 언어 페이지 '
           '<b>조회 수</b>입니다. 방문자 수가 아니고, 그 관광지에 '
           '실제로 갔다는 뜻도 아닙니다. 상위 지역 몇 곳만 봅니다.</p>']
    for 지역, rows, 사유 in blocks:
        if 사유:
            out.append(f'<h3>{_esc(지역)}</h3>'
                       f'<p class="note">{_esc(사유)}</p>')
            continue
        body = "".join(
            f"<tr><td>{_esc(r['관광지'])}</td><td>{_esc(r['분류'] or '')}</td>"
            f"<td class='num'>{_fmt(r['조회수'])}</td></tr>"
            for r in rows)
        out.append(f"<h3>{_esc(지역)}</h3>"
                   f'<div class="scroll"><table><thead><tr>'
                   f'<th scope="col">관광지</th><th scope="col">분류</th>'
                   f'<th scope="col">조회수</th></tr></thead>'
                   f"<tbody>{body}</tbody></table></div>")
    return "".join(out)


def render_report(frame, meta, *, sort_column, limit=None, languages=None):
    warn = ""
    if meta["세션상태"] == "만료":
        warn = ('<div class="warn">로그인 세션이 만료되어 훑기를 중간에 '
                f"멈췄습니다. <code>{_esc(LOGIN_HINT)}</code>를 실행한 뒤 "
                "다시 생성하세요. (datalab-auth 스킬)</div>")
    return (
        f"{STYLE}"
        f'<div class="wrap">'
        f"<h1>{_esc(meta['국가'])} 관광객 지역 후보</h1>"
        f'<p class="sub">범위 {_esc(meta["범위"])} · '
        f'기준기간 {_esc(meta["기준기간"])} · '
        f'시군구 {meta["훑은지역수"]}곳 중 값이 나온 곳 '
        f'{meta["값있는지역수"]}곳</p>'
        f"{warn}"
        f'<div class="warn">{SCALE_VS_SHARE}</div>'
        f'<div class="warn">{PER_VISITOR_CAVEAT}</div>'
        f"<h2>후보 지역</h2>"
        f'<p class="note">{_esc(sort_column)} 기준 내림차순입니다. '
        f"순위를 하나로 합치지 않았습니다.</p>"
        f"{_table(frame, limit)}"
        f"{_language_section(languages)}"
        f"{_glossary()}"
        f"{_missing(meta)}"
        f'<p class="note">고른 지역을 깊게 보려면 '
        f"<code>region-market-scan</code>, 방문객 구성을 보려면 "
        f"<code>region-visitor-profile</code>을 쓰세요.</p>"
        f"<footer>{_esc(footer_text())}</footer>"
        f"</div>"
    )
