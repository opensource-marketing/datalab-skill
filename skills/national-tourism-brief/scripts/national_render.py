"""전국 브리프를 Artifact용 HTML로 렌더링한다.

문서 래퍼(<html>, <head>, <body>)는 넣지 않는다 — Artifact가 감싼다.
스타일과 출처 표기는 inbound-country-brief의 report.py에서 가져다 쓴다.

# 모듈 이름에 national_ 접두사를 붙인 이유: 다른 스킬도 render.py를
# 가지고 있다. 한 프로세스에서 둘 다 쓰면 먼저 import된 쪽이
# sys.modules를 차지해 다른 쪽 함수를 조용히 대신 실행한다.

**액수를 조·억으로 줄여 쓴다.** 전국 값은 자릿수가 열넷까지 간다
(93,664,351,622,807원). 그대로 두면 읽는 사람이 자릿수를 세다가
1조와 10조를 구분하지 못한다. 원래 값은 title 속성에 남긴다.

**기준 시점을 카드마다 적는다.** 한 화면에 있다고 같은 달이 아니다 —
방한 외래객은 6월까지인데 국내 여행객은 7월까지다. 하나로 뭉뚱그리면
거짓이 된다.
"""
import html as html_mod
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "inbound-country-brief" / "scripts",
           _SKILLS_ROOT / "datalab-fetch" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from report import STYLE, footer_text  # noqa: E402

MIXED_SOURCE_NOTE = (
    "이 표의 숫자들은 출처가 서로 다릅니다(이동통신·신용카드·한국관광통계·"
    "인허가). 같은 잣대로 잰 값이 아니므로 서로 나누거나 빼지 마세요."
)
SEARCH_NOTE = "검색 건수는 방문자 수가 아닙니다."
VISIT_NOTE = (
    "방문자 수는 연인원입니다. 한 사람이 여러 번 가면 여러 번 셉니다 — "
    "인구와 비교하지 마세요."
)


def _esc(value):
    return html_mod.escape(str(value))


def _money(value):
    """원 단위를 조·억으로 줄인다. 못 줄이면 그대로 쉼표만 찍는다."""
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    n = abs(value)
    if n >= 1_0000_0000_0000:
        return f"{sign}{n / 1_0000_0000_0000:,.1f}조원"
    if n >= 1_0000_0000:
        return f"{sign}{n / 1_0000_0000:,.0f}억원"
    return f"{sign}{n:,.0f}원"


def _people(value):
    """명 단위를 억·만으로 줄인다."""
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    n = abs(value)
    if n >= 1_0000_0000:
        return f"{sign}{n / 1_0000_0000:,.2f}억명"
    if n >= 1_0000:
        return f"{sign}{n / 1_0000:,.0f}만명"
    return f"{sign}{n:,.0f}명"


def fmt_value(value, unit):
    """단위에 맞게 값을 줄여 쓴다. 단위를 모르면 숫자만 돌려준다."""
    if value is None:
        return "—"
    if unit == "원":
        return _money(value)
    if unit == "명":
        return _people(value)
    if unit == "%":
        return f"{value:,.1f}%"
    if unit in ("건", "개"):
        return f"{value:,.0f}{unit}"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def fmt_delta(value, unit):
    """증감을 부호와 함께. 단위(%·%p)를 반드시 붙인다."""
    if value is None:
        return "—"
    return f"{value:+.1f}{unit}"


def _delta_class(value):
    if value is None:
        return "flat"
    return "up" if value > 0 else ("down" if value < 0 else "flat")


def _card_html(card):
    delta = fmt_delta(card["증감"], card["증감단위"])
    cls = _delta_class(card["증감"])
    if card["종류"] == "목록":
        items = "".join(
            f"<li><span>{_esc(i['이름'])}</span>"
            f"<b>{_esc(fmt_value(i['값'], i['단위']))}</b>"
            f"<i class='{_delta_class(i['증감'])}'>"
            f"{_esc(fmt_delta(i['증감'], '%'))}</i></li>"
            for i in card["항목"])
        body = f"<ul class='mini'>{items}</ul>" if items else "<p class='muted'>—</p>"
    else:
        raw = "" if card["값"] is None else f"{card['값']:,}"
        body = (f"<p class='big' title='{_esc(raw)}'>"
                f"{_esc(fmt_value(card['값'], card['값단위']))}</p>"
                f"<p class='delta {cls}'>{_esc(delta)}</p>")
    return (f"<div class='card'><h4>{_esc(card['이름'])}</h4>{body}"
            f"<p class='muted'>{_esc(card['기준'])} · {_esc(card['기준설명'])}</p>"
            f"</div>")


def _summary_section(summary):
    if not summary:
        return "<p class='warn'>전국 요약을 받지 못했습니다.</p>"
    out, group = [], None
    for card in summary["카드"]:
        if card["구분"] != group:
            if group is not None:
                out.append("</div>")
            group = card["구분"]
            out.append(f"<h3>{_esc(group)}</h3><div class='cards'>")
        out.append(_card_html(card))
    if group is not None:
        out.append("</div>")
    return "".join(out)


def _rollup_section(rows):
    if not rows:
        return ""
    body = "".join(
        f"<tr><td>{_esc(r['이름'])}</td>"
        f"<td class='num'>{_esc(fmt_value(r['값'], r['단위']))}</td>"
        f"<td class='num'>{_esc(fmt_value(r['전년'], r['단위']))}</td>"
        f"<td class='num {_delta_class(r['증감률'])}'>"
        f"{_esc(fmt_delta(r['증감률'], '%'))}</td>"
        f"<td class='muted'>{_esc(r['출처'])}</td>"
        f"<td class='muted'>{_esc(r['기준'])}</td></tr>" for r in rows)
    return (f"<h3>전국 5대 지표 (연간 누적)</h3>"
            f"<table><thead><tr><th scope='col'>지표</th><th scope='col'>올해</th><th scope='col'>전년 같은 기간</th>"
            f"<th scope='col'>증감</th><th scope='col'>출처</th><th scope='col'>기준</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
            f"<p class='note'>{_esc(MIXED_SOURCE_NOTE)}</p>")


def _trend_section(trends, missing):
    if not trends:
        return ""
    out = ["<h3>월별 추이</h3>"]
    for name, data in trends.items():
        rows = data["행"]
        if not rows:
            continue
        body = "".join(
            f"<tr><td>{_esc(r['기준월'])}</td>"
            f"<td class='num'>{_esc(fmt_value(r['값'], data['단위']))}</td>"
            f"<td class='num'>{_esc(fmt_value(r['전년동월'], data['단위']))}</td>"
            f"<td class='num {_delta_class(r['증감률'])}'>"
            f"{_esc(fmt_delta(r['증감률'], '%'))}</td></tr>" for r in rows)
        gap = missing.get(name)
        note = (f"<p class='note'>요청한 기간 중 {_esc(', '.join(gap))}은 "
                f"아직 발표되지 않아 빠졌습니다. 값이 0인 것이 아닙니다.</p>"
                if gap else "")
        out.append(
            f"<h4>{_esc(data['이름'])} <span class='muted'>({_esc(data['단위'])})"
            f"</span></h4>"
            f"<table><thead><tr><th scope='col'>월</th><th scope='col'>값</th><th scope='col'>전년 동월</th>"
            f"<th scope='col'>증감</th></tr></thead><tbody>{body}</tbody></table>{note}")
    return "".join(out)


def _countries_section(rows):
    if not rows:
        return ""
    body = "".join(
        f"<tr><td class='num'>{i}</td><td>{_esc(r['국가'])}</td>"
        f"<td class='num'>{_esc(fmt_value(r['방한객수'], '명'))}</td></tr>"
        for i, r in enumerate(rows, 1))
    return (f"<h3>방한객 상위 10개국</h3>"
            f"<table><thead><tr><th scope='col'>순위</th><th scope='col'>국가</th><th scope='col'>방한객수</th></tr>"
            f"</thead><tbody>{body}</tbody></table>"
            f"<p class='note'>상위 10개국만 나옵니다. 다 더해도 전체 "
            f"방한객수가 아닙니다.</p>")


def _balance_section(rows):
    """관광수지. 항목 이름에 단위가 적혀 있으니 그대로 옮긴다."""
    if not rows:
        return ""
    항목 = []
    for r in rows:
        if r["항목"] not in 항목:
            항목.append(r["항목"])
    달 = []
    for r in rows:
        if r["기준월"] not in 달:
            달.append(r["기준월"])
    표 = {(r["기준월"], r["항목"]): r["값"] for r in rows}
    head = "".join(f"<th scope='col'>{_esc(i)}</th>" for i in 항목)
    body = "".join(
        "<tr><td>" + _esc(m) + "</td>" + "".join(
            f"<td class='num'>{_esc(fmt_value(표.get((m, i)), ''))}</td>"
            for i in 항목) + "</tr>"
        for m in 달)
    return (f"<h3>관광수지</h3>"
            f"<table><thead><tr><th scope='col'>기준월</th>{head}</tr>"
            f"</thead><tbody>{body}</tbody></table>"
            f"<p class='note'>단위가 항목 이름에 적혀 있습니다 — 전체는 "
            f"백만 달러, 1인당은 달러입니다. 한국은 관광수지 적자라 "
            f"음수가 정상입니다.</p>")


def _survey_section(items):
    """국민여행조사. 연 단위 설문이라 월별 추이와 나란히 두지 않는다."""
    if not items:
        return ""
    연도 = []
    for it in items:
        for r in it["연도별"]:
            if r["연도"] not in 연도:
                연도.append(r["연도"])
    연도.sort()
    head = "".join(f"<th scope='col'>{_esc(y)}</th>" for y in 연도)
    body = ""
    for it in items:
        값 = {r["연도"]: r["값"] for r in it["연도별"]}
        cells = "".join(
            f"<td class='num'>{_esc(fmt_value(값.get(y), it['단위']))}</td>"
            for y in 연도)
        body += f"<tr><td>{_esc(it['이름'])}</td>{cells}</tr>"
    return (f"<h3>국민 국내여행</h3>"
            f"<table><thead><tr><th scope='col'>항목</th>{head}</tr>"
            f"</thead><tbody>{body}</tbody></table>"
            f"<p class='note'><b>설문조사입니다.</b> 이동통신·카드 같은 실측이 "
            f"아니라 표본조사 결과라, 경험률은 응답자 비율입니다. "
            f"1인 평균 지출액은 한 번 여행이 아니라 한 해 동안 쓴 돈입니다.</p>")


def _complaint_section(rows):
    """관광불편신고 시도 순위."""
    if not rows:
        return ""
    body = "".join(
        f"<tr><td class='num'>{_esc(r['순위'])}</td><td>{_esc(r['시도'])}</td>"
        f"<td class='num'>{_esc(fmt_value(r['건수'], '건'))}</td>"
        f"<td class='num'>{_esc(fmt_value(r['비중'], '%'))}</td></tr>"
        for r in rows)
    return (f"<h3>관광불편신고가 많은 곳</h3>"
            f"<table><thead><tr><th scope='col'>순위</th>"
            f"<th scope='col'>시도</th><th scope='col'>건수</th>"
            f"<th scope='col'>비중</th></tr></thead><tbody>{body}</tbody></table>"
            f"<p class='note'>시도 단위까지만 있습니다. 신고가 없는 시도는 "
            f"행이 오지 않습니다. 방문자가 많은 곳이 신고도 많으므로 "
            f"건수만으로 '위험한 곳'이라고 읽지 마십시오.</p>")


def _inbound_mix_section(mix):
    """대륙과 관문을 나란히. 두 표의 합이 같다는 것을 확인해 두었다."""
    if not mix:
        return ""
    out = ["<h3>방한객이 어디서 어디로 들어오나</h3>"]
    for 이름, 열 in (("대륙별", "대륙"), ("입국 공항·항구별", "관문")):
        rows = mix.get(열) or []
        if not rows:
            continue
        body = "".join(
            f"<tr><td>{_esc(r['이름'])}</td>"
            f"<td class='num'>{_esc(fmt_value(r['방한객수'], '명'))}</td>"
            f"<td class='num'>{_esc(fmt_value(r['비중'], '%'))}</td></tr>"
            for r in rows)
        out.append(
            f"<h4>{_esc(이름)}</h4>"
            f"<table><thead><tr><th scope='col'>구분</th>"
            f"<th scope='col'>방한객수</th><th scope='col'>비중</th></tr>"
            f"</thead><tbody>{body}</tbody></table>")
    out.append("<p class='note'>두 표는 같은 방한객을 다르게 자른 것이라 "
               "합이 같습니다. 공항·항구 표는 아홉 갈래로 묶은 것이라 "
               "더 잘게 나눈 표와 행끼리 짝지을 수 없습니다.</p>")
    return "".join(out)


def _hotspot_section(hot):
    if not hot:
        return ""
    out = ["<h3>방문자가 급등한 동네</h3>"]
    for kind, rows in hot.items():
        if not rows:
            continue
        body = "".join(
            f"<tr><td class='num'>{_esc(r['순위'])}</td>"
            f"<td>{_esc(r['시도'])} {_esc(r['시군구'])} {_esc(r['행정동'])}</td>"
            f"<td class='num up'>{_esc(fmt_delta(r['증가율'], '%'))}</td>"
            f"<td class='muted'>{_esc(r['구간'])}</td></tr>" for r in rows)
        out.append(
            f"<h4>{_esc(kind)}</h4>"
            f"<table><thead><tr><th scope='col'>순위</th><th scope='col'>행정동</th><th scope='col'>증가율</th>"
            f"<th scope='col'>구간</th></tr></thead><tbody>{body}</tbody></table>")
    out.append(f"<p class='note'>{_esc(VISIT_NOTE)} 외국인은 모수가 작아 "
               f"증가율이 크게 튑니다 — 순위를 규모로 읽지 마세요.</p>")
    return "".join(out)


def _rising_section(rows):
    if not rows:
        return ""
    body = "".join(
        f"<tr><td class='num'>{_esc(r['순위'])}</td>"
        f"<td>{_esc(r['관광지'])}</td>"
        f"<td class='muted'>{_esc(r['시도'])} {_esc(r['시군구'])}</td>"
        f"<td class='num'>{_esc(fmt_value(r['검색건수'], '건'))}</td>"
        f"<td class='num up'>{_esc(fmt_delta(r['증가율'], '%'))}</td></tr>"
        for r in rows)
    return (f"<h3>검색이 급등한 관광지</h3>"
            f"<table><thead><tr><th scope='col'>순위</th><th scope='col'>관광지</th><th scope='col'>지역</th>"
            f"<th scope='col'>검색건수</th><th scope='col'>증가율</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
            f"<p class='note'>{_esc(SEARCH_NOTE)}</p>")


def _popular_section(rows, meta):
    if not rows:
        return ""
    body = "".join(
        f"<tr><td class='num'>{_esc(r['순위'])}</td>"
        f"<td>{_esc(r['관광지'])}</td>"
        f"<td class='muted'>{_esc(r['시도'])} {_esc(r['시군구'])}</td>"
        f"<td class='num'>{_esc(fmt_value(r['검색건수'], '건'))}</td></tr>"
        for r in rows)
    return (f"<h3>인기 관광지 <span class='muted'>({_esc(meta['연령대'])}, "
            f"{_esc(meta['내비게이션창'])})</span></h3>"
            f"<table><thead><tr><th scope='col'>순위</th><th scope='col'>관광지</th><th scope='col'>지역</th>"
            f"<th scope='col'>검색건수</th></tr></thead><tbody>{body}</tbody></table>"
            f"<p class='note'>{_esc(SEARCH_NOTE)} 내비게이션 데이터는 다른 "
            f"지표와 조회 창이 달라 최근 석 달로 잡았습니다.</p>")


def _stay_section(rows):
    if not rows:
        return ""
    body = "".join(
        f"<tr><td>{_esc(r['시도'])}</td>"
        f"<td class='num'>{_esc(fmt_value(r['평균숙박일'], '일'))}</td>"
        f"<td class='num'>{_esc(fmt_value(r['체류시간'], ''))}</td></tr>"
        for r in rows)
    return (f"<h3>시도별 체류 깊이</h3>"
            f"<table><thead><tr><th scope='col'>시도</th><th scope='col'>평균 숙박일</th>"
            f"<th scope='col'>체류시간</th></tr></thead><tbody>{body}</tbody></table>"
            f"<p class='note'>체류시간은 사이트가 단위를 적어 두지 않아 "
            f"확정하지 못했습니다 — 시도끼리 견주는 데만 쓰세요. "
            f"'전남광주통합특별시'는 광주광역시·전라남도와 겹칩니다.</p>")


def _meta_section(meta):
    lines = [f"기준 기간 {_esc(meta['기준기간'])}",
             f"수록 {meta['수록지표']}/{meta['시도지표']}"]
    out = [f"<p class='muted'>{' · '.join(lines)}</p>"]
    if meta["미수록"]:
        items = "".join(f"<li>{_esc(k)}: {_esc(v)}</li>"
                        for k, v in sorted(meta["미수록"].items()))
        out.append(f"<div class='warn'><b>받지 못한 지표</b><ul>{items}</ul>"
                   f"<p>빈 칸은 값이 0이라는 뜻이 아닙니다.</p></div>")
    if meta["모르는카드"]:
        out.append(
            f"<div class='warn'>데이터랩이 이 스킬이 모르는 지표 "
            f"{len(meta['모르는카드'])}개를 새로 내놓았습니다"
            f"(코드 {_esc(', '.join(meta['모르는카드']))}). "
            f"카탈로그 갱신이 필요합니다.</div>")
    if meta["세션상태"] == "만료":
        out.append("<div class='warn'>로그인 세션이 만료됐습니다. "
                   "datalab-auth 스킬로 다시 로그인하세요.</div>")
    return "".join(out)


EXTRA_STYLE = """
<style>
.cards { display: grid; gap: 12px;
         grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
         margin: 12px 0 20px; }
.card { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.card h4 { margin: 0 0 6px; font-size: 0.92rem; font-weight: 600; }
.card .big { margin: 0; font-size: 1.32rem; font-weight: 700; line-height: 1.25; }
.card .delta { margin: 2px 0 6px; font-size: 0.92rem; font-weight: 600; }
.card .muted { margin: 0; font-size: 0.78rem; }
.up { color: #b42318; } .down { color: #1d4ed8; } .flat { color: var(--muted); }
ul.mini { list-style: none; margin: 0 0 6px; padding: 0; }
ul.mini li { display: flex; justify-content: space-between; gap: 8px;
             font-size: 0.86rem; padding: 2px 0; }
ul.mini li b { font-weight: 600; }
ul.mini li i { font-style: normal; font-size: 0.8rem; }
.note { font-size: 0.82rem; color: var(--muted); margin: 4px 0 18px; }
.warn { background: var(--warn-bg); color: var(--warn-fg);
        padding: 10px 14px; border-radius: 8px; margin: 12px 0; }
td.num, th.num { text-align: right; }
</style>
"""


def render(data, meta):
    """수집 결과를 HTML 조각으로 만든다. 네트워크도 파일도 모른다."""
    parts = [STYLE, EXTRA_STYLE,
             "<h1>전국 관광 현황</h1>",
             _meta_section(meta),
             _summary_section(data.get("요약")),
             _rollup_section(data.get("5대지표")),
             _trend_section(data.get("추이") or {}, meta["빠진달"]),
             _countries_section(data.get("상위국가")),
             _inbound_mix_section(data.get("유입")),
             _balance_section(data.get("관광수지")),
             _survey_section(data.get("국민여행")),
             _complaint_section(data.get("불편신고")),
             _hotspot_section(data.get("급등동네")),
             _rising_section(data.get("급등관광지")),
             _popular_section(data.get("연령인기"), meta),
             _stay_section(data.get("시도체류")),
             f"<p class='muted'>{_esc(footer_text())}</p>"]
    return "\n".join(p for p in parts if p)
